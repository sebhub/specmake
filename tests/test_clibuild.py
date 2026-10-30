# SPDX-License-Identifier: BSD-2-Clause
""" Tests the command to create a package workspace. """

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

from pathlib import Path
import shutil

import pytest

import specmake.clibuild
from specmake.clibuild import clibuild


class _Stop(Exception):
    pass


@pytest.mark.parametrize("names,enabled_set", [("", []), ("a", ["a"]),
                                               ("a,b", ["a", "b"]),
                                               (" a , b ,, ", ["a", "b"])])
def test_enabled_set(tmp_path, monkeypatch, names, enabled_set):
    configs = []

    def _create_workspace(config):
        configs.append(config)
        raise _Stop

    monkeypatch.setattr(specmake.clibuild, "create_workspace",
                        _create_workspace)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(_Stop):
        clibuild([
            "specbuild", "--config-directory",
            str(tmp_path), "--enabled-set", names, "config.yml"
        ])
    assert configs[0].enabled_set == enabled_set


class _Package(dict):

    def __init__(self, deployment_directory):
        super().__init__({"deployment-directory": deployment_directory})


class _Director:

    def __init__(self, deployment_directory):
        self.package = _Package(deployment_directory)
        self.builds = []

    def build_package(self, only, force, skip):
        self.builds.append((only, force, skip))


class _Context:

    def __init__(self, deployment_directory):
        self.director = _Director(deployment_directory)


@pytest.mark.parametrize("export_only", [False, True])
def test_export_only(tmp_path, monkeypatch, export_only):
    deployment = tmp_path / "deployment"
    (deployment / ".git").mkdir(parents=True)
    workspace = _Context(str(deployment))
    buildspace = _Context(str(deployment))
    monkeypatch.setattr(specmake.clibuild, "create_workspace",
                        lambda config: workspace)
    monkeypatch.setattr(specmake.clibuild, "export_to_buildspace",
                        lambda workspace, config: buildspace)
    monkeypatch.chdir(tmp_path)
    file = tmp_path / "deployment-directory.txt"
    argv = [
        "specbuild", "--config-directory",
        str(tmp_path), "--deployment-directory-file",
        str(file), "--force", "f", "config.yml"
    ]
    if export_only:
        argv.insert(1, "--export-only")
    clibuild(argv)
    assert file.read_text(encoding="utf-8") == f"{deployment}\n"
    if export_only:
        assert not buildspace.director.builds
    else:
        assert buildspace.director.builds == [(None, ["f"], None)]


def test_create_the_deployment_directory(tmp_path, monkeypatch):
    tests = Path(__file__).parent
    spec = tmp_path / "config"
    shutil.copytree(tests / "spec-archiver", spec)
    with open(spec / "pkg" / "component.yml", "a", encoding="utf-8") as dst:
        dst.write(f"tmpdir: {tmp_path}\n")
    monkeypatch.chdir(tmp_path)

    clibuild([
        "specbuild", "--config-directory",
        str(tests / "test-files"), "--cache-directory",
        str(tmp_path / "cache"), "--export-only", "--do-not-use-git",
        str(spec),
        str(tests / "spec-license")
    ])

    # The command initializes a Git repository in a new deployment directory
    deployment = tmp_path / "pkg"
    assert (deployment / ".git").is_dir()
    assert (deployment / "build" / "spec" / "pkg" / "component.json").is_file()
    assert not (deployment / "build" / "archive-0.tar.xz").exists()
