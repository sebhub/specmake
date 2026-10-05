# SPDX-License-Identifier: BSD-2-Clause
""" Provides support to populate a workspace. """

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

# pylint: disable=too-many-lines

import contextlib
import copy
import dataclasses
import itertools
import graphlib
import logging
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from typing import Optional
import urllib.request

from specitems import (EnabledSet, Item, ItemCache, ItemCacheConfig,
                       ItemDataByUID, ItemGetValueContext, ItemSelection,
                       JSONItemCache, data_digest, hash_file, is_enabled,
                       link_is_enabled, load_data, to_iterable,
                       verify_specification_format)
from specware import run_command

from .directorystate import DirectoryState, RepositoryState
from .pkgfactory import create_build_item_factory
from .pkgitems import (BuildItem, BuildItemFactory, BuildItemMapper,
                       BuildItemTypeProvider, PackageBuildDirector,
                       PackageComponent)
from .pkgtemplate import BuildItemTemplate, run_attribute_actions


def _git_commit(repository: str, commit: Optional[str] = None) -> str:
    if commit is None:
        commit = "HEAD"
    stdout: list[str] = []
    status = run_command(["git", "rev-parse", commit],
                         repository.removeprefix("file://"), stdout)
    assert status == 0
    return stdout[0].strip()


def _is_missing_attribute(err: BaseException | None) -> bool:
    while err is not None:
        if isinstance(err, ValueError) and str(
                err).startswith("cannot get value for") and isinstance(
                    err.__cause__, KeyError):
            return True
        err = err.__cause__
    return False


def _verify_specification_format(item_cache: ItemCache, verify: bool):
    if verify:
        logger = logging.getLogger()
        level = logger.getEffectiveLevel()
        logger.setLevel(logging.ERROR)
        status = verify_specification_format(item_cache)
        assert status.critical == 0
        assert status.error == 0
        logger.setLevel(level)


def _workspace_hash(data: dict) -> str:
    # Filter out link hashes and the workspace hash
    links = []
    for link in data["links"]:
        if "hash" in link:
            link_2 = link.copy()
            link_2["hash"] = None
            links.append(link_2)
        else:
            links.append(link)
    data_2 = data.copy()
    data_2["links"] = links
    data_2["workspace-hash"] = None
    return data_digest(data_2)


_DUMMY_DATA = {
    "SPDX-License-Identifier": "CC-BY-SA-4.0 OR BSD-2-Clause",
    "copyrights": ["Copyright (C) 2025 embedded brains GmbH & Co. KG"],
    "enabled-by": False,
    "links": [],
    "pkg-type": "dummy",
    "type": "pkg",
    "workspace-hash": None
}

_DUMMY_DATA["workspace-hash"] = _workspace_hash(_DUMMY_DATA)

_DEFAULT_ATTRIBUTES = ("SPDX-License-Identifier", "copyrights", "enabled-by",
                       "links", "type")


def _make_directory_state_data(item: Item, directory_state_type: str) -> dict:
    return {
        "directory":
        item["destination-directory"],
        "directory-state-type":
        item.get("directory-state-type", directory_state_type),
        "files": [],
        "hash":
        None,
        "pkg-type":
        "directory-state"
    }


class _WorkspaceItem(BuildItem):

    def __init__(self,
                 director: PackageBuildDirector,
                 item: Item,
                 mapper: None | BuildItemMapper = None) -> None:
        super().__init__(director, item, mapper)
        self.attribute_actions: list[dict] | None = self.item.get(
            "attribute-actions")

    def load_workspace_state(self) -> str:
        """
        Load the workspace state of the item.  Returns the hash of the state.
        """
        return _workspace_hash(self.item.data)

    def copy_attributes(self, data: dict, attributes: tuple[str, ...]) -> None:
        """
        Assign a deep copy of default attributes and the specified attributes
        of the item to the associated data elements.
        """
        for key in itertools.chain(_DEFAULT_ATTRIBUTES, attributes):
            try:
                value = copy.deepcopy(self.item[key])
            except KeyError:
                pass
            else:
                data[key] = value

    def prepare_buildspace_data(self) -> dict:
        """
        Prepare the workspace item state for export from the workspace to the
        buildspace.  Return the buildspace item data.
        """
        raise NotImplementedError

    def get_buildspace_data(self) -> dict:
        """
        Export the workspace item state from the workspace to the buildspace.
        Return the buildspace item data.
        """
        data = self.prepare_buildspace_data()
        run_attribute_actions(self.attribute_actions, self.component, data)
        return data

    def copy_to_buildspace(self, buildspace_item: BuildItem) -> None:
        """ Copies the associated workspace state to the buildspace. """


