# SPDX-License-Identifier: BSD-2-Clause
""" Generates a command to run executables. """

# Copyright (C) 2024, 2025 embedded brains GmbH & Co. KG
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

import inspect
import logging
import os
import stat
import subprocess

from .directorystate import DirectoryState
from .elf import ELF_SCRIPT_FUNCTIONS
from .executablerecord import REUSE_SCRIPT_FUNCTIONS
from .pkgitems import Redirection
from .testrunner import TestLog, TestRunner

_COMMAND_HEAD = """#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-2-Clause
\"\"\" Runs the executable on the target. \"\"\"

# Copyright (C) 2024 embedded brains GmbH & Co. KG
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

import argparse
import base64
import json
import hashlib
import os
import struct
import subprocess
import sys
"""

_COMMAND_TAIL = """def _hash_file(path: str) -> str:
    file_hash = hashlib.sha512()
    if os.path.islink(path):
        file_hash.update(os.readlink(path).encode("utf-8"))
    else:
        buf = bytearray(65536)
        memview = memoryview(buf)
        with open(path, "rb", buffering=0) as src:
            for size in iter(lambda: src.readinto(memview), 0):  # type: ignore
                file_hash.update(memview[:size])
    return base64.urlsafe_b64encode(file_hash.digest()).decode("ascii")


def _loadable_sha512(path: str) -> str | None:
    if os.path.islink(path):
        return None
    with open(path, "rb") as src:
        return elf_loadable_sha512(src.read())


def main(script: str, argv: list[str]) -> int:
    \"\"\" Runs the executables on the target. \"\"\"
    package_directory = os.path.normpath(
        os.path.join(os.path.dirname(__file__), ".."))
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--runner-type",
        default="simulator",
        type=str,
        help=f"the type of the executable runner (default: simulator)")
    parser.add_argument(
        "--package-directory",
        default=package_directory,
        type=str,
        help=f"the package directory (default: {package_directory})")
    parser.add_argument("--do-not-use-test-logs",
                        action="store_true",
                        help=f"do not use the test logs to look up a report")
    parser.add_argument("target",
                        metavar="TARGET",
                        nargs=1,
                        help="the target on which the executables should run; "
                        "the target is the name of an installed BSP "
                        f"(one of {list(_TARGETS_BY_BSP.keys())}) "
                        f"or a runner (one of {list(_COMMANDS.keys())})")
    parser.add_argument("executables",
                        metavar="EXECUTABLES",
                        nargs="+",
                        help="the executable files to run")
    args = parser.parse_args(argv)
    target = args.target[0]
    target = _TARGETS_BY_BSP.get(target, target)
    try:
        command = _COMMANDS[target]
    except KeyError:
        command = _COMMANDS.get(f"{target}/{args.runner_type}", None)
    reports: list = []
    if not args.do_not_use_test_logs:
        for test_log_file in _TEST_LOGS_BY_TARGET.get(target, []):
            path = test_log_file.replace("${package-directory}",
                                         args.package_directory)
            try:
                with open(path, "r", encoding="utf-8") as file:
                    reports.extend(json.load(file)["reports"])
            except FileNotFoundError:
                pass
    index = index_reports(reports)
    for executable in args.executables:
        try:
            loadable_sha512 = _loadable_sha512(executable)
        except ValueError as err:
            print(f"{script}: {executable}: {err}", file=sys.stderr)
            return 1
        report = find_report(index, _hash_file(executable), loadable_sha512)
        if report is None:
            if command is None:
                print(
                    f"{script}: in your environment, "
                    "there is no service available to run the executable "
                    f"on the target '{target}'; "
                    f"available runner targets are: {list(_COMMANDS.keys())} ",
                    file=sys.stderr)
                return 1
            command = [
                arg.replace("${executable}",
                            executable).replace("${package-directory}",
                                                args.package_directory)
                for arg in command
            ]
            subprocess.run(command, check=True, stdin=subprocess.DEVNULL)
        else:
            print("\\n".join(report["output"]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[0], sys.argv[1:]))
"""


class RunExecutableCommand(DirectoryState):
    """ Generates a command to run executables. """

    def run(self) -> None:
        self.set_files([self["file-name"]])
        file_path = self.file
        logging.info("%s: create run executable command: %s", self.uid,
                     file_path)
        target_by_bsp: dict[str, str] = {}
        test_logs_by_target: dict[str, list[str]] = {}
        deployment_directory = self.substitute(
            "${.:/component/deployment-directory}")
        for test_log in self.inputs("test-log"):
            assert isinstance(test_log, TestLog)
            with self.component_scope(test_log.component):
                target = self._target()
                test_logs_by_target.setdefault(target, []).append(
                    test_log.file.replace(deployment_directory,
                                          "${package-directory}"))
                target_by_bsp[self.substitute(
                    "${.:/component/arch}-${.:/component/bsp}"
                    "${.:/component/config:dash}${.:/component/bsp-extra:dash}"
                )] = target
                target_by_bsp[self.substitute(
                    "${.:/component/arch}-${.:/component/bsp}"
                    "${.:/component/config:dash}"
                    "${.:/component/bsp-qual-only:dash}")] = target
        commands_by_runner: dict[str, list[str]] = {}
        for redirection in self.inputs("test-runner"):
            assert isinstance(redirection, Redirection)
            with self.component_scope(redirection.component):
                test_runner = redirection.target()
                assert isinstance(test_runner, TestRunner)
                with test_runner.component_scope(redirection.component):
                    command = test_runner.get_run_command("$${executable}")
                    if command is None:
                        continue
                    command = [
                        arg.replace(deployment_directory,
                                    "${package-directory}") for arg in command
                    ]
                    runner_type = redirection["params"]["test-runner-type"]
                    runner = f"{self._target()}/{runner_type}"
                    assert runner not in commands_by_runner
                    commands_by_runner[runner] = command
                    logging.info("%s: add command %s for runner %s", self.uid,
                                 command, runner)
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as file:
            file.write(_COMMAND_HEAD)
            for function in ELF_SCRIPT_FUNCTIONS + REUSE_SCRIPT_FUNCTIONS:
                file.write(f"\n\n{inspect.getsource(function)}")
            file.write("\n\n")
            file.write(f"""_TARGETS_BY_BSP: dict[str, str] = {target_by_bsp}

_TEST_LOGS_BY_TARGET: dict[str, str] = {test_logs_by_target}

_COMMANDS: dict[str, list[str]] = {commands_by_runner}
""")
            file.write(_COMMAND_TAIL)
        os.chmod(file_path, stat.S_IRWXU | stat.S_IRWXG | stat.S_IRWXO)
        subprocess.run(["yapf", "-i", file_path], check=True)

        self.description.add(f"""Produce the test run script
file {self.description.path(file_path)}.""")

    def _target(self) -> str:
        return self.substitute("${.:/component/arch}/${.:/component/bsp}"
                               "${.:/component/config:slash}")
