# SPDX-License-Identifier: BSD-2-Clause
""" Tests for the linkhub module. """

# Copyright (C) 2025, 2026 embedded brains GmbH & Co. KG
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

from pathlib import Path
from types import SimpleNamespace

import pytest

from specitems import EmptyItemCache

from specmake.linkhub import (_get_associated_items, _name_info_key_default,
                              get_kind, SpecMapper)

from .util import create_package, get_and_clear_log


def test_linkhub(caplog, tmp_path):
    package = create_package(caplog, tmp_path, Path("spec-packagebuild"),
                             ["djf-svs", "link-hub"])
    item_cache = package.item.cache
    director = package.director
    director.build_package()

    with pytest.raises(ValueError, match="no name information for:"):
        _name_info_key_default(package.item)

    link_hub = director["/pkg/steps/link-hub"]
    assert link_hub.get_sdd_link(
        "function", "blub", link_hub.mapper
    ) == f"`blub() <{tmp_path}/pkg/doc-ddf-sdd/html/group__Blub.html#ga754ccc677acbd87ede8b3c082bb9ff6b>`__"
    with pytest.raises(KeyError):
        link_hub.get_sdd_link("function", "nil", link_hub.mapper)
    assert link_hub.get_file_sdd_link(
        "a.c", link_hub.mapper
    ) == f"`a.c <{tmp_path}/pkg/doc-ddf-sdd/html/a_8c.html>`__"
    assert link_hub.get_function_sdd_link(
        "blub", link_hub.mapper
    ) == f"`blub() <{tmp_path}/pkg/doc-ddf-sdd/html/group__Blub.html#ga754ccc677acbd87ede8b3c082bb9ff6b>`__"

    mapper = SpecMapper(link_hub.item, link_hub, "icd")
    assert mapper.substitute(
        "${.:/sdd-define:DISABLED}"
    ) == f"`DISABLED <{tmp_path}/pkg/doc-ddf-sdd/html/group__Blub.html#gabd5c8ab57c190a6522ccdbf0ed7577da>`__"
    assert mapper.substitute(
        "${.:/sdd-enum:the_enum}"
    ) == f"`the_enum <{tmp_path}/pkg/doc-ddf-sdd/html/group__Blub.html#ga582a1afc79f3b607104a52d7aa268624>`__"
    assert mapper.substitute(
        "${.:/sdd-enumerator:ENUMERATOR}"
    ) == f"`ENUMERATOR <{tmp_path}/pkg/doc-ddf-sdd/html/group__Blub.html#gga582a1afc79f3b607104a52d7aa268624a183cf8edbca25c5db49f6fda4224f87a>`__"
    assert mapper.substitute(
        "${.:/sdd-file:a.c}"
    ) == f"`a.c <{tmp_path}/pkg/doc-ddf-sdd/html/a_8c.html>`__"
    assert mapper.substitute(
        "${.:/sdd-function:blub}"
    ) == f"`blub() <{tmp_path}/pkg/doc-ddf-sdd/html/group__Blub.html#ga754ccc677acbd87ede8b3c082bb9ff6b>`__"
    assert mapper.substitute(
        "${.:/sdd-group:GroupA}"
    ) == f"`A <{tmp_path}/pkg/doc-ddf-sdd/html/group__GroupA.html>`__"
    assert mapper.substitute(
        "${.:/sdd:GroupA}"
    ) == f"`A <{tmp_path}/pkg/doc-ddf-sdd/html/group__GroupA.html>`__"
    with pytest.raises(ValueError):
        mapper.substitute("${.:/sdd:DoesNotExist}")
    assert mapper.substitute(
        "${.:/sdd-object:obj}"
    ) == f"`obj <{tmp_path}/pkg/doc-ddf-sdd/html/group__Blub.html#gafc83d933ee990064a19b6b66ccad1800>`__"
    assert mapper.substitute(
        "${.:/sdd-type:Union}"
    ) == f"`Union <{tmp_path}/pkg/doc-ddf-sdd/html/unionUnion.html>`__"
    assert mapper.substitute(
        "${.:/sdd-tag:StructBoth}"
    ) == f"`StructBoth <{tmp_path}/pkg/doc-ddf-sdd/html/structStructBoth.html>`__"
    assert mapper.substitute(
        "${.:/sdd-type:StructBoth}"
    ) == f"`StructBoth <{tmp_path}/pkg/doc-ddf-sdd/html/group__Blub.html#gafc3408bd38e181fb80afd4d06fec20ff>`__"

    assert mapper.substitute(
        "${/rtems/if/func:/spec}") == ":ref:`blub() <SpecRtemsIfFunc>`"
    assert mapper.substitute(
        "${/rtems/if/define-disabled:/spec}") == "``DISABLED``"

    assert mapper.make_reference(
        link_hub.item
    ) == ":ref:`spec:/​pkg/​steps/​link-hub <SpecPkgStepsLinkHub>`"
    assert mapper.make_reference(link_hub.item,
                                 "name") == ":ref:`name <SpecPkgStepsLinkHub>`"

    assert mapper.get_link(item_cache["/rtems/if/func"],
                           "icd") == ":ref:`blub() <SpecRtemsIfFunc>`"
    assert mapper.get_link(
        item_cache["/req/root"], "foobar"
    ) == f"`spec:/​req/​root <{tmp_path}/pkg/doc-ts-srs/html/requirements.html#specreqroot>`__"
    assert mapper.get_link(item_cache["/req/disabled"],
                           "foobar") == "``spec:/​req/​disabled``"
    assert mapper.get_link(item_cache["/req/disabled"], "foobar",
                           "name") == "``name``"
    assert mapper.get_link(item_cache["/rtems/if/forward-decl-disabled"],
                           "foobar") == "``StructOnly``"
    assert mapper.get_link(item_cache["/rtems/if/func-disabled"],
                           "foobar") == "``disabled()``"
    assert mapper.get_link(item_cache["/rtems/if/header-disabled"],
                           "foobar") == "``<blub.h>``"

    assert get_kind(item_cache["/rtems/if/func"]) == "directive"


