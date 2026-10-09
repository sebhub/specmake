# SPDX-License-Identifier: BSD-2-Clause
""" Builds a package manual. """

# Copyright (C) 2020, 2026 embedded brains GmbH & Co. KG
# Copyright (C) 2021 EDISOFT
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
import logging
import os
from typing import Iterator, NamedTuple

from specitems import (CommonMarkContent, Copyrights, Item,
                       ItemGetValueContext, Link, ROW_SPAN, TextContent,
                       make_label)
from specware import (gather_api_items, run_command)

from .archiver import Archiver
from .directorystate import DirectoryState, RepositoryState
from .docbuilder import DocumentBuilder
from .membench import generate, generate_variants_table, MembenchVariant
from .pkgitems import PackageBuildDirector
from .packagechanges import PackageChanges
from .testaggregator import (CoverageGap, CoverageScope, NotValidatedItem,
                             RetriedProgram, TestAggregator)
from .rtems import get_substitution_errors
from .testanalysis import NO_TEST_RESULTS, TestAnalysis
from .testrunner import TestLog
from .util import variant_order

_EnvToStats = dict[str, tuple[float, float, float]]
_ItemToEnvStats = dict[str, _EnvToStats]


def _run_pkg_config(content: TextContent, cmd: list[str]) -> None:
    cmd = ["pkg-config"] + cmd
    content.add(f"$ {' '.join(cmd)}")
    stdout: list[str] = []
    status = run_command(cmd, stdout=stdout)
    assert status == 0
    content.append(stdout)


def _gather_runtime_performance_items(items: set[Item], item: Item) -> None:
    if item.type == "requirement/non-functional/performance-runtime":
        items.add(item)
    for child in item.children("requirement-refinement"):
        _gather_runtime_performance_items(items, child)


def _add_licenses(content: TextContent, deployment_directory: str,
                  member: DirectoryState,
                  license_listing: dict[str, Copyrights]) -> None:
    if "license-files" in member:
        license_files = member["license-files"]
        directory = os.path.relpath(member.directory, deployment_directory)
        with content.section(f"Directory - {directory}"):
            content.add(license_files.get("description", None))
            for name in license_files["files"]:
                with content.section(f"File - {name}"):
                    content.add(f"""The license file
{content.path(os.path.join(directory, name))}
is applicable to this directory or parts of the directory:""")
                    content.add_blank_line()
                    file_path = os.path.join(member.directory, name)
                    with open(file_path, "r", encoding="utf-8") as src:
                        content.add_code_block(src.readlines(),
                                               line_number_start=-1)
    for info in member["license-info"]:
        license_listing.setdefault(info["license"],
                                   Copyrights()).register(info["copyrights"])


def _get_performance_environments(
        measurements_by_variant: dict[int, _ItemToEnvStats]) -> list[str]:
    # We cannot use the performance runtime measurement environments specified
    # by items, since we have a target defined number of the Load/N
    # environments.
    #
    # Iterate over all gathered performance statistics since some providers may
    # have no results.  Try the best to produce a report even with insufficient
    # data.
    all_envs: set[str] = set()
    for item_to_env_stats in measurements_by_variant.values():
        for env_to_stats in item_to_env_stats.values():
            all_envs.update(env_to_stats.keys())
    return sorted(all_envs, key=variant_order)


