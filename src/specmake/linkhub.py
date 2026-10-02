# SPDX-License-Identifier: BSD-2-Clause
""" Provides links from items to documents. """

# Copyright (C) 2022, 2026 embedded brains GmbH & Co. KG
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

# pylint: disable=too-many-lines

import functools
import itertools
import os
from typing import Any, Optional
from xml.etree import ElementTree

from specitems import Item, ItemGetValueContext, list_terms

from .directorystate import DirectoryState
from .pkgitems import BuildItem, BuildItemMapper, PackageBuildDirector
from .rtems import RTEMSItemCache

# Sorted by expected frequency
_ELEMENT_KINDS = ("function", "define", "group", "file", "type", "enum",
                  "object", "enumerator")


def _member_link(elem: Any) -> str:
    return f"{elem.find('anchorfile').text}#{elem.find('anchor').text}"


def _arglist(elem: Any) -> str:
    arglist = elem.find('arglist').text
    if not arglist:
        return ""
    return arglist


def _type(elem: Any) -> str:
    return elem.find('type').text


def _sdd_link(name_info: dict[str, Any], link: str) -> str:
    return f"{name_info['dir/sdd']}/{link}"


def _get_file_path(elem: Any) -> str:
    path = elem.find("path").text
    if not path:
        path = ""
    return f"{path}{elem.find('name').text}"


def _add_doxygen_item(name_info: dict[str, Any], elem: Any, parent: Any,
                      name: str, elem_info: dict[str, Any]) -> None:
    parent_kind = parent.attrib.get("kind", "")
    if parent_kind == "class":
        return
    if parent_kind == "file":
        elem_info["file"] = _get_file_path(parent)
    anchorfile = elem.find("anchorfile")
    if anchorfile is not None:
        elem_info_2 = name_info.setdefault(name, {}).setdefault(
            "instances", {}).setdefault(anchorfile.text, {})
    else:
        elem_info_2 = name_info.setdefault(name, {})
    elem_info_2.update(elem_info)
    if parent_kind == "group":
        elem_info_2.setdefault("groups", set()).add(parent.find("name").text)


def _doxygen_define(name_info: dict[str, Any], elem: Any, parent: Any) -> None:
    name = elem.find("name").text
    arglist = _arglist(elem)
    elem_info = {
        "doxygen": f"@def {name}{arglist}",
        "link": _sdd_link(name_info, _member_link(elem)),
        "name": f"{name}()" if arglist else name
    }
    _add_doxygen_item(name_info, elem, parent, f"define/{name}", elem_info)


def _doxygen_enumeration(name_info: dict[str, Any], elem: Any,
                         parent: Any) -> None:
    name = elem.find("name").text
    elem_info = {
        "doxygen": f"@enum {name}",
        "link": _sdd_link(name_info, _member_link(elem)),
        "name": name
    }
    _add_doxygen_item(name_info, elem, parent, f"enum/{name}", elem_info)


def _doxygen_enumvalue(name_info: dict[str, Any], elem: Any,
                       parent: Any) -> None:
    name = elem.find("name").text
    elem_info = {
        "doxygen": f"@var {name}",
        "link": _sdd_link(name_info, _member_link(elem)),
        "name": name
    }
    _add_doxygen_item(name_info, elem, parent, f"enumerator/{name}", elem_info)


def _doxygen_file(name_info: dict[str, Any], elem: Any, parent: Any) -> None:
    prefix = f"{name_info['dir/source']}"
    name = _get_file_path(elem)
    name_info[f"file-key/{name}"] = name
    elem_info = {
        "doxygen": f"@file {name}",
        "link": _sdd_link(name_info,
                          elem.find('filename').text),
        "name": name,
        "prefix": prefix
    }
    _add_doxygen_item(name_info, elem, parent, f"file/{name}", elem_info)


