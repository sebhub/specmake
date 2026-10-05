# SPDX-License-Identifier: BSD-2-Clause
"""
Provides a command line interface to draw and compare runtime performance
measurements.
"""

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

import argparse
import dataclasses
import hashlib
import json
import math
import os
import re
import statistics
import sys
from typing import Any

from specitems import (CommonMarkContent, MarkdownContent, SphinxContent,
                       TextContent)
import matplotlib

matplotlib.use("Agg")

# pylint: disable=wrong-import-position
import matplotlib.pyplot as plt  # noqa: E402

from .testoutputparser import augment_report  # noqa: E402
from .util import PDF_METADATA, command_arguments  # noqa: E402

JSON_BEGIN = "*** BEGIN OF JSON ***"
JSON_END = "*** END OF JSON ***"

_DPI = 100
_WIDTH_INCHES = 12.0
_METADATA = {"pdf": PDF_METADATA, "svg": {"Date": None}}
_STEM_LENGTH = 100

Samples = dict[tuple[str, str], list[float]]

_TEXT_FORMATS: dict[str, tuple[type[TextContent], str]] = {
    "commonmark": (CommonMarkContent, ".md"),
    "myst": (MarkdownContent, ".md"),
    "rest": (SphinxContent, ".rst"),
}


@dataclasses.dataclass
class Statistics:
    """ Holds the statistics of the samples of one measurement. """
    minimum: float
    q1: float
    median: float
    q3: float
    maximum: float


def ratio(value: float, reference: float) -> float:
    """
    Returns the ratio of the value to the reference.

    Two zero values have the ratio one.  A non-zero value has the ratio
    infinity to a zero reference.
    """
    if reference == 0.0:
        return 1.0 if value == 0.0 else math.inf
    return value / reference


def _relative_noise(noise: float, reference: float) -> float:
    """
    Returns the noise relative to the reference.

    A zero noise has the relative noise zero.  A non-zero noise has the
    relative noise infinity to a zero reference.
    """
    if noise == 0.0:
        return 0.0
    return ratio(noise, reference)


@dataclasses.dataclass
class Comparison:
    """ Holds the comparison of the runs A and B of one measurement. """
    name: str
    variant: str
    a: Statistics
    b: Statistics
    median_noise: float
    maximum_noise: float

    @property
    def median_change(self) -> float:
        """ Is the change of the median from A to B relative to A. """
        return ratio(self.b.median, self.a.median) - 1.0

    @property
    def maximum_change(self) -> float:
        """ Is the change of the maximum from A to B relative to A. """
        return ratio(self.b.maximum, self.a.maximum) - 1.0

    @property
    def verdict(self) -> str:
        """ Is the verdict of the median against the noise. """
        if self.b.median < self.a.median - self.median_noise:
            return "improved"
        if self.b.median > self.a.median + self.median_noise:
            return "regressed"
        return "neutral"

    @property
    def maximum_regressed(self) -> bool:
        """ Is true, if the B maximum exceeds the A maximum and the noise. """
        return self.b.maximum > self.a.maximum + self.maximum_noise


@dataclasses.dataclass
class Run:
    """ Holds the sources of one run of a comparison. """
    label: str
    a: Samples
    b: Samples | None
    a2: Samples | None


def get_statistics(samples: list[float]) -> Statistics:
    """ Returns the statistics of the samples. """
    ordered = sorted(samples)
    if len(ordered) < 2:
        value = ordered[0]
        return Statistics(value, value, value, value, value)
    q1, q2, q3 = statistics.quantiles(ordered, n=4, method="inclusive")
    return Statistics(ordered[0], q1, q2, q3, ordered[-1])


def _add_samples(samples: Samples, name: str, variant: str,
                 values: list[float]) -> None:
    if values:
        samples.setdefault((name, variant), []).extend(values)


def _load_test_reports(data: dict[str, Any], samples: Samples) -> None:
    for report in data["reports"]:
        if "info" not in report:
            augment_report(report, report.get("output", []))
        try:
            test_cases = report["test-suite"]["test-cases"]
        except KeyError:
            continue
        for test_case in test_cases:
            for measurement in test_case["runtime-measurements"]:
                _add_samples(samples, measurement["name"],
                             measurement["variant"], measurement["samples"])