class PackageManualBuilder(DocumentBuilder):
    """ Builds a package user manual. """

    def __init__(self, director: PackageBuildDirector, item: Item):
        super().__init__(director, item)
        self._membench: dict[str, dict] = {}
        my_type = self.item.type
        self.mapper.add_get_value(f"{my_type}:/benchmark-variants-list",
                                  self._get_benchmark_variants_list)
        self.mapper.add_get_value(f"{my_type}:/memory-benchmarks",
                                  self._get_membench)
        self.mapper.add_get_value(f"{my_type}:/memory-benchmark-section",
                                  self._get_membench_section)
        self.mapper.add_get_value(f"{my_type}:/memory-benchmark-reference",
                                  self._get_membench_ref)
        self.mapper.add_get_value(
            f"{my_type}:/memory-benchmark-based-on-reference",
            self._get_membench_based_on_ref)
        self.mapper.add_get_value(
            f"{my_type}:/memory-benchmark-compare-section",
            self._get_membench_compare_section)
        self.mapper.add_get_value(
            f"{my_type}:/memory-benchmark-variants-table",
            self._get_membench_variants_table)
        self.mapper.add_get_value(f"{my_type}:/performance-variants-table",
                                  self._get_performance_variants_table)
        self.mapper.add_get_value(f"{my_type}:/pkg-config",
                                  self._get_pkg_config)
        self.mapper.add_get_value(f"{my_type}:/pre-qualified-interfaces",
                                  self._get_pre_qualified_interfaces)
        self.mapper.add_get_value(f"{my_type}:/repositories", self._get_repos)
        self.mapper.add_get_value(f"{my_type}:/change-list",
                                  self._get_change_list)
        self.mapper.add_get_value(f"{my_type}:/open-issues",
                                  self._get_open_issues)
        self.mapper.add_get_value(f"{my_type}:/license-info",
                                  self._get_license_info)
        self.mapper.add_get_value(f"{my_type}:/targets", self._get_targets)
        for name in [my_type, "pkg/sphinx-section"]:
            self.mapper.add_get_value(f"{name}:/object-size",
                                      self._get_object_size)

    def run(self) -> None:
        for membench in self.inputs("membench-results"):
            assert isinstance(membench, DirectoryState)
            self._membench.update(membench.json_load())
        super().run()

    def _get_benchmark_variants_list(self, ctx: ItemGetValueContext) -> str:
        with self.section_content(ctx) as (content, _):
            for link, test_log in self._yield_benchmark_variants():
                content.add_definition_item(
                    test_log.substitute(link["variant-name"]),
                    test_log.substitute(link["description"]))
            return content.join()

    def _get_membench_build_label(self) -> str:
        return self.substitute("${.:/component/membench-build-label}")

    def _get_membench(self, ctx: ItemGetValueContext) -> str:
        with self.section_content(ctx) as (content, _):
            content.push_label(
                make_label(self.substitute("${.:/component/ident}")))
            label = self._get_membench_build_label()
            sections_by_uid = self._membench[label]["membench"]
            root = self.item.cache["/rtems/req/mem-basic"]
            table_pivots = ("/rtems/req/mem-smp-1", )
            generate(content, sections_by_uid, root, table_pivots, self.mapper)
            return content.join()

    def _get_membench_section(self, ctx: ItemGetValueContext) -> str:
        assert ctx.args
        uid, section = ctx.args.split(":")
        item = self.item.cache[uid]
        label = self._get_membench_build_label()
        sections = self._membench[label]["membench"][item.uid]
        return str(sections[section])

    def _membench_get_ref(self, ctx: ItemGetValueContext, section: str) -> str:
        assert ctx.args
        item = self.item.cache[ctx.args]
        scope = make_label(self.substitute("${.:/component/ident}"))
        label = f"{scope}{section}{item.ident}"
        return f":ref:`{item.spec_2} <{label}>`"

    def _get_membench_ref(self, ctx: ItemGetValueContext) -> str:
        return self._membench_get_ref(ctx, "BenchmarkSpec")

    def _get_membench_based_on_ref(self, ctx: ItemGetValueContext) -> str:
        return self._membench_get_ref(ctx, "BenchmarksBasedOnSpec")

    def _get_membench_compare_section(self, ctx: ItemGetValueContext) -> str:
        assert ctx.args
        uid, other_uid, section = ctx.args.split(":")
        item = self.item.cache[uid]
        label = self._get_membench_build_label()
        sections = self._membench[label]["membench"][item.uid]
        other_item = self.item.cache[other_uid]
        other_sections = self._membench[label]["membench"][other_item.uid]
        return f"{other_sections[section] - sections[section]:+}"

    def _yield_benchmark_variants(self) -> Iterator[tuple[Link, TestLog]]:
        for link, test_log in sorted(self.input_links("benchmark-variant"),
                                     key=lambda x: x[0]["priority"]):
            logging.info("%s: use benchmark variant of: %s", self.uid,
                         test_log.uid)
            assert isinstance(test_log, TestLog)
            yield link, test_log

    def _get_membench_variants_table(self, ctx: ItemGetValueContext) -> str:
        with self.section_content(ctx) as (content, _):
            root = self.item.cache["/rtems/req/mem-basic"]
            variants: list[MembenchVariant] = []
            for link, test_log in self._yield_benchmark_variants():
                build_label = test_log.input(
                    "build-configuration")["build-label"]
                if build_label not in self._membench:
                    logging.warning(
                        "%s: no memory benchmark for build label: %s",
                        self.uid, build_label)
                    continue
                variants.append(
                    MembenchVariant(test_log.substitute(link["variant-name"]),
                                    build_label))
            generate_variants_table(content, self._membench, root, variants)
            return content.join()

    def _get_measurements_by_variant(self) -> dict[int, _ItemToEnvStats]:
        measurements_by_variant: dict[int, _ItemToEnvStats] = {}
        for index, (_,
                    test_log) in enumerate(self._yield_benchmark_variants()):
            with open(test_log.file, "r", encoding="utf-8") as src:
                data = json.load(src)
            measurements: _ItemToEnvStats = {}
            for report in data["reports"]:
                for test_case in report.get("test-suite",
                                            {}).get("test-cases", []):
                    for measurement in test_case["runtime-measurements"]:
                        stats = (measurement["min"], measurement["q2"],
                                 measurement["max"])
                        measurements.setdefault(
                            measurement["name"],
                            {})[measurement["variant"]] = stats
            measurements_by_variant[index] = measurements
        return measurements_by_variant

    def _make_performance_variants_rows(
        self, item: Item, envs: list[str], env_links: dict[str, str],
        measurements_by_variant: dict[int, _ItemToEnvStats]
    ) -> list[tuple[str | int, ...]]:
        # pylint: disable=too-many-locals
        rows: list[tuple[str | int, ...]] = []
        info_spec: str | int = self.mapper.get_link(item)
        for env in envs:
            env_link = env_links[env.split("/")[0]]
            info_env: str | int = self.mapper.format_link(env, env_link)
            for index, (link, test_log) in enumerate(
                    self._yield_benchmark_variants()):
                stats = measurements_by_variant[index].get(item.ident,
                                                           {}).get(env, None)
                info = (info_spec, info_env,
                        test_log.substitute(link["variant-name"]))
                if index == 0:
                    if not stats:
                        rows.append(info + ("?", "?", "?"))
                        continue
                    base = stats
                    rows.append(info + tuple(f"{value * 1e6:.3f}"
                                             for value in stats))
                elif stats:
                    rows.append(info + tuple(
                        f"{(value - base[j]) / base[j] * 100.0:+.3g} %"
                        for j, value in enumerate(stats)))
                else:
                    rows.append(info + ("?", "?", "?"))
                info_spec = ROW_SPAN
                info_env = ROW_SPAN
        return rows

    def _get_performance_variants_table(self, ctx: ItemGetValueContext) -> str:
        with self.section_content(ctx) as (content, _):
            measurements_by_variant = self._get_measurements_by_variant()
            if not measurements_by_variant:
                return "There is no performance variants table available."
            items: set[Item] = set()
            _gather_runtime_performance_items(items,
                                              self.item.cache["/req/root"])
            _, test_log = next(self._yield_benchmark_variants())
            envs = _get_performance_environments(measurements_by_variant)
            req_path = test_log.substitute(
                "${.:/component/deployment-directory}/doc/ts/srs/"
                "requirements.html#spec-req-perf-runtime-environment-")
            env_links = {
                "HotCache": f"{req_path}hot-cache",
                "FullCache": f"{req_path}full-cache",
                "DirtyCache": f"{req_path}dirty-cache",
                "Load": f"{req_path}load"
            }
            rows: list[tuple[str | int, ...]] = [
                ("Specification", "Environment", "Variant", "Min [μs]",
                 "Median [μs]", "Max [μs]")
            ]
            for item in sorted(items):
                rows.extend(
                    self._make_performance_variants_rows(
                        item, envs, env_links, measurements_by_variant))
            content.add_grid_table(rows, [31, 14, 19, 12, 12, 12],
                                   font_size=-3)
            return content.join()

    def _get_pkg_config(self, _ctx: ItemGetValueContext) -> str:
        pkg = self.substitute(
            "${.:/component/deployment-directory}/lib/pkgconfig/"
            "${.:/component/arch}-rtems${.:/component/rtems-version}-"
            "${.:/component/bsp}${.:/component/config:dash}"
            "${.:/component/bsp-qual-only:dash}.pc")
        content = self.mapper.create_content()
        with content.directive("code-block", value="none"):
            _run_pkg_config(content, ["--variable=ABI_FLAGS", pkg])
            _run_pkg_config(content, ["--cflags", pkg])
            _run_pkg_config(content, ["--variable=LDFLAGS", pkg])
        return content.join()

    def _get_pre_qualified_interfaces(self, ctx: ItemGetValueContext) -> str:
        with self.section_content(ctx) as (content, _):
            content.push_label(
                make_label(self.substitute("${.:/component/ident}")))
            items: dict[str, list[Item]] = {}
            gather_api_items(self.item.cache, items)
            for group, group_items in sorted(items.items()):
                with content.section(group):
                    content.add_list(
                        self.mapper.get_link(item) for item in group_items)
            return content.join()

    def _get_repos(self, ctx: ItemGetValueContext) -> str:
        with self.section_content(ctx) as (content, _):
            prefix = self.substitute("${.:/component/deployment-directory}")
            for item in self.component.item.children("repository"):
                repo = self.director[item.uid]
                assert isinstance(repo, RepositoryState)
                assert repo.lazy_verify()
                origin_branch = repo["origin-branch"]
                origin_commit = repo["origin-commit"]
                if origin_branch and origin_commit:
                    dest = os.path.relpath(repo["directory"], prefix)
                    with content.section(f"Git Repository: {dest}"):
                        content.add(repo["description"])
                        content.add(f"""The {content.code(repo['branch'])}
branch with commit {content.code(repo['commit'])} was used to build the
package.  This branch is checked out after unpacking the archive.  It is based
on commit {content.link(origin_commit, repo['origin-commit-url'])} of the
{content.code(origin_branch)} branch of the {content.code('origin')} remote
repository.""")
            return content.join()

    def _get_object_size(self, ctx: ItemGetValueContext) -> str:
        assert ctx.args
        label = self._get_membench_build_label()
        return str(self._membench[label]["object-sizes"][ctx.args])

    def _get_change_list(self, ctx: ItemGetValueContext) -> str:
        with self.section_level_scope(ctx):
            changes = self.input("package-changes")
            assert isinstance(changes, PackageChanges)
            return changes.get_change_list(self.mapper, self.section_level)

    def _get_open_issues(self, ctx: ItemGetValueContext) -> str:
        with self.section_level_scope(ctx):
            changes = self.input("package-changes")
            assert isinstance(changes, PackageChanges)
            return changes.get_open_issues(self.mapper, self.section_level)

    def _get_license_info(self, ctx: ItemGetValueContext) -> str:
        archiver = self.input("archive")
        assert isinstance(archiver, Archiver)
        with self.section_content(ctx) as (content, _):
            license_listing: dict[str, Copyrights] = {}
            deployment_directory = self.substitute(
                "${.:/component/deployment-directory}")
            content.add(f"""All directories and file paths in this section are
relative to {content.path(deployment_directory)}.  A delivered file states
the license of its work only.  This section states the other licenses of its
parts, so read a delivered file together with this section.""")
            for member in archiver.inputs("member"):
                assert isinstance(member, DirectoryState)
                _add_licenses(content, deployment_directory, member,
                              license_listing)
            provider = self.director.license_provider
            for the_license in sorted(license_listing):
                copyrights = license_listing[the_license]
                if not copyrights:
                    continue
                with content.section(f"{the_license} copyrights"):
                    content.add(copyrights.get_statements("| ©"))
                    text = provider.text_of(the_license)
                    if text is not None:
                        content.add_code_block(text.split("\n"),
                                               line_number_start=-1)
                    else:
                        uri = provider.uri_of(the_license)
                        if uri is not None:
                            content.add(
                                f"The text of the license is at {uri}.")
            return content.join()

    def _get_targets(self, ctx: ItemGetValueContext) -> str:
        with self.section_content(ctx) as (content, _):
            targets: set[str] = set()
            for component in self.component.components():
                with component.scope():
                    targets.update(
                        item.uid
                        for item in component.item.parents("design-target"))
            for uid in sorted(targets):
                target = self.item.cache[uid]
                with content.section(target["name"], label=self.label(target)):
                    content.add(self.substitute(target["brief"]))
                    content.add(self.substitute(target["description"]))
            return content.join()


