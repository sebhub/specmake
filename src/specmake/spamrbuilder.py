# SPDX-License-Identifier: BSD-2-Clause
""" Provides a builder for the software product assurance milestone report. """

# Copyright (C) 2020 EDISOFT
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

import collections
import csv
import functools
import json
import os
from typing import Any, Callable, NamedTuple, Optional
import urllib.parse

from specitems import Item, ItemGetValueContext, SphinxContent

from .directorystate import DirectoryState
from .docbuilder import DocumentBuilder
from .packagechanges import PackageChanges
from .pkgitems import BuildItem, PackageBuildDirector
from .rtems import RTEMSItemCache

# The metrics of the quality model which the report checks, in the order of
# the quality model table of the software product assurance plan.
_METRICS = (
    ("requirement-implementation-coverage",
     "Requirement implementation coverage"),
    ("requirement-completeness", "Requirement completeness"),
    ("vv-coverage", "V&V coverage"),
    ("requirement-clarity", "Requirement clarity"),
    ("documentation-suitability", "Documentation suitability"),
    ("cyclomatic-complexity", "Cyclomatic complexity (VG)"),
    ("nesting-level", "Nesting level"),
    ("lines-of-code", "Lines of code (LOC)"),
    ("comment-frequency", "Comment frequency"),
    ("requirement-testability", "Requirement testability"),
    ("spr-ncr-status", "SPR/NCR status"),
    ("safety-activities-adequacy", "Safety activities adequacy"),
    ("user-documentation-clarity", "User documentation clarity"),
    ("user-documentation-completeness", "User documentation completeness"),
    ("user-manual-suitability", "User manual suitability"),
    ("milestone-tracking", "Milestone tracking"),
    ("rid-action-status", "RID/action status"),
)

# A reviewer provides the value and the result of these metrics.
_MANUAL_METRICS = frozenset(
    ("requirement-clarity", "documentation-suitability",
     "safety-activities-adequacy", "user-documentation-clarity",
     "user-manual-suitability", "milestone-tracking"))

_PERCENT_METRICS = frozenset(("comment-frequency", "requirement-testability"))

_ANNEX_FINDINGS = {
    "clang-analyzer": "AnnexClangFindings",
    "cppcheck": "AnnexCppcheckFindings",
    "quality-scanner": "AnnexTBDTBCFindings"
}

_ANNEX_CODE_METRICS = "AnnexCodeMetrics"

_TOOL_NAMES = {
    "clang-analyzer": "Clang",
    "cppcheck": "Cppcheck",
    "quality-scanner": "QualityScanner"
}


class _Finding(NamedTuple):
    tool: str
    rule: str
    location: str
    message: str
    suppression: Optional[str]
    item: Optional[str] = None
    document: Optional[str] = None


class _Region(NamedTuple):
    path: str
    name: str
    line: int
    cyclomatic: int
    nesting: int
    code: int
    comments: int

    @property
    def comment_frequency(self) -> float:
        """ Return the comment frequency in percent. """
        total = self.code + self.comments
        return 100.0 * self.comments / total if total else 0.0


class _CodeMetrics(NamedTuple):
    functions: list[_Region]
    file_lines: dict[str, int]


def _uri_to_path(uri: str) -> str:
    if uri.startswith("file://"):
        uri = urllib.parse.urlparse(uri).path
    return urllib.parse.unquote(uri)


def _relative_path(path: str, bases: list[str]) -> str:
    for base in bases:
        if path.startswith(f"{base}/"):
            return os.path.relpath(path, base)
    return path


def _files(state: BuildItem, suffix: str) -> list[str]:
    assert isinstance(state, DirectoryState)
    return sorted(path for path in state.files() if path.endswith(suffix))


def _int(value: str) -> int:
    return int(value) if value else 0


_FILE_LINES = ("std.code.filelines:code", "std.code.filelines:preprocessor")