def _apply_patch_file(workspace_directory: str,
                      unpacked_archive: DirectoryState, patch_file: str,
                      git_directory: str) -> None:
    command = [
        "git", f"--git-dir={git_directory}", "apply", "-v", "-p", "1",
        os.path.join(workspace_directory, patch_file)
    ]
    env = copy.deepcopy(os.environ.copy())
    env["LANG"] = "en_US.UTF-8"
    logging.info("%s: apply patch in '%s': %s", unpacked_archive.uid,
                 unpacked_archive.directory, " ".join(command))
    output = subprocess.check_output(command,
                                     cwd=unpacked_archive.directory,
                                     env=env,
                                     stderr=subprocess.STDOUT)
    patched_files = [
        line[14:].removesuffix(" cleanly.")
        for line in output.decode("utf-8").splitlines()
        if line.startswith("Applied patch ")
    ]
    logging.info("%s: patched files: %s", unpacked_archive.uid, patched_files)
    unpacked_archive.add_files(patched_files)


def _apply_patches(workspace_directory: str,
                   unpacked_archive: DirectoryState) -> None:
    # An empty git directory of its own keeps git out of a repository which
    # contains the archive.  Git reads its configuration from that directory,
    # so no file and no directory of the archive root reaches it.
    with tempfile.TemporaryDirectory() as git_directory:
        # Do not substitute patches
        for patch in unpacked_archive.item["archive-patches"]:
            if not is_enabled(unpacked_archive.enabled_set,
                              patch["enabled-by"]):
                continue
            if patch["type"] == "inline":
                with tempfile.TemporaryDirectory() as name:
                    patch_file = Path(name) / "patch"
                    patch_file.write_bytes(patch["patch"].encode("utf-8"))
                    _apply_patch_file(workspace_directory, unpacked_archive,
                                      str(patch_file), git_directory)
            else:
                _apply_patch_file(workspace_directory, unpacked_archive,
                                  patch["file"], git_directory)


class WorkspaceArchive(_WorkspaceItem):
    """ Represents a workspace archive. """

    def prepare_buildspace_data(self) -> dict:
        data = _make_directory_state_data(self.item, "unpacked-archive")
        data["archive-file"] = os.path.basename(self["archive-file"])
        self.copy_attributes(
            data,
            ("archive-hash", "archive-patches", "archive-url", "license-files",
             "license-info", "description", "symbolic-links"))
        return data

    def _download(self, archive_file: str, actual_digest: str | None,
                  expected_digest: str) -> str | None:
        timeout = self.get("archive-download-timeout-in-seconds", 1200)
        for url in to_iterable(self["archive-url"]):
            logging.info("%s: download from: %s", self.uid, url)
            try:
                with urllib.request.urlopen(url, timeout=timeout) as response:
                    with open(archive_file, "wb") as dst:
                        shutil.copyfileobj(response, dst)
            # pylint: disable-next=broad-exception-caught
            except Exception as err:
                logging.error("%s: download failed: %s", self.uid, err)
                continue
            download_digest = hash_file(archive_file)
            if download_digest == expected_digest:
                return expected_digest
            logging.error(
                "%s: downloaded archive file '%s' "
                "digest is %s, expected %s", self.uid, archive_file,
                download_digest, expected_digest)
            actual_digest = download_digest
        return actual_digest

    def copy_to_buildspace(self, buildspace_item: BuildItem) -> None:
        assert isinstance(buildspace_item, DirectoryState)
        archive_file = self["archive-file"]
        actual_digest: str | None = None
        expected_digest = buildspace_item["archive-hash"]
        try:
            actual_digest = hash_file(archive_file)
        except FileNotFoundError:
            logging.info("%s: file not found: %s", self.uid, archive_file)
            actual_digest = self._download(archive_file, actual_digest,
                                           expected_digest)
        else:
            if actual_digest != expected_digest:
                logging.error(
                    "%s: present archive file '%s' "
                    "digest is %s, expected %s", self.uid, archive_file,
                    actual_digest, expected_digest)
                actual_digest = self._download(archive_file, actual_digest,
                                               expected_digest)
        if actual_digest != expected_digest:
            raise IOError(
                f"{self.uid}: actual archive file '{archive_file}' "
                f"digest is {actual_digest}, expected {expected_digest}")
        buildspace_item.add_tarfile_members(archive_file,
                                            buildspace_item.directory, True)
        buildspace_item.compact()
        buildspace_item.create_symbolic_links(
            buildspace_item["symbolic-links"])
        _apply_patches(self.substitute("${.:/component/workspace-directory}"),
                       buildspace_item)
        buildspace_item.load()


def _get_view(ctx: ItemGetValueContext) -> str:
    return ctx.item.view[ctx.key]


