# SPDX-License-Identifier: BSD-2-Clause
""" Converts test reports to the Common Test Report Format. """

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

import datetime
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as metadata_version
import os
from typing import Any, Iterable, Optional

from specitems import CommonMarkContent

from .testanalysis import get_outcome_errors, is_zero_count

CTRF_REPORT_FORMAT = "CTRF"

# The version of the Common Test Report Format specification this module
# follows.  The specification requires it in the MAJOR.MINOR.PATCH form, so it
# cannot be the version of this package.
CTRF_SPEC_VERSION = "1.0.0"

CTRF_PASSED = "passed"
CTRF_FAILED = "failed"
CTRF_SKIPPED = "skipped"

# The value a test log uses for something a test did not report
_UNREPORTED = "?"

_OUTCOME_MESSAGES = {
    "no-begin-of-test-message": "no begin of test message",
    "no-end-of-test-message": "no end of test message"
}

# The count of test output lines of the trace of a failed test
_MAX_TRACE_LINES = 40

_Data = dict[str, Any]


def ctrf_milliseconds(seconds: float | str) -> int:
    """
    Convert a duration in seconds to whole milliseconds.

    A test which reported no duration has the unreported marker instead of a
    number, which is a duration of zero.  Any other value is invalid and raises
    a ValueError.
    """
    if seconds == _UNREPORTED:
        return 0
    return int(round(float(seconds) * 1000.0))


def ctrf_epoch_milliseconds(time_stamp: str) -> int:
    """
    Convert an ISO 8601 time stamp to milliseconds since the epoch.

    A time stamp without a time zone is an UTC time stamp.  An empty time stamp
    is an unknown instant, which is the epoch.  Any other value is invalid and
    raises a ValueError.
    """
    if not time_stamp:
        return 0
    value = datetime.datetime.fromisoformat(time_stamp)
    if value.tzinfo is None:
        value = value.replace(tzinfo=datetime.timezone.utc)
    return int(round(value.timestamp() * 1000.0))


def _trace(report: _Data, begin: int, end: Optional[int] = None) -> str:
    """
    Get the test output from line begin up to and including line end.

    Without an end the trace runs to the end of the output.  The lines of a
    data range hold base64 encoded data, so leave them out.  Keep only the last
    lines, since the reason of a failure shows at the end of the output.
    """
    output = report.get("output", [])
    stop = len(output) if end is None else end + 1
    ranges = report.get("data-ranges", [])
    lines = [
        line for index, line in enumerate(output[begin:stop], begin)
        if not any(low <= index <= high for low, high in ranges)
    ]
    if len(lines) > _MAX_TRACE_LINES:
        lines = ["[...]"] + lines[-_MAX_TRACE_LINES:]
    return "\n".join(lines)


def _steps_message(data: _Data) -> str:
    failed = data.get("failed-steps-count", _UNREPORTED)
    total = data.get("step-count", _UNREPORTED)
    if failed == _UNREPORTED:
        return "the test steps are incomplete"
    return f"{failed} of {total} test steps failed"


def _test_suite_error(test_suite: _Data) -> str:
    """
    Get the reason why the test suite report is not clean.

    The failed test steps of a test suite include those of its test cases.  A
    test case reports its own failed steps, so only the difference needs a test
    for the executable, otherwise a failed test case is reported twice.
    """
    failed = test_suite.get("failed-steps-count", _UNREPORTED)
    if failed == _UNREPORTED:
        return _steps_message(test_suite)
    accounted = sum(
        test_case["failed-steps-count"]
        for test_case in test_suite["test-cases"]
        if test_case.get("failed-steps-count", _UNREPORTED) != _UNREPORTED)
    if failed > accounted:
        total = test_suite.get("step-count", _UNREPORTED)
        return (f"{failed - accounted} of {total} test steps failed "
                "outside a test case")
    return ""


def _executable_error(report: _Data) -> str:
    """
    Get the reason why the executable did not produce a valid test result.

    Return an empty string if the executable produced a valid test result, or
    if the test cases of the executable already report every failed test step.
    """
    errors = get_outcome_errors(report)
    if errors:
        if errors[0] == "test-runner-error":
            return report["error"]
        return _OUTCOME_MESSAGES[errors[0]]
    test_suite = report.get("test-suite", None)
    if test_suite is None:
        return ""
    return _test_suite_error(test_suite)


def _add_trace(test: _Data,
               report: _Data,
               begin: int,
               end: Optional[int] = None) -> None:
    """ Add the test output of the failure to the test. """
    trace = _trace(report, begin, end)
    if trace:
        test["trace"] = trace


