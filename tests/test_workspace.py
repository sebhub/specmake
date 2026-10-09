# SPDX-License-Identifier: BSD-2-Clause
""" Tests for the workspace and buildspace. """

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

import logging
import os
import shutil
import pytest

from specware import run_command

import specmake
from specmake import (BuildItem, BuildspaceConfig, DirectoryState,
                      PackageComponent, WorkspaceConfig,
                      create_build_item_factory, create_workspace,
                      create_workspace_item_factory, export_to_buildspace)
from specmake.pkgworkspace import _WorkspaceItem


def _git_commit(directory, what):
    stdout = []
    status = run_command(["git", "rev-parse", what], directory, stdout)
    assert status == 0
    return stdout[0].strip()


def _create_workspace(tmp_dir, spec_dir):
    test_dir = os.path.dirname(__file__)
    if isinstance(spec_dir, str):
        spec_dir = [spec_dir]
    spec_dir.append("spec-pkg-wk/component")
    workspace_config = WorkspaceConfig(
        spec_directories=[os.path.join(test_dir, name) for name in spec_dir],
        workspace_directory=os.path.join(test_dir, "workspace"),
        cache_directory=os.path.join(tmp_dir, "cache-workspace"),
        factory=create_workspace_item_factory())
    workspace = create_workspace(workspace_config)
    workspace.director.package.item["deployment-directory"] = str(tmp_dir)
    return workspace


def _create_buildspace_from_workspace(tmp_dir, workspace, factory=None):
    buildspace_config = BuildspaceConfig(
        spec_directory=os.path.join(tmp_dir, "spec"),
        cache_directory=os.path.join(tmp_dir, "cache-buildspace"),
        verify_specification_format=True,
        factory=factory)
    return export_to_buildspace(workspace, buildspace_config)


def _create_buildspace(tmp_dir, spec_dir, factory=None):
    workspace = _create_workspace(tmp_dir, spec_dir)
    buildspace = _create_buildspace_from_workspace(tmp_dir, workspace, factory)
    return buildspace, workspace


def test_workspace_not_implemented():
    with pytest.raises(NotImplementedError):
        _WorkspaceItem.prepare_buildspace_data(0)


def test_workspace_archive_invalid_digest(tmpdir):
    with pytest.raises(IOError, match="actual archive file"):
        _create_buildspace(tmpdir, "spec-pkg-wk/archive/invalid-digest")


def test_workspace_archive_config_dir(tmpdir):
    buildspace, _ = _create_buildspace(tmpdir,
                                       "spec-pkg-wk/archive/config-dir")
    archive = buildspace.director["/archive"]
    with open(os.path.join(archive.directory, "README.md"), "r") as src:
        assert src.read() == "This is an archive.\nAdded by inline patch.\n"


def test_workspace_archive_download(tmpdir):
    buildspace, _ = _create_buildspace(tmpdir, "spec-pkg-wk/archive/download")
    archive = buildspace.director["/archive"]
    assert isinstance(archive, DirectoryState)
    assert archive["directory-state-type"] == "unpacked-archive"
    assert os.path.exists(archive.file)


def test_workspace_dir_attribute_actions(tmp_path):
    buildspace, _ = _create_buildspace(str(tmp_path),
                                       "spec-pkg-wk/dir/attribute-actions")
    assert buildspace.director["/dir"]["directory-state-type"] == "explicit"
    assert (tmp_path / "attribute-modified" / "t.txt").is_file()


def test_workspace_dir_patterns(tmp_path):
    buildspace, _ = _create_buildspace(str(tmp_path),
                                       "spec-pkg-wk/dir/patterns")
    assert buildspace.director["/dir"]["directory-state-type"] == "explicit"
    assert (tmp_path / "rc1" / "c1" / "c1").is_file()
    assert (tmp_path / "rcn" / "rcn" / "cn").is_file()
    assert (tmp_path / "c" / "a").is_file()
    assert (tmp_path / "rs" / "s").is_file()
    assert (tmp_path / "e" / "re").is_file()
    assert (tmp_path / "n").is_file()
    with open(tmp_path / "t.txt", "r", encoding="utf-8") as file:
        assert file.read() == f"{tmp_path}\n"