def _load_measurements(data: dict[str, Any], samples: Samples) -> None:
    for measurement in data["measurements"]:
        _add_samples(samples, measurement["name"], str(measurement["variant"]),
                     measurement["samples"])


def _extract_json(text: str) -> dict[str, Any]:
    lines: list[str] = []
    inside = False
    for line in text.splitlines():
        line = line.strip()
        if line == JSON_BEGIN:
            inside = True
            lines = []
        elif line == JSON_END and inside:
            inside = False
            return json.loads("\n".join(lines))
        elif inside:
            lines.append(line)
    raise ValueError("the output holds no complete JSON block")


def load_samples(source: str) -> Samples:
    """
    Loads the samples of a source.

    The source is the path to a JSON test report, a JSON file with
    measurements, or an output which holds such a JSON file between the
    JSON_BEGIN and JSON_END lines.  A source of the form PATH#PREFIX keeps
    the measurements with names which start with PREFIX and a slash.  It
    removes this start from the names.
    """
    path, _, prefix = source.partition("#")
    with open(path, "r", encoding="utf-8") as src:
        text = src.read()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = _extract_json(text)
    samples: Samples = {}
    if "reports" in data:
        _load_test_reports(data, samples)
    else:
        _load_measurements(data, samples)
    if not prefix:
        return samples
    start = f"{prefix}/"
    return {
        (name[len(start):], variant): values
        for (name, variant), values in samples.items()
        if name.startswith(start)
    }


_ENVIRONMENTS = {"HotCache": 0, "FullCache": 1, "DirtyCache": 2}


def _variant_key(variant: str) -> tuple[int, float, str]:
    try:
        return (0, float(variant), variant)
    except ValueError:
        pass
    if variant in _ENVIRONMENTS:
        return (1, float(_ENVIRONMENTS[variant]), variant)
    if variant.startswith("Load/"):
        try:
            return (1, float(variant[5:]) + 2.0, variant)
        except ValueError:
            pass
    return (2, 0.0, variant)


def _variants_are_numbers(variants: list[str]) -> bool:
    return all(_variant_key(variant)[0] == 0 for variant in variants)


def _names_and_variants(samples: Samples) -> dict[str, list[str]]:
    names: dict[str, list[str]] = {}
    for name, variant in samples:
        names.setdefault(name, []).append(variant)
    for variants in names.values():
        variants.sort(key=_variant_key)
    return dict(sorted(names.items()))


def compare(run: Run) -> list[Comparison]:
    """ Compares the runs A and B of the run. """
    assert run.b is not None
    comparisons: list[Comparison] = []
    for name, variants in _names_and_variants(run.a).items():
        for variant in variants:
            key = (name, variant)
            if key not in run.b:
                continue
            a_stats = get_statistics(run.a[key])
            b_stats = get_statistics(run.b[key])
            median_noise = 0.0
            maximum_noise = 0.0
            if run.a2 is not None and key in run.a2:
                a2_stats = get_statistics(run.a2[key])
                median_noise = abs(a2_stats.median - a_stats.median)
                maximum_noise = abs(a2_stats.maximum - a_stats.maximum)
            comparisons.append(
                Comparison(name, variant, a_stats, b_stats, median_noise,
                           maximum_noise))
    return comparisons


def _scale_and_unit(value: float) -> tuple[float, str]:
    if value < 1e-6:
        return 1e9, "ns"
    if value < 1e-3:
        return 1e6, "μs"
    if value < 1.0:
        return 1e3, "ms"
    return 1.0, "s"


def _format(value: float) -> str:
    scale, unit = _scale_and_unit(value)
    return f"{scale * value:.3f} {unit}"


