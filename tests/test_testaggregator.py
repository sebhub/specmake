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


class _Item:

    def __init__(self, uid, type_name, order, validated):
        self.uid = uid
        self.type = type_name
        self.view = {"order": order, "validated": validated}


def _make_aggregator(root, items):
    return SimpleNamespace(component={"ident": "i"},
                           spec=SimpleNamespace(get_spec_root=lambda: root,
                                                related_items=set(items)))


def test_get_not_validated_items():
    root = _Item("/r", "requirement/non-functional/design", (0, ), False)
    items = [
        root,
        _Item("/b", "interface/define", (2, 1, 0), False),
        _Item("/c", "requirement/functional/action", (1, 0), True),
        _Item("/a", "interface/group", (2, 0), False)
    ]
    assert testaggregator.TestAggregator.get_not_validated_items(
        _make_aggregator(root, items)) == [
            testaggregator.NotValidatedItem(
                "i", (0, ), "/r", "requirement/non-functional/design"),
            testaggregator.NotValidatedItem("i", (2, 0), "/a",
                                            "interface/group"),
            testaggregator.NotValidatedItem("i", (2, 1, 0), "/b",
                                            "interface/define")
        ]
    root.view["validated"] = True
    assert testaggregator.TestAggregator.get_not_validated_items(
        _make_aggregator(root, items)) == []


def _limits(percent):
    return {
        "branch-min-percent": percent,
        "function-min-percent": percent,
        "line-min-percent": percent
    }


class _Aggregator:
    uid = "/pkg/steps/aggregate-test-results"


def _file_coverage(file_path, count):
    return {
        "file":
        file_path,
        "lines": [{
            "line_number": 10,
            "count": count,
            "gcovr/md5": "d0",
            "branches": [{
                "count": count,
                "destination_block_id": 3
            }]
        }],
        "functions": [{
            "name": "f",
            "execution_count": count
        }]
    }


def _coverage_summary(files, limits_by_area):
    return testaggregator._CoverageSummary(
        _Aggregator(), {
            "files": files,
            "html-directory": "html",
            "limits-by-area": limits_by_area,
            "scope": "Scope",
            "target-uid": "/target/simulator",
            "verifications": {}
        })


def test_file_limits_by_pattern():
    limits_by_area = {
        "overall": _limits(100.0),
        "per-file": _limits(100.0),
        "file-lib/*": _limits(10.0),
        "file-lib/sub/*": _limits(20.0),
        "file-lib/sub/a.c": _limits(30.0),
        "file-lib/sub/[ab].c": _limits(40.0)
    }
    summary = _coverage_summary([], limits_by_area)
    assert summary._file_limits("src/a.c") is None
    assert summary._file_limits("lib/a.c") == _limits(10.0)
    assert summary._file_limits("lib/x/y/a.c") == _limits(10.0)
    assert summary._file_limits("lib/sub/c.c") == _limits(20.0)
    assert summary._file_limits("lib/sub/a.c") == _limits(30.0)
    assert summary._file_limits("lib/sub/b.c") == _limits(40.0)


def test_unjustified_gaps_of_files_with_limits():
    files = [
        _file_coverage("src/a.c", 0),
        _file_coverage("src/b.c", 1),
        _file_coverage("lib/c.c", 0),
        _file_coverage("lib/d.c", 0)
    ]
    limits_by_area = {
        "overall": _limits(100.0),
        "per-file": _limits(0.0),
        "file-lib/*": _limits(0.0),
        "file-lib/d.c": _limits(100.0)
    }
    summary = _coverage_summary(files, limits_by_area)
    assert "error" in summary.overall
    assert summary.overall["line-total"] == 2
    assert summary.overall["per-file-line-total"] == 2
    assert [stats["file-path"] for stats in summary.bad_files] == ["lib/d.c"]
    assert sorted(gap.file for gap in summary.get_unjustified_gaps()) == [
        "lib/d.c", "lib/d.c", "lib/d.c", "src/a.c", "src/a.c", "src/a.c"
    ]
    limits_by_area["overall"] = _limits(0.0)
    summary = _coverage_summary(files, limits_by_area)
    assert "error" not in summary.overall
    assert sorted(gap.file for gap in summary.get_unjustified_gaps()) == [
        "lib/d.c", "lib/d.c", "lib/d.c"
    ]


def test_limits_order():
    areas = ["file-lib/sub/a.c", "per-file", "file-lib/*", "overall"]
    assert sorted(
        ((area, None) for area in areas),
        key=testaggregator._limits_order) == [("overall", None),
                                              ("per-file", None),
                                              ("file-lib/*", None),
                                              ("file-lib/sub/a.c", None)]


class _GapItem(dict):

    def __init__(self, uid, file_path, may_be_covered):
        super().__init__({
            "areas": {
                "Scope": {
                    file_path: {
                        "branches": [],
                        "functions": [],
                        "lines": [{
                            "line": 10,
                            "md5": "d0"
                        }]
                    }
                }
            }
        })
        if may_be_covered is not None:
            self["may-be-covered"] = may_be_covered
        self.uid = uid
        self.type = "verification/code-coverage-gap"


class _GapTarget:
    uid = "/target/simulator"

    def __init__(self, gaps):
        self._gaps = gaps

    def parents(self, _role):
        return self._gaps

    def children(self, _role):
        return []


def test_gather_gaps_which_may_be_covered():
    verifications = {}
    may_be_covered = set()
    testaggregator._gather_coverage_gap_verifications(
        "/pkg/aggregate",
        _GapTarget([
            _GapItem("/gap/a", "src/a.c", True),
            _GapItem("/gap/b", "src/b.c", False),
            _GapItem("/gap/c", "src/c.c", None)
        ]), verifications, may_be_covered)
    assert may_be_covered == {"/gap/a"}
    assert verifications == {
        "Scope": {
            "src/a.c": {
                "line/10": ("/gap/a", "d0")
            },
            "src/b.c": {
                "line/10": ("/gap/b", "d0")
            },
            "src/c.c": {
                "line/10": ("/gap/c", "d0")
            }
        }
    }


def test_covered_gap_which_may_be_covered():
    limits_by_area = {"overall": _limits(0.0), "per-file": _limits(0.0)}
    coverage = {
        "files": [_file_coverage("src/a.c", 1),
                  _file_coverage("src/b.c", 1)],
        "html-directory": "html",
        "limits-by-area": limits_by_area,
        "may-be-covered": ["/gap/a"],
        "scope": "Scope",
        "target-uid": "/target/simulator",
        "verifications": {
            "src/a.c": {
                "line/10": ("/gap/a", "d0")
            },
            "src/b.c": {
                "line/10": ("/gap/b", "d0")
            }
        }
    }
    summary = testaggregator._CoverageSummary(_Aggregator(), coverage)
    unrelated = summary.issues["Unrelated code coverage justifications"]
    assert {subject.text.replace("\u200b", "")
            for subject in unrelated} == {"spec:/gap/b"}
    coverage["verifications"] = {"src/a.c": {"line/10": ("/gap/a", "d0")}}
    summary = testaggregator._CoverageSummary(_Aggregator(), coverage)
    assert "Unrelated code coverage justifications" not in summary.issues