def test_workspace_dir_repository(tmp_path):
    buildspace, _ = _create_buildspace(str(tmp_path),
                                       "spec-pkg-wk/dir/repository")
    repo = buildspace.director["/dir"]
    assert repo["directory-state-type"] == "repository"
    dir_path = tmp_path / "dir"
    assert (dir_path / "rc1" / "c1" / "c1").is_file()
    assert (dir_path / "rcn" / "rcn" / "cn").is_file()
    assert (dir_path / "c" / "a").is_file()
    assert (dir_path / "rs" / "s").is_file()
    assert (dir_path / "e" / "re").is_file()
    assert (dir_path / "n").is_file()
    with open(dir_path / "t.txt", "r", encoding="utf-8") as file:
        assert file.read() == f"{tmp_path}\n"
    assert repo["commit"] == _git_commit(repo.directory, "main")
    assert repo.lazy_verify()


def test_workspace_file_single(tmpdir):
    buildspace, _ = _create_buildspace(tmpdir, "spec-pkg-wk/file/single")
    assert buildspace.director["/file"]["directory-state-type"] == "explicit"
    with open(os.path.join(tmpdir, "file", "c.txt"), "rb") as file:
        assert file.read() == b"b\n"


def test_workspace_file_list(tmpdir):
    buildspace, _ = _create_buildspace(tmpdir, "spec-pkg-wk/file/list")
    assert buildspace.director["/file"]["directory-state-type"] == "explicit"
    with open(os.path.join(tmpdir, "file", "c.txt"), "rb") as file:
        assert file.read() == b"b\n"


def test_workspace_file_no_file(tmpdir):
    with pytest.raises(ValueError, match="file: no source file available"):
        _create_buildspace(tmpdir, "spec-pkg-wk/file/no-file")


def test_workspace_redirect(tmpdir):
    buildspace, _ = _create_buildspace(tmpdir, "spec-pkg-wk/redirect")
    item = buildspace.director["/redirect"].item
    assert item.type == "requirement/non-functional/design"
    assert item["references"] == [
        {
            "identifier": "https://www.example.com/redirect-source-2",
            "type": "url",
        },
        {
            "identifier": "https://www.example.com/redirect-source",
            "type": "url",
        },
        {
            "identifier": "https://www.example.com/redirect",
            "type": "url",
        },
    ]


def test_workspace_repo_clone_workaround(tmpdir, monkeypatch):

    def _run_command(args, cwd=None, stdout=None, status=None):
        if "--revision" in args:
            return 1
        if "fetch" in args:
            return 1
        return run_command(args, cwd, stdout, status)

    monkeypatch.setattr(specmake.pkgworkspace, "run_command", _run_command)
    with pytest.raises(IOError, match="cannot clone"):
        _create_buildspace(
            tmpdir, ["spec-pkg-wk/repo/archive", "spec-pkg-wk/repo/default"])


def test_workspace_repo_default(tmpdir):
    buildspace, workspace = _create_buildspace(
        tmpdir, ["spec-pkg-wk/repo/archive", "spec-pkg-wk/repo/default"])
    wk_repo = workspace.director["/repo"]
    assert wk_repo.substitute(
        "${.:/git-commit}") == "40abab3c7aca7f38d06f339d784fa08178588f47"
    assert wk_repo.substitute(
        "${.:/git-commit:main}") == "40abab3c7aca7f38d06f339d784fa08178588f47"
    assert wk_repo.substitute(
        "${.:/git-commit-head}") == "40abab3c7aca7f38d06f339d784fa08178588f47"
    repo = buildspace.director["/repo"]
    assert repo["commit"] == "40abab3c7aca7f38d06f339d784fa08178588f47"
    assert repo.lazy_verify()