def comparison_table(runs: list[Run], content: TextContent) -> None:
    """ Adds the comparison of the runs as a table to the content. """
    rows = [("Run", "Name", "Variant", "A median", "B median", "Median change",
             "Noise", "Maximum change", "Verdict")]
    for run in runs:
        if run.b is None:
            continue
        for item in compare(run):
            verdict = item.verdict
            if item.maximum_regressed:
                verdict += ", maximum regressed"
            noise = _relative_noise(item.median_noise, item.a.median)
            rows.append(
                (run.label, item.name, item.variant, _format(item.a.median),
                 _format(item.b.median), f"{100 * item.median_change:+.1f} %",
                 f"{100 * noise:.1f} %", f"{100 * item.maximum_change:+.1f} %",
                 verdict))
    content.add_simple_table(rows)


def count_regressions(runs: list[Run]) -> int:
    """ Returns the count of medians and maxima which regressed. """
    count = 0
    for run in runs:
        if run.b is None:
            continue
        for item in compare(run):
            if item.verdict == "regressed":
                count += 1
            if item.maximum_regressed:
                count += 1
    return count


def _file_name(label: str, name: str) -> str:
    """
    Returns the file name stem of the label and the name.

    The readable part replaces each run of other characters by a hyphen and
    has at most 100 characters.  The digest of the label and the name makes
    the stem unique.
    """
    readable = re.sub(r"[^A-Za-z0-9_.-]+", "-",
                      f"{label}-{name}").strip("-")[:_STEM_LENGTH]
    digest = hashlib.sha256(json.dumps([label, name]).encode("utf-8"))
    return f"{readable}-{digest.hexdigest()[:8]}"


def _save(fig: Any, base: str, formats: list[str]) -> list[str]:
    files = []
    for fmt in formats:
        path = f"{base}.{fmt}"
        with matplotlib.rc_context({"svg.hashsalt": os.path.basename(path)}):
            fig.savefig(path, metadata=_METADATA.get(fmt))
        files.append(path)
    plt.close(fig)
    return files


def draw_ratios(runs: list[Run], title: str, base: str,
                formats: list[str]) -> list[str]:
    """
    Draws the ratio of the B median to the A median of each measurement.

    Each name gets a panel.  Each run gets a line.  The band of a run shows
    the noise of the A median.  An infinite ratio is a triangle with the label
    inf at the top of its panel.  An infinite noise ends the band there.
    """
    compared = [(run.label, compare(run)) for run in runs if run.b is not None]
    names = sorted({item.name for _, items in compared for item in items})
    if not names:
        return []
    fig, axes_list = plt.subplots(len(names),
                                  1,
                                  squeeze=False,
                                  figsize=(_WIDTH_INCHES,
                                           3.5 * len(names) + 1.0),
                                  dpi=_DPI)
    fig.suptitle(title)
    for axes, name in zip((row[0] for row in axes_list), names):
        _draw_ratio_panel(axes, name, compared)
    fig.tight_layout()
    return _save(fig, base, formats)


def _get_top(selections: list[tuple[str, list[Comparison]]]) -> float:
    finite = [1.0]
    for _, selected in selections:
        for item in selected:
            finite.append(ratio(item.b.median, item.a.median))
            finite.append(1.0 +
                          _relative_noise(item.median_noise, item.a.median))
    return max(2.0,
               1.25 * max(value for value in finite if math.isfinite(value)))


def _draw_infinite_ratios(axes: Any, x: list[float],
                          selected: list[Comparison], top: float,
                          color: str) -> bool:
    infinite = False
    for x_value, item in zip(x, selected):
        if math.isinf(ratio(item.b.median, item.a.median)):
            infinite = True
            axes.plot([x_value], [top], marker="^", markersize=10, color=color)
            axes.annotate("inf", (x_value, top),
                          textcoords="offset points",
                          xytext=(0, 8),
                          ha="center",
                          color=color)
    return infinite


def _draw_ratio_line(axes: Any, label: str, x: list[float],
                     selected: list[Comparison], top: float) -> bool:
    ratios = [
        min(ratio(item.b.median, item.a.median), top) for item in selected
    ]
    lines = axes.plot(x, ratios, marker="o", label=label)
    color = lines[0].get_color()
    infinite = _draw_infinite_ratios(axes, x, selected, top, color)
    noise = [
        min(_relative_noise(item.median_noise, item.a.median), top - 1.0)
        for item in selected
    ]
    axes.fill_between(x, [1.0 - value for value in noise],
                      [1.0 + value for value in noise],
                      color=color,
                      alpha=0.15,
                      linewidth=0)
    return infinite


