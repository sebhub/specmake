# SPDX-License-Identifier: BSD-2-Clause
""" Builds test report documents. """

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

from contextlib import contextmanager
import os
import re
from typing import Iterator

from specitems import (Item, ItemGetValueContext, SphinxContent,
                       base64_to_hex_text)

from .docbuilder import DocumentBuilder
from .pkgitems import BuildItemMapper, PackageBuildDirector
from .perfimages import environment_order
from .testaggregator import TestAggregator
from .testanalysis import (ERRORS, ConfigRef, Failures, InfoChecks,
                           IssueSubject, LimitCheck, TestAnalysis, TestCheck)
from .util import duration

_NON_ORDINARY = re.compile(r"[^\x20-\x7e]")


def _escape_char(match: re.Match[str]) -> str:
    return f"\\x{ord(match.group(0)):02x}"


def _invisible_spaces(text: str) -> str:
    return "\u200b".join(iter(_NON_ORDINARY.sub(_escape_char, text)))


def _target_hash(target_hash: str) -> str:
    if not target_hash:
        return "\u200b"
    return _invisible_spaces(target_hash)


_INVISIBLE_KEYS = frozenset(
    ("bsp", "build-label", "compiler", "report-hash", "tools", "version"))

_HEADER = ["Property", "Line", "Reported", "Expected", "Status"]

_WIDTHS = [42, 8, 20, 20, 10]


def _ok(good: bool) -> str:
    if good:
        return "OK"
    return "NOK"


def _reported(check: TestCheck) -> str:
    if check.line is None:
        return "?"
    if check.key == "duration":
        return duration(check.reported)
    if check.key == "target-hash":
        return _target_hash(check.reported)
    if check.reported is None:
        return "?"
    if check.key in _INVISIBLE_KEYS:
        return _invisible_spaces(check.reported)
    return str(check.reported)


def _expected(check: TestCheck) -> str:
    if check.key == "duration":
        return ":math:`\\geq` 0"
    if check.key == "target-hash":
        return ", ".join(
            _invisible_spaces(target_hash)
            for target_hash in check.expected.split(", "))
    if check.key in _INVISIBLE_KEYS:
        return _invisible_spaces(check.expected)
    return check.expected


def _limit_row(check: LimitCheck) -> list[str]:
    if check.kind == "minimum":
        assert check.lower_bound is not None
        return [
            "Minimum", f"{duration(check.lower_bound)} :math:`\\leq` Minimum",
            duration(check.value),
            _ok(check.ok)
        ]
    if check.kind == "median":
        assert check.lower_bound is not None
        assert check.upper_bound is not None
        return [
            "Median", f"{duration(check.lower_bound)} :math:`\\leq` Median "
            f":math:`\\leq` {duration(check.upper_bound)}",
            duration(check.value),
            _ok(check.ok)
        ]
    assert check.upper_bound is not None
    return [
        "Maximum", f"Maximum :math:`\\leq` {duration(check.upper_bound)}",
        duration(check.value),
        _ok(check.ok)
    ]


def _format_group(group: ConfigRef | str) -> str:
    if isinstance(group, ConfigRef):
        return f":ref:`Configuration - {group.key} <{group.anchor}>`"
    return group


def _format_subject(mapper: BuildItemMapper,
                    subject: str | IssueSubject) -> str:
    if isinstance(subject, IssueSubject):
        if subject.link:
            return mapper.format_link(subject.text, subject.link)
        return subject.text
    return subject


