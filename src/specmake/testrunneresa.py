# SPDX-License-Identifier: BSD-2-Clause
""" Provides a test runner using the ESA run tests service.  """

# Copyright (C) 2023, 2026 embedded brains GmbH & Co. KG
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

import bz2
import datetime
import logging
import math
from pathlib import Path
import socket
import time
import yaml

from specware import run_command

from .directorystate import RepositoryState
from .testrunner import Executable, Report, TestRunner


def _bz2_file(executable: Executable) -> str:
    return f"{Path(executable.path).name}.bz2"


class ESATestRunner(TestRunner):
    """
    Runs the tests using the ESA run tests service.

    The interface to the service is a Git repository located at:

    https://gitrepos.estec.esa.int/ttsiodras/RemoteExecutionOfTestBinaries
    """

    def describe(self) -> str:
        return f"""This test procedure requests the `ESA run tests service
<https://gitlab.esa.int/flight-software/fsw-boards-server/\
FSWBoardsServerRemoteExecution_Binaries.git>`__
to run the test programs for the ``{self.component['bsp'].upper()}`` target
board."""

    def _create_branch(self, working_directory: Path,
                       repository: RepositoryState) -> str:
        """
        Create a unique branch to carry out the request.

        Returns the branch name.
        """
        hostname = socket.gethostname()
        now = datetime.datetime.utcnow().strftime('%Y-%m-%d-%H-%M-%S-%f')
        branch = f"pkg-{self.component['name']}-{hostname}-{now}"
        status = run_command(
            ["git", "checkout", "-B", branch, repository["commit"]],
            cwd=working_directory)
        assert status == 0
        return branch

    def _copy_and_prepare_executables(self, working_directory: Path,
                                      executables: list[Executable]) -> None:
        """
        Copy, strip, and compress (bzip2) the executables.

        The files are placed into the working directory.
        """
        strip = self["strip-program-path"]
        for executable in executables:
            source = Path(executable.path)
            stripped = working_directory / source.name
            status = run_command(
                [strip, str(source), "-o",
                 str(stripped)],
                cwd=working_directory)
            assert status == 0
            with stripped.open("rb") as src:
                data = bz2.compress(src.read())
            stripped.unlink()
            compressed = working_directory / _bz2_file(executable)
            with compressed.open("wb") as dst:
                dst.write(data)

    def _write_request_file(
            self, working_directory: Path,
            remaining: list[Executable]) -> tuple[str, int, list[Executable]]:
        """
        Write the request file to run the prepared remaining executables.

        Returns the request file name and the overall timeout in seconds.
        """
        request_file = working_directory / "request.yaml"
        overall_timeout = 0
        todo: list[Executable] = []
        max_overall_timeout = self["max-overall-timeout-in-seconds"]
        timeout_scaler = self["timeout-scaling-factor"]
        with request_file.open("w", encoding="utf-8") as dst:
            jobs: list[dict[str, dict[str, int]]] = []
            max_timeout = 0
            while True:
                try:
                    executable = remaining.pop(0)
                except IndexError:
                    break
                timeout = int(math.ceil(executable.timeout * timeout_scaler))
                if overall_timeout == 0:
                    # Ignore the maximum overall timeout for the first
                    # executable
                    overall_timeout = timeout
                else:
                    new_overall_timeout = overall_timeout + timeout
                    if new_overall_timeout > max_overall_timeout:
                        # Move executable to next request
                        remaining.insert(0, executable)
                        break
                    overall_timeout = new_overall_timeout
                max_timeout = max(max_timeout, timeout)
                todo.append(executable)
                jobs.append(
                    {_bz2_file(executable): {
                         "timeout_in_seconds": timeout
                     }})
            request = {
                "version":
                1,
                "target_board":
                self["bsp-to-target-board"][self.substitute(
                    "${.:/component/arch}/${.:/component/bsp}")],
                "timeout_in_seconds":
                max_timeout,
                "jobs":
                jobs
            }
            dst.write(
                yaml.dump(request,
                          default_flow_style=False,
                          allow_unicode=True))
        return request_file.name, overall_timeout, todo

    def _wait_for_update(self, working_directory: Path, branch: str,
                         overall_timeout: int) -> None:
        """
        Wait for a branch update on the remote repository.

        The time to wait is limited by the maximum request delay and the
        overall timeouts of the executables.
        """
        max_duration = float(self["max-request-delay-in-seconds"] +
                             overall_timeout)
        begin = time.monotonic()
        while time.monotonic() - begin < max_duration:
            time.sleep(self["git-fetch-polling-interval-in-seconds"])
            status = run_command(["git", "fetch", "origin", branch],
                                 cwd=working_directory)
            if status != 0:
                logging.warning("%s: fetch from remote repository failed",
                                self.uid)
            stdout: list[str] = []
            status = run_command(
                ["git", "log", f"HEAD..origin/{branch}", "--oneline"],
                stdout=stdout,
                cwd=working_directory)
            assert status == 0
            if stdout:
                return

    def _add_reports(self, working_directory: Path,
                     executables: list[Executable],
                     reports: list[Report]) -> None:
        """ Add the reports from the result text file of each executable.  """
        for executable in executables:
            result_file = f"{Path(executable.path).name}.bz2.result.txt"
            result_path = working_directory / result_file
            report: Report = {
                "executable": executable.path,
                "executable-sha512": executable.digest,
                "command-line": []
            }
            try:
                with result_path.open("r", encoding="utf-8") as src:
                    output = src.read().rstrip().replace("\r\n",
                                                         "\n").split("\n")
            except FileNotFoundError:
                continue
            report["output"] = output
            reports.append(report)

    def run_tests(self, executables: list[Executable]) -> list[Report]:
        reports: list[Report] = []
        repository = self.director[self.item.parent(
            "weak-package-build-dependency").uid]
        assert isinstance(repository, RepositoryState)
        working_directory = Path(repository.directory)
        self._copy_and_prepare_executables(working_directory, executables)
        branch = self._create_branch(working_directory, repository)
        remaining = executables.copy()
        counter = 0
        while remaining:
            request_file, overall_timeout, todo = self._write_request_file(
                working_directory, remaining)
            files = [_bz2_file(executable) for executable in todo]
            status = run_command(["git", "add"] + files + [request_file],
                                 cwd=working_directory)
            assert status == 0
            status = run_command(["git", "commit", "-m", f"Request {counter}"],
                                 cwd=working_directory)
            assert status == 0
            status = run_command(["git", "push", "origin", branch],
                                 cwd=working_directory)
            assert status == 0
            self._wait_for_update(working_directory, branch, overall_timeout)
            status = run_command(
                ["git", "reset", "--hard", f"origin/{branch}"],
                cwd=working_directory)
            assert status == 0
            self._add_reports(working_directory, todo, reports)
            counter += 1
        if self["delete-remote-branch"]:
            status = run_command(["git", "push", "-d", "origin", branch],
                                 cwd=working_directory)
            assert status == 0
        status = run_command(["git", "checkout", repository["branch"]],
                             cwd=working_directory)
        assert status == 0
        status = run_command(["git", "branch", "-D", branch],
                             cwd=working_directory)
        assert status == 0
        return reports