def _draw_ratio_panel(axes: Any, name: str,
                      compared: list[tuple[str, list[Comparison]]]) -> None:
    variants = sorted(
        {
            item.variant
            for _, items in compared
            for item in items if item.name == name
        },
        key=_variant_key)
    numbers = _variants_are_numbers(variants)
    positions = {variant: index for index, variant in enumerate(variants)}
    selections = [(label, [item for item in items if item.name == name])
                  for label, items in compared]
    top = _get_top(selections)
    infinite = False
    for label, selected in selections:
        if numbers:
            x: list[float] = [float(item.variant) for item in selected]
        else:
            x = [float(positions[item.variant]) for item in selected]
        if _draw_ratio_line(axes, label, x, selected, top):
            infinite = True
    if numbers:
        if all(float(variant) > 0.0 for variant in variants):
            axes.set_xscale("log", base=2)
    else:
        axes.set_xticks(range(len(variants)), variants)
    if infinite:
        axes.set_ylim(top=1.1 * top)
    axes.axhline(1.0, color="black", linewidth=0.8)
    axes.set_title(name)
    axes.set_ylabel("B median / A median")
    axes.grid(True, which="both", linewidth=0.3)
    axes.legend(fontsize=8, ncol=4)


def draw_boxplots(run: Run, base_directory: str,
                  formats: list[str]) -> list[str]:
    """
    Draws the samples of each measurement of the run as box plots.

    Each name gets an image.  Each variant gets a box of A and, if the run
    has one, a box of B.
    """
    files: list[str] = []
    for name, variants in _names_and_variants(run.a).items():
        base = os.path.join(base_directory, _file_name(run.label, name))
        files.extend(_draw_boxplot(run, name, variants, base, formats))
    return files


_A_COLOR = "deepskyblue"
_B_COLOR = "orange"


@dataclasses.dataclass
class _Boxes:
    data: list[list[float]] = dataclasses.field(default_factory=list)
    positions: list[float] = dataclasses.field(default_factory=list)
    colors: list[str] = dataclasses.field(default_factory=list)
    ticks: list[float] = dataclasses.field(default_factory=list)

    def add(self, samples: list[float], scale: float, position: float,
            color: str) -> None:
        """ Adds a box of the samples. """
        self.data.append([scale * value for value in samples])
        self.positions.append(position)
        self.colors.append(color)


def _draw_boxplot(run: Run, name: str, variants: list[str], base: str,
                  formats: list[str]) -> list[str]:
    scale, unit = _scale_and_unit(
        max(
            get_statistics(run.a[(name, variant)]).median
            for variant in variants))
    boxes = _Boxes()
    for index, variant in enumerate(variants):
        boxes.add(run.a[(name, variant)], scale, 3 * index, _A_COLOR)
        if run.b is not None and (name, variant) in run.b:
            boxes.add(run.b[(name, variant)], scale, 3 * index + 1, _B_COLOR)
            boxes.ticks.append(3 * index + 0.5)
        else:
            boxes.ticks.append(3 * index)
    fig, axes = plt.subplots(figsize=(_WIDTH_INCHES, 6.0), dpi=_DPI)
    artists = axes.boxplot(boxes.data,
                           positions=boxes.positions,
                           widths=0.8,
                           patch_artist=True,
                           showfliers=False)
    for patch, color in zip(artists["boxes"], boxes.colors):
        patch.set_facecolor(color)
    axes.set_xticks(boxes.ticks, variants)
    axes.set_title(f"{run.label} - {name}")
    axes.set_xlabel("Variant")
    axes.set_ylabel(f"Runtime [{unit}]")
    axes.grid(True, axis="y", linewidth=0.3)
    if _B_COLOR in boxes.colors:
        axes.legend([
            artists["boxes"][boxes.colors.index(_A_COLOR)],
            artists["boxes"][boxes.colors.index(_B_COLOR)]
        ], ["A", "B"])
    fig.tight_layout()
    return _save(fig, base, formats)