def test_workspace_repo_git_commit_ref(tmpdir):
    _, workspace = _create_buildspace(
        tmpdir, ["spec-pkg-wk/repo/archive", "spec-pkg-wk/repo/default"])
    workspace.director.package.item["refs"] = {"repo": "main"}
    wk_repo = workspace.director["/repo"]
    head = "40abab3c7aca7f38d06f339d784fa08178588f47"
    assert wk_repo.substitute(
        "${.:/git-commit:%(.:/component/refs/repo)}") == head
    assert wk_repo.substitute(
        "${.:/git-commit:%(.:/component/refs/repo),default=HEAD}") == head
    assert wk_repo.substitute(
        "${.:/git-commit:%(.:/component/refs/other),default=HEAD}") == head
    with pytest.raises(ValueError):
        wk_repo.substitute("${.:/git-commit:%(.:/component/refs/other)}")
    with pytest.raises(ValueError):
        wk_repo.substitute(
            "${.:/git-commit:%(no-such-item:/refs/repo),default=HEAD}")


def test_workspace_repo_git_commit_match_head(tmpdir):
    _, workspace = _create_buildspace(
        tmpdir, ["spec-pkg-wk/repo/archive", "spec-pkg-wk/repo/default"])
    wk_repo = workspace.director["/repo"]
    source = os.path.join(tmpdir, "source", "repo")
    status = run_command(["git", "branch", "side"], source)
    assert status == 0
    status = run_command([
        "git", "-c", "user.name=A", "-c", "user.email=a@b", "commit",
        "--allow-empty", "--no-verify", "-m", "x"
    ], source)
    assert status == 0
    head = _git_commit(source, "HEAD")
    assert wk_repo.substitute("${.:/git-commit:main,match-head=1}") == head
    with pytest.raises(ValueError, match="side.*does not match HEAD"):
        wk_repo.substitute("${.:/git-commit:side,match-head=1}")
    assert wk_repo.substitute("${.:/git-commit:side,match-head=0}") != head
    assert wk_repo.substitute("${.:/git-commit:side}") != head
    with pytest.raises(ValueError,
                       match="argument 'match-head' has the value 'yes'"):
        wk_repo.substitute("${.:/git-commit:main,match-head=yes}")


def test_workspace_repo_git_commit_escaped_ref(tmpdir):
    _, workspace = _create_buildspace(
        tmpdir, ["spec-pkg-wk/repo/archive", "spec-pkg-wk/repo/default"])
    wk_repo = workspace.director["/repo"]
    source = os.path.join(tmpdir, "source", "repo")
    for ref in ("a,b", "a=b"):
        status = run_command(["git", "branch", ref], source)
        assert status == 0
    status = run_command([
        "git", "-c", "user.name=A", "-c", "user.email=a@b", "commit",
        "--allow-empty", "--no-verify", "-m", "x"
    ], source)
    assert status == 0
    status = run_command(["git", "branch", "-f", "a,b"], source)
    assert status == 0
    head = _git_commit(source, "HEAD")
    base = _git_commit(source, "HEAD~1")
    assert wk_repo.substitute("${.:/git-commit:a\\cb}") == head
    assert wk_repo.substitute("${.:/git-commit:a\\eb}") == base
    assert wk_repo.substitute("${.:/git-commit:a\\cb,match-head=1}") == head


def test_workspace_repo_clone_depth(tmpdir):
    buildspace, _ = _create_buildspace(
        tmpdir, ["spec-pkg-wk/repo/archive", "spec-pkg-wk/repo/clone-depth"])
    repo = buildspace.director["/repo"]
    assert repo["commit"] == "40abab3c7aca7f38d06f339d784fa08178588f47"
    assert repo.lazy_verify()


