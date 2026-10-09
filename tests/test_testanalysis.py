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

from specmake.testanalysis import (ConfigRef, LimitCheck, TestAnalysis,
                                   TestCheck, check_runtime_limits)

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