# pylint: disable=too-many-arguments
# pylint: disable=too-many-positional-arguments
def _doxygen_decl(name_info: dict[str, Any],
                  elem: Any,
                  parent: Any,
                  kind: str,
                  cmd: str,
                  postfix: str = "") -> None:
    name = elem.find("name").text
    elem_info = {
        "doxygen": f"@{cmd} {_type(elem)} {name}{_arglist(elem)}",
        "link": _sdd_link(name_info, _member_link(elem)),
        "name": f"{name}{postfix}"
    }
    _add_doxygen_item(name_info, elem, parent, f"{kind}/{name}", elem_info)


def _doxygen_function(name_info: dict[str, Any], elem: Any,
                      parent: Any) -> None:
    _doxygen_decl(name_info, elem, parent, "function", "fn", "()")


def _doxygen_group(name_info: dict[str, Any], elem: Any, parent: Any) -> None:
    file_keys: list[str] = []
    for key in elem.findall("file"):
        file_keys.append(f"{key.attrib.get('path', '')}{key.text}")
    subgroups: list[str] = []
    for key in elem.findall("subgroup"):
        subgroups.append(key.text)
    group = elem.find("name").text
    name_info.setdefault("groups/all", []).append(group)
    elem_info = {
        "doxygen": f"@addtogroup {group}",
        "link": _sdd_link(name_info,
                          elem.find("filename").text),
        "name": elem.find("title").text,
        "file-keys": file_keys,
        "subgroups": subgroups
    }
    _add_doxygen_item(name_info, elem, parent, f"group/{group}", elem_info)


def _doxygen_type(name_info: dict[str, Any], elem: Any, parent: Any,
                  kind: str) -> None:
    if elem.tag == "compound":
        name = elem.find("name").text
        elem_info = {
            "doxygen": f"@{kind} {name}",
            "link": _sdd_link(name_info,
                              elem.find("filename").text)
        }
    else:
        # This is required to get the file of compounds
        assert elem.tag == "class"
        name = elem.text
        elem_info = {}
    elem_info["name"] = name
    _add_doxygen_item(name_info, elem, parent, f"type/{name}", elem_info)


def _doxygen_struct(name_info: dict[str, Any], elem: Any, parent: Any) -> None:
    _doxygen_type(name_info, elem, parent, "struct")


def _doxygen_typedef(name_info: dict[str, Any], elem: Any,
                     parent: Any) -> None:
    _doxygen_decl(name_info, elem, parent, "type", "typedef")


def _doxygen_union(name_info: dict[str, Any], elem: Any, parent: Any) -> None:
    _doxygen_type(name_info, elem, parent, "union")


def _doxygen_variable(name_info: dict[str, Any], elem: Any,
                      parent: Any) -> None:
    if parent.attrib.get("kind", "") in ("struct", "union"):
        return
    if "::" in elem.find("name").text:
        # Compound members may show up in groups.  In this case, they have a
        # "::" in the name.  Do not add a name information for them.
        return
    _doxygen_decl(name_info, elem, parent, "object", "var")


def _doxygen_nop(_name_info: dict[str, Any], _elem: Any, _parent: Any) -> None:
    pass


_DOXYGEN_KINDS = {
    "define": _doxygen_define,
    "enumeration": _doxygen_enumeration,
    "enumvalue": _doxygen_enumvalue,
    "file": _doxygen_file,
    "function": _doxygen_function,
    "group": _doxygen_group,
    "struct": _doxygen_struct,
    "typedef": _doxygen_typedef,
    "union": _doxygen_union,
    "variable": _doxygen_variable
}


def _depth_iter(element):
    stack = [(iter([element]), None)]
    while stack:
        element_2 = next(stack[-1][0], None)
        if element_2 is None:
            stack.pop()
        else:
            stack.append((iter(element_2), element_2))
            yield (element_2, stack[-2][1])


def _gather_name_info(name_info: dict[str, Any], tagfile: str) -> None:
    tree = ElementTree.parse(tagfile)
    for elem, parent in _depth_iter(tree.getroot()):
        try:
            kind = elem.attrib["kind"]
        except KeyError:
            continue
        _DOXYGEN_KINDS.get(kind, _doxygen_nop)(name_info, elem, parent)


