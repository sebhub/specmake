# SPDX-License-Identifier: BSD-2-Clause
""" Analyses aggregated test results. """

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

from contextlib import contextmanager
import functools
import itertools
import os
import re
from typing import (Any, Callable, Iterable, Iterator, NamedTuple,
                    TYPE_CHECKING)

if TYPE_CHECKING:
    from .testaggregator import TestAggregator  # pragma: no cover

VERDICTS = ("passed", "expected-failures", "unexpected-failures",
            "unexpected-passes")

ERRORS = {
    "no-begin-of-test-message":
    "The test output contains no begin of test message.",
    "no-end-of-test-message":
    "The test output contains no end of test message.",
    "test-runner-error":
    "The test runner reported an error.",
    "unexpected-bsp":
    "The BSP has not the expected name.",
    "unexpected-build":
    "At least one build configuration option has not the expected value "
    "or the build configuration information is not present.",
    "unexpected-build-label":
    "The build label has not the expected value.",
    "unexpected-compiler":
    "The compiler version has not the expected value.",
    "unexpected-duration":
    "The test duration has not the expected value.",
    "unexpected-failed-steps-count":
    "The failed test steps count value is not zero.",
    "unexpected-report-hash":
    "The report hash has not the expected value.",
    "unexpected-rtems-debug":
    "The RTEMS_DEBUG build configuration option has not the expected value.",
    "unexpected-rtems-multiprocessing":
    "The RTEMS_MULTIPROCESSING build configuration option "
    "has not the expected value.",
    "unexpected-rtems-posix-api":
    "The RTEMS_POSIX_API build configuration option "
    "has not the expected value.",
    "unexpected-rtems-profiling":
    "The RTEMS_PROFILING build configuration option "
    "has not the expected value.",
    "unexpected-rtems-smp":
    "The RTEMS_SMP build configuration option has not the expected value.",
    "unexpected-runtime-maximum":
    "A maximum runtime value is greater than expected.",
    "unexpected-runtime-median":
    "A median runtime value is not in the expected interval.",
    "unexpected-runtime-minimum":
    "A minimum runtime value is less than expected.",
    "unexpected-step-count":
    "The test step count value is not positive.",
    "unexpected-target-hash":
    "The target hash has not the expected value.",
    "unexpected-tools":
    "The tools version has not the expected value.",
    "unexpected-version":
    "The RTEMS Git commit has not the expected value.",
}

COVERAGE_ISSUES = "For this target, the following code coverage issues " \
    "were present."


class ConfigRef(NamedTuple):
    """
    Locates a test error in the test report of a configuration.

    The anchor is the label of the test report section which shows the test
    error.
    """
    key: str
    anchor: str


class IssueSubject(NamedTuple):
    """ Represents a subject of a coverage issue with an optional link. """
    text: str
    link: str = ""


class TestCheck(NamedTuple):
    """
    Represents the check of a value which a test output reports.

    The line is None if the test output does not report the value.  The
    reported value is None if the line holds no value of the expected form.
    """
    key: str
    name: str
    line: int | str | None
    reported: Any
    expected: str
    ok: bool


class LimitCheck(NamedTuple):
    """ Represents the check of a runtime value against its limits. """
    kind: str
    lower_bound: float | None
    upper_bound: float | None
    value: float
    ok: bool


class InfoChecks(NamedTuple):
    """
    Represents the checks of the test information of a test output.

    A line is None if the test output has no such message.
    """
    begin: int | str | None
    end: int | str | None
    checks: list[TestCheck]


# A failure group is the configuration of a test error or the name of a
# coverage issue.  The group maps to the reasons of a test error or to the
# subjects of a coverage issue.
FailureGroups = dict[ConfigRef | str, set[str | IssueSubject]]

# The failures of a target map the UID of an item and a text to the groups.
Failures = dict[str, dict[tuple[str, str], FailureGroups]]