def _load_code_metrics(path: str, bases: list[str]) -> _CodeMetrics:
    functions: list[_Region] = []
    file_lines: dict[str, int] = {}
    with open(path, "r", encoding="utf-8", newline="") as src:
        reader = csv.DictReader(src)
        missing = [
            name for name in _FILE_LINES
            if name not in (reader.fieldnames or [])
        ]
        if missing:
            raise ValueError(
                f"{path}: the columns {missing} are missing; collect the "
                "metrics with the options --std.code.filelines.code and "
                "--std.code.filelines.preprocessor of metrix++")
        for row in reader:
            kind = row["type"]
            file_path = _relative_path(row["file"], bases)
            if kind == "file":
                # A region shares a line with its enclosing region if both
                # have code on it, so only the file metrics count each line
                # once.
                file_lines[file_path] = sum(
                    _int(row[name]) for name in _FILE_LINES)
                continue
            code = _int(row["std.code.lines:code"]) + _int(
                row["std.code.lines:preprocessor"])
            if kind == "function":
                functions.append(
                    _Region(file_path, row["region"], _int(row["line start"]),
                            _int(row["std.code.complexity:cyclomatic"]),
                            _int(row["std.code.complexity:maxindent"]), code,
                            _int(row["std.code.lines:comments"])))
    return _CodeMetrics(functions, file_lines)


def _scanner_finding(result: dict[str, Any], artifacts: list[dict[str, Any]],
                     suppression: Optional[str]) -> _Finding:
    location = result["locations"][0]
    physical = location["physicalLocation"]
    properties = artifacts[physical["artifactLocation"]["index"]]["properties"]
    uid = properties["uid"]
    if properties["kind"] == "document":
        document = f"{uid}: {properties['path']}"
        return _Finding(_TOOL_NAMES["quality-scanner"], result["ruleId"],
                        f"{document}:{physical['region']['startLine']}",
                        result["message"]["text"], suppression, None, document)
    return _Finding(_TOOL_NAMES["quality-scanner"], result["ruleId"],
                    location["logicalLocations"][0]["fullyQualifiedName"],
                    result["message"]["text"], suppression, uid, None)


def _tool_location(result: dict[str, Any], artifacts: list[dict[str, Any]],
                   bases: list[str]) -> str:
    locations = result.get("locations") or [{}]
    physical = locations[0].get("physicalLocation", {})
    artifact_location = physical.get("artifactLocation", {})
    uri = artifact_location.get("uri", None)
    if uri is None and "index" in artifact_location:
        artifact = artifacts[artifact_location["index"]]
        uri = artifact.get("location", {}).get("uri", None)
    if uri is None:
        return "-"
    file_path = _relative_path(_uri_to_path(uri), bases)
    line = physical.get("region", {}).get("startLine", None)
    return file_path if line is None else f"{file_path}:{line}"


def _load_findings(tool: str, paths: list[str],
                   bases: list[str]) -> list[_Finding]:
    findings: list[_Finding] = []
    for path in paths:
        with open(path, "r", encoding="utf-8") as src:
            sarif = json.load(src)
        for run in sarif["runs"]:
            artifacts = run.get("artifacts", [])
            for result in run.get("results", []):
                suppressions = result.get("suppressions", [])
                suppression = suppressions[0].get("justification",
                                                  "") if suppressions else None
                if tool == "quality-scanner":
                    findings.append(
                        _scanner_finding(result, artifacts, suppression))
                    continue
                findings.append(
                    _Finding(_TOOL_NAMES[tool], result["ruleId"],
                             _tool_location(result, artifacts, bases),
                             result["message"]["text"], suppression))
    return findings


def _load_scanned_documents(paths: list[str]) -> list[str]:
    uids: set[str] = set()
    for path in paths:
        with open(path, "r", encoding="utf-8") as src:
            sarif = json.load(src)
        for run in sarif["runs"]:
            for artifact in run.get("artifacts", []):
                properties = artifact["properties"]
                if properties["kind"] == "document":
                    uids.add(properties["uid"])
    return sorted(uids)


def _count(count: int, singular: str, plural: str) -> str:
    return f"{count} {singular if count == 1 else plural}"


def _cell(content: SphinxContent, text: str) -> str:
    text = content.escape(text)
    # A lone hyphen in a table cell starts a bullet list.
    return "\\-" if text == "-" else text


def _breakable(content: SphinxContent, text: str) -> str:
    # A zero-width space lets LaTeX break a long location in a narrow column
    text = content.escape(text)
    for char in "/-_.":
        text = text.replace(char, f"{char}\u200b")
    return text


def _file_location(content: SphinxContent, location: str) -> str:
    if location == "-":
        return _cell(content, location)
    path, separator, line = location.rpartition(":")
    if separator and line.isdigit():
        return f"{content.path(path)}:{line}"
    return content.path(location)