def _name_info_key_default(item: Item) -> str:
    raise ValueError(f"no name information for: {item.uid}")


def _name_info_key_define(item: Item) -> str:
    return f"define/{item['name']}"


def _name_info_key_enum(item: Item) -> str:
    return f"enum/{item['name']}"


def _name_info_key_enumerator(item: Item) -> str:
    return f"enumerator/{item['name']}"


def _name_info_key_header_file(item: Item) -> str:
    return f"file/{item['prefix']}/{item['path']}"


def _name_info_key_forward_decl(item: Item) -> str:
    target = item.parent("interface-target")
    return f"{target['interface-type']}/{target['name']}"


def _name_info_key_function(item: Item) -> str:
    return f"function/{item['name']}"


def _name_info_key_group(item: Item) -> str:
    return f"group/{item['identifier']}"


def _name_info_key_appl_config_group(item: Item) -> str:
    return f"group/RTEMSApplConfig{item['name'].replace(' ', '')}"


def _name_info_key_object(item: Item) -> str:
    return f"object/{item['name']}"


def _name_info_key_type(item: Item) -> str:
    return f"type/{item['name']}"


def spec_label(item: Item) -> str:
    """ Return the specification label of the item. """
    return f"Spec{item.ident}"


def _name_name(item: Item) -> str:
    return item['name']


def _name_forward_decl(item: Item) -> str:
    return item.parent("interface-target")["name"]


def _name_function(item: Item) -> str:
    return f"{item['name']}()"


def _name_header_file(item: Item) -> str:
    return f"<{item['path']}>"


def _name_unspecified_type(item: Item) -> str:
    return f"{item['interface-type'][12:]} {item['name']}"


def _name_spec(item: Item) -> str:
    return item.spec_2


def _set_name_and_defaults(item: Item, default_key: str,
                           default_path: str) -> None:
    item.view["name"] = _ITEM_SPECIFICS[item.type][2](item)
    item.view["default-document-key"] = default_key
    item.view["default-document-path"] = default_path
    item.view["document-paths"] = {}


def _augment_default(_item: Item, _name_info: dict[str, Any]) -> None:
    pass


def _add_sdd_info(item: Item, name_info: dict[str, Any],
                  name: Optional[str]) -> None:
    try:
        elem_info = name_info[_ITEM_SPECIFICS[item.type][3](item)]
    except KeyError:
        return
    item.view["sdd-info"] = elem_info
    if name is None:
        item.view["sdd-name"] = item.view["name"]
    else:
        item.view["sdd-name"] = elem_info[name]
    path = elem_info.get("file", None)
    if path is not None:
        item.view["source-file"] = path
    item.view["document-paths"]["sdd"] = elem_info["link"]


def _anchor(item: Item) -> str:
    return f"#spec{item.ident.lower()}"


def _augment_interface(item: Item, name_info: dict[str, Any]) -> None:
    _set_name_and_defaults(
        item, "icd", f"{name_info['dir/icd']}/"
        f"requirements-and-design.html{_anchor(item)}")
    _add_sdd_info(item, name_info, None)


def _augment_requirement(item: Item, name_info: dict[str, Any]) -> None:
    _set_name_and_defaults(
        item, "srs", f"{name_info['dir/srs']}/"
        f"requirements.html{_anchor(item)}")


def _augment_design_group(item: Item, name_info: dict[str, Any]) -> None:
    _augment_requirement(item, name_info)
    _add_sdd_info(item, name_info, "name")


def _augment_requirement_self_test(item: Item, name_info: dict[str,
                                                               Any]) -> None:
    _augment_requirement(item, name_info)
    item.view["document-paths"]["test-plan"] = (
        f"{name_info['dir/svs']}/"
        f"test-case-specification.html{_anchor(item)}")


def _augment_interface_requirement(item: Item, name_info: dict[str,
                                                               Any]) -> None:
    _set_name_and_defaults(
        item, "icd", f"{name_info['dir/icd']}/"
        f"requirements-and-design.html{_anchor(item)}")