class WorkspaceComponent(_WorkspaceItem, PackageComponent):
    """ Represents a workspace component. """

    @classmethod
    def prepare_factory(cls, factory: BuildItemFactory,
                        type_name: str) -> None:
        PackageComponent.prepare_factory(factory, type_name)
        factory.add_get_value(f"{type_name}:/workspace-commit", _get_view)
        factory.add_get_value(f"{type_name}:/workspace-directory", _get_view)

    def prepare_buildspace_data(self) -> dict:
        data = copy.deepcopy(self.item.data)
        del data["enabled-set-actions"]
        del data["enabled-set-feedback-mapping"]
        del data["workspace-type"]
        data["pkg-type"] = "component"
        return data


class WorkspaceDirectory(_WorkspaceItem, DirectoryState):
    """ Represents a workspace directory. """

    def load_workspace_state(self) -> str:
        self.load()
        return super().load_workspace_state()

    def prepare_buildspace_data(self) -> dict:
        data = _make_directory_state_data(self.item, "explicit")
        self.copy_attributes(data, ("directory-state-load-before-use",
                                    "license-files", "license-info", "params"))
        return data

    def _copy_to_buildspace_actions(self,
                                    buildspace_item: DirectoryState) -> None:
        buildspace_item.run_actions_provider.run(
            self.item.get("copy-to-buildspace-actions", {}))

    def copy_to_buildspace(self, buildspace_item: BuildItem) -> None:
        assert isinstance(buildspace_item, DirectoryState)
        buildspace_item.lazy_clone(self,
                                   file_mappings=self.item.get(
                                       "file-mappings", None))
        self._copy_to_buildspace_actions(buildspace_item)


class WorkspaceDirectoryRepository(WorkspaceDirectory):
    """ Represents a workspace directory repository. """

    def load_workspace_state(self) -> str:
        self.director.package.view.setdefault("submodules",
                                              []).append(self.uid)
        return super().load_workspace_state()

    def prepare_buildspace_data(self) -> dict:
        data = _make_directory_state_data(self.item, "repository")
        data["branch"] = "main"
        data["commit"] = "01234567890abcdef01234567890abcdef012345"
        data["description"] = ("This is a directory managed as a "
                               "Git repository in the buildspace.")
        for key in ("origin-branch", "origin-commit", "origin-commit-url",
                    "origin-url"):
            data[key] = None
        self.copy_attributes(data, ("directory-state-load-before-use",
                                    "license-files", "license-info", "params"))
        return data

    def copy_to_buildspace(self, buildspace_item: BuildItem) -> None:
        assert isinstance(buildspace_item, RepositoryState)
        destination_directory = buildspace_item.directory
        try:
            shutil.rmtree(os.path.join(destination_directory, ".git"))
        except FileNotFoundError:
            pass
        super().copy_to_buildspace(buildspace_item)
        status = run_command(["git", "init", "--initial-branch=main", "."],
                             destination_directory)
        assert status == 0
        status = run_command(["git", "add", "."], destination_directory)
        assert status == 0
        status = run_command(
            ["git", "commit", "--allow-empty", "-m", "Initial import"],
            destination_directory)
        assert status == 0
        buildspace_item.item.data["commit"] = _git_commit(
            destination_directory)
        buildspace_item.git_add(destination_directory)


class WorkspaceFile(WorkspaceDirectory):
    """ Represents a workspace file. """

    def load_workspace_state(self) -> str:
        for source_file in to_iterable(self["source-file"]):
            source_path = os.path.join(self.directory, source_file)
            if os.path.isfile(source_path):
                self.set_files([source_file])
                break
            logging.info("%s: source file does not exist: %s", self.uid,
                         source_path)
        else:
            raise ValueError(f"{self.uid}: no source file available")
        return super().load_workspace_state()

    def copy_to_buildspace(self, buildspace_item: BuildItem) -> None:
        assert isinstance(buildspace_item, DirectoryState)
        buildspace_item.copy_file(self.file, self["destination-file"])
        buildspace_item.load()
        self._copy_to_buildspace_actions(buildspace_item)


class WorkspaceTestLog(WorkspaceFile):
    """ Represents a workspace test log. """

    def prepare_buildspace_data(self) -> dict:
        data = super().prepare_buildspace_data()
        data["directory-state-type"] = "test-log"
        return data


class WorkspaceRedirect(_WorkspaceItem):
    """ Represents a workspace item redirection. """

    def __init__(self,
                 director: PackageBuildDirector,
                 item: Item,
                 mapper: None | BuildItemMapper = None) -> None:
        super().__init__(director, item, mapper)
        self.redirect: _WorkspaceItem | None = None

    def load_workspace_state(self) -> str:
        item = self.item
        data = load_data(self["source"])
        data["links"][:0] = self.item["links"]
        item.cache.remove_item(item.uid)
        self.item = item.cache.add_item(item.uid, data)
        redirect = self.director.factory.create(self.director, self.item)
        if isinstance(redirect, _WorkspaceItem):
            self.redirect = redirect
            return redirect.load_workspace_state()
        return super().load_workspace_state()

    def prepare_buildspace_data(self) -> dict:
        if self.redirect is None:
            return self.item.data
        return self.redirect.get_buildspace_data()

    def copy_to_buildspace(self, buildspace_item: BuildItem) -> None:
        if self.redirect is None:
            return super().copy_to_buildspace(buildspace_item)
        return self.redirect.copy_to_buildspace(buildspace_item)