class _TestContext:

    def __init__(self, reporter: "TestReporter", analysis: TestAnalysis):
        self.content = SphinxContent(context=reporter.mapper.context)
        self.mapper = reporter.mapper
        self.cache = reporter.item.cache
        self.analysis = analysis
        self.output_label = ""

    def begin_report(self, report: dict) -> None:
        """ Begins the report. """
        self.output_label = f"{self.content.get_label()}Output"
        executable = os.path.basename(report["executable"])
        self.content.add(f"""This report was produced by the
:file:`{executable}`
executable.  The executable file had an SHA512 digest of
{base64_to_hex_text(report['executable-sha512'])}.""")
        error = report.get("error")
        if error:
            with self.content.directive("error", value="Test runner error"):
                self.content.add(error)
        else:
            self.content.gap = False

    def output_line_ref(self, line: int | str) -> str:
        """ Gets the output line reference for the line. """
        if isinstance(line, str):
            return line
        return (f":ref:`{line + 1} <"
                f"{self.output_label}{line - line % 100}>`")

    def add_failures(self, which: str, failures: Failures,
                     test_aggregator: TestAggregator) -> None:
        """ Add the test failures to the content. """
        with self.content.section(f"List of {which} test failures"):
            if not failures:
                self.content.add(f"There were no {which} test errors "
                                 "found in the test outputs.")
                return
            for target_uid, by_item in failures.items():
                target_data = test_aggregator.targets[target_uid]
                target_section = f"Target - {target_data['name']}"
                with self.content.section(target_section):
                    for uid_text, groups in sorted(by_item.items()):
                        item = self.cache[uid_text[0]]
                        with self.content.section(item.spec_2):
                            self.content.add(uid_text[1])
                            for group, subjects in sorted(
                                (_format_group(group), subjects)
                                    for group, subjects in groups.items()):
                                self.content.add_list_item(f"{group}:")
                                self.content.add_blank_line()
                                with self.content.indent("  "):
                                    self.content.add_list(
                                        sorted(
                                            _format_subject(
                                                self.mapper, subject)
                                            for subject in subjects))

    def add_table(self, rows: list[list[str]], widths: list[int]) -> None:
        """ Add a table to the content with the rows and widths. """
        self.content.add_grid_table(rows, widths, font_size=-3)

    def add_checks(self, checks: list[TestCheck]) -> None:
        """ Add a table of the checks to the content. """
        rows = [_HEADER]
        for check in checks:
            line = "?" if check.line is None else self.output_line_ref(
                check.line)
            rows.append([
                check.name, line,
                _reported(check),
                _expected(check),
                _ok(check.ok)
            ])
        self.add_table(rows, _WIDTHS)

    def add_test_info(self, info_checks: InfoChecks) -> None:
        """ Add the checks of the test information to the content. """
        if info_checks.begin is None:
            self.content.wrap(ERRORS["no-begin-of-test-message"])
        else:
            begin = self.output_line_ref(info_checks.begin)
            self.content.wrap(
                f"There is a valid begin of test message at line {begin}.")
        self.content.gap = False
        if info_checks.end is None:
            self.content.wrap(ERRORS["no-end-of-test-message"])
        else:
            end = self.output_line_ref(info_checks.end)
            self.content.wrap(f"""There is a valid end of test message at line
{end}.  This indicates that the test program executed without a detected
error.""")
        self.content.gap = False
        self.content.wrap("""The following table lists an evaluation of the
reported test information.""")
        self.add_checks(info_checks.checks)

    def add_limits(self, checks: list[LimitCheck]) -> None:
        """ Add the runtime performance limits to the content. """
        rows = [["Limit Kind", "Specified Limits", "Actual Value", "Status"]]
        rows.extend(_limit_row(check) for check in checks)
        self.add_table(rows, [15, 45, 25, 15])

    @contextmanager
    def file_scope(self, file_path: str, data: dict) -> Iterator[str]:
        """ Opens a file scope. """
        file_name = os.path.basename(data["report-file"])
        self.content.add(file_name)
        content = self.content
        self.content = SphinxContent(context=content.context)
        yield file_name
        self.content.write(
            os.path.join(os.path.dirname(file_path), f"{file_name}.rst"))
        self.content = content


def _add_output(ctx: _TestContext, report: dict) -> None:
    ctx.content.add_program_output(report["output"], report["data-ranges"],
                                   ctx.output_label)


def _add_test_output(ctx: _TestContext, report: dict) -> None:
    with ctx.content.section("Test output"):
        ctx.content.add(
            "The test report was generated from the following test output.")
        _add_output(ctx, report)