_MAX_GAP_ROWS = 20

_COUNT_HEADER = ("Passed", "Expected failures", "Unexpected failures",
                 "Unexpected passes")

_COUNT_KEYS = ("passed", "expected-failures", "unexpected-failures",
               "unexpected-passes")


class _FailedSubstitution(NamedTuple):
    component: str
    uid: str
    error: str


class _Verdicts(NamedTuple):
    component: str
    failures: dict[str, list[str]]
    reasons: dict[str, dict[str, list[str]]]
    counts: dict[str, dict[str, int]]


def _add_gap_rows(rows: list[list[str]], notes: list[str],
                  scope: CoverageScope, gaps: list[CoverageGap],
                  with_uid: bool) -> None:
    # pylint: disable=too-many-arguments
    # pylint: disable=too-many-positional-arguments
    for gap in gaps[:_MAX_GAP_ROWS]:
        row = [
            scope.component, scope.target, scope.config, scope.scope, gap.file,
            gap.spot
        ]
        if with_uid:
            row.insert(0, gap.uid)
        rows.append(row)
    more = len(gaps) - _MAX_GAP_ROWS
    if more > 0:
        notes.append(f"And {more} more in scope {scope.scope} of "
                     f"{scope.target} and configuration {scope.config} of "
                     f"component {scope.component}.")


