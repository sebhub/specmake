# SPDX-License-Identifier: BSD-2-Clause
""" Tests for the elf module. """

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

from pathlib import Path

import pytest

from specmake import elf_loadable_sha512, elf_notes, is_elf_file

from .elfutil import Note, NoteSection, Segment, build_elf

_FORMATS = [(1, "<"), (1, ">"), (2, "<"), (2, ">")]

_SEGMENTS = [
    Segment(0x1000, 0x1000, b"text"),
    Segment(0x2000, 0x8000, b"data", memsz=16, flags=6)
]


@pytest.mark.parametrize("elf_class,order", _FORMATS)
def test_loadable_digest_ignores_non_loaded_parts(elf_class, order):
    base = elf_loadable_sha512(build_elf(elf_class, order, _SEGMENTS))
    assert base is not None
    assert elf_loadable_sha512(
        build_elf(elf_class, order, _SEGMENTS, debug=b"other debug")) == base
    assert elf_loadable_sha512(
        build_elf(
            elf_class,
            order,
            _SEGMENTS,
            note_sections=[NoteSection([Note(b"RTEMS\0", 1,
                                             b"6.0.0.abc\0")])])) == base
    assert elf_loadable_sha512(
        build_elf(elf_class, order, list(reversed(_SEGMENTS)))) == base
    assert elf_loadable_sha512(
        build_elf(elf_class, order,
                  _SEGMENTS + [Segment(0, 0, b"note", p_type=4)])) == base
    assert elf_loadable_sha512(
        build_elf(elf_class, order, _SEGMENTS, extended_counts=True)) == base


@pytest.mark.parametrize("elf_class,order", _FORMATS)
def test_loadable_digest_covers_loaded_parts(elf_class, order):
    base = elf_loadable_sha512(build_elf(elf_class, order, _SEGMENTS))
    variants = [
        build_elf(elf_class, order, _SEGMENTS, entry=0x1004),
        build_elf(elf_class, order, _SEGMENTS, machine=3),
        build_elf(elf_class, order, _SEGMENTS, flags=1),
        build_elf(elf_class, order, [_SEGMENTS[0]]),
        build_elf(elf_class, order,
                  [_SEGMENTS[0], _SEGMENTS[1]._replace(content=b"date")]),
        build_elf(elf_class, order,
                  [_SEGMENTS[0], _SEGMENTS[1]._replace(vaddr=0x2004)]),
        build_elf(elf_class, order,
                  [_SEGMENTS[0], _SEGMENTS[1]._replace(paddr=0x8004)]),
        build_elf(elf_class, order,
                  [_SEGMENTS[0], _SEGMENTS[1]._replace(memsz=20)]),
        build_elf(elf_class, order,
                  [_SEGMENTS[0], _SEGMENTS[1]._replace(flags=7)]),
        build_elf(elf_class, order, [
            Segment(0x1000, 0x1000, b"tex"),
            Segment(0x2000, 0x8000, b"tdata", memsz=16, flags=6)
        ])
    ]
    digests = [elf_loadable_sha512(variant) for variant in variants]
    assert base not in digests
    assert len(set(digests)) == len(digests)


def test_loadable_digest_differs_by_format():
    digests = set(
        elf_loadable_sha512(build_elf(elf_class, order, _SEGMENTS))
        for elf_class, order in _FORMATS)
    assert len(digests) == len(_FORMATS)


def test_loadable_digest_of_no_elf_file():
    assert not is_elf_file(b"#!/bin/sh\n")
    assert elf_loadable_sha512(b"#!/bin/sh\n") is None


def test_loadable_digest_of_example_file():
    data = Path(__file__).parent.joinpath("some.elf").read_bytes()
    assert elf_loadable_sha512(data) == (
        "d0XpDjvS5KFSzceOwa7m-zNDVWQD2aDUmV74Cvu_VmSeic9xPYVvei8u8vVFSHSmlC6N"
        "lMmnadFlMG7mLKSUDA==")