class WorkspaceRepository(_WorkspaceItem):
    """ Represents a workspace repository. """

    def __init__(self,
                 director: PackageBuildDirector,
                 item: Item,
                 mapper: Optional[BuildItemMapper] = None) -> None:
        super().__init__(director, item, mapper)
        my_type = self.item.type
        self.mapper.add_get_value(f"{my_type}:/git-commit", self._git_commit)
        self.mapper.add_get_value(f"{my_type}:/git-commit-head",
                                  self._git_commit_head)

    def load_workspace_state(self) -> str:
        self.director.package.view.setdefault("submodules",
                                              []).append(self.uid)
        self.item["commit"] = self["commit"]
        self.item["origin-commit"] = self["origin-commit"]
        return super().load_workspace_state()

    def prepare_buildspace_data(self) -> dict:
        data = _make_directory_state_data(self.item, "repository")
        data["commit"] = self["commit"]
        data["origin-commit"] = self["origin-commit"]
        self.copy_attributes(data,
                             ("branch", "license-files", "license-info",
                              "description", "origin-branch", "origin-commit",
                              "origin-commit-url", "origin-url"))
        return data

    def copy_to_buildspace(self, buildspace_item: BuildItem) -> None:
        assert isinstance(buildspace_item, RepositoryState)
        self._git_clone(buildspace_item)

    def _git_commit(self, ctx: ItemGetValueContext) -> str:
        args, kwargs = ctx.unpack_args_dict()
        ref = args[0] if args else None
        default = kwargs.get("default")
        if ref is not None:
            try:
                ref = ctx.substitute(ref)
            except ValueError as err:
                if default is None or not _is_missing_attribute(err):
                    raise
                ref = default
        if not ref:
            ref = default
        directory = self["directory"]
        commit = _git_commit(directory, ref)
        if ctx.arg_bool("match-head"):
            head = _git_commit(directory)
            if commit != head:
                raise ValueError(f"{self.uid}: commit {commit} of '{ref}' "
                                 f"does not match HEAD {head} of "
                                 f"'{directory}'")
        return commit

    def _git_commit_head(self, _ctx: ItemGetValueContext) -> str:
        return _git_commit(self["directory"])

    def _git_depth(self) -> list[str]:
        clone_depth = self["clone-depth"]
        if clone_depth is None:
            return []
        return ["--depth", str(clone_depth)]

    def _git_prepare_destination_directory(self,
                                           destination_directory: str) -> None:
        logging.info("%s: remove Git repository '%s'", self.uid,
                     destination_directory)
        with contextlib.suppress(FileNotFoundError):
            shutil.rmtree(destination_directory)
        os.makedirs(destination_directory)

    def _git_clone_revision(self, repository: str, commit: str,
                            workspace_directory: str,
                            destination_directory: str) -> int:
        self._git_prepare_destination_directory(destination_directory)
        return run_command(
            ["git", "clone", "--no-local", "--revision", commit] +
            self._git_depth() + [repository, destination_directory],
            workspace_directory)

    def _git_init_fetch(self, repository: str, commit: str,
                        workspace_directory: str,
                        destination_directory: str) -> int:
        self._git_prepare_destination_directory(destination_directory)
        status = run_command(["git", "init", destination_directory],
                             workspace_directory)
        assert status == 0
        status = run_command(["git", "remote", "add", "origin", repository],
                             destination_directory)
        assert status == 0
        return run_command(["git", "fetch"] + self._git_depth() +
                           ["origin", commit], destination_directory)

    def _git_clone(self, buildspace_item: RepositoryState) -> None:
        repository = self["directory"]
        branch = self["branch"]
        commit = self["commit"]
        if repository.startswith("file://"):
            source_directory = repository[7:]
            status = run_command(["git", "branch", "-f", branch, commit],
                                 source_directory)
            if status != 0:
                status = run_command(["git", "fetch", "origin"],
                                     source_directory)
                assert status == 0
                status = run_command(["git", "branch", "-f", branch, commit],
                                     source_directory)
                assert status == 0
        workspace_directory = self.substitute(
            "${.:/component/workspace-directory}")
        destination_directory = buildspace_item.directory
        status = self._git_clone_revision(repository, commit,
                                          workspace_directory,
                                          destination_directory)
        if status != 0:
            status = self._git_init_fetch(repository, commit,
                                          workspace_directory,
                                          destination_directory)
        if status != 0:
            raise IOError(f"{self.uid}: cannot clone or "
                          f"initialize repository: {repository}")
        status = run_command(["git", "checkout", "-B", branch, commit],
                             destination_directory)
        assert status == 0
        for fetch in self["origin-fetch"]:
            if is_enabled(self.enabled_set, fetch["enabled-by"]):
                status = run_command(
                    ["git", "fetch", "origin", fetch["value"]],
                    destination_directory)
                assert status == 0
        origin_url = self["origin-url"]
        if origin_url:
            status = run_command(["git", "remote", "add", "tmp", origin_url],
                                 destination_directory)
            assert status == 0
            status = run_command(["git", "remote", "remove", "origin"],
                                 destination_directory)
            assert status == 0
            status = run_command(["git", "remote", "rename", "tmp", "origin"],
                                 destination_directory)
            assert status == 0
        origin_branch = self["origin-branch"]
        origin_commit = self["origin-commit"]
        if origin_branch and origin_commit:
            status = run_command(
                ["git", "checkout", "-b", origin_branch, origin_commit],
                destination_directory)
            assert status == 0
            status = run_command(["git", "checkout", branch],
                                 destination_directory)
            assert status == 0
            status = run_command([
                "git", "symbolic-ref", "refs/remotes/origin/HEAD",
                f"refs/remotes/origin/{origin_branch}"
            ], destination_directory)
            assert status == 0
        buildspace_item.create_symbolic_links(
            buildspace_item.substitute(self.item["symbolic-links"]))
        for command in self["post-clone-commands"]:
            status = run_command(command, destination_directory)
            assert status == 0
        _git_commit(destination_directory)
        buildspace_item.item["patterns"] = [{"include": "**/*", "exclude": []}]
        buildspace_item.load()
        del buildspace_item.item.data["patterns"]
        buildspace_item.git_add(destination_directory)


