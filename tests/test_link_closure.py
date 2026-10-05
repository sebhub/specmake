# SPDX-License-Identifier: BSD-2-Clause
""" Tests for the speclinkclosure command line interface. """

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

import os

import pytest

from specmake.clilinkclosure import clilinkclosure

_CLOSURE_A = [
    "spec/build/opt.yml",
    "spec/build/top.yml",
    "spec/req/group.yml",
    "spec/req/perf.yml",
    "spec/req/root.yml",
    "spec/val/perf.yml",
    "tests/tc-perf.c",
]


def _argv(tmpdir, *more):
    base = os.path.join(os.path.dirname(__file__), "link-closure")
    repo_a = os.path.join(base, "repo-a")
    repo_b = os.path.join(base, "repo-b")
    return [
        "--log-level=WARNING", "--cache-directory",
        os.path.join(tmpdir, "cache"), "--spec-directory",
        os.path.join(repo_a, "spec"), "--spec-directory",
        os.path.join(repo_b, "spec"), "--root", repo_a, "--seed",
        os.path.join(repo_a, "spec", "build", "*"), "--seed",
        os.path.join(repo_a, "spec", "req", "perf.yml"), "--seed",
        os.path.join(repo_b, "spec", "*"), "--exclude-uid", "/val/grp"
    ] + list(more)


def test_link_closure_output(tmpdir):
    output = os.path.join(tmpdir, "closure.txt")
    clilinkclosure(_argv(tmpdir, "--output", output))
    with open(output, "r", encoding="utf-8") as src:
        assert src.read().splitlines() == _CLOSURE_A


def test_link_closure_stdout(tmpdir, capsys):
    clilinkclosure(_argv(tmpdir))
    assert capsys.readouterr().out.splitlines() == _CLOSURE_A


def test_link_closure_why(tmpdir, capsys):
    clilinkclosure(_argv(tmpdir, "--why"))
    lines = capsys.readouterr().out.splitlines()
    assert "spec/build/top.yml" in lines
    assert "spec/req/group.yml\t<- /b (refinement)" in lines or (
        "spec/req/group.yml\t<- /req/perf (refinement)" in lines)
    assert "spec/val/perf.yml\t<- /req/perf (measurement)" in lines


def test_link_closure_without_exclude(tmpdir, capsys):
    argv = _argv(tmpdir)
    argv = argv[:-2]
    clilinkclosure(argv)
    lines = capsys.readouterr().out.splitlines()
    assert "spec/val/grp.yml" in lines
    assert "spec/req/other.yml" in lines


def test_link_closure_check(tmpdir):
    expected = os.path.join(tmpdir, "expected.txt")
    with open(expected, "w", encoding="utf-8") as dst:
        dst.write("\n".join(_CLOSURE_A) + "\n")
    clilinkclosure(_argv(tmpdir, "--check", expected))
    with open(expected, "w", encoding="utf-8") as dst:
        dst.write("\n".join(_CLOSURE_A[1:]) + "\n")
    with pytest.raises(SystemExit) as exc:
        clilinkclosure(_argv(tmpdir, "--check", expected))
    assert exc.value.code == 1
    with open(expected, "w", encoding="utf-8") as dst:
        dst.write("\n".join(_CLOSURE_A + ["spec/req/other.yml"]) + "\n")
    with pytest.raises(SystemExit) as exc:
        clilinkclosure(_argv(tmpdir, "--check", expected))
    assert exc.value.code == 1


def _write_item(path, test_target):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as dst:
        dst.write("SPDX-License-Identifier: CC-BY-SA-4.0 OR BSD-2-Clause\n"
                  "copyrights:\n"
                  "- Copyright (C) 2026 embedded brains GmbH & Co. KG\n"
                  "enabled-by: true\n"
                  "links: []\n"
                  f"test-target: {test_target}\n"
                  "type: thing\n")


@pytest.mark.parametrize("test_target", ["../outside.c", "/outside.c"])
def test_link_closure_test_target_outside_root(tmpdir, test_target):
    root = os.path.join(tmpdir, "repo")
    _write_item(os.path.join(root, "spec", "val", "t.yml"), test_target)
    with pytest.raises(ValueError,
                       match=r"/val/t: test-target .* is not below the root"):
        clilinkclosure([
            "--log-level=WARNING", "--cache-directory",
            os.path.join(tmpdir, "cache"), "--spec-directory",
            os.path.join(root, "spec"), "--root", root, "--seed",
            os.path.join(root, "spec", "*")
        ])


def test_link_closure_test_target_normalized(tmpdir, capsys):
    root = os.path.join(tmpdir, "repo")
    _write_item(os.path.join(root, "spec", "val", "t.yml"), "a/../b/t.c")
    clilinkclosure([
        "--log-level=WARNING", "--cache-directory",
        os.path.join(tmpdir, "cache"), "--spec-directory",
        os.path.join(root, "spec"), "--root", root, "--seed",
        os.path.join(root, "spec", "*")
    ])
    assert capsys.readouterr().out.splitlines() == ["b/t.c", "spec/val/t.yml"]


def test_link_closure_check_order(tmpdir, capsys):
    expected = os.path.join(tmpdir, "expected.txt")
    with open(expected, "w", encoding="utf-8") as dst:
        dst.write("\n".join(reversed(_CLOSURE_A)) + "\n")
    with pytest.raises(SystemExit) as exc:
        clilinkclosure(_argv(tmpdir, "--check", expected))
    assert exc.value.code == 1
    assert "differs in the order or in duplicate lines" in capsys.readouterr(
    ).err
    with open(expected, "w", encoding="utf-8") as dst:
        dst.write("\n".join(_CLOSURE_A + _CLOSURE_A[:1]) + "\n")
    with pytest.raises(SystemExit) as exc:
        clilinkclosure(_argv(tmpdir, "--check", expected))
    assert exc.value.code == 1
    assert "differs in the order or in duplicate lines" in capsys.readouterr(
    ).err