def _augment_test_case(item: Item, name_info: dict[str, Any]) -> None:
    try:
        if "validation" in item.parent("test-case").parent(
                "requirement-refinement").uid:
            key = "svs"
        else:
            key = "suitp"
    except IndexError as err:
        raise ValueError("no test-case to test-suite to "
                         "requirement-refinement link for (likely cause is "
                         f"that no build item is enabled): {item.uid} -> "
                         f"{[item.uid for item in item.parents()]}") from err
    prefix = name_info[f"dir/{key}"]
    _set_name_and_defaults(
        item, key, f"{prefix}/test-case-specification.html{_anchor(item)}")


def _augment_test_suite_for_document(item: Item, name_info: dict[str, Any],
                                     document: str) -> None:
    prefix = name_info[f"dir/{document}"]
    _set_name_and_defaults(item, document,
                           f"{prefix}/test-design.html{_anchor(item)}")


def _augment_test_suite(item: Item, name_info: dict[str, Any]) -> None:
    if "validation" in item.parent("requirement-refinement").uid:
        document = "svs"
    else:
        document = "suitp"
    _augment_test_suite_for_document(item, name_info, document)


def _augment_memory_benchmark(item: Item, name_info: dict[str, Any]) -> None:
    _augment_test_suite_for_document(item, name_info, "svs")


def _augment_other_validation(item: Item, name_info: dict[str, Any]) -> None:
    prefix = name_info["dir/svs"]
    _set_name_and_defaults(item, "svs",
                           f"{prefix}/validation-other.html{_anchor(item)}")


_ITEM_DEFAULT = ("unknown", _augment_default, _name_spec,
                 _name_info_key_default)