def _add_gap_section(content: TextContent, name: str, rows: list[list[str]],
                     notes: list[str]) -> None:
    if len(rows) > 1:
        with content.section(name):
            content.add_simple_table(rows)
            for note in notes:
                content.add(note)


def _count(count: int, singular: str, plural: str) -> str:
    return f"{count} {singular if count == 1 else plural}"


def _add_status(content: TextContent, verdicts: list[_Verdicts],
                not_validated: list[NotValidatedItem],
                failed_substitutions: list[_FailedSubstitution],
                root_inspected: bool) -> None:
    # The test report lists the coverage issues of a target under the UID of
    # the target.  A coverage scope which misses its limits and a stale gap
    # item are coverage issues of their target.
    items = 0
    targets = 0
    for verdicts_2 in verdicts:
        for target, uids in verdicts_2.failures.items():
            items += sum(1 for uid in uids if uid != target)
            targets += int(target in uids)
    causes: list[str] = []
    if items:
        causes.append(
            _count(items, "item with unexpected test failures",
                   "items with unexpected test failures"))
    if targets:
        causes.append(
            _count(targets, "target with coverage issues",
                   "targets with coverage issues"))
    if not_validated:
        causes.append(
            _count(len(not_validated), "item is not validated",
                   "items are not validated"))
    if failed_substitutions:
        causes.append(
            _count(len(failed_substitutions),
                   "item text fails the substitution",
                   "item texts fail the substitution"))
    if causes:
        with content.section("❌ Failed"):
            content.add_list(causes)
    else:
        with content.section("✅ Passed"):
            root = "  The specification root is validated.  All item " \
                "texts pass the substitution." if root_inspected else ""
            content.add("There are no unexpected test failures.  All "
                        "coverage scopes meet their limits.  There are no "
                        f"stale gap items.{root}")


