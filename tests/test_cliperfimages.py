# SPDX-License-Identifier: BSD-2-Clause
""" Tests for the cliperfimages module. """

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

import json
import math
import os
import pathlib
import re

import pytest
from specitems import CommonMarkContent

from specmake.cliperfimages import (JSON_BEGIN, JSON_END, Run, cliperfimages,
                                    compare, comparison_table,
                                    count_regressions, draw_boxplots,
                                    draw_ratios, get_statistics, load_samples,
                                    parse_run, ratio)


def _table_rows(text: str) -> list[list[str]]:
    return [[cell.strip() for cell in line.strip().strip("|").split("|")]
            for line in text.splitlines() if line.strip().startswith("|")]


def _measurements(scale: float, spread: float = 0.0) -> dict:
    return {
        "measurements": [{
            "name":
            f"impl-{impl}/work",
            "variant":
            variant,
            "samples": [(scale + spread * index) * variant * 1e-9
                        for index in range(11)]
        } for impl in ("a", "b") for variant in (1, 2, 3)]
    }


def _write_json(tmp_path, name: str, data: dict) -> str:
    path = tmp_path / name
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


def _write_output(tmp_path, name: str, data: dict) -> str:
    path = tmp_path / name
    path.write_text("\n".join([
        "*** BEGIN OF TEST BENCH ***", JSON_BEGIN,
        json.dumps(data, indent=1), JSON_END, "*** END OF TEST BENCH ***"
    ]),
                    encoding="utf-8")
    return str(path)


def _test_report(samples: list[float]) -> dict:
    return {
        "reports": [{
            "executable": "build/ts-performance.exe",
            "info": {},
            "test-suite": {
                "test-cases": [{
                    "runtime-measurements": [{
                        "name": "PerfOne",
                        "variant": variant,
                        "samples": samples
                    } for variant in ("HotCache", "Load/1", "FullCache")]
                }, {
                    "runtime-measurements": []
                }]
            }
        }, {
            "executable": "build/ts-other.exe",
            "info": {}
        }]
    }


def test_statistics_of_one_sample():
    stats = get_statistics([2.0])
    assert stats.minimum == 2.0
    assert stats.median == 2.0
    assert stats.maximum == 2.0


def test_statistics_of_several_samples():
    stats = get_statistics([5.0, 1.0, 3.0, 2.0, 4.0])
    assert stats.minimum == 1.0
    assert stats.q1 == 2.0
    assert stats.median == 3.0
    assert stats.q3 == 4.0
    assert stats.maximum == 5.0


def test_load_measurements_with_a_prefix(tmp_path):
    path = _write_json(tmp_path, "one.json", _measurements(10.0))
    samples = load_samples(f"{path}#impl-a")
    assert sorted(samples) == [("work", "1"), ("work", "2"), ("work", "3")]
    assert samples[("work", "2")][0] == pytest.approx(20e-9)


def test_load_measurements_from_an_output(tmp_path):
    path = _write_output(tmp_path, "one.txt", _measurements(10.0))
    samples = load_samples(path)
    assert ("impl-b/work", "3") in samples


@pytest.mark.parametrize("text", [f"{JSON_BEGIN}\n{{\n", f"{JSON_END}\n"])
def test_an_output_without_a_complete_json_block(tmp_path, text):
    path = tmp_path / "one.txt"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError, match="no complete JSON block"):
        load_samples(str(path))


def test_an_output_with_an_end_marker_before_the_block(tmp_path):
    path = tmp_path / "one.txt"
    data = {"measurements": [{"name": "work", "variant": 1, "samples": [1.0]}]}
    path.write_text("\n".join(
        [JSON_END, JSON_BEGIN,
         json.dumps(data), JSON_END]),
                    encoding="utf-8")
    assert load_samples(str(path)) == {("work", "1"): [1.0]}


def test_load_test_report(tmp_path):
    path = _write_json(tmp_path, "one.json", _test_report([1e-6, 2e-6]))
    samples = load_samples(path)
    assert samples[("PerfOne", "Load/1")] == [1e-6, 2e-6]
    assert len(samples) == 3


def test_load_test_report_with_an_output(tmp_path):
    data = {"reports": [{"executable": "build/a.exe", "output": []}]}
    path = _write_json(tmp_path, "one.json", data)
    assert not load_samples(path)


