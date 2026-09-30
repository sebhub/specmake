# SPDX-License-Identifier: BSD-2-Clause
""" Run actions. """

# Copyright (C) 2022, 2026 embedded brains GmbH & Co. KG
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

import copy
import contextlib
import dataclasses
import functools
import itertools
import os
import logging
from pathlib import Path
import shutil
from typing import Any, Callable, Iterator, Optional, TextIO

from specitems import (EnabledSet, Item, ItemGetValueContext, IS_ENABLED_OPS,
                       escape_code_line, is_enabled_with_ops,
                       run_subprocess_action)

from .dirstatebase import DirectoryStateBase
from .pkgitems import BuildItem, BuildItemMapper, PackageBuildDirector
from .util import copy_file, copy_and_substitute, remove_empty_directories


def _get_host_processor_count(_ctx: ItemGetValueContext) -> str:
    count = os.cpu_count()
    return str(count if count is not None else 1)


@dataclasses.dataclass
class _Env:
    clear: tuple[str, ...] = ()
    path: dict[str, tuple[list[str],
                          list[str]]] = dataclasses.field(default_factory=dict)
    var_set: dict[str, str] = dataclasses.field(default_factory=dict)
    var_unset: list[str] = dataclasses.field(default_factory=list)


def _env_clear(env: _Env, _action: dict[str, str]) -> None:
    env.clear = ("-i", )


def _env_ignore(_env: _Env, _action: dict[str, str]) -> None:
    pass


def _env_path_append(env: _Env, action: dict[str, str]) -> None:
    env.path.setdefault(action["name"], ([], []))[1].append(action["value"])


def _env_path_prepend(env: _Env, action: dict[str, str]) -> None:
    env.path.setdefault(action["name"], ([], []))[0].append(action["value"])


def _env_set(env: _Env, action: dict[str, str]) -> None:
    name = action["name"]
    env.var_set[name] = action["value"]
    env.path.pop(name, None)


def _env_unset(env: _Env, action: dict[str, str]) -> None:
    name = action["name"]
    env.var_unset.append(name)
    env.path.pop(name, None)
    env.var_set.pop(name, None)


_ENV_ACTIONS = {
    "clear": _env_clear,
    "ignore": _env_ignore,
    "path-append": _env_path_append,
    "path-prepend": _env_path_prepend,
    "set": _env_set,
    "unset": _env_unset
}


def _add_description(client: BuildItem, line: str) -> None:
    client.description.append(escape_code_line(line))


def _copy_and_op(client: BuildItem, action: dict,
                 output: Optional[DirectoryStateBase],
                 operation: Callable[[BuildItem, str, str], None]) -> None:
    action = client.substitute(action)
    assert isinstance(output, DirectoryStateBase)
    input_name = action["input-name"]
    if input_name == ".":
        input_state = client
    else:
        input_state = client.input(input_name)
    assert isinstance(input_state, DirectoryStateBase)
    source = action["source"]
    source_base = input_state.directory
    target_base = output.directory
    if source is None:
        prefix = action["target"]
        if prefix is None:
            prefix = "."
        targets: list[str] = []
        for source_file in input_state:
            tail = os.path.relpath(source_file, source_base)
            target_file = os.path.join(target_base, prefix, tail)
            targets.append(tail)
            _add_description(client, f"cp {source_file} {target_file}")
            operation(client, source_file, target_file)
        output.add_files(targets)
    else:
        source_file = os.path.join(source_base, source)
        target = action["target"]
        if target is None:
            target_file = output.file
        else:
            output.add_files([target])
            target_file = os.path.join(target_base, target)
        _add_description(client, f"cp {source_file} {target_file}")
        operation(client, source_file, target_file)


def _do_copy(client: BuildItem, source_file: str, target_file: str) -> None:
    copy_file(source_file, target_file, client.uid)


def _do_copy_and_substitute(client: BuildItem, source_file: str,
                            target_file: str) -> None:
    copy_and_substitute(source_file, target_file, client.mapper, client.uid)


def _eq(_ops: dict, _enabled_set: EnabledSet, enabled_by: Any) -> bool:
    for value in enabled_by[:-1]:
        if value != enabled_by[-1]:
            return False
    return True


