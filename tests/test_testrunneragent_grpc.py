# SPDX-License-Identifier: BSD-2-Clause
""" Tests the agent test runner through gRPC. """

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

import dataclasses
import grpc
from pathlib import Path
import pytest

from specitems import ItemSelection

import specmake
from specmake import RunnerExecutable, AgentTestRunner

from .util import create_package


@dataclasses.dataclass
class _Result:
    stdout = """01234567 T bsp_reset
foobar
not-a-hex-number T bsp_reset
"""


def _subprocess_run(args, check=True, capture_output=False, text=False):
    if args[0].endswith("strip"):
        stripped = Path(args[3])
        assert stripped.name.endswith("stripped")
        stripped.write_bytes(b"")
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

    counter = 0

    def __init__(self, channel):
        pass

    def request_describe_target(self, request):
        counter = _GRPCServiceStub.counter + 1
        _GRPCServiceStub.counter = counter
        if counter % 2 == 0:
            return _Description(str(counter))
        raise grpc.RpcError("the error")

    def request_run_image(self, request):
        counter = _GRPCServiceStub.counter + 1
        _GRPCServiceStub.counter = counter
        if counter % 3 == 0:
            return _RunResult(b"", "success", 1.0, 2.0)
        if counter % 3 == 1:
            return _RunResult(b"", "error", 3.0, 4.0)
        if counter % 3 != 0:
            raise grpc.RpcError("the error")


def test_testrunnergrpc(caplog, tmp_path, monkeypatch):
    _GRPCServiceStub.counter = 0
    monkeypatch.setattr(specmake.testrunneragent.subprocess, "run",
                        _subprocess_run)
    monkeypatch.setattr(specmake.testrunneragent, "GRPCServiceStub",
                        _GRPCServiceStub)
    package = create_package(caplog, tmp_path, Path("spec-packagebuild"),
                             ["test-runner-grpc"])
    test_logs_uid = "/pkg/test-logs/test-runner-grpc"
    director = package.director
    director.build_package(only=[test_logs_uid])

    runner = director["/pkg/test-runner/grpc"]
    assert isinstance(runner, AgentTestRunner)

    assert runner.substitute("${.:/target-name}") == "the/target"

    item_cache = runner.item.cache
    with item_cache.selection(ItemSelection(item_cache, ("no-target", ))):
        with pytest.raises(ValueError):
            runner.substitute("${.:/target-name}")

    assert runner.describe() == (
        "Requesting the target description of "
        "``the/target`` from the test server at iris:50051 failed: the error.")
    assert runner.describe() == "10"

    runner.item["strip"] = None
    director.build_package(only=[test_logs_uid], force=[test_logs_uid])