def test_compare_with_noise(tmp_path):
    a_path = _write_json(tmp_path, "a.json", _measurements(10.0))
    b_path = _write_json(tmp_path, "b.json", _measurements(8.0))
    a2_path = _write_json(tmp_path, "a2.json", _measurements(10.5))
    run = parse_run(f"one={a_path}#impl-a,{b_path}#impl-a,{a2_path}#impl-a")
    items = compare(run)
    assert [item.variant for item in items] == ["1", "2", "3"]
    assert all(item.verdict == "improved" for item in items)
    assert items[0].median_change == pytest.approx(-0.2)
    assert items[0].median_noise == pytest.approx(0.5e-9)
    assert count_regressions([run]) == 0


def test_compare_neutral_and_regressed():
    a_samples = {("work", "1"): [10.0], ("work", "2"): [10.0]}
    a2_samples = {("work", "1"): [10.5], ("work", "2"): [10.0]}
    b_samples = {("work", "1"): [10.4], ("work", "2"): [11.0]}
    run = Run("one", a_samples, b_samples, a2_samples)
    items = compare(run)
    assert items[0].verdict == "neutral"
    assert not items[0].maximum_regressed
    assert items[1].verdict == "regressed"
    assert items[1].maximum_regressed
    assert count_regressions([run]) == 2


def test_variants_in_order_and_runs_without_b(tmp_path):
    variants = ["Other", "Load/x", "Load/2", "DirtyCache", "HotCache"]
    a_samples = {("work", variant): [2e-3] for variant in variants}
    b_samples = {("work", variant): [3.0] for variant in variants}
    run = Run("one", a_samples, b_samples, None)
    assert [item.variant for item in compare(run)
            ] == ["HotCache", "DirtyCache", "Load/2", "Load/x", "Other"]
    alone = Run("two", a_samples, None, None)
    content = CommonMarkContent(context="CC-BY-SA-4.0")
    comparison_table([alone, run], content)
    rows = _table_rows(str(content))
    assert ["one", "work", "HotCache", "2.000 ms",
            "3.000 s"] in [row[:5] for row in rows]
    assert "two" not in [row[0] for row in rows]
    assert count_regressions([alone, run]) == 10


def test_zero_medians(tmp_path):
    a_samples = {("work", "1"): [0.0], ("work", "2"): [0.0]}
    b_samples = {("work", "1"): [0.0], ("work", "2"): [1e-9]}
    run = Run("one", a_samples, b_samples, a_samples)
    items = compare(run)
    assert items[0].median_change == 0.0
    assert items[0].verdict == "neutral"
    assert items[1].median_change == math.inf
    assert items[1].verdict == "regressed"
    assert ratio(2.0, 4.0) == 0.5
    path = _write_json(
        tmp_path, "a.json",
        {"measurements": [{
            "name": "work",
            "variant": 1,
            "samples": [0.0]
        }]})
    out = tmp_path / "out"
    cliperfimages([
        "specperfimages", "--output-directory",
        str(out), "--format", "png", f"one={path},{path}"
    ])
    assert ["one", "work", "1"] in [
        row[:3]
        for row in _table_rows((out /
                                "comparison.md").read_text(encoding="utf-8"))
    ]


def test_compare_skips_missing_variants():
    run = Run("one", {
        ("work", "1"): [1.0],
        ("work", "2"): [1.0]
    }, {("work", "1"): [1.0]}, None)
    assert [item.variant for item in compare(run)] == ["1"]


@pytest.mark.parametrize(
    "text",
    ["one", "=a", "one=", "one=a,b,c,d", "one=a,", "one=a,,b", "one=,b"])
def test_invalid_run(text):
    with pytest.raises(ValueError, match="invalid run"):
        parse_run(text)