def check_runtime_limits(env_data: dict, limits: dict) -> list[LimitCheck]:
    """ Check the runtime values of a measurement environment. """
    lower_bound = limits["min-lower-bound"]
    value = env_data["min"]
    checks = [
        LimitCheck("minimum", lower_bound, None, value, lower_bound <= value)
    ]
    lower_bound = limits["median-lower-bound"]
    upper_bound = limits["median-upper-bound"]
    value = env_data["q2"]
    checks.append(
        LimitCheck("median", lower_bound, upper_bound, value,
                   lower_bound <= value <= upper_bound))
    upper_bound = limits["max-upper-bound"]
    value = env_data["max"]
    checks.append(
        LimitCheck("maximum", None, upper_bound, value, value <= upper_bound))
    return checks


class TestAnalysis:
    """
    Holds the analysis of aggregated test results.

    The analysis maps the data of a test output to its checks by identity.
    """

    def __init__(self) -> None:
        self.expected_failures: Failures = {}
        self.unexpected_failures: Failures = {}
        self.program_counts: dict[str, dict[str, int]] = {}
        self.info_checks_by_id: dict[int, InfoChecks] = {}
        self.checks_by_id: dict[int, list[TestCheck]] = {}
        self.limit_checks_by_id: dict[int, list[LimitCheck]] = {}

    def get_info_checks(self, report: dict) -> InfoChecks:
        """ Get the checks of the test information of the report. """
        return self.info_checks_by_id[id(report)]

    def get_checks(self, data: dict) -> list[TestCheck]:
        """ Get the checks of the test suite or test case data. """
        return self.checks_by_id[id(data)]

    def get_limit_checks(self, env_data: dict) -> list[LimitCheck]:
        """ Get the limit checks of the measurement environment data. """
        return self.limit_checks_by_id[id(env_data)]

    def get_unexpected_failures(self) -> dict[str, list[str]]:
        """ Get the UIDs of the items with unexpected failures by target. """
        return {
            target_uid: [uid_text[0] for uid_text in sorted(by_item)]
            for target_uid, by_item in sorted(self.unexpected_failures.items())
        }

    def get_unexpected_failure_reasons(
            self) -> dict[str, dict[str, list[str]]]:
        """
        Get the reasons of the unexpected failures by target and item UID.

        The reasons of a target are the names of its coverage issues.
        """
        target_to_reasons: dict[str, dict[str, list[str]]] = {}
        for target_uid, by_item in sorted(self.unexpected_failures.items()):
            reasons: dict[str, set[str]] = {}
            for uid_text, groups in by_item.items():
                reasons.setdefault(uid_text[0], set()).update(
                    _get_reasons(target_uid, uid_text, groups))
            target_to_reasons[target_uid] = {
                uid: sorted(texts)
                for uid, texts in sorted(reasons.items())
            }
        return target_to_reasons


def _get_reasons(target_uid: str, uid_text: tuple[str, str],
                 groups: FailureGroups) -> set[str]:
    if uid_text[0] == target_uid:
        return set(str(group) for group in groups)
    if groups:
        return set(
            str(reason)
            for reason in itertools.chain.from_iterable(groups.values()))
    return {uid_text[1]}


_RSB_COMMIT = re.compile(r"RSB ([^,]+),")


def _rtems_version_to_commit(version: str) -> str:
    return version.split(".")[-1]


def _rsb_version_to_commit(version: str) -> str | None:
    match = _RSB_COMMIT.search(version)
    if match is None:
        return None
    return match.group(1)


_PROPERTY_TRANSFORM: dict[str, Callable[[Any], Any]] = {
    "rtems-source-builder-version": _rsb_version_to_commit,
    "rtems-version": _rtems_version_to_commit
}


def _same(value: Any) -> Any:
    return value


def _listed(listed: bool) -> str:
    if listed:
        return "listed"
    return "not listed"


def _option(option: str, options: list[str]) -> str:
    return _listed(option in options)


def _zero_one(value: bool) -> str:
    if value:
        return "1"
    return "0"