def _add_retries(test: _Data, report: _Data) -> None:
    retries = len(report.get("failed-attempts", []))
    if not retries:
        return
    test["retries"] = retries
    test["flaky"] = test["status"] == CTRF_PASSED


def _add_extra(test: _Data, extra: _Data) -> None:
    """
    Add the extra attributes which have a value to the test.

    A test log uses the unreported marker for a value which the test did not
    report.  An absent attribute says the same with less noise.
    """
    test["extra"] = {
        key: value
        for key, value in extra.items() if value not in ("", _UNREPORTED)
    }


def _test_case_to_test(report: _Data, test_suite: _Data, test_case: _Data,
                       start: int) -> _Data:
    duration = ctrf_milliseconds(test_case.get("duration", 0.0))
    failed_steps = test_case.get("failed-steps-count", _UNREPORTED)
    test: _Data = {
        "name": test_case["name"],
        "status": CTRF_PASSED if is_zero_count(failed_steps) else CTRF_FAILED,
        "duration": duration,
        "suite": [test_suite["name"]],
        "filePath": os.path.basename(report["executable"]),
        "start": start,
        "stop": start + duration
    }
    if test["status"] == CTRF_FAILED:
        test["message"] = _steps_message(test_case)
        _add_trace(test, report, test_case["line-begin"],
                   test_case["line-end"])
    _add_retries(test, report)
    _add_extra(
        test, {
            "executable": report["executable"],
            "spec-uid": test_case.get("uid", ""),
            "step-count": test_case.get("step-count", _UNREPORTED),
            "failed-steps-count": failed_steps
        })
    return test


def _executable_to_test(report: _Data, error: str, spec_uid: str) -> _Data:
    info = report.get("info", {})
    test_suite = report.get("test-suite", {})
    duration = ctrf_milliseconds(report.get("duration", 0.0))
    start = ctrf_epoch_milliseconds(report.get("start-time", ""))
    test: _Data = {
        "name": os.path.basename(report["executable"]),
        "status": CTRF_FAILED if error else CTRF_PASSED,
        "duration": duration,
        "filePath": os.path.basename(report["executable"]),
        "start": start,
        "stop": start + duration
    }
    suite = test_suite.get("name", "") or info.get("name", "")
    if suite:
        test["suite"] = [suite]
    if error:
        test["message"] = error
        _add_trace(test, report, info.get("line-begin-of-test", 0))
    _add_retries(test, report)
    _add_extra(
        test, {
            "executable": report["executable"],
            "spec-uid": spec_uid or test_suite.get("uid", ""),
            "step-count": test_suite.get("step-count", _UNREPORTED),
            "failed-steps-count": test_suite.get("failed-steps-count",
                                                 _UNREPORTED)
        })
    return test


def report_to_ctrf_tests(report: _Data, spec_uid: str = "") -> list[_Data]:
    """
    Convert a test report of one executable to a list of CTRF tests.

    A report of a test suite contributes one test per test case.  A report
    which did not produce a valid test result contributes in addition a test
    for the executable itself, so that a test suite which stopped in the middle
    is not silently reduced to the test cases which completed.  A test suite
    which ran to its end contributes a test for the executable only for the
    failed test steps which none of its test cases accounts for, so that a
    failed test case is not reported twice.  A report without a test suite
    contributes exactly one test for the executable.

    The test log provides no time stamp for an individual test case.  The start
    of a test case is the start of the report plus the durations of the
    preceding test cases.  The order of the test cases is exact, the instants
    are approximations.

    An executable which did not run has no command line list.  The test runner
    of the package build uses an empty command line string for it.
    """
    if not isinstance(report.get("command-line", None), list):
        return [{
            "name": os.path.basename(report["executable"]),
            "status": CTRF_SKIPPED,
            "duration": 0,
            "filePath": os.path.basename(report["executable"]),
            "message": "the executable did not run",
            "extra": {
                "executable": report["executable"]
            }
        }]
    tests: list[_Data] = []
    test_suite = report.get("test-suite", None)
    if test_suite is not None:
        start = ctrf_epoch_milliseconds(report.get("start-time", ""))
        for test_case in test_suite["test-cases"]:
            test = _test_case_to_test(report, test_suite, test_case, start)
            start = test["stop"]
            tests.append(test)
    error = _executable_error(report)
    if error or not tests:
        tests.append(_executable_to_test(report, error, spec_uid))
    return tests