def _add_warnings(content: TextContent, retried: list[RetriedProgram]) -> None:
    if retried:
        with content.section("⚠️ Warnings"):
            content.add_list([
                _count(len(retried), "test program has failed attempts",
                       "test programs have failed attempts")
            ])


def _add_test_overview(content: TextContent,
                       verdicts: list[_Verdicts]) -> None:
    with content.section("Test overview"):
        rows = [["Component", "Target", *_COUNT_HEADER]]
        for verdicts_2 in verdicts:
            for target, counts in verdicts_2.counts.items():
                rows.append([verdicts_2.component, target] +
                            [str(counts[key]) for key in _COUNT_KEYS])
        if len(rows) == 1:
            content.add("There are no test program results.")
        else:
            content.add("The table counts the test programs.")
            content.add_simple_table(rows)


def _sentence(text: str) -> str:
    return text if text.endswith(".") else f"{text}."


def _add_unexpected_failures(content: TextContent,
                             verdicts: list[_Verdicts]) -> None:
    rows = [["Component", "Target", "Item", "Reason"]]
    for verdicts_2 in verdicts:
        reasons = verdicts_2.reasons
        for target, uids in verdicts_2.failures.items():
            rows.extend([
                verdicts_2.component, target, uid, " ".join(
                    _sentence(reason)
                    for reason in reasons.get(target, {}).get(uid, []))
            ] for uid in uids)
    if len(rows) > 1:
        with content.section("Unexpected failures"):
            content.add_simple_table(rows)


