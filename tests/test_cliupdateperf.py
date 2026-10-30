# SPDX-License-Identifier: BSD-2-Clause
""" Tests the command to update the performance limits. """

# Copyright (C) 2026 embedded brains GmbH & Co. KG
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

import json
from pathlib import Path

import yaml

from specmake.cliupdateperf import cliupdateperf

_HEADER = """SPDX-License-Identifier: CC-BY-SA-4.0 OR BSD-2-Clause
copyrights:
- Copyright (C) 2026 embedded brains GmbH & Co. KG
enabled-by: true
"""

_PERF = _HEADER + """links: []
non-functional-type: performance-runtime
requirement-type: non-functional
type: requirement
"""

_ITEMS = {
    "req/perf":
    _PERF,
    "req/other":
    _PERF,
    "req/quality":
    _HEADER + """links: []
non-functional-type: quality
requirement-type: non-functional
type: requirement
""",
    "req/func":
    _HEADER + """links: []
requirement-type: functional
type: requirement
""",
    "glossary":
    _HEADER + """links: []
type: glossary
""",
    "limits":
    _HEADER + """links:
- role: requirement-refinement
  uid: req/func
- limits:
    Wide:
      max-upper-bound: 9.0
      median-lower-bound: 1.0
      median-upper-bound: 9.0
      min-lower-bound: 1.0
    Narrow:
      max-upper-bound: 5.0
      median-lower-bound: 5.0
      median-upper-bound: 3.0
      min-lower-bound: 5.0
  role: performance-runtime-limits
  uid: /req/perf
type: performance-runtime-limits-provider
""",
}


def _spec_directory(tmp_path: Path) -> Path:
    directory = tmp_path / "spec"
    for name, text in _ITEMS.items():
        path = directory / f"{name}.yml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return directory


def _measurement(name: str, variant: str, minimum: float, median: float,
                 maximum: float) -> dict:
    return {
        "name": name,
        "variant": variant,
        "min": minimum,
        "q2": median,
        "max": maximum
    }


def _report(tmp_path: Path, reports: list[dict]) -> str:
    path = tmp_path / "report.json"
    path.write_text(json.dumps({"reports": reports}), encoding="utf-8")
    return str(path)


def _update(tmp_path: Path, reports: list[dict], *extra: str) -> dict:
    spec = _spec_directory(tmp_path)
    cliupdateperf([
        "specupdateperf", "--spec-directory",
        str(spec), "--cache-directory",
        str(tmp_path / "cache"), *extra, "/limits",
        _report(tmp_path, reports)
    ])
    data = yaml.safe_load((spec / "limits.yml").read_text(encoding="utf-8"))
    return {
        link["uid"]: link["limits"]
        for link in data["links"]
        if link["role"] == "performance-runtime-limits"
    }


def _perf_report(measurements: list[dict]) -> dict:
    return {
        "executable": "build/ts-performance-0.exe",
        "info": {},
        "test-suite": {
            "test-cases": [{
                "runtime-measurements": measurements
            }]
        }
    }


def _bounds(minimum: float, median: float, maximum: float) -> dict:
    return {
        "max-upper-bound": 1.5 * maximum,
        "median-lower-bound": 0.5 * median,
        "median-upper-bound": 1.5 * median,
        "min-lower-bound": 0.5 * minimum
    }


_SCALERS = ("--lower-bound-scaler", "0.5", "--upper-bound-scaler", "1.5")


def test_the_limits_follow_the_measurements(tmp_path):
    limits = _update(tmp_path, [
        _perf_report([
            _measurement("ReqPerf", "Wide", 2.0, 4.0, 8.0),
            _measurement("ReqOther", "Fresh", 2.0, 4.0, 8.0)
        ])
    ], *_SCALERS)

    # The update replaces the limits of a variant and keeps the others
    assert limits == {
        "/req/other": {
            "Fresh": _bounds(2.0, 4.0, 8.0)
        },
        "/req/perf": {
            "Narrow": {
                "max-upper-bound": 5.0,
                "median-lower-bound": 5.0,
                "median-upper-bound": 3.0,
                "min-lower-bound": 5.0
            },
            "Wide": _bounds(2.0, 4.0, 8.0)
        }
    }


def test_the_median_bounds_stay_within_the_extreme_bounds(tmp_path):
    limits = _update(
        tmp_path,
        [_perf_report([_measurement("ReqOther", "Fresh", 4.0, 2.0, 1.0)])],
        *_SCALERS)

    assert limits["/req/other"]["Fresh"] == {
        "max-upper-bound": 1.5,
        "median-lower-bound": 2.0,
        "median-upper-bound": 1.5,
        "min-lower-bound": 2.0
    }


def test_the_lazy_mode_keeps_the_limits_which_hold(tmp_path):
    limits = _update(tmp_path, [
        _perf_report([
            _measurement("ReqPerf", "Wide", 2.0, 4.0, 8.0),
            _measurement("ReqPerf", "Narrow", 2.0, 4.0, 8.0),
            _measurement("ReqOther", "Fresh", 2.0, 4.0, 8.0)
        ])
    ], "--lazy", *_SCALERS)

    assert limits == {
        "/req/other": {
            "Fresh": _bounds(2.0, 4.0, 8.0)
        },
        "/req/perf": {
            "Narrow": _bounds(2.0, 4.0, 8.0),
            "Wide": {
                "max-upper-bound": 9.0,
                "median-lower-bound": 1.0,
                "median-upper-bound": 9.0,
                "min-lower-bound": 1.0
            }
        }
    }


def test_reports_without_performance_data(tmp_path, capsys):
    limits = _update(tmp_path, [{
        "executable": "build/ts-unit.exe"
    }, {
        "executable": "build/ts-performance-1.exe",
        "info": {}
    }])

    assert capsys.readouterr().out == (
        "no performance data available for: build/ts-performance-1.exe\n")
    assert list(limits) == ["/req/perf"]


def test_a_report_without_info_gets_parsed(tmp_path):
    log = Path(__file__).parent / "test-files" / "pkg" / "test-log-perf.json"
    with open(log, "r", encoding="utf-8") as src:
        report = json.load(src)["reports"][0]
    del report["info"]
    del report["test-suite"]
    spec = tmp_path / "spec" / "rtems" / "req"
    spec.mkdir(parents=True)
    (spec / "perf.yml").write_text(_PERF, encoding="utf-8")
    limits = _update(tmp_path, [report])

    # The output of the report provides the measurements
    assert sorted(limits["/rtems/req/perf"]) == [
        "DirtyCache", "FullCache", "HotCache", "Load/1"
    ]