def make_ctrf_summary(tests: Iterable[_Data], start: int, stop: int) -> _Data:
    """
    Make the CTRF summary of the tests.

    The summary contains the tests, so the start and stop of the summary widen
    to the start and stop of the tests.  A test log which reused the reports of
    a previous run has tests which ran before the log started.

    The suite count is the count of the distinct suites of the tests.  A test
    without a suite belongs to none of them.

    The summary has no run duration.  A test log which reused the reports of a
    previous run spans the time from the oldest report to the newest one, which
    is no duration of a test run.
    """
    summary = {
        "tests": 0,
        "passed": 0,
        "failed": 0,
        "pending": 0,
        "skipped": 0,
        "other": 0,
        "flaky": 0,
        "start": start,
        "stop": stop
    }
    suites = set()
    for test in tests:
        summary["tests"] += 1
        summary[test["status"]] += 1
        if test.get("flaky", False):
            summary["flaky"] += 1
        suites.add(tuple(test.get("suite", [])))
        test_start = test.get("start", 0)
        if test_start:
            if summary["start"]:
                summary["start"] = min(summary["start"], test_start)
            else:
                summary["start"] = test_start
            summary["stop"] = max(summary["stop"], test["stop"])
    suites.discard(tuple())
    summary["suites"] = len(suites)
    return summary


def _make_environment(environment: _Data) -> _Data:
    """
    Make the CTRF environment of the values.

    Drop a value which is empty, so that an unknown value is absent instead of
    empty.
    """
    return {key: value for key, value in environment.items() if value}


def make_ctrf_report(tests: list[_Data],
                     tool_version: str,
                     start: int = 0,
                     stop: int = 0,
                     environment: Optional[_Data] = None) -> _Data:
    """
    Make a CTRF report of the tests.

    The specification version is the version of the Common Test Report Format
    which this module follows.  The version of this package is the version of
    the tool.
    """
    results: _Data = {
        "tool": {
            "name": "specmake",
            "version": tool_version
        },
        "summary": make_ctrf_summary(tests, start, stop),
        "tests": tests
    }
    if environment:
        results["environment"] = _make_environment(environment)
    return {
        "reportFormat": CTRF_REPORT_FORMAT,
        "specVersion": CTRF_SPEC_VERSION,
        "results": results
    }


def convert_test_log(test_log: _Data,
                     tool_version: str,
                     environment: Optional[_Data] = None) -> _Data:
    """ Convert a test log to a CTRF report. """
    tests: list[_Data] = []
    for report in test_log.get("reports", []):
        tests.extend(report_to_ctrf_tests(report))
    return make_ctrf_report(
        tests, tool_version,
        ctrf_epoch_milliseconds(test_log.get("start-time", "")),
        ctrf_epoch_milliseconds(test_log.get("end-time", "")), environment)


def get_ctrf_tool_version() -> str:
    """ Get the version of this package. """
    try:
        return metadata_version("specmake")
    except PackageNotFoundError:
        return "unknown"


def _cell(text: Any) -> str:
    """
    Get the value as a table cell.

    An absent value is an empty cell.  The content escapes the cell separator.
    """
    return "" if text is None else str(text)


def ctrf_markdown_summary(report: _Data, max_failures: int = 50) -> str:
    """
    Get a short summary of the CTRF report in CommonMark.

    The summary lists at most max_failures failed tests and states how many it
    left out.  A test log of a test runner which ran no test at all has a
    failed test for each executable, which is not a short summary.
    """
    results = report["results"]
    summary = results["summary"]
    # The summary goes to the standard output and states no license.
    content = CommonMarkContent(context="CC-BY-SA-4.0")
    content.add_header("Test results")
    content.add_simple_table([["Tests", "Passed", "Failed", "Skipped"],
                              [
                                  _cell(summary["tests"]),
                                  _cell(summary["passed"]),
                                  _cell(summary["failed"]),
                                  _cell(summary["skipped"])
                              ]])
    failures = [
        test for test in results["tests"] if test["status"] == CTRF_FAILED
    ]
    if failures:
        content.add_header("Failures", 1)
        rows = [["Test", "Suite", "Reason"]]
        rows.extend([
            _cell(test["name"]),
            _cell(" / ".join(test.get("suite", []))),
            _cell(test.get("message"))
        ] for test in failures[:max_failures])
        content.add_simple_table(rows)
        left_out = len(failures) - max_failures
        if left_out > 0:
            content.add(f"{left_out} more failed tests are not listed.")
    return str(content)
