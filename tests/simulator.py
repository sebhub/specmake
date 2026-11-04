#!/usr/bin/env python
# SPDX-License-Identifier: BSD-2-Clause
""" Simulates the test output of a test executable. """

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

import base64
import hashlib
import os
import sys
import time

_HEAD = ["Fake simulator", ""]

_INFO = [
    "*** TEST VERSION: 6.0.0.aaaa",
    "*** TEST STATE: EXPECTED_PASS",
    "*** TEST BUILD:",
    "*** TEST TOOLS: 6.0.0.bbbb",
]

_SUITE_INFO = [
    "S:Platform:RTEMS",
    "S:Compiler:6.0.0.bbbb",
    "S:Version:6.0.0.aaaa",
    "S:BSP:sim",
    "S:BuildLabel:sim/uni",
    "S:TargetHash:SHA256:",
    "S:RTEMS_DEBUG:0",
    "S:RTEMS_MULTIPROCESSING:0",
    "S:RTEMS_POSIX_API:0",
    "S:RTEMS_PROFILING:0",
    "S:RTEMS_SMP:0",
]


def _report_hash(lines):
    """ Compute the report hash over the lines of the test suite report. """
    state = hashlib.sha256()
    for line in lines:
        state.update(f"{line}\n".encode("latin-1"))
    return base64.urlsafe_b64encode(state.digest()).decode("ascii")


def _test_suite(name, cases):
    """ Get the output lines of a test suite with the test cases. """
    lines = [f"A:{name}"] + _SUITE_INFO
    failed = 0
    for case_name, case_failed in cases:
        failed += case_failed
        lines.append(f"B:{case_name}")
        lines.append(f"E:{case_name}:N:1:F:{case_failed}:D:0.000100")
    lines.append(f"Z:{name}:C:{len(cases)}:N:{len(cases)}:F:{failed}:D:0.001")
    return [f"*** BEGIN OF TEST {name} ***"] + _INFO + lines + [
        f"Y:ReportHash:SHA256:{_report_hash(lines)}",
        f"*** END OF TEST {name} ***"
    ]


def _output(name):
    if name == "ts-pass.exe":
        return _test_suite("TestsuitesPass", [("CasePassOne", 0),
                                              ("CasePassTwo", 0)])
    if name == "ts-fail.exe":
        return _test_suite("TestsuitesFail", [("CasePass", 0),
                                              ("CaseFail", 1)])
    if name == "hello.exe":
        return (["*** BEGIN OF TEST HELLO ***"] + _INFO +
                ["Hello!", "*** END OF TEST HELLO ***"])
    if name in ("crash.exe", "xfail-crash.exe"):
        return (["*** BEGIN OF TEST CRASH ***"] + _INFO +
                ["cpu 0 in error mode (tt = 0x80)"])
    if name == "hang.exe":
        time.sleep(30.0)
        return ["never reached"]
    if name == "discarded.exe":
        return ["the simulator lost the connection"]
    return ["nothing to report"]


def main(argv):
    """ Print the test output of the executable. """
    name = os.path.basename(argv[-1])
    for line in _HEAD + _output(name):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
