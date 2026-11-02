# SPDX-License-Identifier: BSD-2-Clause
""" This module provides the agent test runner.  """

# Copyright (C) 2024, 2026 embedded brains GmbH & Co. KG
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
from pathlib import Path
import subprocess
import tempfile
import time
from typing import Any

import grpc  # type: ignore

from specitems import is_enabled, Item, ItemGetValueContext

# pylint: disable=no-name-in-module
from spectestrunner import (GRPCDescribeTargetRequest, GRPCRunImageRequest,
                            GRPCServiceStub)  # type: ignore
from spectestrunner import gitclient, gitproto, gitwire, image, steps

from .pkgitems import PackageBuildDirector
from .testrunner import RunnerExecutable, RunnerReport, TestRunner
from .util import now_utc

_POLL_INTERVAL_IN_SECONDS = 10.0

_GIT_ERRORS = (gitclient.RequestGone, gitclient.Rejected,
               gitclient.WaitTimeout, gitproto.ProtocolError, gitwire.GitError)

_TRANSPORTS = ("git", "grpc")


def get_symbols(exe_path: str, nm_path: str) -> dict[str, list[int]]:
    """ Return the symbols of the executable using the nm tool. """
    result = subprocess.run([nm_path, exe_path],
                            check=True,
                            capture_output=True,
                            text=True)
    symbols: dict[str, list[int]] = {}
    for line in result.stdout.split("\n"):
        try:
            address, _, name = line.split(None, 2)
        except ValueError:
            pass
        else:
            try:
                symbols.setdefault(name, []).append(int(address, 16))
            except ValueError:
                pass
    return symbols


def _get_git_report_output(result: dict[str, Any]) -> list[str]:
    output = result.get("output")
    if output is None:
        return []
    return [
        line.removesuffix("\r")
        for line in output.decode("latin-1").split("\n")
    ]