class TestReporter(DocumentBuilder):
    """ Builds a test report. """

    def __init__(self, director: PackageBuildDirector, item: Item):
        super().__init__(director, item)
        if any(True for _ in self.input_links("test-property")):
            raise ValueError(
                f"{self.uid}: the test properties are inputs of the test "
                "aggregation and not of the test report")
        self.mapper.add_get_value(f"{self.item.type}:/reports", self._reports)

    def _add_image(self, ctx: _TestContext, base: str | None) -> None:
        # Only a performance images item sets the base of an image.
        if base is not None:
            ctx.content.add_image(
                os.path.relpath(f"{base}.*", os.path.dirname(self.file_path)),
                "50%")

    def _add_runtime_measurements(self, ctx: _TestContext,
                                  suite_data: dict) -> dict[str, str]:
        uid_to_label: dict[str, str] = {}
        for req_uid, measurement_data in sorted(
                suite_data["runtime-measurements"].items()):
            req = self.item.cache[req_uid]
            with ctx.content.section(f"Runtime measurement - {req.spec_2}",
                                     label=measurement_data["label"]):
                ctx.content.wrap(f"""For the runtime performance requirement
{self.mapper.get_link(req, 'test-plan')}, the following runtime values were
measured on this target and configuration in the listed measurement
environments.""")
                self._add_image(ctx, measurement_data.get("boxplot"))
                uid_to_label[req_uid] = ctx.content.get_label()
                for env_name, env_data in sorted(
                        measurement_data["variants"].items(),
                        key=environment_order):
                    ctx.content.add_label(env_data["label"])
                    ctx.content.add_rubric(
                        f"Measurement environment - {env_name}")
                    begin = ctx.output_line_ref(env_data["line-begin"])
                    end = ctx.output_line_ref(env_data["line-end"])
                    ctx.content.add(f"""The runtime measurement report for this
measurement environment was generated from lines {begin} up to and including
{end} of the test output.""")
                    self._add_image(ctx, env_data.get("histogram"))
                    ctx.add_limits(ctx.analysis.get_limit_checks(env_data))
        return uid_to_label

    def _add_remarks(self, ctx: _TestContext, remarks: list) -> None:
        if not remarks:
            return
        test_cases: list[tuple[str, str]] = []
        for remark in remarks:
            try:
                uid = remark["uid"]
            except KeyError:
                pass
            else:
                link = self.mapper.get_link(self.item.cache[uid], "test-plan")
                line = ctx.output_line_ref(remark["line"])
                test_cases.append((link, line))
        if len(test_cases) == 1:
            test_case = test_cases[0]
            ctx.content.append(f"""It runs the parameterized test case
{test_case[0]} reported in line {test_case[1]}.""")
            return
        ctx.content.append("It runs the following parameterized test cases:")
        for test_case in test_cases:
            ctx.content.add_list_item(
                f"{test_case[0]} reported in line {test_case[1]}")

    def _add_test_cases(self, ctx: _TestContext, suite_data: dict,
                        uid_to_label: dict[str, str]) -> None:
        for case_uid, case_data in sorted(suite_data["test-cases"].items()):
            case_item = self.item.cache[case_uid]
            with ctx.content.section(f"Test case - {case_item.spec_2}",
                                     label=case_data["label"]):
                ctx.content.add(f"""This test case is specified by
{self.mapper.get_link(case_item, 'test-plan')}.""")
                self._add_remarks(ctx, case_data["remarks"])
                begin = ctx.output_line_ref(case_data["line-begin"])
                end = ctx.output_line_ref(case_data["line-end"])
                ctx.content.add(f"""The following table lists an evaluation of
the test case information reported in lines {begin} up to and including {end}
of the test output.""")
                ctx.add_checks(ctx.analysis.get_checks(case_data))
                uids = set(
                    measurement_data["requirement-uid"]
                    for measurement_data in case_data["runtime-measurements"])
                if uids:
                    ctx.content.wrap("""This test case contains the
following runtime measurements presented in the preceeding sections:""")
                    for uid in sorted(uids):
                        item = self.item.cache[uid]
                        ctx.content.add_list_item(
                            f":ref:`{item.spec_2} <{uid_to_label[uid]}>`")

    def _add_one_test_suite(self, ctx: _TestContext, suite_uid: str,
                            suite_data: dict) -> None:
        suite_item = self.item.cache[suite_uid]
        suite_section = f"Test suite - {suite_item.spec_2}"
        with ctx.content.section(suite_section, label=suite_data["label"]):
            report = suite_data["report"]
            ctx.begin_report(report)
            ctx.content.wrap(f"""This test suite is specified by
{self.mapper.get_link(suite_item)}.""")
            ctx.content.gap = False
            ctx.add_test_info(ctx.analysis.get_info_checks(report))
            begin = ctx.output_line_ref(report["test-suite"]["line-begin"])
            end = ctx.output_line_ref(report["test-suite"]["line-end"])
            ctx.content.wrap(f"""The following table lists an evaluation of the
test suite information reported in lines {begin} up to and including {end} of
the test output.""")
            if suite_data["runtime-measurements"]:
                ctx.content.gap = False
                ctx.content.wrap("""The runtime measurements and test cases
of this test suite are presented in the following sections.""")
            else:
                ctx.content.gap = False
                ctx.content.wrap("""The test cases of this test suite are
presented in the following sections.""")
            ctx.add_checks(ctx.analysis.get_checks(suite_data))
            uid_to_label = self._add_runtime_measurements(ctx, suite_data)
            self._add_test_cases(ctx, suite_data, uid_to_label)
            _add_test_output(ctx, report)

    def _add_test_suites(self, ctx: _TestContext, config_data: dict) -> None:
        for suite_uid, suite_data in sorted(
                config_data["test-suites"].items()):
            with ctx.file_scope(self.file_path, suite_data):
                self._add_one_test_suite(ctx, suite_uid, suite_data)

    def _add_test_programs(self, ctx: _TestContext, config_data: dict) -> None:
        for uid, report in sorted(config_data["test-programs"].items()):
            with ctx.file_scope(self.file_path, report) as file_name:
                program_item = self.item.cache[uid]
                program_section = f"Test program - {program_item.spec_2}"
                with ctx.content.section(program_section, label=file_name):
                    ctx.begin_report(report)
                    ctx.add_test_info(ctx.analysis.get_info_checks(report))
                    for image in report.get("images", []):
                        ctx.content.add_image(
                            os.path.relpath(f"{image}.*",
                                            os.path.dirname(self.file_path)),
                            "50%")
                    _add_test_output(ctx, report)

    def _add_other_programs(self, ctx: _TestContext,
                            config_data: dict) -> None:
        for executable, report in sorted(
                config_data["other-programs"].items()):
            with ctx.file_scope(self.file_path, report) as file_name:
                program_section = f"Other program - {executable}"
                with ctx.content.section(program_section, label=file_name):
                    ctx.begin_report(report)
                    _add_output(ctx, report)

    def _add_coverage(self, ctx: _TestContext,
                      test_aggregator: TestAggregator) -> None:
        with ctx.content.section("Coverage data"):
            coverage_count = 0
            with ctx.content.directive("toctree"):
                report = {"report-file": "coverage"}
                with ctx.file_scope(self.file_path, report):
                    with ctx.content.label_scope("Coverage"):
                        for target_data in test_aggregator.targets.values():
                            target_section = f"Target - {target_data['name']}"
                            with ctx.content.section(target_section):
                                for config_data in target_data["configs"]:
                                    if "coverage" not in config_data:
                                        continue
                                    coverage_count += 1
                                    test_aggregator.add_coverage_of_config(
                                        ctx.content, self.mapper, config_data)
                        if coverage_count:
                            test_aggregator.add_coverage_across_targets(
                                ctx.content, self.mapper)
            if coverage_count == 0:
                ctx.content.add("There is no coverage data available.")

    def _reports(self, _unused: ItemGetValueContext) -> str:
        test_aggregator = self.input("test-aggregation")
        assert isinstance(test_aggregator, TestAggregator)
        analysis = test_aggregator.get_analysis()
        ctx = _TestContext(self, analysis)
        for target_data in test_aggregator.targets.values():
            with ctx.content.section(f"Target - {target_data['name']}",
                                     label=target_data["label"]):
                with ctx.content.section("Test procedure description"):
                    ctx.content.add(target_data["test-runner-description"])
                for config_data in target_data["configs"]:
                    config_key = config_data["config-key"]
                    config_section = f"Configuration - {config_key}"
                    with ctx.content.section(config_section,
                                             label=config_data["label"]):
                        with ctx.content.directive("toctree"):
                            self._add_test_suites(ctx, config_data)
                            self._add_test_programs(ctx, config_data)
                            self._add_other_programs(ctx, config_data)
        self._add_coverage(ctx, test_aggregator)
        ctx.add_failures("expected", analysis.expected_failures,
                         test_aggregator)
        ctx.add_failures("unexpected", analysis.unexpected_failures,
                         test_aggregator)
        self["unexpected-test-failures"] = analysis.get_unexpected_failures()
        self["unexpected-test-failure-reasons"] = \
            analysis.get_unexpected_failure_reasons()
        self["test-program-counts"] = analysis.program_counts
        return ctx.content.join()