_ITEM_SPECIFICS = {
    "constraint": (
        "constraint",
        _augment_requirement,
        _name_spec,
        _name_info_key_default,
    ),
    "errata": (
        "erratum",
        _augment_requirement,
        _name_spec,
        _name_info_key_default,
    ),
    "glossary/group": (
        "glossary group",
        _augment_requirement,
        _name_spec,
        _name_info_key_default,
    ),
    "glossary/term": (
        "glossary term",
        _augment_default,
        _name_spec,
        _name_info_key_default,
    ),
    "interface/appl-config-group": (
        "application configuration group",
        _augment_interface,
        _name_name,
        _name_info_key_appl_config_group,
    ),
    "interface/appl-config-option/feature": (
        "application configuration option",
        _augment_interface,
        _name_name,
        _name_info_key_define,
    ),
    "interface/appl-config-option/feature-enable": (
        "application configuration option",
        _augment_interface,
        _name_name,
        _name_info_key_define,
    ),
    "interface/appl-config-option/initializer": (
        "application configuration option",
        _augment_interface,
        _name_name,
        _name_info_key_define,
    ),
    "interface/appl-config-option/integer": (
        "application configuration option",
        _augment_interface,
        _name_name,
        _name_info_key_define,
    ),
    "interface/define": (
        "define",
        _augment_interface,
        _name_name,
        _name_info_key_define,
    ),
    "interface/domain": (
        "interface domain",
        _augment_interface_requirement,
        _name_name,
        _name_info_key_group,
    ),
    "interface/enum": (
        "enumeration",
        _augment_interface,
        _name_name,
        _name_info_key_enum,
    ),
    "interface/enumerator": (
        "enumerator",
        _augment_interface,
        _name_name,
        _name_info_key_enumerator,
    ),
    "interface/forward-declaration": (
        "forward declaration",
        _augment_interface,
        _name_forward_decl,
        _name_info_key_forward_decl,
    ),
    "interface/function": (
        "directive",
        _augment_interface,
        _name_function,
        _name_info_key_function,
    ),
    "interface/group": (
        "interface group",
        _augment_interface,
        _name_name,
        _name_info_key_group,
    ),
    "interface/header-file": (
        "header file",
        _augment_interface,
        _name_header_file,
        _name_info_key_header_file,
    ),
    "interface/macro": (
        "macro",
        _augment_interface,
        _name_function,
        _name_info_key_define,
    ),
    "interface/register-block": (
        "register block",
        _augment_interface,
        _name_name,
        _name_info_key_type,
    ),
    "interface/struct": (
        "structure",
        _augment_interface,
        _name_name,
        _name_info_key_type,
    ),
    "interface/typedef": (
        "type definition",
        _augment_interface,
        _name_name,
        _name_info_key_type,
    ),
    "interface/union": (
        "union",
        _augment_interface,
        _name_name,
        _name_info_key_type,
    ),
    "interface/unspecified-define": (
        "define",
        _augment_interface,
        _name_name,
        _name_info_key_define,
    ),
    "interface/unspecified-enum": (
        "enumeration",
        _augment_interface,
        _name_unspecified_type,
        _name_info_key_enum,
    ),
    "interface/unspecified-enumerator": (
        "enumerator",
        _augment_interface,
        _name_name,
        _name_info_key_enumerator,
    ),
    "interface/unspecified-function": (
        "directive",
        _augment_interface,
        _name_function,
        _name_info_key_function,
    ),
    "interface/unspecified-group": (
        "group",
        _augment_interface,
        _name_name,
        _name_info_key_group,
    ),
    "interface/unspecified-header-file": (
        "header file",
        _augment_interface,
        _name_header_file,
        _name_info_key_header_file,
    ),
    "interface/unspecified-macro": (
        "macro",
        _augment_interface,
        _name_function,
        _name_info_key_define,
    ),
    "interface/unspecified-object": (
        "object",
        _augment_interface,
        _name_name,
        _name_info_key_object,
    ),
    "interface/unspecified-struct": (
        "type",
        _augment_interface,
        _name_unspecified_type,
        _name_info_key_type,
    ),
    "interface/unspecified-typedef": (
        "type definition",
        _augment_interface,
        _name_name,
        _name_info_key_type,
    ),
    "interface/unspecified-union": (
        "type",
        _augment_interface,
        _name_unspecified_type,
        _name_info_key_type,
    ),
    "interface/variable": (
        "object",
        _augment_interface,
        _name_name,
        _name_info_key_object,
    ),
    "memory-benchmark": (
        "memory benchmark",
        _augment_memory_benchmark,
        _name_spec,
        _name_info_key_default,
    ),
    "requirement/functional/action": (
        "action requirement",
        _augment_requirement_self_test,
        _name_spec,
        _name_info_key_default,
    ),
    "requirement/functional/capability": (
        "capability requirement",
        _augment_requirement,
        _name_spec,
        _name_info_key_default,
    ),
    "requirement/functional/interface-define-not-defined": (
        "interface define requirement",
        _augment_requirement,
        _name_spec,
        _name_info_key_default,
    ),
    "requirement/functional/fatal-error": (
        "fatal error",
        _augment_requirement,
        _name_spec,
        _name_info_key_default,
    ),
    "requirement/functional/function": (
        "function requirement",
        _augment_requirement,
        _name_spec,
        _name_info_key_default,
    ),
    "requirement/non-functional/design": (
        "design requirement",
        _augment_requirement,
        _name_spec,
        _name_info_key_default,
    ),
    "requirement/non-functional/design-group": (
        "design group",
        _augment_design_group,
        _name_spec,
        _name_info_key_group,
    ),
    "requirement/non-functional/design-target": (
        "design target",
        _augment_requirement,
        _name_spec,
        _name_info_key_default,
    ),
    "requirement/non-functional/interface": (
        "interface requirement",
        _augment_requirement,
        _name_spec,
        _name_info_key_default,
    ),
    "requirement/non-functional/interface-requirement": (
        "interface requirement",
        _augment_interface_requirement,
        _name_spec,
        _name_info_key_default,
    ),
    "requirement/non-functional/performance": (
        "performance requirement",
        _augment_requirement,
        _name_spec,
        _name_info_key_default,
    ),
    "requirement/non-functional/performance-runtime": (
        "runtime performance requirement",
        _augment_requirement_self_test,
        _name_spec,
        _name_info_key_default,
    ),
    "requirement/non-functional/performance-runtime-environment": (
        "runtime performance measurement environment",
        _augment_requirement,
        _name_spec,
        _name_info_key_default,
    ),
    "requirement/non-functional/quality": (
        "quality requirement",
        _augment_requirement,
        _name_spec,
        _name_info_key_default,
    ),
    "runtime-measurement-test": (
        "runtime measurement test",
        _augment_test_case,
        _name_spec,
        _name_info_key_default,
    ),
    "spec": (
        "specification specification",
        _augment_default,
        _name_spec,
        _name_info_key_default,
    ),
    "test-case": (
        "test case",
        _augment_test_case,
        _name_spec,
        _name_info_key_default,
    ),
    "test-suite": (
        "test suite",
        _augment_test_suite,
        _name_spec,
        _name_info_key_default,
    ),
    "validation/by-analysis": (
        "validation by analysis",
        _augment_other_validation,
        _name_spec,
        _name_info_key_default,
    ),
    "validation/by-inspection": (
        "validation by inspection",
        _augment_other_validation,
        _name_spec,
        _name_info_key_default,
    ),
    "validation/by-review-of-design": (
        "validation by review of design",
        _augment_other_validation,
        _name_spec,
        _name_info_key_default,
    ),
}


