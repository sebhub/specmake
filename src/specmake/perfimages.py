# SPDX-License-Identifier: BSD-2-Clause
""" Generates runtime performance measurement images. """

# Copyright (C) 2022, 2025 embedded brains GmbH & Co. KG
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

import logging
import multiprocessing
import os
import matplotlib.pyplot as plt  # type: ignore
from matplotlib import ticker  # type: ignore

from specitems import Item

from .directorystate import DirectoryState
from .pkgitems import PackageBuildDirector
from .testaggregator import TestAggregator
from .util import PDF_METADATA, variant_order

logging.getLogger("matplotlib").setLevel(logging.WARNING)
logging.getLogger("PIL").setLevel(logging.WARNING)


def environment_order(env_name_data: tuple) -> tuple[int, float, str]:
    """
    Returns the environment order key for the environment name and data pair.
    """
    return variant_order(env_name_data[0])


def _worker(work_queue: multiprocessing.Queue, build_item_uid: str):
    while True:
        measurement_data = work_queue.get()
        if measurement_data is None:
            logging.info("%s: worker done", build_item_uid)
            return
        req_uid = measurement_data["requirement-uid"]
        config = measurement_data["test-case"]["test-suite"]["config"]
        config_key = config["config-key"]
        target_name = config["target"]["name"]
        logging.info("%s: create images for: %s - %s - %s", build_item_uid,
                     target_name, config_key, req_uid)
        spec = f"spec:{req_uid}"
        env_samples = []
        env_names = []
        max_median = 0
        for env_name, env_data in sorted(measurement_data["variants"].items(),
                                         key=environment_order):
            env_names.append(env_name)
            env_samples.append(env_data["samples"])
            max_median = max(max_median, env_data["q2"])
            base = env_data["histogram"]
            title = f"""{spec}
Target - {target_name}
Configuration - {config_key}
Measurement Environment - {env_name}"""
            _histogram(title, base, env_data)
        base = measurement_data["boxplot"]
        title = f"""{spec}
Target - {target_name}
Configuration - {config_key}"""
        _boxplot(title, base, max_median, env_samples, env_names)


def _scale_and_unit(value: float) -> tuple[float, str]:
    if value < 1e-6:
        return 1e9, "ns"
    if value < 1e-3:
        return 1e6, "μs"
    if value < 1.0:
        return 1e3, "ms"
    return 1.0, "s"


def _freedman_draconis(scale: float, env_data: dict) -> int:
    sample_count = len(env_data["samples"])
    try:
        width = 2 * scale * (env_data["q3"] -
                             env_data["q1"]) / sample_count**(1. / 3.)
        bin_count = int(scale * (env_data["max"] - env_data["min"]) / width)
        return min(bin_count, sample_count)
    except ZeroDivisionError:
        return sample_count


def _histogram(title: str, base: str, env_data: dict) -> None:
    scale, unit = _scale_and_unit(env_data["q2"])
    scaled_samples = list(scale * sample for sample in env_data["samples"])
    q123 = [
        scale * env_data["q1"], scale * env_data["q2"], scale * env_data["q3"]
    ]
    fig, axes = plt.subplots()
    axes.set_title(title)
    axes.set_xlabel(f"Runtime [{unit}]")
    # Quartiles reported by the target may lie outside the sample range. Keep
    # them within the limits, otherwise their labels are rendered far off the
    # canvas and the glyph rasterization fails.
    axes.set_xlim(min(scale * env_data["min"], *q123),
                  max(scale * env_data["max"], *q123))
    axes.set_ylabel("Sample Count")
    ymax = len(scaled_samples)
    ymin = 0
    axes.set_ylim(ymin, ymax)
    axes.hist(scaled_samples,
              _freedman_draconis(scale, env_data),
              color="deepskyblue")
    axes.hist(scaled_samples,
              list(sorted(set(scaled_samples))),
              histtype="step",
              color="black",
              cumulative=True)
    plt.vlines(q123, ymin=ymin, ymax=ymax)
    for i, quartile in enumerate(q123):
        plt.text(quartile, (2 * i + 1) * ymax / 8, f"Q{i + 1}")
    fig.tight_layout()
    plt.savefig(f"{base}.png")
    plt.savefig(f"{base}.pdf", metadata=PDF_METADATA)
    plt.close()


def _boxplot(title: str, base: str, max_median: float,
             env_samples: list[list[float]], env_names: list[str]) -> None:
    scale, unit = _scale_and_unit(max_median)
    scaled_samples = []
    for samples in env_samples:
        scaled_samples.append(list(scale * sample for sample in samples))
    fig, axes = plt.subplots()
    axes.set_title(title)
    axes.set_xlabel("Measurement Environment")
    axes.xaxis.set_major_locator(
        ticker.FixedLocator(list(range(len(env_names), 1))))
    axes.xaxis.set_major_formatter(ticker.FixedFormatter(env_names))
    axes.set_ylabel(f"Runtime [{unit}]")
    axes.yaxis.set_major_formatter(ticker.FormatStrFormatter("%.3f"))
    axes.boxplot(scaled_samples)
    fig.tight_layout()
    plt.savefig(f"{base}.png")
    plt.savefig(f"{base}.pdf", metadata=PDF_METADATA)
    plt.close()


class BuildPerformanceImages(DirectoryState):
    """ Generates runtime performance measurement images. """

    def __init__(self, director: PackageBuildDirector, item: Item):
        super().__init__(director, item)
        tests = self.input("test-aggregation")
        assert isinstance(tests, TestAggregator)
        files: list[str] = []
        for measurement_data in tests.runtime_measurements:
            uid = measurement_data["requirement-uid"]
            config = measurement_data["test-case"]["test-suite"]["config"]
            target = config["target"]
            name = f"{target['key']}-{config['config-key']}-{uid[1:]}".replace(
                "/", "-")
            for env_name, env_data in measurement_data["variants"].items():
                name_2 = f"{name}-{env_name.replace('/', '-')}"
                files.append(f"{name_2}.pdf")
                files.append(f"{name_2}.png")
                base = os.path.join(self.directory, name_2)
                env_data["histogram"] = base
            files.append(f"{name}.pdf")
            files.append(f"{name}.png")
            base = os.path.join(self.directory, name)
            measurement_data["boxplot"] = base
        self._perf_files = files

    def run(self) -> None:
        self.discard_and_clear()
        os.makedirs(self.directory, exist_ok=True)
        tests = self.input("test-aggregation")
        assert isinstance(tests, TestAggregator)
        work_queue: multiprocessing.Queue = multiprocessing.Queue()
        for measurement_data in tests.runtime_measurements:
            work_queue.put(measurement_data)
        processes = []
        for _ in range(
                min(multiprocessing.cpu_count(),
                    len(tests.runtime_measurements))):
            process = multiprocessing.Process(target=_worker,
                                              args=(work_queue, self.uid),
                                              daemon=True)
            work_queue.put(None)
            process.start()
            processes.append(process)
        for process in processes:
            process.join()
        failed = [process for process in processes if process.exitcode != 0]
        if failed:
            # Workers which died left their work items in the queue. Discard
            # them, otherwise the queue feeder thread blocks the process exit.
            work_queue.cancel_join_thread()
            raise RuntimeError(f"{self.uid}: {len(failed)} of "
                               f"{len(processes)} image workers failed")
        self.set_files(self._perf_files)

        self.description.add(f"""Produce performance images in directory
{self.description.path(self.directory)}""")