def _ge(_ops: dict, _enabled_set: EnabledSet, enabled_by: Any) -> bool:
    for index, value in enumerate(enabled_by[:-1]):
        if int(value) < int(enabled_by[index + 1]):
            return False
    return True


def _gt(_ops: dict, _enabled_set: EnabledSet, enabled_by: Any) -> bool:
    for index, value in enumerate(enabled_by[:-1]):
        if int(value) <= int(enabled_by[index + 1]):
            return False
    return True


def _is_empty(_ops: dict, _enabled_set: EnabledSet, enabled_by: Any) -> bool:
    return not enabled_by


def _le(_ops: dict, _enabled_set: EnabledSet, enabled_by: Any) -> bool:
    for index, value in enumerate(enabled_by[:-1]):
        if int(value) > int(enabled_by[index + 1]):
            return False
    return True


def _lt(_ops: dict, _enabled_set: EnabledSet, enabled_by: Any) -> bool:
    for index, value in enumerate(enabled_by[:-1]):
        if int(value) >= int(enabled_by[index + 1]):
            return False
    return True


class RunActionsProvider:
    """ Runs actions provider. """

    # pylint: disable=too-few-public-methods

    def __init__(self, client: BuildItem) -> None:
        self._client = client
        client.mapper.add_get_value(
            f"{client.item.type}:/host-processor-count",
            _get_host_processor_count)
        self._is_enabled_ops = IS_ENABLED_OPS | {
            "eq": _eq,
            "ge": _ge,
            "gt": _gt,
            "is-empty": _is_empty,
            "has-output": self._has_output,
            "le": _le,
            "lt": _lt,
        }

    def _run_actions(self, client: BuildItem, actions: dict) -> None:
        for index, action in enumerate(actions):
            action_type = action["action"]
            logging.info("%s: run action %i: %s", client.uid, index,
                         action_type)
            if is_enabled_with_ops(self._is_enabled_ops, client.enabled_set,
                                   client.substitute(action["enabled-by"])):
                output_name = action.get("output-name", None)
                if output_name is None:
                    output: None | BuildItem = None
                elif output_name == ".":
                    output = client
                else:
                    try:
                        output = client.output(output_name)
                    except KeyError:
                        continue
                assert output is None or isinstance(output, DirectoryStateBase)
                RunActionsProvider._ACTIONS[action_type](self, client, action,
                                                         output)

    def run(self, actions: dict) -> None:
        """ Run the actions. """
        if not actions:
            return
        client = self._client
        client.description.add("Run the following actions:")
        with client.description.directive("code-block", "none", [":linenos:"]):
            self._run_actions(client, actions)

    def _has_output(self, _ops: dict, _enabled_set: EnabledSet,
                    enabled_by: Any) -> bool:
        assert isinstance(enabled_by, str)
        try:
            self._client.output(enabled_by)
        except KeyError:
            return False
        return True

    def _copy(self, client: BuildItem, action: dict,
              output: Optional[DirectoryStateBase]) -> None:
        _copy_and_op(client, action, output, _do_copy)

    def _copy_and_substitute(self, client: BuildItem, action: dict,
                             output: Optional[DirectoryStateBase]) -> None:
        _add_description(client, "# substitute content")
        _copy_and_op(client, action, output, _do_copy_and_substitute)

    @contextlib.contextmanager
    def _create_target(
            self, client: BuildItem, action: dict,
            output: Optional[DirectoryStateBase]
    ) -> Iterator[tuple[str, TextIO]]:
        assert isinstance(output, DirectoryStateBase)
        target = client.substitute(action["target"])
        if target is None:
            target = output.file
        else:
            output.add_files([target])
            target = os.path.join(output.directory, target)
        logging.info("%s: create: %s", client.uid, target)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        yield target, open(target, "w", encoding="utf-8")

    def _is_enabled(self, component: dict) -> bool:
        client = self._client
        return is_enabled_with_ops(self._is_enabled_ops, client.enabled_set,
                                   client.substitute(component["enabled-by"]))

    def _create_ini_file(self, client: BuildItem, action: dict,
                         output: Optional[DirectoryStateBase]) -> None:
        with self._create_target(client, action, output) as (target, file):
            for section in action["sections"]:
                if not self._is_enabled(section):
                    continue
                name = client.substitute(section["name"])
                file.write(f"[{name}]\n")
                for key_value in section["key-value-pairs"]:
                    if not self._is_enabled(key_value):
                        continue
                    key_value = client.substitute(key_value)
                    file.write(f"{key_value['key']} = {key_value['value']}\n")
            _add_description(client, f"# create INI file {target}")

    def _create_kconfig_file(self, client: BuildItem, action: dict,
                             output: Optional[DirectoryStateBase]) -> None:
        with self._create_target(client, action, output) as (target, file):
            for key_value in action["key-value-pairs"]:
                if self._is_enabled(key_value):
                    key_value = client.substitute(key_value)
                    file.write(f"{key_value['key']}={key_value['value']}\n")
            _add_description(client, f"# create Kconfig file {target}")

    def _directory_state_clear(self, client: BuildItem, _action: dict,
                               output: Optional[DirectoryStateBase]) -> None:
        assert isinstance(output, DirectoryStateBase)
        output.clear()
        _add_description(client, f"# clear directory state {output.item.spec}")

    def _directory_state_discard(self, client: BuildItem, _action: dict,
                                 output: Optional[DirectoryStateBase]) -> None:
        assert isinstance(output, DirectoryStateBase)
        output.discard()
        _add_description(client,
                         f"# discard directory state {output.item.spec}")

    def _directory_state_discard_and_clear(
            self, client: BuildItem, action: dict,
            output: Optional[DirectoryStateBase]) -> None:
        self._directory_state_discard(client, action, output)
        self._directory_state_clear(client, action, output)

    def _directory_state_discard_excludes(
            self, client: BuildItem, _action: dict,
            output: Optional[DirectoryStateBase]) -> None:
        assert isinstance(output, DirectoryStateBase)
        for exclude_item in client.item.parents("directory-state-exclude"):
            exclude_state = client.director[exclude_item.uid]
            assert isinstance(exclude_state, DirectoryStateBase)
            exclude_state.discard()
            _add_description(
                client, f"# discard directory state {exclude_state.item.spec}")

    def _directory_state_add_files(
            self, client: BuildItem, action: dict,
            output: Optional[DirectoryStateBase]) -> None:
        action = client.substitute(action)
        assert isinstance(output, DirectoryStateBase)
        root = Path(action["path"]).absolute()
        pattern = action["pattern"]
        logging.info("%s: add files matching '%s' in: %s", client.uid, pattern,
                     root)
        base = output.directory
        output.add_files([
            os.path.relpath(path, base) for path in root.glob(pattern)
            if path.is_symlink() or not path.is_dir()
        ])
        _add_description(client,
                         f"# add files to directory state {output.item.spec}")

    def _directory_state_add_tarfile_members(
            self, client: BuildItem, action: dict,
            output: Optional[DirectoryStateBase]) -> None:
        action = client.substitute(action)
        assert isinstance(output, DirectoryStateBase)
        root = Path(action["search-path"])
        pattern = action["pattern"]
        logging.info("%s: search for tarfiles matching '%s' in: %s",
                     client.uid, pattern, root)
        for path in root.glob(pattern):
            output.add_tarfile_members(path, action["prefix-path"],
                                       action["extract"])
            _add_description(
                client, f"# add files from {path} to "
                f"directory state {output.item.spec}")

    def _directory_state_tree_op(self, client: BuildItem, action: dict,
                                 output: DirectoryStateBase,
                                 tree_op: Any) -> tuple[str, str]:
        action = client.substitute(action)
        root = Path(action["root"]).absolute()
        prefix = action["prefix"]
        if prefix is None:
            prefix = "."
        tree_op(output, root, prefix, action["excludes"])
        return os.path.normpath(root), os.path.normpath(
            os.path.join(output.directory, prefix))

    def _directory_state_add_tree(
            self, client: BuildItem, action: dict,
            output: Optional[DirectoryStateBase]) -> None:
        assert isinstance(output, DirectoryStateBase)
        source, _ = self._directory_state_tree_op(client, action, output,
                                                  DirectoryStateBase.add_tree)
        _add_description(
            client, f"# add files of directory {source} "
            f"to directory state {output.item.spec}")

    def _directory_state_copy_tree(
            self, client: BuildItem, action: dict,
            output: Optional[DirectoryStateBase]) -> None:
        assert isinstance(output, DirectoryStateBase)
        source, target = self._directory_state_tree_op(
            client, action, output, DirectoryStateBase.copy_tree)
        _add_description(client, f"mkdir -p {target}")
        _add_description(
            client,
            f"# add files of below copy to directory state {output.item.spec}")
        _add_description(client, f"cp -r {source} {target}")

    def _directory_state_move_tree(
            self, client: BuildItem, action: dict,
            output: Optional[DirectoryStateBase]) -> None:
        assert isinstance(output, DirectoryStateBase)
        source, target = self._directory_state_tree_op(
            client, action, output, DirectoryStateBase.move_tree)
        _add_description(
            client,
            f"# add files of below move to directory state {output.item.spec}")
        _add_description(
            client, f"rsync -a --remove-source-files {source}/* {target}")

    def _directory_state_copy_file(
        self,
        client: BuildItem,
        action: dict,
        output: Optional[DirectoryStateBase],
    ) -> None:
        action = client.substitute(action)
        assert isinstance(output, DirectoryStateBase)
        source_file = action["source"]
        input_name = action.get("input-name", None)
        if input_name is not None:
            if input_name == ".":
                input_state = client
            else:
                input_state = client.input(input_name)
            assert isinstance(input_state, DirectoryStateBase)
            source_file = os.path.join(input_state.directory, source_file)
        target = action["target"]
        output.copy_file(source_file, target)
        _add_description(
            client,
            f"# add files of below copy to directory state {output.item.spec}")
        _add_description(
            client,
            f"cp {source_file} {os.path.join(output.directory, target)}")

    def _process(self, client: BuildItem, action: dict,
                 _output: Optional[DirectoryStateBase]) -> None:
        # pylint: disable=too-many-locals
        arg_is_enabled = functools.partial(is_enabled_with_ops,
                                           self._is_enabled_ops,
                                           client.enabled_set)
        action_2: dict = {}
        for key, value in action.items():
            if key == "command":
                action_2[key] = client.mapper.substitute_flexible_list(
                    value, arg_is_enabled)
            else:
                action_2[key] = client.mapper.substitute_data(value)
        run_subprocess_action(client.uid, action_2)
        cwd = action_2["working-directory"]
        stdout = action_2.get("stdout", None)
        redirect = "" if stdout is None else f" > {stdout}"
        if cwd != ".":
            cmd = f"cd {cwd} && "
        else:
            cmd = ""
        env_actions = action_2["env"]
        if env_actions:
            env = _Env()
            for env_action in env_actions:
                _ENV_ACTIONS[env_action["action"]](env, env_action)
            args = list(env.clear)
            args.extend(f"-u {name}" for name in env.var_unset)
            for name, values in sorted(env.path.items()):
                value = ":".join(
                    itertools.chain(values[0],
                                    [env.var_set.get(name, f"${{{name}}}")],
                                    values[1]))
                args.append(f"{name}={value}")
                env.var_set.pop(name, None)
            args.extend(f"{name}={value}"
                        for name, value in sorted(env.var_set.items()))
            cmd = f"{cmd}env {' '.join(args)} "
        _add_description(client,
                         f"{cmd}{' '.join(action_2['command'])}{redirect}")

    def _for_each(self, client: BuildItem, action: dict,
                  _output: Optional[DirectoryStateBase]) -> None:
        for link, _ in client.input_links("run-actions-member"):
            params = client.item["params"]
            client.item["params"] = copy.deepcopy(params)
            client.item["params"].update(link["params"])
            self._run_actions(client, action["member-actions"])
            client.item["params"] = params

    def _mkdir(self, client: BuildItem, action: dict,
               _output: Optional[DirectoryStateBase]) -> None:
        action = client.substitute(action)
        path = Path(action["path"])
        logging.info("%s: make directory: %s", client.uid, path)
        path.mkdir(parents=action["parents"], exist_ok=action["exist-ok"])
        _add_description(client, f"mkdir -p {path}")

    def _remove_path(self, client: BuildItem, path: Path) -> None:
        if path.is_dir():
            logging.info("%s: remove directory: %s", client.uid, path)
            path.rmdir()
            _add_description(client, f"rm -r {path}")
        else:
            logging.info("%s: unlink file: %s", client.uid, path)
            path.unlink()
            _add_description(client, f"rm {path}")

    def _remove(self, client: BuildItem, action: dict,
                _output: Optional[DirectoryStateBase]) -> None:
        action = client.substitute(action)
        path = Path(action["path"])
        if action["missing-ok"]:
            try:
                self._remove_path(client, path)
            except FileNotFoundError:
                pass
        else:
            self._remove_path(client, path)

    def _remove_empty_directories(
            self, client: BuildItem, action: dict,
            _output: Optional[DirectoryStateBase]) -> None:
        path = client.substitute(action["path"])
        remove_empty_directories(client.uid, path)
        _add_description(client,
                         f"find {path} -type d -empty -exec rmdir {{}} \\;")

    def _remove_glob(self, client: BuildItem, action: dict,
                     _output: Optional[DirectoryStateBase]) -> None:
        action = client.substitute(action)
        root = Path(action["path"])
        for pattern in action["patterns"]:
            logging.info(
                "%s: remove files and directories matching with '%s' in: %s",
                client.uid, pattern, root)
            for path in root.glob(pattern):
                if path.is_symlink() or not path.is_dir():
                    logging.info("%s: remove file: %s", client.uid, path)
                    path.unlink()
                    _add_description(client, f"rm {path}")
                elif action["remove-tree"]:
                    logging.info("%s: remove directory tree: %s", client.uid,
                                 path)
                    shutil.rmtree(path)
                    _add_description(client, f"rm -r {path}")
                else:
                    logging.info("%s: remove directory: %s", client.uid, path)
                    path.rmdir()
                    _add_description(client, f"rm -r {path}")

    def _remove_tree(self, client: BuildItem, action: dict,
                     _output: Optional[DirectoryStateBase]) -> None:
        action = client.substitute(action)
        path = action["path"]
        logging.info("%s: remove directory tree: %s", client.uid, path)
        if action["missing-ok"]:
            try:
                shutil.rmtree(path)
            except FileNotFoundError:
                pass
            _add_description(client, f"rm -rf {path}")
        else:
            shutil.rmtree(path)
            _add_description(client, f"rm -r {path}")

    def _touch(self, client: BuildItem, action: dict,
               _output: Optional[DirectoryStateBase]) -> None:
        action = client.substitute(action)
        path = Path(action["path"])
        logging.info("%s: touch file: %s", client.uid, path)
        path.touch(exist_ok=action["exist-ok"])
        _add_description(client, f"touch {path}")

    _ACTIONS = {
        "copy": _copy,
        "copy-and-substitute": _copy_and_substitute,
        "create-ini-file": _create_ini_file,
        "create-kconfig-file": _create_kconfig_file,
        "directory-state-add-files": _directory_state_add_files,
        "directory-state-add-tarfile-members":
        _directory_state_add_tarfile_members,
        "directory-state-add-tree": _directory_state_add_tree,
        "directory-state-clear": _directory_state_clear,
        "directory-state-copy-file": _directory_state_copy_file,
        "directory-state-copy-tree": _directory_state_copy_tree,
        "directory-state-discard": _directory_state_discard,
        "directory-state-discard-and-clear":
        _directory_state_discard_and_clear,
        "directory-state-discard-excludes": _directory_state_discard_excludes,
        "directory-state-move-tree": _directory_state_move_tree,
        "for-each": _for_each,
        "mkdir": _mkdir,
        "remove": _remove,
        "remove-empty-directories": _remove_empty_directories,
        "remove-glob": _remove_glob,
        "remove-tree": _remove_tree,
        "subprocess": _process,
        "touch": _touch
    }


class RunActions(BuildItem):
    """ Runs actions. """

    def __init__(self,
                 director: PackageBuildDirector,
                 item: Item,
                 mapper: Optional[BuildItemMapper] = None) -> None:
        super().__init__(director, item, mapper)
        self._run_actions_provider = RunActionsProvider(self)

    def run(self) -> None:
        self._run_actions_provider.run(self.item["actions"])