def create_workspace_item_factory() -> BuildItemFactory:
    """ Create the workspace build item factory. """
    factory = BuildItemFactory()
    factory.add_constructor("pkg/template/component", BuildItemTemplate)
    factory.add_constructor("pkg/template/file-item", BuildItemTemplate)
    factory.add_constructor("pkg/template/inline-item", BuildItemTemplate)
    factory.add_constructor("pkg/template/redirect", BuildItemTemplate)
    factory.add_constructor("pkg/workspace/archive", WorkspaceArchive)
    factory.add_constructor("pkg/workspace/component", WorkspaceComponent)
    factory.add_constructor("pkg/workspace/directory", WorkspaceDirectory)
    factory.add_constructor("pkg/workspace/directory-repository",
                            WorkspaceDirectoryRepository)
    factory.add_constructor("pkg/workspace/file", WorkspaceFile)
    factory.add_constructor("pkg/workspace/redirect", WorkspaceRedirect)
    factory.add_constructor("pkg/workspace/repository", WorkspaceRepository)
    factory.add_constructor("pkg/workspace/test-log", WorkspaceTestLog)
    return factory


def _apply_enabled_set_actions(component: WorkspaceComponent,
                               selection: ItemSelection, item: Item) -> None:
    for action in component.substitute(item["enabled-set-actions"]):
        selection.apply_action(action)
    logging.info("%s: enabled set after %s actions: %s", component.uid,
                 item.uid, sorted(selection.enabled_set))
    for template in itertools.chain(
            item.parents("use-package-component-template"),
            item.children("add-package-component-template")):
        _apply_enabled_set_actions(component, selection, template)


def _gather_feedback(component: WorkspaceComponent, selection: ItemSelection,
                     item: Item, feedback_set: set[str]) -> None:
    for template in itertools.chain(
            item.parents("use-package-component-template"),
            item.children("add-package-component-template")):
        _gather_feedback(component, selection, template, feedback_set)
    mapping = component.substitute(item["enabled-set-feedback-mapping"])
    for pattern, replacement in mapping.items():
        try:
            compiled = re.compile(pattern)
        except re.error as err:
            raise ValueError(
                f"{component.uid}: the enabled set feedback mapping of "
                f"{item.uid} states the invalid pattern '{pattern}': "
                f"{err}") from err
        for key in selection.enabled_set:
            match = compiled.fullmatch(key)
            if match is None:
                continue
            try:
                feedback_set.add(match.expand(replacement).lower())
            except re.error as err:
                raise ValueError(
                    f"{component.uid}: the enabled set feedback mapping of "
                    f"{item.uid} states the invalid replacement "
                    f"'{replacement}' of the pattern '{pattern}' for the "
                    f"enabled set key '{key}': {err}") from err