@pytest.mark.parametrize("elf_class,order", _FORMATS)
def test_notes(elf_class, order):
    data = build_elf(elf_class,
                     order,
                     _SEGMENTS,
                     note_sections=[
                         NoteSection([
                             Note(b"RTEMS\0", 1, b"6.0.0.abc\0"),
                             Note(b"GNU\0", 3, b"12345678"),
                             Note(b"RTEMS\0", 2, b"RTEMS_SMP\0")
                         ]),
                         NoteSection([Note(b"RTEMS\0", 6, b"PASS\0")], align=8)
                     ])
    assert elf_notes(data, b"RTEMS") == [(1, b"6.0.0.abc\0"),
                                         (2, b"RTEMS_SMP\0"), (6, b"PASS\0")]
    assert elf_notes(data, b"GNU") == [(3, b"12345678")]
    assert not elf_notes(build_elf(elf_class, order, _SEGMENTS), b"RTEMS")


def _expect_error(data: bytes, message: str) -> None:
    with pytest.raises(ValueError) as err:
        elf_loadable_sha512(data)
    assert str(err.value) == message


def test_errors():
    data = build_elf(1, "<", _SEGMENTS)
    _expect_error(data[:20], "the ELF file is truncated in the ELF header")
    _expect_error(data[:4] + b"\3" + data[5:], "the ELF class 3 is invalid")
    _expect_error(data[:5] + b"\3" + data[6:],
                  "the ELF data encoding 3 is invalid")
    _expect_error(data[:60],
                  "the ELF file is truncated in the program header 0")
    _expect_error(data[:122], "the ELF file is truncated in the segment 1")
    _expect_error(data[:28] + b"\xff" * 4 + data[32:],
                  "the ELF file is truncated in the program header 0")
    _expect_error(data[:42] + b"\x10\0" + data[44:],
                  "the ELF program header size is too small")
    notes = build_elf(
        1,
        "<",
        _SEGMENTS,
        note_sections=[NoteSection([Note(b"RTEMS\0", 1, b"6.0.0.abc\0")])])
    with pytest.raises(ValueError) as err:
        elf_notes(notes[:-50], b"RTEMS")
    assert str(err.value).startswith("the ELF file is truncated in the ")
    with pytest.raises(ValueError) as err:
        elf_notes(b"#!/bin/sh\n", b"RTEMS")
    assert str(err.value) == "the file has no ELF magic number"


def test_no_headers():
    data = bytearray(build_elf(1, "<", _SEGMENTS))
    data[28:36] = b"\0" * 8
    assert elf_loadable_sha512(bytes(data)) is not None
    assert not elf_notes(bytes(data), b"RTEMS")


def test_section_errors():
    data = build_elf(
        1,
        "<",
        _SEGMENTS,
        note_sections=[NoteSection([Note(b"RTEMS\0", 1, b"6.0.0.abc\0")])])
    shoff = int.from_bytes(data[32:36], "little")
    small = data[:46] + b"\x10\0" + data[48:]
    with pytest.raises(ValueError) as err:
        elf_notes(small, b"RTEMS")
    assert str(err.value) == "the ELF section header size is too small"
    extended = build_elf(1, "<", _SEGMENTS, extended_counts=True)
    with pytest.raises(ValueError) as err:
        elf_loadable_sha512(extended[:46] + b"\x10\0" + extended[48:])
    assert str(err.value) == "the ELF section header size is too small"
    note_header = shoff + 2 * 40
    oversized = bytearray(data)
    oversized[note_header + 20:note_header + 24] = (0xffff).to_bytes(
        4, "little")
    with pytest.raises(ValueError) as err:
        elf_notes(bytes(oversized), b"RTEMS")
    assert str(err.value) == "the ELF file is truncated in the section 2"
    note_offset = int.from_bytes(data[note_header + 16:note_header + 20],
                                 "little")
    long_desc = bytearray(data)
    long_desc[note_offset + 4:note_offset + 8] = (100).to_bytes(4, "little")
    with pytest.raises(ValueError) as err:
        elf_notes(bytes(long_desc), b"RTEMS")
    assert str(err.value) == "the ELF note of section 2 exceeds the section"


def test_one_extended_count():
    notes = [NoteSection([Note(b"RTEMS\0", 1, b"6.0.0.abc\0")])]
    base = build_elf(1, "<", _SEGMENTS, note_sections=notes)
    extended = build_elf(1,
                         "<",
                         _SEGMENTS,
                         note_sections=notes,
                         extended_counts=True)
    only_sections = extended[:44] + base[44:46] + extended[46:]
    only_segments = extended[:48] + base[48:50] + extended[50:]
    for data in (only_sections, only_segments):
        assert elf_loadable_sha512(data) == elf_loadable_sha512(base)
        assert elf_notes(data, b"RTEMS") == [(1, b"6.0.0.abc\0")]