def _add_not_validated(content: TextContent,
                       not_validated: list[NotValidatedItem]) -> None:
    if not_validated:
        with content.section("Not validated items"):
            content.add("The specification root is not validated.  The table "
                        "lists the related items without a successful "
                        "validation in the order of the specification tree.")
            content.add_simple_table([["Component", "Item", "Type"]] +
                                     [[item.component, item.uid, item.type]
                                      for item in not_validated])


def _add_failed_substitutions(
        content: TextContent,
        failed_substitutions: list[_FailedSubstitution]) -> None:
    if failed_substitutions:
        with content.section("Failed substitutions"):
            content.add("The table lists the items with a text which fails "
                        "the substitution and the first error of each item.")
            content.add_simple_table(
                [["Component", "Item", "Error"]] +
                [[failed.component, failed.uid, failed.error]
                 for failed in failed_substitutions])


def _add_retried_programs(content: TextContent,
                          retried: list[RetriedProgram]) -> None:
    if retried:
        with content.section("Retried test programs"):
            content.add("The table lists the test programs which the test "
                        "runner ran again after a failed attempt.")
            content.add_simple_table([[
                "Component", "Target", "Configuration", "Program",
                "Failed attempts"
            ]] + [[
                program.component, program.target, program.config,
                program.program,
                str(program.failed_attempts)
            ] for program in retried])


def _add_coverage(content: TextContent, scopes: list[CoverageScope]) -> None:
    with content.section("Coverage"):
        if not scopes:
            content.add("There is no coverage data available.")
            return
        rows = [[
            "Component", "Target", "Configuration", "Scope", "Functions",
            "Status", "Lines", "Status", "Branches", "Status"
        ]]
        rows.extend(
            [scope.component, scope.target, scope.config, scope.scope] +
            scope.cells for scope in scopes)
        content.add_simple_table(rows)


class _Aggregations(NamedTuple):
    verdicts: list[_Verdicts]
    scopes: list[CoverageScope]
    not_validated: list[NotValidatedItem]
    failed_substitutions: list[_FailedSubstitution]
    retried: list[RetriedProgram]


def _first_line(text: str) -> str:
    return text.splitlines()[0].replace("|", "\\|")


def _make_verdicts(ident: str, analysis: TestAnalysis,
                   not_validated: set[str]) -> _Verdicts:
    # A not validated item states a missing test result, so the failures
    # leave it out.  An item has one entry for each target.
    failures: dict[str, list[str]] = {}
    reasons: dict[str, dict[str, list[str]]] = {}
    all_reasons = analysis.get_unexpected_failure_reasons()
    for target, uids in analysis.get_unexpected_failures().items():
        by_uid: dict[str, list[str]] = {}
        for uid in uids:
            texts = all_reasons[target][uid]
            if uid in not_validated:
                texts = [text for text in texts if text != NO_TEST_RESULTS]
            if texts:
                by_uid[uid] = texts
        if by_uid:
            failures[target] = list(by_uid)
            reasons[target] = by_uid
    return _Verdicts(ident, failures, reasons, analysis.program_counts)