def _prepare_components(director: PackageBuildDirector,
                        component: WorkspaceComponent,
                        upper_selection: ItemSelection) -> EnabledSet:
    # Add the enabled set of the upper level component to our own enabled set
    selection = component.selection
    logging.info("%s: initial enabled set: %s", component.uid,
                 sorted(selection.enabled_set))
    selection.extend_enabled_set(upper_selection.enabled_set)
    logging.info("%s: enabled set after upper level extension: %s",
                 component.uid, sorted(selection.enabled_set))

    # Apply enabled set actions of templates and us
    _apply_enabled_set_actions(component, selection, component.item)

    # Add enabled set feedback from templates and us
    feedback_set: set[str] = set()
    _gather_feedback(component, selection, component.item, feedback_set)
    selection.extend_enabled_set(feedback_set)
    logging.info("%s: enabled set after template and own feedback: %s",
                 component.uid, sorted(selection.enabled_set))

    # Prepare next level components and get their enabled set feedback
    for link in component.item.links_to_children("input"):
        if link.item.get("workspace-type", None) == "component":
            subcomponent = director[link.item.uid]
            assert isinstance(subcomponent, WorkspaceComponent)
            feedback_set.update(
                _prepare_components(director, subcomponent, selection))
    selection.extend_enabled_set(feedback_set)
    logging.info("%s: enabled set after lower level feedback: %s",
                 component.uid, sorted(selection.enabled_set))

    component.item["enabled-set"] = sorted(selection.enabled_set)
    logging.info("%s: enabled set feedback for upper level: %s", component.uid,
                 sorted(feedback_set))
    return feedback_set


def _expand_templates(director: PackageBuildDirector,
                      component: WorkspaceComponent) -> None:
    with component.scope():
        new_uids: list[str] = []
        for item in itertools.chain(
                component.item.parents(("use-package-template",
                                        "use-package-component-template")),
                component.item.children(("add-package-template",
                                         "add-package-component-template"))):
            template = director[item.uid]
            template.expand_template(component, new_uids)
        director.item_cache.initialize_links(new_uids)
        for link in component.item.links_to_children("input"):
            if link.item.get("workspace-type", None) == "component":
                subcomponent = director[link.item.uid]
                assert isinstance(subcomponent, WorkspaceComponent)
                _expand_templates(director, subcomponent)


@dataclasses.dataclass
class WorkspaceConfig:
    """ Represents a workspace configuration. """
    # pylint: disable=too-many-instance-attributes
    spec_directories: list[str]
    workspace_directory: str = "."
    package_uid: str = "/pkg/component"
    cache_directory: str = "cache-workspace"
    enabled_set: list[str] = dataclasses.field(default_factory=list)
    verify_specification_format: bool = True
    factory: BuildItemFactory | None = None
    extra_type_data_by_uid: ItemDataByUID = dataclasses.field(
        default_factory=dict)


@dataclasses.dataclass
class WorkspaceContext:
    """
    Provides a context with a workspace director and associated elements.
    """
    cache: ItemCache
    director: PackageBuildDirector
    workspace_directory: str
    extra_type_data_by_uid: ItemDataByUID


def create_workspace(config: WorkspaceConfig) -> WorkspaceContext:
    """ Create a workspace package build director. """
    cache_config = ItemCacheConfig(enabled_set=config.enabled_set,
                                   paths=config.spec_directories,
                                   resolve_proxies=False,
                                   cache_directory=config.cache_directory)
    type_provider = BuildItemTypeProvider(config.extra_type_data_by_uid)
    item_cache = ItemCache(cache_config, type_provider=type_provider)
    factory = config.factory
    if factory is None:
        factory = create_workspace_item_factory()
    director = PackageBuildDirector(item_cache, config.package_uid, factory)
    package = director.package
    package.item.view["workspace-commit"] = _git_commit(
        config.workspace_directory)
    package.item.view["workspace-directory"] = config.workspace_directory
    assert isinstance(package, WorkspaceComponent)
    _prepare_components(director, package, item_cache.active_selection)
    _expand_templates(director, package)
    _verify_specification_format(item_cache,
                                 config.verify_specification_format)
    return WorkspaceContext(item_cache, director, config.workspace_directory,
                            config.extra_type_data_by_uid)


