# SPDX-License-Identifier: BSD-2-Clause
""" Generates images for special test programs of the RTEMS test suites. """

# Copyright (C) 2024, 2025 embedded brains GmbH & Co. KG
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
import math
import os
import re
import statistics
from typing import Any, Callable
import matplotlib.pyplot as plt  # type: ignore
from matplotlib import ticker  # type: ignore

from specitems import Item

from .directorystate import DirectoryState
from .pkgitems import PackageBuildDirector
from .testaggregator import TestAggregator
from .util import PDF_METADATA

logging.getLogger("matplotlib").setLevel(logging.WARNING)
logging.getLogger("PIL").setLevel(logging.WARNING)


def _default_files(base: str) -> list[str]:
    return [base]


def _savefig(fig: plt.Figure, axes: plt.Axes, base: str) -> list[str]:
    axes.legend(loc="best")
    fig.tight_layout()
    plt.savefig(f"{base}.png")
    plt.savefig(f"{base}.pdf", metadata=PDF_METADATA)
    return [f"{base}.png", f"{base}.pdf"]


def _tmfine01_build(title: str, base: str, data: dict) -> list[str]:
    fig, axes = plt.subplots()
    axes.set_title(f"{title}\nUncontested Mutex Performance")
    axes.set_xlabel("Active Workers")
    axes.set_ylabel("Operation Count")
    x = list(range(1, len(data[0]["counter"]) + 1))
    axes.xaxis.set_major_locator(ticker.FixedLocator(x))
    for samples in data:
        if samples["type"] != "private-mutex":
            continue
        y = [sum(values) for values in samples["counter"]]
        axes.plot(x,
                  y,
                  label=samples["description"].replace(
                      "Obtain/Release Private ", ""),
                  marker="o")
    return _savefig(fig, axes, base)


def _tmcontext01_build(title: str, base: str, data: dict) -> list[str]:
    fig, axes = plt.subplots()
    axes.set_title(f"{title}\nContext Switch Timing Test")
    axes.set_xlabel("Function Nest Level")
    axes.set_ylabel("Context Switch Time [μs]")
    x = list(range(0, len(data[0]["stats-by-function-nest-level"])))
    axes.xaxis.set_major_locator(ticker.FixedLocator(x))
    for samples in data:
        y = [
            values[2] / 1000.0
            for values in samples["stats-by-function-nest-level"]
        ]
        axes.plot(x, y, label=samples["environment"], marker="o")
    return _savefig(fig, axes, base)


def _tmtimer01_build(title: str, base: str, data: dict) -> list[str]:
    fig, axes = plt.subplots()
    axes.set_title(f"{title}\nTimer Fire and Cancel Timing Test")
    axes.set_xlabel("Active Timers")
    axes.set_xscale("log")
    axes.set_ylabel("Timer Fire and Cancel Duration [μs]")
    x = [sample["active-timers"] for sample in data["samples"]]
    for key in ("first", "middle", "last"):
        y = [sample[key] / 1000.0 for sample in data["samples"]]
        axes.plot(x, y, label=f"operate on {key} timer", marker="o")
    return _savefig(fig, axes, base)


def _smpopenmp01_build(title: str, base: str, data: dict) -> list[str]:
    fig, axes = plt.subplots()
    axes.set_title(f"{title}\nOpenMP Microbench")
    axes.set_xlabel("Number of Threads")
    axes.set_ylabel("Relative Duration")
    x = list(range(1, len(data) + 1))
    axes.xaxis.set_major_locator(ticker.FixedLocator(x))
    for key in ("barrier-bench", "dynamic-bench", "guided-bench",
                "parallel-bench", "runtime-bench", "single-bench",
                "static-bench"):
        d = [results[key] for results in data]
        y = [x / d[0] for x in d]
        axes.plot(x, y, label=key.replace("-bench", ""), marker="o")
    return _savefig(fig, axes, base)


def _normed_coefficient_of_variation(counter: list[int]) -> float:
    return (statistics.stdev(counter) / statistics.mean(counter)) / math.sqrt(
        len(counter))


def _smplock01_files(base: str) -> list[str]:
    return [f"{base}-fair", f"{base}-perf"]


def _smplock01_fair(title: str, base: str, data: dict) -> list[str]:
    fig, axes = plt.subplots()
    axes.set_title(f"{title}\nSMP Lock Fairness")
    axes.set_xlabel("Active Workers")
    axes.set_ylabel("Normed Coefficient of Variation")
    axes.set_yscale("symlog", linthresh=1e-6)
    x = list(range(2, len(data[0]["results"]) + 1))
    axes.xaxis.set_major_locator(ticker.FixedLocator(x))
    for samples in data:
        if samples["lock-object"] != "global":
            continue
        if samples["section-type"] != "local counter":
            continue
        y = [
            _normed_coefficient_of_variation(results["counter"])
            for results in samples["results"][1:]
        ]
        axes.plot(x, y, label=samples["lock-type"], marker="o")
    return _savefig(fig, axes, f"{base}-fair")


