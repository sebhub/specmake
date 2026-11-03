# SPDX-License-Identifier: BSD-2-Clause
""" Provides a filter of the history of a repository. """

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

import contextlib
import dataclasses
import logging
import subprocess
from typing import Any, Iterable

import git_filter_repo  # type: ignore[import-untyped]
from specitems import EnabledSet, Item, data_digest, is_enabled
from specware import run_command

_REF = "refs/heads/repository-filter"

_WARN_PATH_LIMIT = 10


def _decode(path: bytes) -> str:
    return path.decode("utf-8", "surrogateescape")


def _encode(path: str) -> bytes:
    return path.encode("utf-8", "surrogateescape")


@dataclasses.dataclass
class RepositoryFilter:
    """
    Represents the enabled rules of a repository filter item.

    A rule element which ends with a slash is a directory prefix.  Any other
    element is an exact path.  The longest element which matches a path
    decides whether the path is kept.  A path which no element matches is
    kept.  A replaced file decides before the elements.
    """
    uid: str
    baseline: str
    path_rules: dict[str, bool]
    replace_files: dict[str, str]

    def digest(self) -> str:
        """ Return the digest of the enabled rules. """
        return data_digest({
            "baseline":
            self.baseline,
            "path-rules":
            dict(sorted(self.path_rules.items())),
            "replace-files":
            dict(sorted(self.replace_files.items()))
        })

    def keep(self, path: str) -> bool:
        """ Return true, if the path passes the filter. """
        if path in self.replace_files:
            return True
        keep = self.path_rules.get(path)
        end = path.rfind("/")
        while keep is None and end >= 0:
            keep = self.path_rules.get(path[:end + 1])
            end = path.rfind("/", 0, end)
        return True if keep is None else keep

    def is_filtered(self, path: str) -> bool:
        """ Return true, if a rule drops or replaces the path. """
        return path in self.replace_files or not self.keep(path)

    def _warn_baseline_paths(self, directory: str) -> None:
        output = subprocess.run(
            ["git", "ls-tree", "-r", "-z", "--name-only", self.baseline],
            cwd=directory,
            check=True,
            capture_output=True).stdout
        paths = [
            path for path in map(_decode, output.split(b"\0"))
            if path and self.is_filtered(path)
        ]
        if paths:
            more = ", ..." if len(paths) > _WARN_PATH_LIMIT else ""
            logging.warning(
                "%s: the rules drop or replace %d paths of the baseline %s, "
                "they stay unchanged up to the first filtered commit which "
                "changes them: %s%s", self.uid, len(paths), self.baseline,
                ", ".join(paths[:_WARN_PATH_LIMIT]), more)

    def is_ancestor_of_baseline(self, directory: str, commit: str) -> bool:
        """
        Return true, if the commit is the baseline or an ancestor of it in
        the repository of the directory.
        """
        return run_command(
            ["git", "merge-base", "--is-ancestor", commit, self.baseline],
            directory) == 0

    def run(self, directory: str, commit: str) -> str:
        """
        Filter the commits which follow the baseline up to the commit in the
        bare repository of the directory.  Return the filtered commit.
        """
        if run_command(
            ["git", "merge-base", "--is-ancestor", self.baseline, commit],
                directory) != 0:
            raise ValueError(f"{self.uid}: the baseline {self.baseline} is "
                             f"no ancestor of commit {commit}")
        status = run_command(["git", "update-ref", _REF, commit], directory)
        assert status == 0
        self._warn_baseline_paths(directory)
        replacements = {
            _encode(path): content.encode("utf-8")
            for path, content in self.replace_files.items()
        }

        def filename_callback(filename: bytes) -> bytes | None:
            if self.keep(_decode(filename)):
                return filename
            return None

        def file_info_callback(filename: bytes, mode: bytes, blob_id: bytes,
                               value: Any) -> tuple[bytes, bytes, bytes]:
            content = replacements.get(filename, None)
            if content is not None:
                blob_id = value.insert_file_with_contents(content)
            return filename, mode, blob_id

        logging.info("%s: filter the commits from %s to %s in: %s", self.uid,
                     self.baseline, commit, directory)
        args = git_filter_repo.FilteringOptions.parse_args(
            ["--force", "--quiet", "--refs", f"{self.baseline}..{_REF}"])
        with contextlib.chdir(directory):
            git_filter_repo.RepoFilter(
                args,
                filename_callback=filename_callback,
                file_info_callback=file_info_callback).run()
        stdout: list[str] = []
        status = run_command(["git", "rev-parse", _REF], directory, stdout)
        assert status == 0
        return stdout[0].strip()


def export_no_data(_item: Item, _present: bool, _built_later: bool) -> None:
    """ Export no data of a repository filter item. """
    return None


def _add_elements(uid: str, path_rules: dict[str, bool], elements: list[str],
                  keep: bool) -> None:
    for element in elements:
        other = path_rules.setdefault(element, keep)
        if other != keep:
            raise ValueError(f"{uid}: the path rule element '{element}' "
                             "is in an enabled drop and keep list")


def _add_item(item: Item, enabled_set: EnabledSet, path_rules: dict[str, bool],
              replace_files: dict[str, str]) -> None:
    uid = item.uid
    for rule in item["path-rules"]:
        if is_enabled(enabled_set, rule["enabled-by"]):
            _add_elements(uid, path_rules, rule["drop"], False)
            _add_elements(uid, path_rules, rule["keep"], True)
    for replace in item["replace-files"]:
        if is_enabled(enabled_set, replace["enabled-by"]):
            path = replace["path"]
            content = replace_files.setdefault(path, replace["content"])
            if content != replace["content"]:
                raise ValueError(f"{uid}: the file '{path}' has enabled "
                                 "replacements with different contents")


def load_repository_filter(uid: str, items: Iterable[Item],
                           enabled_set: EnabledSet) -> RepositoryFilter | None:
    """
    Load the enabled rules of the repository filter items.  Return None
    without an item.
    """
    baseline: str | None = None
    path_rules: dict[str, bool] = {}
    replace_files: dict[str, str] = {}
    for item in items:
        if baseline is None:
            baseline = item["baseline"]
        elif baseline != item["baseline"]:
            raise ValueError(f"{item.uid}: the baseline {item['baseline']} "
                             f"differs from the baseline {baseline} of the "
                             f"other repository filters of {uid}")
        _add_item(item, enabled_set, path_rules, replace_files)
    if baseline is None:
        return None
    return RepositoryFilter(uid, baseline, path_rules, replace_files)