def test_cli_draws_and_compares(tmp_path, capsys):
    a_path = _write_output(tmp_path, "a.txt", _measurements(10.0, 0.1))
    b_path = _write_output(tmp_path, "b.txt", _measurements(9.0, 0.1))
    out = tmp_path / "out"
    cliperfimages([
        "specperfimages", "--output-directory",
        str(out), "--format", "png", "--format", "pdf",
        f"one={a_path}#impl-a,{b_path}#impl-a",
        f"two={a_path}#impl-b,{b_path}#impl-b"
    ])
    files = sorted(
        re.sub(r"-[0-9a-f]{8}\.", ".", path.name) for path in out.iterdir())
    assert files == [
        "comparison.md", "one-work.pdf", "one-work.png", "ratio.pdf",
        "ratio.png", "two-work.pdf", "two-work.png"
    ]
    table = (out / "comparison.md").read_text(encoding="utf-8")
    assert ["one", "work", "2"] in [row[:3] for row in _table_rows(table)]
    assert "improved" in table
    assert table in capsys.readouterr().out
    for path in out.glob("*.pdf"):
        assert b"CreationDate" not in path.read_bytes()


def test_cli_with_environments(tmp_path):
    a_path = _write_json(tmp_path, "a.json", _test_report([1e-6, 2e-6]))
    b_path = _write_json(tmp_path, "b.json", _test_report([1e-6, 3e-6]))
    out = tmp_path / "out"
    with pytest.raises(SystemExit) as exc_info:
        cliperfimages([
            "specperfimages", "--output-directory",
            str(out), "--fail-on-regression", f"one={a_path},{b_path}"
        ])
    assert exc_info.value.code == 1
    assert (out / "ratio.svg").exists()


def test_cli_without_b(tmp_path):
    a_path = _write_json(tmp_path, "a.json", _measurements(10.0))
    out = tmp_path / "out"
    cliperfimages([
        "specperfimages", "--output-directory",
        str(out), "--format", "png", f"one={a_path}"
    ])
    files = sorted(
        re.sub(r"-[0-9a-f]{8}\.", ".", path.name) for path in out.iterdir())
    assert files == ["one-impl-a-work.png", "one-impl-b-work.png"]


def test_regroup(tmp_path):
    data = {
        "reports": [{
            "executable": "build/ts-performance.exe",
            "info": {},
            "test-suite": {
                "test-cases": [{
                    "runtime-measurements": [{
                        "name": f"PerfWork{size}",
                        "variant": "HotCache",
                        "samples": [size * 1e-6]
                    } for size in (1, 2)] + [{
                        "name": "Other",
                        "variant": "HotCache",
                        "samples": [1e-6]
                    }]
                }]
            }
        }]
    }
    path = _write_json(tmp_path, "a.json", data)
    run = parse_run(f"one={path}", r"Perf(?P<name>[A-Za-z]+)(?P<variant>\d+)")
    assert run.a == {
        ("Work/HotCache", "1"): [1e-6],
        ("Work/HotCache", "2"): [2e-6]
    }
    out = tmp_path / "out"
    cliperfimages([
        "specperfimages", "--output-directory",
        str(out), "--format", "png", "--regroup",
        r"Perf(?P<name>[A-Za-z]+)(?P<variant>\d+)", f"one={path},{path}"
    ])
    assert ["one", "Work/HotCache", "2"] in [
        row[:3]
        for row in _table_rows((out /
                                "comparison.md").read_text(encoding="utf-8"))
    ]


def test_cli_without_regression(tmp_path):
    a_path = _write_json(tmp_path, "a.json", _measurements(10.0))
    out = tmp_path / "out"
    cliperfimages([
        "specperfimages", "--output-directory",
        str(out), "--format", "png", "--fail-on-regression",
        f"one={a_path},{a_path}"
    ])
    assert (out / "comparison.md").exists()


def test_skip_empty_measurements(tmp_path):
    data = {
        "measurements": [{
            "name": "work",
            "variant": 1,
            "samples": []
        }, {
            "name": "work",
            "variant": 2,
            "samples": [1e-6]
        }]
    }
    assert load_samples(_write_json(tmp_path, "a.json", data)) == {
        ("work", "2"): [1e-6]
    }


def test_no_common_measurements(tmp_path):
    run = Run("one", {("a", "1"): [1.0]}, {("b", "1"): [1.0]}, None)
    assert not draw_ratios([run], "title", str(tmp_path / "ratio"), ["png"])
    assert not list(tmp_path.iterdir())


def test_cli_text_format(tmp_path):
    a_path = _write_json(tmp_path, "a.json", _measurements(10.0))
    out = tmp_path / "out"
    cliperfimages([
        "specperfimages", "--output-directory",
        str(out), "--format", "png", "--text-format", "rest",
        f"one={a_path},{a_path}"
    ])
    assert not (out / "comparison.md").exists()
    assert ".. table::" in (out / "comparison.rst").read_text(encoding="utf-8")


