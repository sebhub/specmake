# SPDX-License-Identifier: BSD-2-Clause
""" Tests for the perfimages module. """

# Copyright (C) 2025 embedded brains GmbH & Co. KG
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

import multiprocessing
from pathlib import Path

import pytest

from .util import create_package, get_and_clear_log


def test_perfimages(caplog, tmpdir):
    tmp_dir = Path(tmpdir)
    package = create_package(caplog, tmp_dir, Path("spec-packagebuild"),
                             ["aggregate-test-results", "performance-images"])
    uid = "/pkg/deployment/perf-images"
    director = package.director
    director.build_package(only=[uid])
    assert list(director[uid].files()) == [
        f"{tmpdir}/pkg/perf-images/a-build-config-key-rtems-req-perf-DirtyCache.pdf",
        f"{tmpdir}/pkg/perf-images/a-build-config-key-rtems-req-perf-DirtyCache.png",
        f"{tmpdir}/pkg/perf-images/a-build-config-key-rtems-req-perf-FullCache.pdf",
        f"{tmpdir}/pkg/perf-images/a-build-config-key-rtems-req-perf-FullCache.png",
        f"{tmpdir}/pkg/perf-images/a-build-config-key-rtems-req-perf-HotCache.pdf",
        f"{tmpdir}/pkg/perf-images/a-build-config-key-rtems-req-perf-HotCache.png",
        f"{tmpdir}/pkg/perf-images/a-build-config-key-rtems-req-perf-Load-1.pdf",
        f"{tmpdir}/pkg/perf-images/a-build-config-key-rtems-req-perf-Load-1.png",
        f"{tmpdir}/pkg/perf-images/a-build-config-key-rtems-req-perf.pdf",
        f"{tmpdir}/pkg/perf-images/a-build-config-key-rtems-req-perf.png"
    ]
    for path in director[uid].files():
        if path.endswith(".pdf"):
            assert b"CreationDate" not in Path(path).read_bytes()


class _DeadProcess:
    """ Image worker which dies right away. """

    exitcode = 1

    def __init__(self, target, args, daemon):
        pass

    def start(self):
        pass

    def join(self):
        pass


def test_perfimages_worker_died(caplog, tmpdir, monkeypatch):
    tmp_dir = Path(tmpdir)
    package = create_package(caplog, tmp_dir, Path("spec-packagebuild"),
                             ["aggregate-test-results", "performance-images"])
    uid = "/pkg/deployment/perf-images"
    monkeypatch.setattr(multiprocessing, "Process", _DeadProcess)
    with pytest.raises(RuntimeError, match="image workers failed"):
        package.director.build_package(only=[uid])