def get_kind(item: Item) -> str:
    """ Returns the item kind. """
    return _ITEM_SPECIFICS[item.type][0]


def _get_group_items(name_info: dict[str, Any], spec: RTEMSItemCache,
                     info: dict[str, Any]) -> list[Item]:
    items = []
    try:
        for group in info["groups"]:
            name = f"group/{group}"
            try:
                items.append(spec.name_to_item[name])
            except KeyError:
                items.extend(_get_group_items(name_info, spec,
                                              name_info[name]))
    except KeyError:
        doxygen = info["doxygen"]
        if doxygen.startswith("@file"):
            spec.item.view.setdefault("files-without-group",
                                      set()).add(doxygen[6:])
        if doxygen.startswith("@addtogroup"):
            spec.item.view.setdefault("groups-without-items",
                                      set()).add(doxygen[11:])
    return items


def _get_associated_items(name_info: dict[str, Any], spec: RTEMSItemCache,
                          name: str, info: dict[str, Any]) -> list[Item]:
    item = spec.name_to_item.get(name, None)
    if item is not None:
        return [item]
    groups = info.get("groups", None)
    if groups is not None:
        return _get_group_items(name_info, spec, info)
    if name.startswith("file/"):
        file_info = info
    else:
        try:
            file_info = name_info[f"file/{info['file']}"]
        except KeyError as err:
            raise ValueError(
                f"'{name}' is not associated with a file: {info}") from err
    return _get_group_items(name_info, spec, file_info)


def _augment_name_info_default(name_info: dict[str, Any], spec: RTEMSItemCache,
                               name: str, info: dict[str, Any]) -> None:
    for variant in itertools.chain([info], info.get("variants", [])):
        items = _get_associated_items(name_info, spec, name, variant)
        variant["items"] = set(items)


def _augment_name_info_group(name_info: dict[str, Any], spec: RTEMSItemCache,
                             name: str, info: dict[str, Any]) -> None:
    try:
        items = [spec.name_to_item[name]]
    except KeyError:
        items = _get_group_items(name_info, spec, info)
    info["items"] = set(items)


def _augment_name_info_nop(_name_info: dict[str, Any], _spec: RTEMSItemCache,
                           _name: str, _info: dict[str, Any]) -> None:
    pass


_AUGMENT_NAME_INFO = {
    "dir": _augment_name_info_nop,
    "file-key": _augment_name_info_nop,
    "group": _augment_name_info_group,
    "groups": _augment_name_info_nop
}


def _check_mapping_completeness(spec: RTEMSItemCache) -> None:
    without = spec.item.view.get("files-without-group")
    if without:
        raise ValueError(f"files without group: {' '.join(sorted(without))}")
    without = spec.item.view.get("groups-without-items")
    if without:
        raise ValueError(f"groups without items: {' '.join(sorted(without))}")