def _is_equal(expected: str, reported: Any) -> bool:
    return reported is not None and reported == expected


def is_positive_count(value: Any) -> bool:
    """ Tell whether the reported value is a positive count. """
    try:
        return float(str(value)) > 0.0
    except ValueError:
        return False


def is_zero_count(value: Any) -> bool:
    """ Tell whether the reported value is a count of zero. """
    try:
        return int(str(value)) == 0
    except ValueError:
        return False


def get_outcome_errors(report: dict) -> list[str]:
    """
    Get the errors of the outcome of a test program.

    The errors are in the order of their weight.  A program without an error
    produced a complete test output.
    """
    errors: list[str] = []
    if report.get("error", ""):
        errors.append("test-runner-error")
    info = report.get("info", {})
    if "line-begin-of-test" not in info:
        errors.append("no-begin-of-test-message")
    if "line-end-of-test" not in info:
        errors.append("no-end-of-test-message")
    return errors


def _is_positive(_expected: str, reported: Any) -> bool:
    return is_positive_count(reported)


def _is_zero(_expected: str, reported: Any) -> bool:
    return is_zero_count(reported)


def _is_duration(_expected: str, reported: Any) -> bool:
    # The test output parser gives a question mark for an invalid duration.
    return reported != "?"


class _TestProperty(NamedTuple):
    name: str
    type: str
    expected: str


