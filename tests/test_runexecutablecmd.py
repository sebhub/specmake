# SPDX-License-Identifier: BSD-2-Clause
""" Tests for the perfimages module. """

# Copyright (C) 2025, 2026 embedded brains GmbH & Co. KG
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
from pathlib import Path
import subprocess
import sys

from specitems import Item, hash_file

from specmake import PackageBuildDirector, TestRunner, elf_loadable_sha512

from .elfutil import Segment, build_elf

from .util import create_package

TestRunner.__test__ = False


class _TestRunner(TestRunner):

    def __init__(self, director: PackageBuildDirector, item: Item):
        super().__init__(director, item)
        self._toggle = True

    def get_run_command(self, executable: str) -> None | list[str]:
        toggle = self._toggle
        self._toggle = not toggle
        if toggle:
            return None
        return [executable]


def test_runexecutablecmd(caplog, tmpdir):
    tmp_dir = Path(tmpdir)
    package = create_package(
        caplog, tmp_dir, Path("spec-packagebuild"),
        ["aggregate-test-results", "run-executable-command"])
    director = package.director
    director.factory.add_constructor("pkg/test-runner/test", _TestRunner)
    build_item = director["/pkg/deployment/run"]
    director.build_package(only=[build_item.uid])
    with open(build_item.file, "r", encoding="utf-8") as src:
        script = src.read()
    assert script.startswith("#!/usr/bin/env python3\n")
    assert """_TARGETS_BY_BSP: dict[str, str] = {
    'sparc-gr712rc-smp-extra': 'sparc/gr712rc/smp',
    'sparc-gr712rc-smp-qual-only': 'sparc/gr712rc/smp'
}

_TEST_LOGS_BY_TARGET: dict[str, str] = {
    'sparc/gr712rc/smp': ['${package-directory}/test-log-bsp.json']
}

_COMMANDS: dict[str, list[str]] = {'sparc/gr712rc/smp/one': ['$${executable}']}
""" in script
    _check_script(Path(build_item.file))


def _run(script: Path, executable: Path) -> subprocess.CompletedProcess:
    return subprocess.run([
        sys.executable, "-I",
        str(script), "sparc-gr712rc-smp-extra",
        str(executable)
    ],
                          capture_output=True,
                          text=True,
                          check=False)


def _check_script(script: Path) -> None:
    package_directory = script.parent.parent
    segments = [Segment(0x1000, 0x1000, b"text")]
    by_file = package_directory / "by-file.exe"
    by_file.write_text("#!/bin/sh\n", encoding="utf-8")
    run_elf = build_elf(1, ">", segments, debug=b"run")
    rebuilt = package_directory / "rebuilt.exe"
    rebuilt.write_bytes(build_elf(1, ">", segments, debug=b"rebuilt"))
    other = package_directory / "other.exe"
    other.write_bytes(build_elf(1, ">", [Segment(0x1000, 0x1000, b"else")]))
    reports = [{
        "executable-sha512": hash_file(str(by_file)),
        "output": ["file", "digest"]
    }, {
        "executable-sha512": "run",
        "loadable-sha512": elf_loadable_sha512(run_elf),
        "output": ["loadable", "digest"]
    }]
    with open(package_directory / "test-log-bsp.json", "w",
              encoding="utf-8") as dst:
        json.dump({"reports": reports}, dst)
    result = _run(script, by_file)
    assert result.returncode == 0
    assert result.stdout == "file\ndigest\n"
    result = _run(script, rebuilt)
    assert result.returncode == 0
    assert result.stdout == "loadable\ndigest\n"
    result = _run(script, other)
    assert result.returncode == 1
    assert "there is no service available" in result.stderr
    broken = package_directory / "broken.exe"
    broken.write_bytes(build_elf(1, ">", segments)[:40])
    result = _run(script, broken)
    assert result.returncode == 1
    assert result.stderr == (f"{script}: {broken}: the ELF file is truncated "
                             "in the ELF header\n")
