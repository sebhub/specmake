# SPDX-License-Identifier: BSD-2-Clause
""" Provides details of the RTEMS specification. """

# Copyright (C) 2021, 2026 embedded brains GmbH & Co. KG
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions
# are met:
# 1. Redistributions of source code must retain the above copyright
#    notice, this list of conditions and the following disclaimer.
# 2. Redistributions in binary form must reproduce the above copyright
#    notice, this list of conditions and the following disclaimer in the
#    documentation and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.

import base64
import functools
import hashlib
import logging
import os
from typing import Callable, Iterable

from specitems import EnabledSet, Item, ItemGetValueContext, is_enabled, Link
from specware import (augment_with_test_case_links, augment_with_test_links,
                      get_inline_enumerators, get_items_by_type_map,
                      get_item_types_by_prefix, get_items_by_types,
                      get_interface_items, get_interface_and_requirement_items,
                      get_register_block_hosts, get_register_block_identifier,
                      get_requirement_items, is_validation_by_test,
                      recursive_is_enabled, validate)

from .pkgitems import (BuildItem, BuildItemFactory, BuildItemMapper,
                       build_item_input, GenericPackageComponent,
                       PackageBuildDirector, PackageComponent)


def _add_unique_name(name_to_item: dict[str, Item], item: Item,
                     name: str) -> None:
    if name in name_to_item:
        raise ValueError(
            f"items {item.uid} and {name_to_item[name].uid} "
            f"specify the same interface group: {name.partition('/')[2]}")
    name_to_item[name] = item


def _name_default(name_to_item: dict[str, Item], item: Item) -> None:
    name_to_item[item.ident] = item


def _name_define(name_to_item: dict[str, Item], item: Item) -> None:
    if not item.enabled:
        return
    _name_default(name_to_item, item)
    name = f"define/{item['name']}"
    if name in name_to_item:
        if not name_to_item[name].type.startswith("interface/unspecified"):
            if not item.type.startswith("interface/unspecified"):
                raise ValueError(f"duplicate defines specified by {item.uid} "
                                 f"and {name_to_item[name].uid}")
            return
    name_to_item[name] = item


def _name_kind(kind: str, key: str, name_to_item: dict[str, Item],
               item: Item) -> None:
    if not item.enabled:
        return
    _name_default(name_to_item, item)
    _add_unique_name(name_to_item, item, f"{kind}/{item[key]}")


def _name_enum(name_to_item: dict[str, Item], item: Item) -> None:
    if not item.enabled:
        return
    _name_kind("enum", "name", name_to_item, item)
    for _, enumerator in get_inline_enumerators(item):
        _add_unique_name(name_to_item, item,
                         f"enumerator/{enumerator['name']}")


_name_enumerator = functools.partial(_name_kind, "enumerator", "name")
_name_function = functools.partial(_name_kind, "function", "name")
_name_group = functools.partial(_name_kind, "group", "identifier")
_name_object = functools.partial(_name_kind, "object", "name")
_name_type = functools.partial(_name_kind, "type", "name")
_name_perf_runtime_env = functools.partial(_name_kind, "perf-runtime-env",
                                           "name")


def _name_design_group(name_to_item: dict[str, Item], item: Item) -> None:
    if not item.enabled:
        return
    _name_default(name_to_item, item)
    identifier = item["identifier"]
    if identifier is None:
        return
    _add_unique_name(name_to_item, item, f"group/{identifier}")


def _name_register_block(name_to_item: dict[str, Item], item: Item) -> None:
    if not item.enabled:
        return
    _name_default(name_to_item, item)
    if item.get("identifier", None) is None and not any(
            link.data.get("identifier", None) is not None
            for link in get_register_block_hosts(item)):
        return
    _add_unique_name(name_to_item, item,
                     f"group/{get_register_block_identifier(item)}")


def _name_ident_group(name_to_item: dict[str, Item], item: Item) -> None:
    if not item.enabled:
        return
    _name_default(name_to_item, item)
    _add_unique_name(name_to_item, item, f"group/{item.ident}")