class _Analyser:
    # pylint: disable=too-many-instance-attributes

    def __init__(self, aggregator: "TestAggregator") -> None:
        self.aggregator = aggregator
        self.analysis = TestAnalysis()
        self.cache = aggregator.item.cache
        self.enabled_set = aggregator.enabled_set
        self.bsp: str = aggregator.component["bsp"]
        self.properties: dict[str, _TestProperty] = {}
        for link, _ in aggregator.input_links("test-property"):
            data = aggregator.substitute(link.data)
            self.properties[data["key"]] = _TestProperty(
                data["property-name"], data["type"], data["expected"])
        self.target_uid = ""
        self.target_hashes: list[str] = []
        self.verifications: dict[str, str] = {}
        self.config_data: dict[str, Any] = {}
        self.item_uid = ""
        self.anchor = ""

    def add_error(self, error: str) -> None:
        """ Add the test error to the failures of the current item. """
        failures = self.analysis.unexpected_failures
        text = ""
        uid = self.verifications.get(self.item_uid, None)
        if uid is not None:
            verification = self.cache[uid]
            if error in verification["acceptable-test-errors"]:
                failures = self.analysis.expected_failures
                text = verification["text"]
        failures.setdefault(self.target_uid, {}).setdefault(
            (self.item_uid, text), {}).setdefault(
                ConfigRef(self.config_data["config-key"], self.anchor),
                set()).add(ERRORS[error])

    # pylint: disable=too-many-arguments
    # pylint: disable=too-many-positional-arguments
    def check(self,
              checks: list[TestCheck],
              info: dict,
              name: str,
              key: str,
              expected: str,
              transform: Callable[[Any], Any] = _same,
              is_ok: Callable[[str, Any], bool] = _is_equal) -> None:
        """ Check the reported value. """
        try:
            line = info[f"line-{key}"]
        except KeyError:
            line = None
            reported = None
            ok = False
        else:
            reported = transform(info[key])
            ok = is_ok(expected, reported)
        if not ok:
            self.add_error(f"unexpected-{key}")
        checks.append(TestCheck(key, name, line, reported, expected, ok))

    def check_property(self, checks: list[TestCheck], info: dict, key: str,
                       property_key: str) -> None:
        """ Check the reported value against the test property. """
        prop = self.properties[property_key]
        self.check(checks, info, prop.name, key, prop.expected,
                   _PROPERTY_TRANSFORM.get(prop.type, _same))

    def is_target_hash(self, _expected: str, reported: Any) -> bool:
        """ Check the target hash. """
        return not reported or reported in self.target_hashes

    def check_test_info(self, report: dict) -> None:
        """ Check the test information of the report. """
        info = report["info"]
        for error in get_outcome_errors(report):
            self.add_error(error)
        begin = info.get("line-begin-of-test", None)
        end = info.get("line-end-of-test", None)
        checks: list[TestCheck] = []
        self.check_property(checks, info, "version", "rtems-commit")
        for option in ("RTEMS_DEBUG", "RTEMS_MULTIPROCESSING",
                       "RTEMS_PARAVIRT", "RTEMS_POSIX_API", "RTEMS_PROFILING",
                       "RTEMS_SMP"):
            self.check(checks, info, option, "build",
                       _listed(option in self.enabled_set),
                       functools.partial(_option, option))
        self.check_property(checks, info, "tools", "compiler-version")
        self.analysis.info_checks_by_id[id(report)] = InfoChecks(
            begin, end, checks)

    def check_counts(self, checks: list[TestCheck], info: dict) -> None:
        """ Check the step counts and the duration. """
        self.check(checks, info, "Step Count", "step-count", "> 0", _same,
                   _is_positive)
        self.check(checks, info, "Failed Steps Count", "failed-steps-count",
                   "0", _same, _is_zero)
        self.check(checks, info, "Duration", "duration", ">= 0", _same,
                   _is_duration)

    def check_test_suite(self, suite_data: dict) -> None:
        """ Check the test suite information. """
        info = suite_data["report"]["test-suite"]
        checks: list[TestCheck] = []
        self.check_property(checks, info, "compiler", "compiler-version")
        self.check_property(checks, info, "version", "rtems-commit")
        self.check(checks, info, "BSP", "bsp", self.bsp)
        self.check(checks, info, "Build Label", "build-label",
                   self.config_data["build-label"])
        self.check(checks, info, "Target Hash", "target-hash",
                   ", ".join(self.target_hashes), _same, self.is_target_hash)
        for option in ("debug", "multiprocessing", "posix-api", "profiling",
                       "smp"):
            key = f"rtems-{option}"
            name = key.replace("-", "_").upper()
            self.check(checks, info, name, key,
                       _zero_one(name in self.enabled_set), _zero_one)
        self.check_counts(checks, info)
        self.check(checks, info, "Report Hash", "report-hash",
                   info["report-hash-calculated"])
        self.analysis.checks_by_id[id(suite_data)] = checks

    def check_runtime_measurements(self, suite_data: dict) -> None:
        """ Check the runtime measurements against their limits. """
        limits_by_req = self.config_data["target"]["limits-by-requirement"]
        for req_uid, measurement_data in sorted(
                suite_data["runtime-measurements"].items()):
            self.anchor = measurement_data["label"]
            limits = limits_by_req[req_uid]
            for env_name, env_data in sorted(
                    measurement_data["variants"].items()):
                checks = check_runtime_limits(env_data, limits[env_name])
                for check in checks:
                    if not check.ok:
                        self.add_error(f"unexpected-runtime-{check.kind}")
                self.analysis.limit_checks_by_id[id(env_data)] = checks

    def check_test_cases(self, suite_data: dict) -> None:
        """ Check the test cases of the test suite. """
        for case_uid, case_data in sorted(suite_data["test-cases"].items()):
            self.item_uid = case_uid
            self.anchor = case_data["label"]
            checks: list[TestCheck] = []
            self.check_counts(checks, case_data)
            self.analysis.checks_by_id[id(case_data)] = checks

    def _count_failures(self, failures: Failures) -> int:
        return sum(
            len(texts)
            for groups in failures.get(self.target_uid, {}).values()
            for texts in groups.values())

    @contextmanager
    def program_scope(self, uids: Iterable[str]) -> Iterator[None]:
        """
        Open a scope which counts the test program by its verdict.

        A program which reports no failure is an unexpected pass if a
        verification of the program or of one of its test cases expects a
        failure.
        """
        analysis = self.analysis
        unexpected = self._count_failures(analysis.unexpected_failures)
        expected = self._count_failures(analysis.expected_failures)
        yield
        if self._count_failures(analysis.unexpected_failures) > unexpected:
            verdict = "unexpected-failures"
        elif self._count_failures(analysis.expected_failures) > expected:
            verdict = "expected-failures"
        elif any(uid in self.verifications for uid in uids):
            verdict = "unexpected-passes"
        else:
            verdict = "passed"
        counts = analysis.program_counts.setdefault(self.target_uid,
                                                    dict.fromkeys(VERDICTS, 0))
        counts[verdict] += 1

    def analyse_test_suites(self) -> None:
        """ Analyse the test suites of the configuration. """
        for suite_uid, suite_data in sorted(
                self.config_data["test-suites"].items()):
            with self.program_scope([suite_uid, *suite_data["test-cases"]]):
                self.item_uid = suite_uid
                self.anchor = suite_data["label"]
                self.check_test_info(suite_data["report"])
                self.check_test_suite(suite_data)
                self.check_runtime_measurements(suite_data)
                self.check_test_cases(suite_data)

    def analyse_test_programs(self) -> None:
        """ Analyse the test programs and the other programs. """
        for uid, report in sorted(self.config_data["test-programs"].items()):
            with self.program_scope([uid]):
                self.item_uid = uid
                self.anchor = os.path.basename(report["report-file"])
                self.check_test_info(report)
        for _ in self.config_data["other-programs"]:
            with self.program_scope([]):
                pass

    def check_validations_by_test(self) -> None:
        """
        Check that each validation by test has a test result for the target.
        """
        for item in self.aggregator.spec.related_validations_by_test:
            if self.target_uid in item.view.get("test-results", {}):
                continue
            text = "There are no test results available for this target."
            verification_uid = self.verifications.get(item.uid, None)
            failures = self.analysis.unexpected_failures
            if verification_uid is not None:
                verification = self.cache[verification_uid]
                if "no-test-results" in verification["acceptable-test-errors"]:
                    failures = self.analysis.expected_failures
                    text = verification["text"]
            failures.setdefault(self.target_uid, {}).setdefault(
                (item.uid, text), {})

    def analyse_targets(self) -> None:
        """ Analyse the test results of each target. """
        for target_uid, target_data in self.aggregator.targets.items():
            self.target_uid = target_uid
            self.target_hashes = list(target_data["target-hash"])
            self.verifications = target_data["test-error-verifications"]
            for config_data in target_data["configs"]:
                self.config_data = config_data
                self.analyse_test_suites()
                self.analyse_test_programs()
            self.check_validations_by_test()

    def analyse_coverage(self) -> None:
        """ Analyse the code coverage of each target. """
        aggregator = self.aggregator
        anchors = aggregator.anchor_target_uids()
        for target_uid, target_data in aggregator.targets.items():
            issues = aggregator.get_coverage_issues(target_uid)
            not_run_scopes = set(
                IssueSubject(f"Scope - {coverage['scope']}")
                for config_data in target_data["configs"]
                for coverage in config_data.get("coverage", [])
                if coverage.get("not-run-groups", []))
            if not_run_scopes and not anchors:
                issues.setdefault(
                    "Coverage limits met only with an excluded test, and no "
                    "target gives complete evidence",
                    set()).update(not_run_scopes)
            if issues:
                groups: FailureGroups = {}
                for issue, subjects in issues.items():
                    group: set[str | IssueSubject] = set(subjects)
                    groups[issue] = group
                self.analysis.unexpected_failures.setdefault(
                    target_uid, {})[(target_uid, COVERAGE_ISSUES)] = groups


def analyse(aggregator: "TestAggregator") -> TestAnalysis:
    """ Analyse the test results of the test aggregator. """
    analyser = _Analyser(aggregator)
    analyser.analyse_targets()
    analyser.analyse_coverage()
    return analyser.analysis