def regroup_samples(samples: Samples, pattern: str) -> Samples:
    """
    Regroups the samples by a regular expression.

    The pattern shall match the name of a measurement and define the groups
    name and variant.  A matched measurement gets the name made of the name
    group, a slash and its variant, and it gets the variant group as its
    variant.  The result has no measurement which the pattern does not match.
    """
    regex = re.compile(pattern)
    regrouped: Samples = {}
    for (name, variant), values in samples.items():
        match = regex.fullmatch(name)
        if match is None:
            continue
        _add_samples(regrouped, f"{match.group('name')}/{variant}",
                     match.group("variant"), values)
    return regrouped


def parse_run(text: str, regroup: str | None = None) -> Run:
    """
    Parses a run argument of the form LABEL=A[,B[,A2]].

    A regroup pattern regroups the samples of each source, see
    regroup_samples().
    """
    label, separator, sources = text.partition("=")
    if not separator or not label or not sources:
        raise ValueError(f"invalid run: {text}")
    paths = sources.split(",")
    if len(paths) > 3 or not all(paths):
        raise ValueError(f"invalid run: {text}")
    loaded: list[Samples | None] = []
    for path in paths:
        samples = load_samples(path)
        if regroup is not None:
            samples = regroup_samples(samples, regroup)
        loaded.append(samples)
    loaded.extend([None] * (3 - len(loaded)))
    a_samples = loaded[0]
    assert a_samples is not None
    return Run(label, a_samples, loaded[1], loaded[2])


def cliperfimages(argv: list[str] | None = None) -> None:
    """ Draw and compare runtime performance measurements. """
    parser = argparse.ArgumentParser(description=cliperfimages.__doc__)
    parser.add_argument("--output-directory",
                        default=".",
                        help="the directory of the images and the table "
                        "(default: .)")
    parser.add_argument("--title",
                        default="Runtime performance",
                        help="the title of the ratio image")
    parser.add_argument("--format",
                        dest="formats",
                        action="append",
                        choices=["png", "svg", "pdf"],
                        help="an image format (default: png and svg)")
    parser.add_argument("--text-format",
                        choices=list(_TEXT_FORMATS),
                        type=str.lower,
                        default="commonmark",
                        help="the text format of the comparison table "
                        "(default: commonmark)")
    parser.add_argument("--regroup",
                        metavar="PATTERN",
                        help="a regular expression with the groups name and "
                        "variant which regroups the measurements by their "
                        "names")
    parser.add_argument("--fail-on-regression",
                        action="store_true",
                        help="exit with a status of one, if a median or a "
                        "maximum regressed")
    parser.add_argument("runs",
                        metavar="RUN",
                        nargs="+",
                        help="a run of the form LABEL=A[,B[,A2]], where A, "
                        "B and A2 are sources of the form PATH[#PREFIX]")
    args = parser.parse_args(command_arguments(argv))
    formats = args.formats or ["png", "svg"]
    runs = [parse_run(text, args.regroup) for text in args.runs]
    labels = [run.label for run in runs]
    if len(set(labels)) != len(labels):
        raise ValueError(f"duplicate run labels: {', '.join(labels)}")
    os.makedirs(args.output_directory, exist_ok=True)
    for run in runs:
        draw_boxplots(run, args.output_directory, formats)
    if any(run.b is not None for run in runs):
        draw_ratios(runs, args.title,
                    os.path.join(args.output_directory, "ratio"), formats)
        content_class, extension = _TEXT_FORMATS[args.text_format]
        content = content_class(context="CC-BY-SA-4.0")
        comparison_table(runs, content)
        table = str(content)
        with open(os.path.join(args.output_directory,
                               f"comparison{extension}"),
                  "w",
                  encoding="utf-8") as dst:
            dst.write(table)
        print(table, end="")
        if args.fail_on_regression and count_regressions(runs) > 0:
            sys.exit(1)