def _name_header(name_to_item: dict[str, Item], item: Item) -> None:
    if not item.enabled:
        return
    _name_default(name_to_item, item)
    name = item.get("prefix", "")
    if name:
        name = f"file/{name}/{item['path']}"
    else:
        name = f"file/{item['path']}"
    _add_unique_name(name_to_item, item, name)


def _name_appl_config_group(name_to_item: dict[str, Item], item: Item) -> None:
    if not item.enabled:
        return
    _name_default(name_to_item, item)
    _add_unique_name(name_to_item, item,
                     f"group/RTEMSApplConfig{item['name'].replace(' ', '')}")


def _name_test_program(name_to_item: dict[str, Item], item: Item) -> None:
    _name_default(name_to_item, item)
    _add_unique_name(name_to_item, item,
                     f"file/{os.path.basename(item['target'])}")


def _name_script(name_to_item: dict[str, Item], item: Item) -> None:
    if item.get("target", None):
        _name_test_program(name_to_item, item)


_NAME: dict[str, Callable[[dict[str, Item], Item], None]] = {
    "build/script": _name_script,
    "build/test-program": _name_test_program,
    "interface/appl-config-group": _name_appl_config_group,
    "interface/appl-config-option/feature": _name_define,
    "interface/appl-config-option/feature-enable": _name_define,
    "interface/appl-config-option/initializer": _name_define,
    "interface/appl-config-option/integer": _name_define,
    "interface/define": _name_define,
    "interface/enum": _name_enum,
    "interface/enumerator": _name_enumerator,
    "interface/function": _name_function,
    "interface/group": _name_group,
    "interface/header-file": _name_header,
    "interface/macro": _name_default,
    "interface/register-block": _name_register_block,
    "interface/struct": _name_type,
    "interface/typedef": _name_type,
    "interface/union": _name_type,
    "interface/unspecified-define": _name_define,
    "interface/unspecified-enum": _name_enum,
    "interface/unspecified-enumerator": _name_enumerator,
    "interface/unspecified-function": _name_function,
    "interface/unspecified-header-file": _name_header,
    "interface/unspecified-macro": _name_define,
    "interface/unspecified-object": _name_object,
    "interface/unspecified-struct": _name_type,
    "interface/unspecified-typedef": _name_type,
    "interface/unspecified-union": _name_type,
    "interface/variable": _name_object,
    "memory-benchmark": _name_ident_group,
    "requirement/functional/action": _name_ident_group,
    "requirement/non-functional/design-group": _name_design_group,
    "requirement/non-functional/performance-runtime-environment":
    _name_perf_runtime_env,
    "runtime-measurement-test": _name_ident_group,
    "test-case": _name_ident_group,
    "test-suite": _name_ident_group,
}


def _get_issue(ctx: ItemGetValueContext) -> str:
    mapper = ctx.mapper
    assert isinstance(mapper, BuildItemMapper)
    database = ctx.item.parent("issue-member")
    url = mapper.substitute(database["url"], ctx.item)
    identifier = mapper.substitute(database["format-identifier"], ctx.item)
    return mapper.format_link(f"{database['name']} {identifier}", url)


def _add_errata(related_items: set[Item]) -> None:
    for item in list(related_items):
        related_items.update(item.parents("errata-resolution"))


def _check_errata(related_items: set[Item]) -> None:
    gaps: set[tuple[str, str]] = set()
    for erratum in related_items:
        if erratum.type != "errata":
            continue
        for document in erratum.parents("reference"):
            for erratum_2 in document.children("reference"):
                if erratum_2.type == "errata" and (erratum_2
                                                   not in related_items):
                    gaps.add((erratum_2.uid, document.uid))
    if gaps:
        raise ValueError("; ".join(
            f"erratum {uid} of {document} has no enabled resolution"
            for uid, document in sorted(gaps)))