@pytest.mark.parametrize("a,a2,noise", [(0.0, 0.0, "0.0 %"),
                                        (10.0, 11.0, "10.0 %"),
                                        (0.0, 1.0, "inf %")])
def test_noise_in_comparison_table(a, a2, noise):
    content = CommonMarkContent(context="CC-BY-SA-4.0")
    comparison_table([
        Run("one", {("work", "1"): [a]}, {("work", "1"): [a]},
            {("work", "1"): [a2]})
    ], content)
    assert _table_rows(str(content))[2][6] == noise


def test_unique_boxplot_files(tmp_path):
    files = draw_boxplots(Run("a-b", {("c", "1"): [1.0]}, None, None),
                          str(tmp_path), ["png"])
    files.extend(
        draw_boxplots(Run("a", {("b-c", "1"): [1.0]}, None, None),
                      str(tmp_path), ["png"]))
    files.extend(
        draw_boxplots(Run("a", {("b/c", "1"): [1.0]}, None, None),
                      str(tmp_path), ["png"]))
    assert len(set(files)) == 3
    assert len(list(tmp_path.iterdir())) == 3


def test_duplicate_run_labels(tmp_path):
    a_path = _write_json(tmp_path, "a.json", _measurements(10.0))
    with pytest.raises(ValueError, match="duplicate run labels"):
        cliperfimages([
            "specperfimages", "--output-directory",
            str(tmp_path / "out"), f"one={a_path}", f"one={a_path}"
        ])


def test_ratio_image_with_different_variants(tmp_path):
    one = {("work", "HotCache"): [1.0], ("work", "Load/1"): [1.0]}
    two = {("work", "Load/1"): [1.0]}
    assert draw_ratios(
        [Run("one", one, one,
             None), Run("two", two, two, None)], "title",
        str(tmp_path / "ratio"), ["png"]) == [str(tmp_path / "ratio.png")]
    assert (tmp_path / "ratio.png").exists()


@pytest.mark.parametrize("variants", [("0", "1"), ("-1", "1")])
def test_ratio_image_with_non_positive_variants(tmp_path, variants):
    samples = {("work", variant): [1.0] for variant in variants}
    draw_ratios([Run("one", samples, samples, None)], "title",
                str(tmp_path / "ratio"), ["png"])
    assert (tmp_path / "ratio.png").exists()


def test_boxplots_of_a_alone_and_with_b(tmp_path):
    a = {("work", "1"): [1.0], ("work", "2"): [1.0]}
    b = {("work", "2"): [1.0]}
    files = draw_boxplots(Run("one", a, b, None), str(tmp_path), ["png"])
    files.extend(
        draw_boxplots(Run("two", a, None, None), str(tmp_path), ["png"]))
    assert len(files) == 2
    assert all(os.path.exists(path) for path in files)


def test_ratio_image_with_infinite_ratios(tmp_path):
    a = {("work", "1"): [0.0], ("work", "2"): [1.0]}
    b = {("work", "1"): [1.0], ("work", "2"): [1.0]}
    a2 = {("work", "1"): [1.0], ("work", "2"): [1.0]}
    assert draw_ratios([Run("one", a, b, a2)], "title",
                       str(tmp_path / "ratio"),
                       ["png"]) == [str(tmp_path / "ratio.png")]
    assert (tmp_path / "ratio.png").exists()


def test_boxplot_of_a_long_name(tmp_path):
    files = draw_boxplots(Run("one", {("x" * 300, "1"): [1.0]}, None, None),
                          str(tmp_path), ["png"])
    assert len(files) == 1
    assert os.path.exists(files[0])
    assert len(os.path.basename(files[0])) < 255


def test_reproducible_images(tmp_path):
    samples = {("work", "1"): [1.0], ("work", "2"): [2.0]}
    run = Run("one", samples, samples, None)
    contents = []
    for directory in ("first", "second"):
        (tmp_path / directory).mkdir()
        files = draw_ratios([run], "title",
                            str(tmp_path / directory / "ratio"),
                            ["png", "svg", "pdf"])
        contents.append([pathlib.Path(path).read_bytes() for path in files])
    assert len(contents[0]) == 3
    assert contents[0] == contents[1]