def _smplock01_perf(title: str, base: str, data: dict) -> list[str]:
    fig, axes = plt.subplots()
    axes.set_title(f"{title}\nSMP Lock Performance")
    axes.set_xlabel("Active Workers")
    axes.set_ylabel("Operation Count")
    x = list(range(1, len(data[0]["results"]) + 1))
    axes.xaxis.set_major_locator(ticker.FixedLocator(x))
    for samples in data:
        if samples["lock-object"] != "global":
            continue
        if samples["section-type"] != "local counter":
            continue
        y = [sum(results["counter"]) for results in samples["results"]]
        axes.plot(x, y, label=samples["lock-type"], marker="o")
    return _savefig(fig, axes, f"{base}-perf")


def _smplock01_build(title: str, base: str, data: dict) -> list[str]:
    files = _smplock01_fair(title, base, data)
    files.extend(_smplock01_perf(title, base, data))
    return files


def _sptimecounter02_build(title: str, base: str, data: dict) -> list[str]:
    fig, axes = plt.subplots()
    axes.set_title(f"{title}\nTimestamp Performance")
    axes.set_xlabel("Active Workers")
    axes.set_ylabel("Operation Count")
    x = list(range(1, len(data[0]["counter"]) + 1))
    axes.xaxis.set_major_locator(ticker.FixedLocator(x))
    for samples in data:
        y = [sum(values) for values in samples["counter"]]
        axes.plot(x, y, label=samples["timecounter"], marker="o")
    return _savefig(fig, axes, base)


_IMAGE_GENERATORS = {
    "/build/testsuites/tmtests/tmfine01": (_default_files, _tmfine01_build),
    "/build/testsuites/tmtests/tmcontext01":
    (_default_files, _tmcontext01_build),
    "/build/testsuites/tmtests/tmtimer01": (_default_files, _tmtimer01_build),
    "/build/testsuites/smptests/smpopenmp01":
    (_default_files, _smpopenmp01_build),
    "/build/testsuites/smptests/smplock01":
    (_smplock01_files, _smplock01_build),
    "/build/testsuites/sptests/sptimecounter02":
    (_default_files, _sptimecounter02_build)
}


def _append_test_images(_title: str, base: str, report: dict,
                        generate: tuple) -> None:
    if _get_json_data(report) is not None:
        report.setdefault("images", []).extend(generate[0](base))


_JSON_DATA = re.compile(r"\*\*\* BEGIN OF JSON DATA \*\*\*(.*)"
                        r"\*\*\* END OF JSON DATA \*\*\*")


def _get_json_data(report: dict) -> Any:
    match = _JSON_DATA.search("".join(report["output"]))
    if match:
        return match.group(1)
    return None


class BuildRTEMSTestsImages(DirectoryState):
    """
    Generates images for special test programs of the RTEMS test suites.
    """

    def __init__(self, director: PackageBuildDirector, item: Item):
        super().__init__(director, item)
        self._generate(_append_test_images)

    def run(self) -> None:
        self.discard_and_clear()
        os.makedirs(self.directory, exist_ok=True)
        self._generate(self._build_test_images)
        plt.close()
        self.description.add(f"""Produce RTEMS tests images in directory
{self.description.path(self.directory)}""")

    def _build_test_images(self, title: str, base: str, report: dict,
                           generate: tuple) -> None:
        json_data = _get_json_data(report)
        if json_data is not None:
            logging.info("%s: generate: %s", self.uid, base)
            self.add_files(generate[1](title, base, json.loads(json_data)))
        else:
            logging.warning("%s: no JSON data for: %s", self.uid, base)

    def _generate(self, work: Callable[[str, str, dict, tuple], None]) -> None:
        tests = self.input("test-aggregation")
        assert isinstance(tests, TestAggregator)
        for target_data in tests.targets.values():
            target = target_data["key"]
            target_name = target_data["name"]
            for config_data in target_data["configs"]:
                config_key = config_data["config-key"]
                for uid, generate in _IMAGE_GENERATORS.items():
                    try:
                        report = config_data["test-programs"][uid]
                    except KeyError:
                        continue
                    name = f"{target}-{config_key}-{uid[1:]}".replace("/", "-")
                    base = os.path.join(self.directory, name)
                    title = f"""spec:{uid}
Target - {target_name}
Configuration - {config_key}"""
                    work(title, base, report, generate)