class RTEMSItemCache(BuildItem):
    """ Augments the items with RTEMS-specific attributes and links. """

    @classmethod
    def prepare_factory(cls, factory: BuildItemFactory,
                        type_name: str) -> None:
        BuildItem.prepare_factory(factory, type_name)
        factory.add_get_value("pkg/issue:/name", _get_issue)

    def __init__(self, director: PackageBuildDirector, item: Item):
        super().__init__(director, item)
        self.item_cache = self.item.cache
        logging.info("%s: augment with test links", self.uid)
        augment_with_test_links(self.item_cache)
        logging.info("%s: augment with test case links", self.uid)
        augment_with_test_case_links(self.item_cache)
        logging.info("%s: gather name information", self.uid)
        self.name_to_item: dict[str, Item] = {}
        for item_2 in self.item_cache.values():
            _NAME.get(item_2.type, _name_default)(self.name_to_item, item_2)
        self.related_items: set[Item] = set()
        self.related_items_by_type: dict[str, list[Item]] = {}
        self.related_validations_by_test: set[Item] = set()

        # Calculate the overall item cache hash.  Ignore package configuration
        # items and specification type changes.
        state = hashlib.sha512()
        for item_2 in sorted(self.item_cache.values()):
            if not item_2.type.startswith(("pkg", "spec")):
                digest = item_2.get("workspace-digest", None)
                if digest is None:
                    digest = item_2.digest
                state.update(digest.encode("ascii"))
        self._hash = base64.urlsafe_b64encode(state.digest()).decode("ascii")

    def run(self) -> None:
        self.description.add("""Augment the component with an RTEMS-specific
view of the specification items.""")

    def _validate_using_test_results(self, item: Item,
                                     validated: bool) -> bool:
        if is_validation_by_test(item):
            self.related_validations_by_test.add(item)

            # A validation by test is a valid validation, if it has at least
            # one test result and the test did not unexpectedly fail (it passed
            # or is an expected failure) in all test results.
            results = False
            for test_results in item.view.get("test-results", {}).values():
                for data in test_results:
                    if data["status"] == "F":
                        return False
                    results = True
            if not results:
                return False
        elif item.type == "requirement/non-functional/design-target":
            if not item.view.get("no-unexpected-test-failures", False):
                return False
        return validated

    def get_spec_root(self) -> Item:
        """ Get the root of the specification. """
        return self.item_cache[self["spec-root-uid"]]

    def validate_using_test_results(self) -> None:
        """ Validate the specification using test results. """
        self.related_items = validate(self.get_spec_root(),
                                      self._validate_using_test_results)
        _add_errata(self.related_items)
        _check_errata(self.related_items)
        self.related_items_by_type = get_items_by_type_map(self.related_items)

    def has_changed(self, link: Link) -> bool:
        return link["hash"] is None or self._hash != link["hash"]

    def refresh_link(self, link: Link) -> None:
        link["hash"] = self._hash

    def get_related_items_by_type(self,
                                  types: str | Iterable[str]) -> list[Item]:
        """ Get related items by a list of types. """
        return get_items_by_types(self.related_items_by_type, types)

    def get_related_types_by_prefix(
        self,
        prefix: str | tuple[str, ...],
        exclude: tuple[str, ...] = tuple()
    ) -> list[str]:
        """
        Get the types of the related items having one of the type prefixes.
        """
        return get_item_types_by_prefix(self.related_items_by_type, prefix,
                                        exclude)

    def get_related_interfaces(self) -> list[Item]:
        """ Get the related interfaces. """
        return get_interface_items(self.related_items_by_type)

    def get_related_requirements(self) -> list[Item]:
        """ Get the related requirements. """
        return get_requirement_items(self.related_items_by_type)

    def get_related_interfaces_and_requirements(self) -> list[Item]:
        """ Get the related interfaces and requirements. """
        return get_interface_and_requirement_items(self.related_items_by_type)


class RTEMSPackageComponent(GenericPackageComponent):
    """ Provides a package with an RTEMS-specific item selection.  """

    def run(self) -> None:
        self.description.add("""Provide settings for the RTEMS-specific
component.""")

    def is_item_enabled(self, enabled_set: EnabledSet, item: Item) -> bool:
        try:
            component_item = build_item_input(item, "component")
        except KeyError:
            return recursive_is_enabled(enabled_set, item)
        component = self.director[component_item.uid]
        assert isinstance(component, PackageComponent)
        return is_enabled(component.selection.enabled_set, item["enabled-by"])
