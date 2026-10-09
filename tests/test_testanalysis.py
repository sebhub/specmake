# SPDX-License-Identifier: BSD-2-Clause
""" Tests for the testanalysis module. """

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

from pathlib import Path

from specitems import EmptyItem

from specmake.testaggregator import _judge, _update_measurement_status
from specmake.testanalysis import (ConfigRef, Expectation, LimitCheck,
                                   TestAnalysis, TestCheck,
                                   check_runtime_limits, expect,
                                   get_count_errors, get_outcome_errors,
                                   get_test_state)

from .util import create_package

TestAnalysis.__test__ = False
TestCheck.__test__ = False

_LIMITS = {
    "min-lower-bound": 1.0,
    "median-lower-bound": 2.0,
    "median-upper-bound": 3.0,
    "max-upper-bound": 4.0
}


def test_check_runtime_limits():
    assert check_runtime_limits({
        "min": 1.0,
        "q2": 2.0,
        "max": 4.0
    }, _LIMITS) == [
        LimitCheck("minimum", 1.0, None, 1.0, True),
        LimitCheck("median", 2.0, 3.0, 2.0, True),
        LimitCheck("maximum", None, 4.0, 4.0, True)
    ]
    assert [
        check.ok
        for check in check_runtime_limits({
            "min": 0.5,
            "q2": 3.5,
            "max": 4.5
        }, _LIMITS)
    ] == [False, False, False]


def _verification(errors):
    item = EmptyItem()
    item["acceptable-test-errors"] = errors
    item["text"] = "Verified."
    return item


def test_expect():
    accepts = _verification(["unexpected-bsp"])
    # A verification decides, whatever the state of the test program.
    assert expect("unexpected-bsp", accepts,
                  "EXPECTED_PASS") == Expectation(True, "Verified.")
    assert expect("unexpected-step-count", accepts,
                  "EXPECTED_FAIL") == Expectation(False, "")
    # Without a verification, a tolerated state decides.
    assert expect("unexpected-step-count", None, "EXPECTED_FAIL") == \
        Expectation(True, "The test program reports the EXPECTED_FAIL state.")
    assert expect("unexpected-step-count", None,
                  "EXPECTED_PASS") == Expectation(False, "")


def test_outcome_errors():
    assert get_outcome_errors({
        "error": "timeout",
        "info": {}
    }) == [
        "test-runner-error", "no-begin-of-test-message",
        "no-end-of-test-message"
    ]
    assert get_outcome_errors(
        {"info": {
            "line-begin-of-test": 1,
            "line-end-of-test": 2
        }}) == []
    assert get_count_errors(
        {}) == ["unexpected-step-count", "unexpected-failed-steps-count"]
    assert get_count_errors({"step-count": 3, "failed-steps-count": 0}) == []
    assert get_test_state({"info": {"state": "EXPECTED_FAIL\n"}}) == \
        "EXPECTED_FAIL"
    assert get_test_state({}) == ""


def test_judge():
    assert _judge([], None, "") == "P"
    assert _judge(["unexpected-step-count"], None, "EXPECTED_FAIL") == "X"
    assert _judge(["unexpected-step-count"], None, "") == "F"
    assert _judge(["unexpected-bsp", "unexpected-step-count"],
                  _verification(["unexpected-bsp"]), "EXPECTED_FAIL") == "F"


def test_update_measurement_status():
    env_data = {"min": 0.5, "q2": 2.0, "max": 4.0}
    measurement_data = {"status": "P"}
    _update_measurement_status(measurement_data, env_data, _LIMITS,
                               _verification(["unexpected-runtime-minimum"]),
                               "")
    assert measurement_data["status"] == "X"
    _update_measurement_status(measurement_data, {
        "min": 1.0,
        "q2": 2.0,
        "max": 4.0
    }, _LIMITS, None, "")
    assert measurement_data["status"] == "X"
    _update_measurement_status(measurement_data, env_data, _LIMITS, None, "")
    assert measurement_data["status"] == "F"


def test_testanalysis(caplog, tmpdir):
    package = create_package(caplog, Path(tmpdir), Path("spec-packagebuild"),
                             ["aggregate-test-results"])
    uid = "/pkg/steps/aggregate-test-results"
    director = package.director
    director.build_package(only=[uid])
    aggregator = director[uid]
    analysis = aggregator.get_analysis()
    target = "/rtems/target-a"
    assert analysis.program_counts == {
        target: {
            "expected-failures": 0,
            "passed": 3,
            "unexpected-failures": 12,
            "unexpected-passes": 0
        }
    }
    failures = analysis.get_unexpected_failures()[target]
    assert "/testsuites/test-suite-pass" in failures
    assert target in failures
    reasons = analysis.get_unexpected_failure_reasons()[target]
    assert reasons["/testsuites/test-suite-pass"] == [
        "The BSP has not the expected name.",
        "The RTEMS Git commit has not the expected value.",
        "The build label has not the expected value.",
        "The compiler version has not the expected value.",
        "The target hash has not the expected value.",
        "The tools version has not the expected value."
    ]
    assert "Insufficient overall line coverage" in reasons[target]

    # A failure of an acceptable test error is an expected failure.
    by_item = analysis.expected_failures[target]
    groups = by_item[("/rtems/val/test-case-xfail",
                      "This test failure is expected to fail.\n")]
    anchor = "ABuildConfigKeyTestsuitesTestSuiteXfailRtemsValTestCaseXfail"
    assert groups == {
        ConfigRef("build-config-key", anchor):
        {"The failed test steps count value is not zero."}
    }

    target_data = aggregator.targets[target]
    suites = target_data["configs"][0]["test-suites"]
    suite_data = suites["/testsuites/test-suite-pass"]
    checks = {check.key: check for check in analysis.get_checks(suite_data)}
    assert checks["bsp"] == TestCheck("bsp", "BSP", 18, "gr740", "gr712rc",
                                      False)
    assert checks["version"].reported == \
        "4260848f3a16b15a8e807d6d45f268b103aee79c"
    assert checks["step-count"].ok
    info = analysis.get_info_checks(suite_data["report"])
    assert info.begin is not None
    assert info.end is not None

    # The output of the failed test suite has no end of test message.
    suite_data = suites["/testsuites/test-suite-fail"]
    info = analysis.get_info_checks(suite_data["report"])
    assert info.begin is not None
    assert info.end is None