@dataclasses.dataclass
class _UIDs:
    # pylint: disable=too-many-instance-attributes
    deleted: list[str]
    workspace: list[str]
    workspace_modified: list[str]
    workspace_copy: list[str]
    workspace_dummy: list[str]
    other_existing: list[str]
    other_new: list[str]
    other_modified: list[str]

    def __init__(self, workspace_cache: ItemCache,
                 buildspace_cache: ItemCache) -> None:
        spec_types: set[str] = set(
            item.uid for item in workspace_cache.items_by_type["spec"])
        workspace_all: set[str] = set(
            itertools.chain(workspace_cache.keys(),
                            workspace_cache.proxies.keys())) - spec_types
        buildspace_all: set[str] = set(
            itertools.chain(buildspace_cache.keys(),
                            buildspace_cache.proxies.keys())) - spec_types

        # Get UIDs of all workspace type items
        workspace: set[str] = set()
        for name in workspace_cache.types:
            if name.startswith("pkg/workspace/"):
                workspace.update(
                    item.uid for item in workspace_cache.items_by_type[name])

        # Get the dependencies of all workspace type items to sort them
        # topologically
        workspace_deps: dict[str, set[str]] = {}
        for uid in workspace:
            workspace_deps.setdefault(uid, set())
            item = workspace_cache[uid]
            for parent in item.parents(
                ("input", "weak-package-build-dependency"),
                    is_link_enabled=link_is_enabled):
                if parent.uid in workspace:
                    workspace_deps[uid].add(parent.uid)
            for parent in item.parents("input-to",
                                       is_link_enabled=link_is_enabled):
                if parent.uid in workspace:
                    workspace_deps.setdefault(parent.uid, set()).add(uid)
        workspace_deps = dict(sorted(workspace_deps.items()))

        self.deleted = sorted(buildspace_all - workspace_all)
        self.workspace = list(
            graphlib.TopologicalSorter(workspace_deps).static_order())
        self.workspace_modified = []
        self.workspace_copy = []
        self.workspace_dummy = []
        other = workspace_all - workspace
        self.other_existing = sorted(other & buildspace_all)
        self.other_new = sorted(other - buildspace_all)
        self.other_modified = []
        assert set(
            itertools.chain(self.other_new, self.other_existing,
                            self.workspace)) == workspace_all


@dataclasses.dataclass
class BuildspaceConfig:
    """
    Represents a buildspace configuration.  The build steps are tracked in the
    Git directory.  If it is None, then Git is not used.
    """
    spec_directory: str
    cache_directory: str = "cache-buildspace"
    git_directory: Optional[str] = None
    verify_specification_format: bool = False
    factory: BuildItemFactory | None = None


@dataclasses.dataclass
class BuildspaceContext:
    """
    Provides a context with a buildspace director and associated elements.
    """
    cache: ItemCache
    director: PackageBuildDirector
    spec_directory: str


def _create_buildspace(
        config: BuildspaceConfig, package_uid: str, enabled_set: list[str],
        extra_type_data_by_uid: ItemDataByUID) -> BuildspaceContext:
    os.makedirs(config.spec_directory, exist_ok=True)
    cache_config = ItemCacheConfig(enabled_set=enabled_set,
                                   paths=[config.spec_directory],
                                   resolve_proxies=False,
                                   cache_directory=config.cache_directory)
    type_provider = BuildItemTypeProvider(extra_type_data_by_uid)
    item_cache = JSONItemCache(cache_config, type_provider=type_provider)
    factory = config.factory
    if factory is None:
        factory = create_build_item_factory()
    director = PackageBuildDirector(item_cache, package_uid, factory,
                                    config.git_directory)
    return BuildspaceContext(item_cache, director, config.spec_directory)


def _gather_workspace_modified(workspace_director: PackageBuildDirector,
                               buildspace_cache: ItemCache,
                               uids: _UIDs) -> None:
    for uid in uids.workspace:
        workspace_item = workspace_director[uid]
        assert isinstance(workspace_item, _WorkspaceItem)
        with workspace_item.scope():
            if workspace_item.item.enabled:
                logging.info("%s: load workspace state", uid)
                digest = workspace_item.load_workspace_state()
                is_dummy = False
            else:
                logging.info("%s: use dummy for disabled item", uid)
                dummy_digest = _DUMMY_DATA["workspace-hash"]
                assert isinstance(dummy_digest, str)
                digest = dummy_digest
                is_dummy = True
        workspace_item["workspace-hash"] = digest
        buildspace_item = buildspace_cache.get(uid, None)
        if buildspace_item is not None and digest == buildspace_item[
                "workspace-hash"]:
            continue
        if buildspace_item is not None:
            uids.workspace_modified.append(uid)
        if is_dummy:
            uids.workspace_dummy.append(uid)
        else:
            uids.workspace_copy.append(uid)
            data = workspace_item.get_buildspace_data()
            data["workspace-hash"] = workspace_item["workspace-hash"]
            workspace_item.item.view["buildspace-data"] = data


def _gather_other_modified(workspace_director: PackageBuildDirector,
                           buildspace_cache: ItemCache, uids: _UIDs) -> None:
    for uid in uids.other_existing:
        workspace_item = workspace_director.item_cache[uid]
        digest = _workspace_hash(workspace_item.data)
        if digest != buildspace_cache[uid]["workspace-hash"]:
            workspace_item["workspace-hash"] = digest
            uids.other_modified.append(uid)


