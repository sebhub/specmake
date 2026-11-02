# SPDX-License-Identifier: BSD-2-Clause
""" Tests for the testrunneragent module. """

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
import json
from pathlib import Path

import pytest

import specmake
from specmake import AgentTestRunner

from .util import create_package

_OUTPUT = b"*** BEGIN OF TEST A ***\r\n*** END OF TEST A ***\r\n"


@dataclasses.dataclass
class _Result:
    stdout = "01234567 T bsp_reset\n"


def _subprocess_run(args, check=True, capture_output=False, text=False):
    if args[0].endswith("strip"):
        Path(args[3]).write_bytes(b"stripped")
    return _Result()


@dataclasses.dataclass
class _Description:
    description: str


@dataclasses.dataclass
class _RunResult:
    output: bytes
    status: str
    load_duration_in_seconds: float
    execution_duration_in_seconds: float


class _GRPCServiceStub:

    def __init__(self, channel):
        self.channel = channel

    def request_describe_target(self, request):
        return _Description(f"grpc {self.channel}")

    def request_run_image(self, request):
        return _RunResult(_OUTPUT, "success", 1.0, 2.0)


class _Client:

    def __init__(self, repo, remote, submitter, wait_timeout, poll_interval):
        # pylint: disable=too-many-arguments
        # pylint: disable=too-many-positional-arguments
        self.remote = remote
        self.wait_timeout = wait_timeout

    def describe_target(self, target):
        return f"git {self.remote} {self.wait_timeout}"

    def run_steps(self, target, timeout, request_steps, data):
        return [{"status": "success", "output": _OUTPUT}]


@contextlib.contextmanager
def _insecure_channel(server_address):
    yield server_address


def test_testrunneragent(caplog, tmp_path, monkeypatch):
    monkeypatch.setattr(specmake.testrunneragent.subprocess, "run",
                        _subprocess_run)
    monkeypatch.setattr(specmake.testrunneragent.grpc, "insecure_channel",
                        _insecure_channel)
    monkeypatch.setattr(specmake.testrunneragent, "GRPCServiceStub",
                        _GRPCServiceStub)
    monkeypatch.setattr(specmake.testrunneragent.gitclient, "Client", _Client)
    log_uid = "/pkg/test-logs/test-runner-agent"
    runner_hashes = []
    for transport, description in (("grpc", "grpc iris:50051"),
                                   ("git", "git /iris.git 60.0")):
        enabled_set = ["test-runner-agent", f"test-runner-agent-{transport}"]
        package = create_package(caplog, tmp_path / transport,
                                 Path("spec-packagebuild"), enabled_set)
        director = package.director
        director.build_package(only=[log_uid])
        with open(director[log_uid].file, "r", encoding="utf-8") as src:
            log_data = json.load(src)
        assert log_data["test-runner-description"] == description
        assert all("error" not in report for report in log_data["reports"])
        runner_hashes.append(log_data["test-runner-hash"])
        runner = director["/pkg/test-runner/agent"]
        assert isinstance(runner, AgentTestRunner)

    # The transport does not contribute to the runner hash
    assert runner_hashes[0] == runner_hashes[1]

    runner.item["transport"] = [{"enabled-by": True, "type": "foo"}]
    with pytest.raises(ValueError,
                       match="the transport type 'foo' is not one of "
                       "git, grpc"):
        runner.describe()
    runner.item["transport"] = []
    with pytest.raises(ValueError,
                       match="there is no transport for enabled "
                       "set"):
        runner.describe()


def test_testrunneragent_reuse(caplog, tmp_path, monkeypatch):
    requests: list[str] = []

    class _CountingClient(_Client):

        def run_steps(self, target, timeout, request_steps, data):
            requests.append("git")
            return super().run_steps(target, timeout, request_steps, data)

    class _CountingStub(_GRPCServiceStub):

        def request_describe_target(self, request):
            requests.append("grpc describe")
            return super().request_describe_target(request)

        def request_run_image(self, request):
            requests.append("grpc")
            return super().request_run_image(request)

    monkeypatch.setattr(specmake.testrunneragent.subprocess, "run",
                        _subprocess_run)
    monkeypatch.setattr(specmake.testrunneragent.grpc, "insecure_channel",
                        _insecure_channel)
    monkeypatch.setattr(specmake.testrunneragent, "GRPCServiceStub",
                        _CountingStub)
    monkeypatch.setattr(specmake.testrunneragent.gitclient, "Client",
                        _CountingClient)
    log_uid = "/pkg/test-logs/test-runner-agent"

    # Run the tests through the Git bridge
    package = create_package(caplog, tmp_path, Path("spec-packagebuild"),
                             ["test-runner-agent", "test-runner-agent-git"])
    package.director.build_package(only=[log_uid])
    log_file = Path(package.director[log_uid].file)
    git_log = json.loads(log_file.read_text(encoding="utf-8"))
    assert git_log["reports"]
    assert set(requests) == {"git"}

    # Build the same deployment with gRPC and reuse the reports as is
    requests.clear()
    caplog.clear()
    package = create_package(caplog, tmp_path, Path("spec-packagebuild"),
                             ["test-runner-agent", "test-runner-agent-grpc"])
    package.director.build_package(only=[log_uid], force=[log_uid])
    assert str(log_file) == package.director[log_uid].file
    grpc_log = json.loads(log_file.read_text(encoding="utf-8"))
    assert not requests
    assert "use previous report for" in caplog.text
    assert grpc_log["test-runner-hash"] == git_log["test-runner-hash"]
    assert grpc_log["test-runner-description"] == "git /iris.git 60.0"
    assert grpc_log["reports"] == git_log["reports"]
    assert grpc_log["start-time"] != git_log["start-time"]