def test_linkhub_no_test_to_req(caplog, tmp_path):
    package = create_package(caplog, tmp_path, Path("spec-packagebuild"),
                             ["djf-svs", "link-hub"])
    item_cache = package.item.cache
    item_cache.remove_item("/build/test-suite")
    with pytest.raises(
            ValueError,
            match="no test-case to test-suite to requirement-refinement"):
        package.director.build_package()


def test_linkhub_files_without_group(caplog, tmp_path):
    package = create_package(
        caplog, tmp_path, Path("spec-packagebuild"),
        ["djf-svs", "link-hub", "link-hub-files-without-group"])
    with pytest.raises(ValueError, match="files without group"):
        package.director.build_package()


def test_linkhub_groups_without_items(caplog, tmp_path):
    package = create_package(
        caplog, tmp_path, Path("spec-packagebuild"),
        ["djf-svs", "link-hub", "link-hub-groups-without-items"])
    with pytest.raises(ValueError, match="groups without items"):
        package.director.build_package()


def test_linkhub_no_file(caplog, tmp_path):
    package = create_package(caplog, tmp_path, Path("spec-packagebuild"),
                             ["djf-svs", "link-hub", "link-hub-no-file"])
    with pytest.raises(ValueError, match="not associated with a file"):
        package.director.build_package()


def test_linkhub_no_tagfile(caplog, tmp_path):
    package = create_package(caplog, tmp_path, Path("spec-packagebuild"),
                             ["djf-svs", "link-hub", "link-hub-no-tagfile"])
    package.director.build_package()
    link_hub = package.director["/pkg/steps/link-hub"]
    mapper = SpecMapper(link_hub.item, link_hub, "icd")
    assert mapper.get_link(package.item.cache["/rtems/if/func"],
                           "icd") == "``blub()``"


def test_linkhub_no_tagfile_qual(caplog, tmp_path):
    package = create_package(
        caplog, tmp_path, Path("spec-packagebuild"),
        ["djf-svs", "link-hub", "link-hub-no-tagfile", "RTEMS_QUAL"])
    with pytest.raises(ValueError, match="there is no associated tagfile"):
        package.director.build_package()


def test_linkhub_get_link(caplog, tmp_path):
    package = create_package(caplog, tmp_path, Path("spec-packagebuild"),
                             ["sub-sub-s-link-hub", "sub-sub-t-link-hub"])
    package.director.build_package()
    subcomponent = package.director["/pkg/sub/component"]
    mapper = SpecMapper(subcomponent.item, subcomponent, "other")
    assert mapper.substitute(
        "${/rtems/if/define-disabled:/name}") == "``DISABLED``"
    assert mapper.substitute("${/rtems/if/unspec-define:/name}") == (
        f"`UnspecDefine <{tmp_path}"
        "/pkg/doc-ts-icd/html/requirements-and-design.html#specrtemsifunspecdefine>`__"
    )
    assert mapper.substitute("${/rtems/if/unspec-macro:/name}") == (
        "``UnspecMacro()`` "
        f"(for `spec:/​pkg/​sub/​s/​component <{tmp_path}"
        "/pkg/doc-ts-icd/html/requirements-and-design.html#specrtemsifunspecmacro>`__ and "
        f"`spec:/​pkg/​sub/​t/​component <{tmp_path}"
        "/pkg/doc-ts-icd/html/requirements-and-design.html#specrtemsifunspecmacro>`__)"
    )
    mapper.base_path = str(tmp_path)
    assert mapper.get_link(
        subcomponent.item.cache["/rtems/if/unspec-macro"], "icd"
    ) == (
        "``UnspecMacro()`` "
        "(for `spec:/​pkg/​sub/​s/​component "
        "<pkg/doc-ts-icd/html/requirements-and-design.html#specrtemsifunspecmacro>`__ and "
        "`spec:/​pkg/​sub/​t/​component "
        "<pkg/doc-ts-icd/html/requirements-and-design.html#specrtemsifunspecmacro>`__)"
    )


def test_linkhub_tag_and_type_of_same_name():
    item_cache = EmptyItemCache()
    item_cache.add_items({
        "/tag": {
            "interface-type": "struct",
            "links": [],
            "type": "interface"
        },
        "/type": {
            "interface-type": "typedef",
            "links": [],
            "type": "interface"
        },
        "/anonymous": {
            "interface-type": "union",
            "links": [],
            "type": "interface"
        },
        "/group": {
            "interface-type": "group",
            "links": [],
            "type": "interface"
        },
    })
    for item in item_cache.values():
        item.type = f"interface/{item['interface-type']}"
    spec = SimpleNamespace(
        name_to_item={
            "tag/status": item_cache["/tag"],
            "type/status": item_cache["/type"],
            "type/other": item_cache["/type"],
            "type/anonymous": item_cache["/anonymous"],
            "group/G": item_cache["/group"]
        })
    info = {"groups": ["G"]}
    assert _get_associated_items({}, spec, "tag/status",
                                 info) == [item_cache["/tag"]]
    assert _get_associated_items({}, spec, "type/status",
                                 info) == [item_cache["/type"]]
    assert _get_associated_items({}, spec, "tag/anonymous",
                                 info) == [item_cache["/anonymous"]]
    assert _get_associated_items({}, spec, "tag/other",
                                 info) == [item_cache["/group"]]
