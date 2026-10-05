# SPDX-License-Identifier: BSD-2-Clause
""" Tests for the testaggregator module. """

# Copyright (C) 2025 embedded brains GmbH & Co. KG
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

from specmake import testaggregator

from .util import create_package


def test_testaggregator(caplog, tmpdir):
    package = create_package(caplog, Path(tmpdir), Path("spec-packagebuild"),
                             ["aggregate-test-results"])
    uid = "/pkg/steps/aggregate-test-results"
    package.director.build_package(only=[uid])


def test_testaggregator_no_perf_limits(caplog, tmpdir):
    package = create_package(caplog, Path(tmpdir), Path("spec-packagebuild"),
                             ["aggregate-test-results", "no-target-a-perf"])
    uid = "/pkg/steps/aggregate-test-results"
    with pytest.raises(ValueError, match="has no performance runtime limits"):
        package.director.build_package(only=[uid])


def test_add_retried_program():
    config_data = {"retried-programs": []}
    testaggregator._add_retried_program(config_data, {"executable": "a/b.exe"})
    testaggregator._add_retried_program(config_data, {
        "executable": "a/c.exe",
        "failed-attempts": []
    })
    testaggregator._add_retried_program(config_data, {
        "executable": "a/d.exe",
        "failed-attempts": [{}, {}]
    })
    assert config_data["retried-programs"] == [("d.exe", 2)]


class _Requirement:

    def __init__(self, uid, type_name, pre_qualified, validated):
        self.uid = uid
        self.type = type_name
        self.view = {"pre-qualified": pre_qualified, "validated": validated}

    def __lt__(self, other):
        return self.uid < other.uid


def test_get_not_validated_requirements():
    requirements = [
        _Requirement("/c", "requirement/functional/function", True, False),
        _Requirement("/b", "requirement/functional/function", False, False),
        _Requirement("/a", "requirement/functional/action", True, True),
        _Requirement("/d", "requirement/non-functional/quality", True, False)
    ]
    aggregator = SimpleNamespace(
        component={"ident": "i"},
        spec=SimpleNamespace(get_related_requirements=lambda: requirements))
    assert testaggregator.TestAggregator.get_not_validated_requirements(
        aggregator) == [testaggregator.NotValidatedRequirement("i", "/c")]