def _gather_aggregations(
        test_aggregators: list[TestAggregator]) -> _Aggregations:
    # Each component validates the specification in its own item view, so
    # query each test aggregator in the scope of its component.
    verdicts: list[_Verdicts] = []
    scopes: list[CoverageScope] = []
    not_validated: set[NotValidatedItem] = set()
    failed_substitutions: set[_FailedSubstitution] = set()
    retried: list[RetriedProgram] = []
    for test_aggregator in test_aggregators:
        with test_aggregator.component.scope():
            ident = test_aggregator.substitute("${.:/component/ident}")
            items = test_aggregator.get_not_validated_items()
            not_validated.update(items)
            verdicts.append(
                _make_verdicts(ident, test_aggregator.get_analysis(),
                               set(item.uid for item in items)))
            failed_substitutions.update(
                _FailedSubstitution(ident, uid, _first_line(error))
                for uid, error in get_substitution_errors(
                    test_aggregator.spec.get_spec_root()))
            scopes.extend(test_aggregator.get_coverage_scopes())
            retried.extend(test_aggregator.get_retried_programs())
    return _Aggregations(verdicts, scopes, sorted(not_validated),
                         sorted(failed_substitutions), retried)


class PackageSummary(DirectoryState):
    """
    Builds a package summary in CommonMark.

    The summary states the overall status at its beginning.  It takes the
    verdicts from the analysis of each test aggregation and needs no test
    report.  A specification root which is not validated fails the package.
    The summary then lists every related item which is not validated.  An item
    text which fails the substitution fails the package.  Only a test
    aggregation inspects the specification root and the item texts.  A test
    program with failed attempts gives a warning.  The summary omits the
    sections of warnings, failures, not validated items, failed substitutions,
    gaps, stale gap items and retried test programs without entries.  The
    summary lists the repositories of the package, unless the
    list-repositories attribute is false.
    """

    def run(self) -> None:
        summary_file = self.file
        self.mapper.set_format(summary_file)
        test_aggregators: list[TestAggregator] = []
        for test_aggregator in self.inputs("test-aggregation"):
            assert isinstance(test_aggregator, TestAggregator)
            test_aggregators.append(test_aggregator)
        aggregations = _gather_aggregations(test_aggregators)
        content = CommonMarkContent(0, context=self.mapper.context)
        with content.section(f"Package summary - {self.component['ident']}"):
            _add_status(content, aggregations.verdicts,
                        aggregations.not_validated,
                        aggregations.failed_substitutions,
                        bool(test_aggregators))
            _add_warnings(content, aggregations.retried)
            _add_test_overview(content, aggregations.verdicts)
            _add_unexpected_failures(content, aggregations.verdicts)
            _add_not_validated(content, aggregations.not_validated)
            _add_failed_substitutions(content,
                                      aggregations.failed_substitutions)
            _add_coverage(content, aggregations.scopes)
            rows = [[
                "Component", "Target", "Configuration", "Scope", "File", "Spot"
            ]]
            notes: list[str] = []
            for scope in aggregations.scopes:
                _add_gap_rows(rows, notes, scope, scope.gaps, False)
            _add_gap_section(content, "Unjustified gaps", rows, notes)
            rows = [[
                "Item", "Component", "Target", "Configuration", "Scope",
                "File", "Spot"
            ]]
            notes = []
            for scope in aggregations.scopes:
                _add_gap_rows(rows, notes, scope, scope.stale, True)
            _add_gap_section(content, "Stale gap items", rows, notes)
            _add_retried_programs(content, aggregations.retried)
            if self.item.get("list-repositories", True):
                with content.section("Repositories"):
                    self._add_repositories(content)
        content.write(summary_file)
        path = self.mapper.create_content().path(summary_file)
        self.description.add(f"""Produce the package summary file
{path}.""")

    def _add_repositories(self, content: TextContent) -> None:
        package = self.director.package
        prefix = package.substitute("${.:/component/deployment-directory}")
        for component in package.components():
            with component.scope():
                for item in component.item.children("input"):
                    if item.type != "pkg/directory-state/repository":
                        continue
                    repo = self.director[item.uid]
                    repo_dir = repo["directory"]
                    with content.section(os.path.relpath(repo_dir, prefix)):
                        stdout: list[str] = []
                        run_command(["git", "log", "-1"], repo_dir, stdout)
                        content.add_code_block(stdout)