def test_workspace_repo_discard(tmpdir):
    deployment_directory = str(tmpdir)
    status = run_command(["git", "init"], deployment_directory)
    assert status == 0
    workspace = _create_workspace(
        tmpdir, ["spec-pkg-wk/repo/archive", "spec-pkg-wk/repo/default"])
    buildspace_config = BuildspaceConfig(
        spec_directory=os.path.join(tmpdir, "build", "spec"),
        cache_directory=os.path.join(tmpdir, "build", "cache"),
        git_directory=deployment_directory)
    export_to_buildspace(workspace, buildspace_config)
    stdout = []
    status = run_command(["git", "ls-files", "--stage", "repo"],
                         deployment_directory, stdout)
    assert status == 0
    assert stdout[0].startswith("160000 ")
    workspace.director.remove("/repo")
    export_to_buildspace(workspace, buildspace_config)
    stdout = []
    status = run_command(["git", "ls-files", "--stage", "repo"],
                         deployment_directory, stdout)
    assert status == 0
    assert not stdout
    status = run_command(["git", "status", "--short"], deployment_directory)
    assert status == 0
    workspace = _create_workspace(
        tmpdir, ["spec-pkg-wk/repo/archive", "spec-pkg-wk/repo/default"])
    export_to_buildspace(workspace, buildspace_config)
    stdout = []
    status = run_command(["git", "ls-files", "--stage", "repo"],
                         deployment_directory, stdout)
    assert status == 0
    assert stdout[0].startswith("160000 ")


def test_workspace_repo_origin_url(tmpdir):
    buildspace, _ = _create_buildspace(
        tmpdir, ["spec-pkg-wk/repo/archive", "spec-pkg-wk/repo/origin-url"])
    repo = buildspace.director["/repo"]
    assert repo["commit"] == "40abab3c7aca7f38d06f339d784fa08178588f47"
    assert repo.lazy_verify()
    stdout: list[str] = []
    status = run_command(["git", "remote", "-v"], repo.directory, stdout)
    assert status == 0
    assert "https://foobar.org" in "".join(stdout)


def test_workspace_repo_fetch(tmpdir):
    buildspace, workspace = _create_buildspace(tmpdir, [
        "spec-pkg-wk/repo/archive", "spec-pkg-wk/repo/default",
        "spec-pkg-wk/repo/fetch"
    ])
    archive = buildspace.director["/archive"]
    repo = buildspace.director["/repo"]
    assert repo["commit"] == "40abab3c7aca7f38d06f339d784fa08178588f47"
    assert repo.lazy_verify()
    status = run_command(["git", "commit", "--amend", "-m", "message"],
                         archive.directory)
    assert status == 0
    wk_repo_2 = workspace.director["/repo-2"]
    commit = _git_commit(archive.directory, "HEAD")
    wk_repo_2.item["commit"] = commit
    buildspace_2 = _create_buildspace_from_workspace(tmpdir, workspace)
    repo_2 = buildspace_2.director["/repo-2"]
    assert _git_commit(repo_2.directory, "other") == commit
    assert _git_commit(repo_2.directory, "post-clone") == commit


def test_workspace_test_log(tmpdir):
    buildspace, _ = _create_buildspace(tmpdir, "spec-pkg-wk/test-log")
    assert buildspace.director["/file"]["directory-state-type"] == "test-log"
    with open(os.path.join(tmpdir, "file", "c.txt"), "rb") as file:
        assert file.read() == b"b\n"


def test_workspace_discard_and_delete_error(tmpdir):
    create_error = False

    class _Item(BuildItem):

        def __init__(self, director, item, mapper=None) -> None:
            super().__init__(director, item, mapper)
            if create_error:
                raise IOError("create error")

    factory = create_build_item_factory()
    factory.add_constructor("pkg/directory-state/explicit", _Item)
    buildspace, workspace = _create_buildspace(
        tmpdir, "spec-pkg-wk/discard-and-delete-error", factory)
    assert "/a" in buildspace.cache
    assert "/b" in buildspace.cache
    assert "/c" in buildspace.cache
    assert buildspace.director["/c"]["directory"] != "foobar"
    workspace.director.remove("/a")
    workspace.director["/c"]["directory"] = "foobar"
    create_error = True
    buildspace.director.clear()
    with pytest.raises(IOError, match="create error"):
        buildspace.director.create_with_dependencies("/a")
    buildspace_2 = _create_buildspace_from_workspace(tmpdir, workspace,
                                                     factory)
    assert "/a" not in buildspace_2.cache
    assert "/b" in buildspace_2.cache
    assert "/c" in buildspace_2.cache
    create_error = False
    assert buildspace_2.director["/c"]["directory"] == "foobar"


