# SPDX-License-Identifier: BSD-2-Clause
""" Tests the command to delete files of a deployment directory. """

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
from pathlib import Path

from specmake.clidecimate import clidecimate

from .util import create_package


def _files(path: Path) -> list[str]:
    return sorted(
        str(Path(root, name).relative_to(path))
        for root, _, names in os.walk(path) for name in names)


def test_decimate_keeps_the_files_of_the_directory_states(caplog, tmp_path):
    package = create_package(caplog, tmp_path, Path("spec-archiver"), [])
    subdir = tmp_path / "dir" / "subdir"
    subdir.mkdir(parents=True, exist_ok=True)
    (subdir / "d.txt").write_text("d", encoding="utf-8")
    package.director.build_package()
    deployment = tmp_path / "pkg"
    assert "build/archive-1.tar.xz" in _files(deployment)
    assert "spec/pkg/a.yml" in _files(deployment)

    clidecimate([
        "specmakedecimate", "--spec-directory",
        str(tmp_path / "spec"), "--cache-directory",
        str(tmp_path / "cache-decimate"), "/pkg/archive-0"
    ])

    # The command removes the directories which become empty
    assert _files(deployment) == ["build/archive-0.tar.xz"]
    assert os.listdir(deployment) == ["build"]