def _set_other_workspace_hash(workspace_cache: ItemCache,
                              other_new: list[str]) -> None:
    for uid in other_new:
        workspace_item = workspace_cache[uid]
        workspace_item["workspace-hash"] = _workspace_hash(workspace_item.data)


def _delete_buildspace_items(director: PackageBuildDirector,
                             deleted_uids: list[str],
                             item_files: list[str]) -> None:
    for uid in deleted_uids:
        logging.info("%s: discard buildspace state", uid)
        try:
            buildspace_item = director.create_with_dependencies(
                uid, permissive_errors=True)
        # pylint: disable-next=broad-exception-caught
        except Exception as err:
            logging.error("%s: create buildspace item failed: %s", uid, err)
        else:
            buildspace_item.discard_and_clear()
            buildspace_item.commit("Delete")
        file = director.item_cache[uid].file
        director.remove(uid)
        logging.info("%s: remove: %s", uid, file)
        os.remove(file)
        item_files.append(file)


def _add_buildspace_submodules(
        workspace_package: PackageComponent,
        buildspace_director: PackageBuildDirector) -> None:
    for uid in workspace_package.view.get("submodules", []):
        try:
            # Creating a repository state will register it as a submodule
            buildspace_director[uid]
        except KeyError:
            pass


def _discard_buildspace_items(director: PackageBuildDirector,
                              discard_uids: list[str]) -> None:
    for uid in discard_uids:
        logging.info("%s: discard buildspace state", uid)
        try:
            buildspace_item = director.create_with_dependencies(
                uid, permissive_errors=True)
        # pylint: disable-next=broad-exception-caught
        except Exception as err:
            logging.error("%s: create buildspace item failed: %s", uid, err)
        else:
            buildspace_item.discard_and_clear()
            buildspace_item.commit("Discard")
        director.remove(uid)


def _add_buildspace_item(buildspace: BuildspaceContext, uid: str,
                         data: dict) -> Item:
    new_item = buildspace.cache.add_item(uid, data, initialize_links=False)
    file = os.path.join(buildspace.spec_directory, f"{uid[1:]}.json")
    new_item.file = file
    os.makedirs(os.path.dirname(file), exist_ok=True)
    return new_item


def _copy_to_buildspace(workspace_director: PackageBuildDirector,
                        buildspace_director: PackageBuildDirector,
                        workspace_copy: list[str]) -> None:
    for uid in workspace_copy:
        workspace_item = workspace_director[uid]
        assert isinstance(workspace_item, _WorkspaceItem)
        with workspace_item.scope():
            buildspace_item = buildspace_director[uid]
            logging.info("%s: copy to buildspace", uid)
            workspace_item.copy_to_buildspace(buildspace_item)
            buildspace_item.commit("Copy to buildspace")


def export_to_buildspace(workspace: WorkspaceContext,
                         config: BuildspaceConfig) -> BuildspaceContext:
    """ Export the workspace to the buildspace. """
    buildspace = _create_buildspace(config, workspace.director.package_uid,
                                    list(workspace.cache.enabled_set),
                                    workspace.extra_type_data_by_uid)
    uids = _UIDs(workspace.cache, buildspace.cache)
    _gather_workspace_modified(workspace.director, buildspace.cache, uids)
    _gather_other_modified(workspace.director, buildspace.cache, uids)
    _set_other_workspace_hash(workspace.cache, uids.other_new)
    item_files: list[str] = []
    _delete_buildspace_items(buildspace.director, uids.deleted, item_files)
    _add_buildspace_submodules(workspace.director.package, buildspace.director)

    # Discard other items first and the modified workspace items in reverse
    # order since we may have modified the package component which provides the
    # Git directory
    _discard_buildspace_items(buildspace.director, uids.other_modified)
    _discard_buildspace_items(buildspace.director,
                              sorted(uids.workspace_modified, reverse=True))

    for uid in uids.workspace_copy:
        _add_buildspace_item(buildspace, uid,
                             workspace.cache[uid].view["buildspace-data"])
    for uid in uids.workspace_dummy:
        item = _add_buildspace_item(buildspace, uid, _DUMMY_DATA)
        item.save()
        item_files.append(item.file)
    for uid in itertools.chain(uids.other_new, uids.other_modified):
        item = _add_buildspace_item(buildspace, uid,
                                    copy.deepcopy(workspace.cache[uid].data))
        item.save()
        item_files.append(item.file)
    buildspace.cache.reinitialize_links()
    _copy_to_buildspace(workspace.director, buildspace.director,
                        uids.workspace_copy)
    if item_files:
        package = buildspace.director.package
        package.git_add(item_files)
        package.commit("Update buildspace items")
    buildspace.cache.resolve_proxies = True
    _verify_specification_format(buildspace.cache,
                                 config.verify_specification_format)
    return buildspace