def test_workspace_moved_deployment_directory(tmpdir):
    old_directory = os.path.join(tmpdir, "old")
    new_directory = os.path.join(tmpdir, "new")
    workspace = _create_workspace(tmpdir, "spec-pkg-wk/file/single")
    package = workspace.director.package
    package.item["deployment-directory"] = old_directory
    os.makedirs(old_directory)
    status = run_command(["git", "init"], old_directory)
    assert status == 0
    export_to_buildspace(
        workspace,
        BuildspaceConfig(spec_directory=os.path.join(old_directory, "build",
                                                     "spec"),
                         cache_directory=os.path.join(old_directory, "build",
                                                      "cache"),
                         git_directory=old_directory))
    commit = _git_commit(old_directory, "HEAD")

    # The buildspace stores the deployment directory of the first export.  It
    # is stale once the deployment directory moves.
    shutil.move(old_directory, new_directory)
    package.item["deployment-directory"] = new_directory
    buildspace = export_to_buildspace(
        workspace,
        BuildspaceConfig(spec_directory=os.path.join(new_directory, "build",
                                                     "spec"),
                         cache_directory=os.path.join(new_directory, "build",
                                                      "cache"),
                         git_directory=new_directory))

    assert not os.path.exists(old_directory)
    assert _git_commit(new_directory, "HEAD") != commit
    assert os.path.exists(os.path.join(new_directory, "file", "c.txt"))
    assert buildspace.director["/file"].directory == os.path.join(
        new_directory, "file")


def test_workspace_component(tmpdir):
    test_dir = os.path.dirname(__file__)
    workspace_config = WorkspaceConfig(
        spec_directories=[
            os.path.join(test_dir, name)
            for name in ("spec-pkg", "spec-pkg-component")
        ],
        workspace_directory=os.path.join(test_dir, "workspace"),
        cache_directory=os.path.join(tmpdir, "cache"))
    workspace = create_workspace(workspace_config)

    package = workspace.director.package
    assert isinstance(package, PackageComponent)
    assert package.item["a"] == "a"
    assert package.item["b"] == "tb"
    assert package.item["c"] == "a/${.:/b}"
    assert package["c"] == "a/tb"
    assert package.item["d"] == ["d", "td"]
    assert package.item["e"] == {"e0": 0, "e1": 1}
    assert package.item["list"] == [{
        "k": 6
    }, {
        "k": 1
    }, {
        "k": 5
    }, 2, [{
        "k": 8
    }, {
        "k": 3
    }, {
        "k": 4
    }, {
        "k": 7
    }]]
    assert package.item["list-2"] == [{"b": 2}]
    assert package.item["list-3"] == ["y"]
    assert package.item["list-4"] == [["Y"]]
    assert package.item["list-5"] == ["a"]
    assert sorted(package.selection.enabled_set) == [
        "pkg.arch.furch", "pkg.bsp-family.furch.lurch",
        "pkg.bsp-family.furch.lurch-2", "pkg.bsp.furch.blur",
        "pkg.bsp.furch.blur-2", "pkg.feature.blue", "pkg.feature.green",
        "pkg.feature.red", "pkg.test.config.bar_baz", "pkg.test.config.foo",
        "pkg.test.second.oo"
    ]

    work_bsp = workspace.director["/pkg/arch/bsp/cfg/component"]
    assert work_bsp.item["has-sibling-0"] == "has-sibling-0"
    assert work_bsp.item["has-sibling-1"] == "has-sibling-1"
    assert work_bsp.item["has-sibling-2"] == "has-sibling-2"
    assert work_bsp.item["has-sibling-3"] == "has-sibling-3"
    assert work_bsp.item["has-sibling-4"] == "has-sibling-4"

    work_item_a = workspace.director["/pkg/template-item-a"]
    assert isinstance(work_item_a, BuildItem)

    work_item_b = workspace.director["/pkg/template-item-b"]
    assert isinstance(work_item_b, BuildItem)

    deployment_directory = str(tmpdir)
    buildspace_config = BuildspaceConfig(
        spec_directory=os.path.join(tmpdir, "build", "spec"),
        cache_directory=os.path.join(tmpdir, "build", "cache"),
        git_directory=deployment_directory,
        verify_specification_format=True)

    assert not os.path.exists(
        os.path.join(buildspace_config.spec_directory,
                     "pkg/template-item-a.json"))

    status = run_command(["git", "init"], deployment_directory)
    assert status == 0
    package.item["deployment-directory"] = deployment_directory

    buildspace = export_to_buildspace(workspace, buildspace_config)

    build_item_a = buildspace.director["/pkg/template-item-a"]
    assert isinstance(build_item_a, DirectoryState)
    assert build_item_a.directory == "."
    assert os.path.exists(
        os.path.join(buildspace_config.spec_directory,
                     "pkg/template-item-a.json"))

    assert work_item_a["directory"] == "."
    work_item_a["directory"] = "foobar"

    build_redirect_a = buildspace.director["/pkg/template-redirect-a"]
    assert isinstance(build_redirect_a, DirectoryState)
    assert build_redirect_a["params"]["list"] == [
        "item-b",
        "template-redirect-b",
        "template-redirect-a",
    ]

    buildspace_2 = export_to_buildspace(workspace, buildspace_config)

    build_item_a_2 = buildspace_2.director["/pkg/template-item-a"]
    assert isinstance(build_item_a_2, DirectoryState)
    assert build_item_a_2.directory == "foobar"

    assert build_item_a.directory == "."
    build_item_a.item.load()
    assert build_item_a.directory == "foobar"

    assert "/pkg/source/delete-me" in buildspace_2.cache
    workspace.director.remove("/pkg/source/delete-me")
    buildspace_3 = export_to_buildspace(workspace, buildspace_config)
    assert "/pkg/source/delete-me" not in buildspace_3.cache