def _bold_if(text: str, condition: bool) -> str:
    return f"**{text}**" if condition else text


class SpamrBuilder(DocumentBuilder):
    """
    Builds the software product assurance milestone report from the outputs
    of the analysis tools, the quality model, and the specification items.
    """

    def __init__(self, director: PackageBuildDirector, item: Item):
        super().__init__(director, item)
        for name, method in (
            ("annex-clang-analyzer-findings",
             self._annex_clang_analyzer_findings),
            ("annex-cppcheck-findings", self._annex_cppcheck_findings),
            ("annex-files", self._annex_files),
            ("annex-functions", self._annex_functions),
            ("annex-quality-scanner-findings",
             self._annex_quality_scanner_findings),
            ("annex-quality-scanner-suppressions",
             self._annex_quality_scanner_suppressions),
            ("clang-analyzer-results", self._clang_analyzer_results),
            ("code-metrics", self._code_metrics),
            ("code-size", self._code_size),
            ("cppcheck-results", self._cppcheck_results),
            ("metrics-overview", self._metrics_overview),
            ("requirement-implementation-and-vv-coverage",
             self._requirement_implementation_and_vv_coverage),
            ("requirement-testability", self._requirement_testability),
            ("requirements-completeness", self._requirements_completeness),
            ("rid-action-status", self._rid_action_status),
            ("spr-ncr-status", self._spr_ncr_status),
            ("sprs-and-ncrws", self._sprs_and_ncrws),
            ("user-documentation-completeness",
             self._user_documentation_completeness),
            ("vv-coverage-unit-integration-level",
             self._vv_coverage_unit_integration),
        ):
            self.mapper.add_get_value(f"{self.item.type}:/{name}",
                                      self._content(method))
        self._compute: dict[str, Callable[[Optional[int]], tuple[
            str, bool]]] = {
                "comment-frequency": self._metric_comment_frequency,
                "cyclomatic-complexity": self._metric_cyclomatic_complexity,
                "lines-of-code": self._metric_lines_of_code,
                "nesting-level": self._metric_nesting_level,
                "requirement-completeness":
                self._metric_requirement_completeness,
                "requirement-implementation-coverage":
                self._metric_requirement_implementation_coverage,
                "requirement-testability":
                self._metric_requirement_testability,
                "rid-action-status": self._metric_rid_action_status,
                "spr-ncr-status": self._metric_spr_ncr_status,
                "user-documentation-completeness":
                self._metric_user_documentation_completeness,
                "vv-coverage": self._metric_vv_coverage,
            }

    def _content(
        self, method: Callable[[SphinxContent], None]
    ) -> Callable[[ItemGetValueContext], str]:

        def _get_value(_ctx: ItemGetValueContext) -> str:
            content = SphinxContent(context=self.mapper.context)
            method(content)
            return content.join()

        return _get_value

    def run(self) -> None:
        # The director reuses the builder, so a run starts with no cached
        # value of a previous run.
        for name, value in vars(SpamrBuilder).items():
            if isinstance(value, functools.cached_property):
                self.__dict__.pop(name, None)
        super().run()

    @functools.cached_property
    def _thresholds(self) -> dict[str, Optional[int]]:
        return self.item.parent("quality-model")["thresholds"]

    @functools.cached_property
    def _source_directories(self) -> list[str]:
        directories: list[str] = []
        for state in self.inputs("rtems"):
            assert isinstance(state, DirectoryState)
            directories.append(state.directory)
        return directories

    @functools.cached_property
    def _findings(self) -> dict[str, list[_Finding]]:
        return dict((tool,
                     _load_findings(tool, _files(self.input(tool), ".sarif"),
                                    self._source_directories))
                    for tool in _TOOL_NAMES)

    @functools.cached_property
    def _code(self) -> _CodeMetrics:
        return _load_code_metrics(
            _files(self.input("metrixplusplus"), ".csv")[0],
            self._source_directories)

    @functools.cached_property
    def _requirements(self) -> list[Item]:
        spec = self.input("spec")
        assert isinstance(spec, RTEMSItemCache)
        return sorted(spec.get_related_requirements())

    @functools.cached_property
    def _issue_status(self) -> tuple[set[Item], set[Item]]:
        changes = self.input("package-changes")
        assert isinstance(changes, PackageChanges)
        return changes.get_current_issue_status(self.mapper)

    @functools.cached_property
    def _issues(self) -> list[Item]:
        closed, opened = self._issue_status
        return sorted(closed | opened)

    def _is_open(self, issue: Item) -> bool:
        return issue in self._issue_status[1]

    def _scanner_items(self) -> set[str]:
        return set(finding.item
                   for finding in self._findings["quality-scanner"]
                   if finding.suppression is None and finding.item)

    def _scanner_documents(self) -> set[str]:
        return set(finding.document
                   for finding in self._findings["quality-scanner"]
                   if finding.suppression is None and finding.document)

    def _incomplete_requirements(self) -> list[Item]:
        uids = self._scanner_items()
        return [req for req in self._requirements if req.uid in uids]

    def _testable_requirements(self) -> list[Item]:
        testable: list[Item] = []
        for item in self._requirements:
            if item.type in ("requirement/functional/action",
                             "requirement/non-functional/performance-runtime",
                             "runtime-measurement-test"):
                testable.append(item)
                continue
            try:
                item.child("validation")
            except IndexError:
                pass
            else:
                testable.append(item)
        return testable

    @functools.cached_property
    def _api_functions(self) -> list[Item]:
        spec = self.input("spec")
        assert isinstance(spec, RTEMSItemCache)
        return [
            function for function in sorted(
                spec.get_related_items_by_type("interface/function"))
            if function.view["pre-qualified"]
        ]

    @functools.cached_property
    def _functions_without_validation(self) -> list[Item]:
        covered = set(
            link.item for requirement in self._requirements
            if requirement.view["validated"]
            for link in requirement.links_to_parents("interface-function"))
        return [
            function for function in self._api_functions
            if function not in covered
        ]

    def _vv_coverage(self) -> tuple[int, int]:
        total = len(self._api_functions)
        return total - len(self._functions_without_validation), total

    def _labeled_issues(self, label: str) -> list[Item]:
        return [issue for issue in self._issues if label in issue["labels"]]

    def _issue_link(self, issue: Item) -> str:
        database = issue.parent("issue-member")
        url = self.mapper.substitute(database["url"], issue)
        identifier = self.mapper.substitute(database["format-identifier"],
                                            issue)
        return f"`{database['name']} {identifier} <{url}>`_"

    def _functions_over(self, key: str,
                        value: Callable[[_Region], float]) -> list[_Region]:
        threshold = self._thresholds[key]
        if threshold is None:
            return []
        return [
            region for region in self._code.functions
            if value(region) > threshold
        ]

    def _files_over(self) -> list[tuple[str, int]]:
        threshold = self._thresholds["lines-of-code"]
        if threshold is None:
            return []
        return sorted((path, lines)
                      for path, lines in self._code.file_lines.items()
                      if lines > threshold)

    def _metric_requirement_implementation_coverage(
            self, threshold: Optional[int]) -> tuple[str, bool]:
        total = len(self._requirements)
        validated = sum(1 for req in self._requirements
                        if req.view["validated"])
        return (
            f"{validated} of {_count(total, 'requirement', 'requirements')}",
            threshold is not None and validated >= threshold * total)

    def _metric_requirement_completeness(
            self, threshold: Optional[int]) -> tuple[str, bool]:
        total = len(self._requirements)
        incomplete = len(self._incomplete_requirements())
        return (f"{incomplete} of "
                f"{_count(total, 'requirement', 'requirements')}",
                threshold is not None and incomplete <= threshold * total)

    def _metric_vv_coverage(self,
                            threshold: Optional[int]) -> tuple[str, bool]:
        covered, total = self._vv_coverage()
        return (f"{covered} of {_count(total, 'function', 'functions')}",
                threshold is not None and covered >= threshold * total)

    def _metric_requirement_testability(
            self, threshold: Optional[int]) -> tuple[str, bool]:
        total = len(self._requirements)
        testable = len(self._testable_requirements())
        percent = 100.0 * testable / total if total else 0.0
        return (f"{percent:.1f} % ({testable} of "
                f"{_count(total, 'requirement', 'requirements')})",
                threshold is not None and 100 * testable >= threshold * total)

    def _metric_functions(
            self, key: str, value: Callable[[_Region],
                                            float]) -> tuple[str, bool]:
        count = len(self._functions_over(key, value))
        return (
            f"{count} of "
            f"{_count(len(self._code.functions), 'function', 'functions')}",
            count == 0)

    def _metric_cyclomatic_complexity(
            self, _threshold: Optional[int]) -> tuple[str, bool]:
        return self._metric_functions("cyclomatic-complexity",
                                      lambda region: region.cyclomatic)

    def _metric_nesting_level(self,
                              _threshold: Optional[int]) -> tuple[str, bool]:
        return self._metric_functions("nesting-level",
                                      lambda region: region.nesting)

    def _metric_comment_frequency(
            self, _threshold: Optional[int]) -> tuple[str, bool]:
        return self._metric_functions("comment-frequency",
                                      lambda region: region.comment_frequency)

    def _metric_lines_of_code(self,
                              _threshold: Optional[int]) -> tuple[str, bool]:
        count = len(self._files_over())
        return (f"{count} of "
                f"{_count(len(self._code.file_lines), 'file', 'files')}",
                count == 0)

    def _metric_user_documentation_completeness(
            self, threshold: Optional[int]) -> tuple[str, bool]:
        documents = len(self._scanner_documents())
        items = len(self._scanner_items())
        return (f"{_count(documents, 'document file', 'document files')}, "
                f"{_count(items, 'item', 'items')}", threshold is not None
                and documents <= threshold and items <= threshold)

    def _metric_spr_ncr_status(self,
                               threshold: Optional[int]) -> tuple[str, bool]:
        count = sum(1 for issue in self._issues if self._is_open(issue))
        return (_count(count, "open issue",
                       "open issues"), threshold is not None
                and count <= threshold)

    def _metric_rid_action_status(
            self, threshold: Optional[int]) -> tuple[str, bool]:
        count = sum(1 for issue in self._labeled_issues("MAI")
                    if self._is_open(issue))
        return (_count(count, "open action",
                       "open actions"), threshold is not None
                and count <= threshold)

    def _evaluate(self, key: str) -> tuple[str, str]:
        threshold = self._thresholds[key]
        if key in _MANUAL_METRICS:
            verdict = self.item["metric-verdicts"].get(key, None)
            if threshold is None:
                return (verdict["value"] if verdict else "-", "n.a.")
            if verdict is None:
                raise ValueError(
                    f"{self.uid}: the metric '{key}' needs a verdict")
            return verdict["value"], verdict["result"]
        value, passed = self._compute[key](threshold)
        if threshold is None:
            return value, "n.a."
        return value, "OK" if passed else "NOK"

    def _metrics_overview(self, content: SphinxContent) -> None:
        rows: list[tuple[str,
                         ...]] = [("Metric", "Value", "Threshold", "Result")]
        for key, name in _METRICS:
            value, result = self._evaluate(key)
            threshold = self._thresholds[key]
            if threshold is None:
                threshold_text = "n.a."
            elif key in _PERCENT_METRICS:
                threshold_text = f"{threshold} %"
            else:
                threshold_text = str(threshold)
            rows.append((name, _cell(content, value), threshold_text,
                         _bold_if(result, result == "NOK")))
        content.add_grid_table(rows, [34, 36, 15, 15])

    def _requirement_implementation_and_vv_coverage(
            self, content: SphinxContent) -> None:
        not_validated = [
            req.uid for req in self._requirements if not req.view["validated"]
        ]
        total = len(self._requirements)
        content.wrap(f"""The package has
{_count(total, "related requirement", "related requirements")}.
{total - len(not_validated)} of them have an associated validation.""")
        if not_validated:
            content.add("The following requirements have no validation:")
            content.add_list(not_validated)

    def _requirements_completeness(self, content: SphinxContent) -> None:
        incomplete = [req.uid for req in self._incomplete_requirements()]
        total = len(self._requirements)
        content.wrap(f"""The quality scanner found an open TBD or TBC in
{len(incomplete)} of
{_count(total, "related requirement", "related requirements")}.""")
        if incomplete:
            content.add_list(incomplete)
        content.wrap(f"""Section
:ref:`{_ANNEX_FINDINGS["quality-scanner"]}` lists each finding and each
suppression of the quality scanner.""")

    def _vv_coverage_unit_integration(self, content: SphinxContent) -> None:
        covered, total = self._vv_coverage()
        functions = _count(total, "pre-qualified API function",
                           "pre-qualified API functions")
        content.wrap(f"""The package has {functions}.
{covered} of them have a requirement with an associated validation.""")
        if self._functions_without_validation:
            content.add("The following pre-qualified API functions have no "
                        "requirement with a validation:")
            content.add_list(
                function.uid
                for function in self._functions_without_validation)

    def _requirement_testability(self, content: SphinxContent) -> None:
        total = len(self._requirements)
        content.wrap(f"""The package has
{_count(total, "related requirement", "related requirements")}.
{len(self._testable_requirements())} of them are verified by test.""")

    def _tool_results(self, content: SphinxContent, tool: str) -> None:
        findings = self._findings[tool]
        counts = collections.Counter(finding.rule for finding in findings)
        content.wrap(f"""The tool reported
{_count(len(findings), "finding", "findings")}.
Section :ref:`{_ANNEX_FINDINGS[tool]}` lists each finding.""")
        if counts:
            rows: list[tuple[str, ...]] = [("Rule", "Findings")]
            rows.extend((content.code(rule), str(counts[rule]))
                        for rule in sorted(counts))
            content.add_grid_table(rows, [80, 20])

    def _cppcheck_results(self, content: SphinxContent) -> None:
        self._tool_results(content, "cppcheck")

    def _clang_analyzer_results(self, content: SphinxContent) -> None:
        self._tool_results(content, "clang-analyzer")

    def _code_metrics(self, content: SphinxContent) -> None:
        rows: list[tuple[str,
                         ...]] = [("Metric", "Threshold", "Exceeded", "Total")]
        for key, name in _METRICS:
            if key not in ("cyclomatic-complexity", "nesting-level",
                           "comment-frequency", "lines-of-code"):
                continue
            value, _ = self._evaluate(key)
            exceeded, total = value.split(" of ", 1)
            threshold = self._thresholds[key]
            threshold_text = "n.a." if threshold is None else (
                f"{threshold} %"
                if key in _PERCENT_METRICS else str(threshold))
            rows.append((name, threshold_text, exceeded, total))
        content.add_grid_table(rows, [40, 20, 20, 20])
        csv_file = os.path.relpath(
            _files(self.input("metrixplusplus"), ".csv")[0],
            self.component["deployment-directory"])
        content.wrap(f"""Section :ref:`{_ANNEX_CODE_METRICS}` lists each
function and file which exceeds a threshold. The file
{content.path(csv_file)} of the package contains the values of all
regions.""")

    def _user_documentation_completeness(self, content: SphinxContent) -> None:
        documents = _load_scanned_documents(
            _files(self.input("quality-scanner"), ".sarif"))
        documents_with_findings = len(self._scanner_documents())
        items_with_findings = len(self._scanner_items())
        content.wrap(f"""The quality scanner found an open TBD or TBC in
{_count(documents_with_findings, "document file", "document files")} and in
{_count(items_with_findings, "item", "items")}.
Section :ref:`{_ANNEX_FINDINGS["quality-scanner"]}` lists each finding and
each suppression.""")
        if documents:
            content.add("The quality scanner scanned these documents:")
            content.add_list(documents)

    def _spr_ncr_status(self, content: SphinxContent) -> None:
        counts: dict[str, list[int]] = collections.defaultdict(lambda: [0, 0])
        for issue in self._issues:
            database = issue.parent("issue-member")["name"]
            counts[database][0 if self._is_open(issue) else 1] += 1
        content.wrap("""The table counts the open and the closed issues of
this package version by issue database. The package status gives the status
of each issue. An issue which does not apply to this package version is not
counted.""")
        rows: list[tuple[str, ...]] = [("Issue database", "Open", "Closed")]
        rows.extend(
            (database, str(counts[database][0]), str(counts[database][1]))
            for database in sorted(counts))
        content.add_grid_table(rows, [60, 20, 20])

    def _sprs_and_ncrws(self, content: SphinxContent) -> None:
        rids = [
            issue for issue in self._labeled_issues("RID")
            if self._is_open(issue)
        ]
        if rids:
            content.add("The following RIDs are open:")
            content.add_list([self._issue_link(issue) for issue in rids])
        else:
            content.add("No RID is open.")

    def _rid_action_status(self, content: SphinxContent) -> None:
        actions = self._labeled_issues("MAI")
        opened = sum(1 for issue in actions if self._is_open(issue))
        content.wrap("""The actions are the issues of this package version
with the label MAI.""")
        content.add_list([
            f"Actions issued: {len(actions)}",
            f"Actions closed: {len(actions) - opened}",
            f"Actions open: {opened}"
        ])
        rids = self._labeled_issues("RID")
        opened = sum(1 for issue in rids if self._is_open(issue))
        content.wrap("""The RIDs are the issues of this package version with
the label RID.""")
        content.add_list([
            f"RIDs issued: {len(rids)}", f"RIDs closed: {len(rids) - opened}",
            f"RIDs open: {opened}"
        ])

    def _code_size(self, content: SphinxContent) -> None:
        content.wrap(f"""The pre-qualified source code has
{sum(self._code.file_lines.values())} lines of code and preprocessor
directives.""")

    def _annex_tool_findings(self, content: SphinxContent, tool: str) -> None:
        rows: list[tuple[str, ...]] = [("Rule", "Location", "Message")]
        rows.extend((content.escape(finding.rule),
                     _file_location(content, finding.location),
                     content.escape(finding.message))
                    for finding in self._findings[tool])
        if len(rows) == 1:
            content.add("The tool reported no finding.")
        else:
            content.add_grid_table(rows, [24, 38, 38], font_size=-2)

    def _annex_cppcheck_findings(self, content: SphinxContent) -> None:
        self._annex_tool_findings(content, "cppcheck")

    def _annex_clang_analyzer_findings(self, content: SphinxContent) -> None:
        self._annex_tool_findings(content, "clang-analyzer")

    def _annex_quality_scanner_findings(self, content: SphinxContent) -> None:
        rows: list[tuple[str, ...]] = [("Marker", "Location")]
        rows.extend((finding.rule, _breakable(content, finding.location))
                    for finding in self._findings["quality-scanner"]
                    if finding.suppression is None)
        if len(rows) == 1:
            content.add("The quality scanner found no open TBD or TBC.")
        else:
            content.add_grid_table(rows, [15, 85], font_size=-2)

    def _annex_quality_scanner_suppressions(self,
                                            content: SphinxContent) -> None:
        rows: list[tuple[str, ...]] = [("Marker", "Location", "Reason")]
        rows.extend((finding.rule, _breakable(content, finding.location),
                     content.escape(finding.suppression or ""))
                    for finding in self._findings["quality-scanner"]
                    if finding.suppression is not None)
        if len(rows) == 1:
            content.add("No finding of the quality scanner is suppressed.")
        else:
            content.add_grid_table(rows, [15, 40, 45], font_size=-2)

    def _annex_functions(self, content: SphinxContent) -> None:
        cyclomatic = self._thresholds["cyclomatic-complexity"]
        nesting = self._thresholds["nesting-level"]
        comments = self._thresholds["comment-frequency"]
        over: dict[str, list[_Region]] = collections.defaultdict(list)
        for region in self._code.functions:
            flags = (cyclomatic is not None
                     and region.cyclomatic > cyclomatic, nesting is not None
                     and region.nesting > nesting, comments is not None
                     and region.comment_frequency > comments)
            if any(flags):
                over[region.path].append(region)
        if not over:
            content.add("No function exceeds a threshold.")
        for path in sorted(over):
            content.add(content.path(path))
            rows: list[tuple[str, ...]] = [("Function", "Line", "VG",
                                            "Nesting", "Comments")]
            for region in sorted(over[path], key=lambda r: r.line):
                rows.append(
                    (content.escape(region.name), str(region.line),
                     _bold_if(
                         str(region.cyclomatic), cyclomatic is not None
                         and region.cyclomatic > cyclomatic),
                     _bold_if(str(region.nesting), nesting is not None
                              and region.nesting > nesting),
                     _bold_if(
                         f"{region.comment_frequency:.0f} %",
                         comments is not None
                         and region.comment_frequency > comments)))
            content.add_grid_table(rows, [44, 14, 14, 14, 14])

    def _annex_files(self, content: SphinxContent) -> None:
        files = self._files_over()
        if files:
            rows: list[tuple[str, ...]] = [("File", "Lines of code")]
            rows.extend(
                (content.path(path), str(lines)) for path, lines in files)
            content.add_grid_table(rows, [80, 20])
        else:
            content.add("No file exceeds the threshold.")