def _augment_name_info(name_info: dict[str, Any],
                       spec: RTEMSItemCache) -> None:
    # Associate files and groups with groups
    for group in name_info["groups/all"]:
        info = name_info[f"group/{group}"]
        files: list[str] = []
        for key in sorted(info["file-keys"]):
            file_key = name_info[f"file-key/{key}"]
            files.append(file_key)
            file_info = name_info[f"file/{file_key}"]
            file_info.setdefault("groups", []).append(group)
        info["files"] = files
        for key in sorted(info["subgroups"]):
            group_info = name_info[f"group/{key}"]
            group_info.setdefault("groups", []).append(group)

    for name, info in name_info.items():
        if isinstance(info, dict) and "instances" in info:
            instances = info["instances"]
            if name.startswith("define/CONFIGURE"):
                for anchorfile, instance in instances.items():
                    if next(iter(
                            instance["groups"])).startswith("RTEMSApplConfig"):
                        first = anchorfile
                        break
                else:
                    first = sorted(instances.keys())[0]
            else:
                first = sorted(instances.keys())[0]
            info.update(instances[first])
            del instances[first]
            info["variants"] = list(instances.values())
            del info["instances"]
    for name, info in name_info.items():
        _AUGMENT_NAME_INFO.get(name[0:name.find("/")],
                               _augment_name_info_default)(name_info, spec,
                                                           name, info)
    _check_mapping_completeness(spec)


class LinkHub(BuildItem):
    """ Provides links from items to documents. """

    def __init__(self, director: PackageBuildDirector, item: Item):
        super().__init__(director, item)
        self.name_info: dict[str, Any] = {}
        for link in self.item.links_to_parents("resource"):
            target = self.director[link.item.uid]
            assert isinstance(target, DirectoryState)
            name = f"dir/{link['resource-key']}"
            self.name_info[name] = os.path.normpath(
                os.path.join(target.directory, link["path"]))
        try:
            tagfile = self.input("tagfile")
        except KeyError as err:
            if "RTEMS_QUAL" in self.enabled_set:
                raise ValueError(
                    f"{self.uid}: there is no associated tagfile") from err
        else:
            assert isinstance(tagfile, DirectoryState)
            _gather_name_info(self.name_info, tagfile.file)
            spec = self.input("spec")
            assert isinstance(spec, RTEMSItemCache)
            _augment_name_info(self.name_info, spec)
            for item_2 in spec.item_cache.values():
                if not item_2.enabled:
                    continue
                _ITEM_SPECIFICS.get(item_2.type,
                                    _ITEM_DEFAULT)[1](item_2, self.name_info)

    def run(self) -> None:
        self.description.add("""Provide documentation links for specification
items.""")

    def get_sdd_link(self, kind: str, name: str,
                     mapper: BuildItemMapper) -> str:
        """ Return the SDD link for the name by kind. """
        elem_info = self.name_info[f"{kind}/{name}"]
        return mapper.format_link(elem_info["name"], elem_info["link"])

    def get_file_sdd_link(self, path: str, mapper: BuildItemMapper) -> str:
        """ Return the SDD link for the file path. """
        return self.get_sdd_link("file", path, mapper)

    def get_function_sdd_link(self, name: str, mapper: BuildItemMapper) -> str:
        """ Return the SDD link for the function with the name. """
        return self.get_sdd_link("function", name, mapper)

    def get_any_sdd_link(self, name: str, mapper: BuildItemMapper) -> str:
        """ Return an SDD link for the name. """
        for kind in _ELEMENT_KINDS:
            elem_info = self.name_info.get(f"{kind}/{name}")
            if elem_info is not None:
                break
        if elem_info is None:
            raise ValueError(f"there is no SDD element with this name: {name}")
        return mapper.format_link(elem_info["name"], elem_info["link"])