def _create_component_workspace(tmpdir, mapping: str):
    test_dir = os.path.dirname(__file__)
    spec_dirs = []
    for name in ("spec-pkg", "spec-pkg-component"):
        spec_dir = os.path.join(tmpdir, name)
        shutil.copytree(os.path.join(test_dir, name), spec_dir)
        spec_dirs.append(spec_dir)
    template = os.path.join(tmpdir, "spec-pkg", "pkg", "template", "bsp",
                            "component.yml")
    with open(template, "r", encoding="utf-8") as src:
        text = src.read()
    text = text.replace("  bsp-feature: pkg.feature.red\n",
                        f"  bsp-feature: pkg.feature.red\n{mapping}\n")
    with open(template, "w", encoding="utf-8") as dst:
        dst.write(text)
    return create_workspace(
        WorkspaceConfig(spec_directories=spec_dirs,
                        workspace_directory=os.path.join(
                            test_dir, "workspace"),
                        cache_directory=os.path.join(tmpdir, "cache")))


def test_workspace_component_invalid_feedback_mapping(tmpdir):
    with pytest.raises(ValueError) as err:
        _create_component_workspace(os.path.join(tmpdir, "a"),
                                    "  TEST_CONFIG_(.*: pkg")
    assert ("the enabled set feedback mapping of /pkg/template/bsp/component "
            "states the invalid pattern 'TEST_CONFIG_(.*': missing ), "
            "unterminated subpattern") in str(err.value)
    with pytest.raises(ValueError) as err:
        _create_component_workspace(os.path.join(tmpdir, "b"),
                                    "  TEST_CONFIG_(F)(.*): pkg.\\3")
    assert ("states the invalid replacement 'pkg.\\3' of the pattern "
            "'TEST_CONFIG_(F)(.*)' for the enabled set key 'TEST_CONFIG_FOO': "
            "invalid group reference 3") in str(err.value)