class AgentTestRunner(TestRunner):
    """
    Runs the tests using an agent of a test server through the first
    transport which the enabled set enables.
    """

    def __init__(self, director: PackageBuildDirector, item: Item):
        super().__init__(director, item)
        self.mapper.add_get_value(f"{self.item.type}:/target-name",
                                  self._get_target_name)

    def _get_optional_value(self, key: str) -> str:
        for optional_value in self[key]:
            if is_enabled(self.enabled_set, optional_value["enabled-by"]):
                return optional_value["value"]
        raise ValueError(f"{self.uid}: there is no value for attribute {key} "
                         f"and enabled set {sorted(self.enabled_set)}")

    def _get_target_name(self, _ctx: ItemGetValueContext) -> str:
        return self._get_optional_value("target")

    def _get_transport(self) -> dict[str, Any]:
        for transport in self["transport"]:
            if is_enabled(self.enabled_set, transport["enabled-by"]):
                if transport["type"] not in _TRANSPORTS:
                    raise ValueError(f"{self.uid}: the transport type "
                                     f"'{transport['type']}' is not one of "
                                     f"{', '.join(_TRANSPORTS)}")
                return transport
        raise ValueError(f"{self.uid}: there is no transport for enabled "
                         f"set {sorted(self.enabled_set)}")

    def describe(self) -> str:
        transport = self._get_transport()
        target_id = self._get_optional_value("target")
        if transport["type"] == "git":
            return self._describe_git(transport, target_id)
        return self._describe_grpc(transport, target_id)

    def run_tests(self,
                  executables: list[RunnerExecutable]) -> list[RunnerReport]:
        transport = self._get_transport()
        if transport["type"] == "git":
            return self._run_tests_git(transport, executables)
        return self._run_tests_grpc(transport, executables)

    def _get_executable_data(self, executable: RunnerExecutable) -> bytes:
        original = Path(executable.path)
        strip = self["strip"]
        if strip is None:
            return original.read_bytes()
        with tempfile.TemporaryDirectory() as directory:
            stripped = Path(directory) / "stripped"
            subprocess.run(
                [self["strip"], "-g", "-o",
                 str(stripped),
                 str(original)],
                check=True)
            return stripped.read_bytes()

    def _get_breakpoints(self, executable: RunnerExecutable) -> list[int]:
        return get_symbols(executable.path,
                           self["nm"])[self._get_optional_value("reset")]

    def _describe_grpc(self, transport: dict[str, Any], target_id: str) -> str:
        server_address = transport["server-address"]
        with grpc.insecure_channel(server_address) as channel:
            stub = GRPCServiceStub(channel)
            try:
                response = stub.request_describe_target(
                    GRPCDescribeTargetRequest(target_id=target_id))
                logging.debug("%s: received target description for: %s",
                              self.uid, target_id)
            except grpc.RpcError as err:
                return (
                    f"Requesting the target description of ``{target_id}`` "
                    f"from the test server at {server_address} "
                    f"failed: {err}.")
            return response.description

    def _run_tests_grpc(
            self, transport: dict[str, Any],
            executables: list[RunnerExecutable]) -> list[RunnerReport]:
        reports: list[RunnerReport] = []
        target_id = self._get_optional_value("target")
        with grpc.insecure_channel(transport["server-address"]) as channel:
            stub = GRPCServiceStub(channel)
            for executable in executables:
                start_time = now_utc()
                monotonic_begin = time.monotonic()
                logging.debug("%s: send request for: %s", self.uid,
                              executable.path)
                breakpoints = self._get_breakpoints(executable)
                report: RunnerReport = {
                    "command-line": [],
                    "executable": executable.path,
                    "executable-sha512": executable.digest,
                    "start-time": start_time
                }
                try:
                    response = stub.request_run_image(
                        GRPCRunImageRequest(
                            target_id=target_id,
                            breakpoints=breakpoints,
                            path=executable.path,
                            digest=executable.digest,
                            data=self._get_executable_data(executable),
                            execution_timeout_in_seconds=executable.timeout))
                    logging.debug("%s: received response for: %s", self.uid,
                                  executable.path)
                except grpc.RpcError as err:
                    report["output"] = []
                    report["error"] = str(err)
                else:
                    report["output"] = [
                        line.removesuffix("\r") for line in
                        response.output.decode("latin-1").split("\n")
                    ]
                    if response.status != "success":
                        report["error"] = response.status
                    report["load-duration-in-seconds"] = \
                        response.load_duration_in_seconds
                    report["execution-duration-in-seconds"] = \
                        response.execution_duration_in_seconds
                report["duration"] = time.monotonic() - monotonic_begin
                reports.append(report)
        return reports

    def _git_client(self, repo: gitwire.Repository,
                    transport: dict[str, Any]) -> gitclient.Client:
        return gitclient.Client(repo, transport["remote"],
                                gitproto.get_default_submitter(),
                                transport["wait-timeout-in-seconds"],
                                _POLL_INTERVAL_IN_SECONDS)

    def _describe_git(self, transport: dict[str, Any], target_id: str) -> str:
        try:
            with gitclient.repository() as repo:
                description = self._git_client(
                    repo, transport).describe_target(target_id)
        except _GIT_ERRORS as err:
            return (f"Requesting the target description of ``{target_id}`` "
                    f"through the Git bridge at {transport['remote']} "
                    f"failed: {err}.")
        logging.debug("%s: received target description for: %s", self.uid,
                      target_id)
        return description

    def _run_executable_git(self, client: gitclient.Client, target_id: str,
                            executable: RunnerExecutable) -> RunnerReport:
        start_time = now_utc()
        monotonic_begin = time.monotonic()
        logging.debug("%s: send request for: %s", self.uid, executable.path)
        data = self._get_executable_data(executable)
        step = {
            "kind": steps.STEP_IMAGE,
            "path": executable.path,
            "digest": image.get_digest(data),
            "breakpoints": self._get_breakpoints(executable)
        }
        report: RunnerReport = {
            "command-line": [],
            "executable": executable.path,
            "executable-sha512": executable.digest,
            "start-time": start_time
        }
        try:
            result = client.run_steps(target_id, executable.timeout, [step],
                                      {0: data})[0]
            logging.debug("%s: received response for: %s", self.uid,
                          executable.path)
        except _GIT_ERRORS as err:
            report["output"] = []
            report["error"] = str(err)
        else:
            report["output"] = _get_git_report_output(result)
            if result["status"] != "success":
                report["error"] = result["status"]
            for key in ("load", "execution"):
                value = result.get(f"{key}_duration_in_seconds")
                if value is not None:
                    report[f"{key}-duration-in-seconds"] = value
        report["duration"] = time.monotonic() - monotonic_begin
        return report

    def _run_tests_git(
            self, transport: dict[str, Any],
            executables: list[RunnerExecutable]) -> list[RunnerReport]:
        target_id = self._get_optional_value("target")
        with gitclient.repository() as repo:
            client = self._git_client(repo, transport)
            return [
                self._run_executable_git(client, target_id, executable)
                for executable in executables
            ]
