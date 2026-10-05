# SPDX-License-Identifier: BSD-2-Clause
""" Tests for the rtemstestsimages module. """

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

from pathlib import Path

from .util import create_package


def test_rtemstestsimages(caplog, tmpdir):
    tmp_dir = Path(tmpdir)
    package = create_package(caplog, tmp_dir, Path("spec-packagebuild"),
                             ["aggregate-test-results", "rtems-tests-images"])
    uid = "/pkg/deployment/rtems-tests-images"
    director = package.director
    director.build_package(only=[uid])
    assert list(director[uid].files()) == [
        f"{tmpdir}/pkg/rtems-tests-images/a-build-config-key-build-testsuites-smptests-smplock01-fair.pdf",
        f"{tmpdir}/pkg/rtems-tests-images/a-build-config-key-build-testsuites-smptests-smplock01-fair.png",
        f"{tmpdir}/pkg/rtems-tests-images/a-build-config-key-build-testsuites-smptests-smplock01-perf.pdf",
        f"{tmpdir}/pkg/rtems-tests-images/a-build-config-key-build-testsuites-smptests-smplock01-perf.png",
        f"{tmpdir}/pkg/rtems-tests-images/a-build-config-key-build-testsuites-smptests-smpopenmp01.pdf",
        f"{tmpdir}/pkg/rtems-tests-images/a-build-config-key-build-testsuites-smptests-smpopenmp01.png",
        f"{tmpdir}/pkg/rtems-tests-images/a-build-config-key-build-testsuites-sptests-sptimecounter02.pdf",
        f"{tmpdir}/pkg/rtems-tests-images/a-build-config-key-build-testsuites-sptests-sptimecounter02.png",
        f"{tmpdir}/pkg/rtems-tests-images/a-build-config-key-build-testsuites-tmtests-tmcontext01.pdf",
        f"{tmpdir}/pkg/rtems-tests-images/a-build-config-key-build-testsuites-tmtests-tmcontext01.png",
        f"{tmpdir}/pkg/rtems-tests-images/a-build-config-key-build-testsuites-tmtests-tmfine01.pdf",
        f"{tmpdir}/pkg/rtems-tests-images/a-build-config-key-build-testsuites-tmtests-tmfine01.png",
        f"{tmpdir}/pkg/rtems-tests-images/a-build-config-key-build-testsuites-tmtests-tmtimer01.pdf",
        f"{tmpdir}/pkg/rtems-tests-images/a-build-config-key-build-testsuites-tmtests-tmtimer01.png"
    ]
    for path in director[uid].files():
        if path.endswith(".pdf"):
            assert b"CreationDate" not in Path(path).read_bytes()