class SpecMapper(BuildItemMapper):
    """ Item mapper for specifications. """

    def __init__(self, item: Item, build_item: BuildItem, whoami: str):
        super().__init__(item, build_item)
        self._whoami = whoami
        for type_path_key in (
                "interface/appl-config-option/feature-enable:/name",
                "interface/appl-config-option/feature:/name",
                "interface/appl-config-option/initializer:/name",
                "interface/appl-config-option/integer:/name",
                "interface/define:/name", "interface/enum:/name",
                "interface/enumerator:/name", "interface/function:/name",
                "interface/group:/name", "interface/header-file:/path",
                "interface/macro:/name", "interface/struct:/name",
                "interface/typedef:/name", "interface/union:/name",
                "interface/unspecified-define:/name",
                "interface/unspecified-enum:/name",
                "interface/unspecified-enumerator:/name",
                "interface/unspecified-function:/name",
                "interface/unspecified-group:/name",
                "interface/unspecified-macro:/name",
                "interface/unspecified-struct:/name",
                "interface/unspecified-typedef:/name",
                "interface/unspecified-union:/name",
                "interface/variable:/name",
                "requirement/non-functional/design-group:/name"):
            self.add_get_value(type_path_key, self._get_value_link)
        for type_name in self.item.cache.items_by_type.keys():
            self.add_get_value(f"{type_name}:/spec", self._get_value_link)
        for kind in ("define", "enum", "enumerator", "file", "function",
                     "group", "object", "type"):
            self.add_default_get_value(
                f"sdd-{kind}", functools.partial(self._get_value_sdd_link,
                                                 kind))
        self.add_default_get_value("sdd", self._get_value_sdd_link_unique)

    def make_reference(self, item: Item, name: Optional[str] = None) -> str:
        """
        Make a document internal reference for the item with the optional
        name.

        When no name is given, then the link name is item.spec_2.
        """
        assert item.enabled
        if name is None:
            name = item.spec_2
        return self.format_reference(name, spec_label(item))

    def get_link(self, item: Item, document_key: Optional[str] = None) -> str:
        try:
            default_key = item.view["default-document-key"]
        except KeyError:
            build_item = self.build_item
            component_links: list[str] = []
            for component in build_item.component.components():
                with build_item.component_scope(component):
                    try:
                        default_key = item.view["default-document-key"]
                    except KeyError:
                        continue
                    if document_key is None:
                        component_key = default_key
                    else:
                        component_key = document_key
                    assert component_key != self._whoami
                    name = item.view["name"]
                    path = item.view["document-paths"].get(
                        component_key, item.view["default-document-path"])
                    component_links.append(
                        self.format_link(component.item.spec_2, path))
            if not component_links:
                name = _ITEM_SPECIFICS.get(item.type, _ITEM_DEFAULT)[2](item)
                return self.format_code(name)
            if len(component_links) == 1:
                return self.format_link(name, path)
            return (f"{self.format_code(name)} "
                    f"(for {list_terms(component_links)})")
        if document_key is None:
            document_key = default_key
        name = item.view["name"]
        if document_key == self._whoami:
            return self.format_reference(name, spec_label(item))
        path = item.view["document-paths"].get(
            document_key, item.view["default-document-path"])
        return self.format_link(name, path)

    def _get_value_link(self, ctx: ItemGetValueContext) -> str:
        return self.get_link(ctx.item)

    def _get_value_sdd_link(self, kind: str, ctx: ItemGetValueContext) -> str:
        link_hub_uid = self.build_item.component.item.child("link-hub").uid
        link_hub = self.build_item.director[link_hub_uid]
        assert isinstance(link_hub, LinkHub)
        assert ctx.args
        return link_hub.get_sdd_link(kind, ctx.args, self)

    def _get_value_sdd_link_unique(self, ctx: ItemGetValueContext) -> str:
        link_hub_uid = self.build_item.component.item.child("link-hub").uid
        link_hub = self.build_item.director[link_hub_uid]
        assert isinstance(link_hub, LinkHub)
        assert ctx.args
        return link_hub.get_any_sdd_link(ctx.args, self)
