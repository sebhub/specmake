# SPDX-License-Identifier: BSD-2-Clause
""" Tests for the executablerecord module. """

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

import os
from pathlib import Path

import pytest

from specmake import (ExecutableRecord, add_executable_record,
                      elf_loadable_sha512, find_report, index_reports,
                      read_executable_record, reuse_report, rtems_notes)

from .elfutil import Note, NoteSection, Segment, build_elf

_SEGMENTS = [Segment(0x1000, 0x1000, b"text")]


def test_rtems_notes():
    assert rtems_notes([]) is None
    assert rtems_notes([(1, b"6.0.0.abc\0"), (2, b"RTEMS_SMP\0"),
                        (3, b"15.2.0\0"), (4, b"arm/zc702\0"), (5, b"label\0"),
                        (6, b"PASS\0"), (1, b"6.0.0.abc\0"),
                        (1, b"6.0.0.def\0"), (9, b"x\0")]) == {
                            "version": "6.0.0.abc",
                            "build": "RTEMS_SMP",
                            "tools": "15.2.0",
                            "bsp": "arm/zc702",
                            "build-label": "label",
                            "test-state": "PASS",
                            "conflicts": [{
                                "type": 1,
                                "desc": "6.0.0.def"
                            }],
                            "unknown": [{
                                "type": 9,
                                "desc": "x"
                            }]
                        }
    assert rtems_notes([(2, b"\0")]) == {"build": ""}


def test_read_executable_record(tmpdir):
    tmp_dir = Path(tmpdir)
    with_notes = tmp_dir / "notes.exe"
    data = build_elf(2,
                     "<",
                     _SEGMENTS,
                     note_sections=[
                         NoteSection([
                             Note(b"RTEMS\0", 1, b"6.0.0.abc\0"),
                             Note(b"GNU\0", 1, b"other\0")
                         ])
                     ])
    with_notes.write_bytes(data)
    assert read_executable_record(str(with_notes), "f") == ExecutableRecord(
        str(with_notes), "f", elf_loadable_sha512(data),
        {"version": "6.0.0.abc"})
    without_notes = tmp_dir / "plain.exe"
    without_notes.write_bytes(build_elf(2, "<", _SEGMENTS))
    record = read_executable_record(str(without_notes), "p")
    assert record.loadable_sha512 == elf_loadable_sha512(data)
    assert record.elf_notes is None
    script = tmp_dir / "script.exe"
    script.write_text("#!/bin/sh\n", encoding="utf-8")
    assert read_executable_record(str(script), "s") == ExecutableRecord(
        str(script), "s", None, None)
    link = tmp_dir / "link.exe"
    os.symlink("notes.exe", link)
    assert read_executable_record(str(link), "l") == ExecutableRecord(
        str(link), "l", None, None)
    broken = tmp_dir / "broken.exe"
    broken.write_bytes(data[:30])
    with pytest.raises(ValueError) as err:
        read_executable_record(str(broken), "b")
    assert str(err.value) == (f"{broken}: the ELF file is truncated in the "
                              "ELF header")


def test_find_report():
    first = {"executable-sha512": "a", "loadable-sha512": "x"}
    second = {"executable-sha512": "b", "loadable-sha512": "x"}
    third = {"executable-sha512": "c"}
    index = index_reports([first, second, third])
    assert find_report(index, "b", "x") is first
    assert find_report(index, "b", "y") is second
    assert find_report(index, "c", None) is third
    assert find_report(index, "c", "x") is first
    assert find_report(index, "d", "y") is None
    assert find_report(index_reports([]), "a", "x") is None


def test_reuse_report():
    record = ExecutableRecord("new.exe", "new", "image", {"version": "v"})
    report = {
        "executable": "old.exe",
        "executable-sha512": "old",
        "loadable-sha512": "image",
        "elf-notes": {
            "version": "u"
        },
        "output": ["x"]
    }
    reuse_report(report, record)
    assert report == {
        "executable": "new.exe",
        "executable-sha512": "new",
        "loadable-sha512": "image",
        "run-executable-sha512": "old",
        "elf-notes": {
            "version": "v"
        },
        "output": ["x"]
    }
    reuse_report(report, ExecutableRecord("newer.exe", "newer", None, None))
    assert report == {
        "executable": "newer.exe",
        "executable-sha512": "newer",
        "run-executable-sha512": "old",
        "output": ["x"]
    }


def test_add_executable_record():
    report = {"executable": "a.exe", "executable-sha512": "a"}
    add_executable_record(report, ExecutableRecord("a.exe", "a", "image",
                                                   None))
    assert report == {
        "executable": "a.exe",
        "executable-sha512": "a",
        "loadable-sha512": "image",
        "run-executable-sha512": "a"
    }
