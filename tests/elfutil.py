# SPDX-License-Identifier: BSD-2-Clause
""" Builds synthetic ELF files for the tests. """

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

import struct
from typing import NamedTuple


class Segment(NamedTuple):
    """ Represents a program header and its content. """
    vaddr: int
    paddr: int
    content: bytes
    memsz: int = -1
    flags: int = 5
    p_type: int = 1


class Note(NamedTuple):
    """ Represents a note record. """
    name: bytes
    note_type: int
    desc: bytes


class NoteSection(NamedTuple):
    """ Represents a note section. """
    notes: list[Note]
    align: int = 4


def _align(data: bytearray, align: int) -> None:
    data.extend(b"\0" * (-len(data) % align))


def note_section_data(order: str, section: NoteSection) -> bytes:
    """ Get the content of the note section. """
    data = bytearray()
    for note in section.notes:
        data.extend(
            struct.pack(f"{order}III", len(note.name), len(note.desc),
                        note.note_type))
        data.extend(note.name)
        _align(data, section.align)
        data.extend(note.desc)
        _align(data, section.align)
    return bytes(data)


# pylint: disable=too-many-arguments
# pylint: disable=too-many-locals
def build_elf(elf_class: int,
              order: str,
              segments: list[Segment],
              note_sections: list[NoteSection] | None = None,
              machine: int = 2,
              flags: int = 0,
              entry: int = 0x1000,
              debug: bytes = b"",
              extended_counts: bool = False) -> bytes:
    """
    Build an ELF file.

    The file holds the header, the program headers, the content of the
    segments, a debug section, the note sections and the section headers.
    The extended counts move the segment count and the section count into
    section 0.
    """
    is_64 = elf_class == 2
    ehsize = 64 if is_64 else 52
    phentsize = 56 if is_64 else 32
    shentsize = 64 if is_64 else 40
    data = bytearray(ehsize + phentsize * len(segments))
    offsets = []
    for segment in segments:
        _align(data, 4)
        offsets.append(len(data))
        data.extend(segment.content)
    sections = [(0, 0, 0, 0)]
    _align(data, 4)
    sections.append((1, len(data), len(debug), 1))
    data.extend(debug)
    for section in note_sections or []:
        _align(data, section.align)
        content = note_section_data(order, section)
        sections.append((7, len(data), len(content), section.align))
        data.extend(content)
    _align(data, 8)
    shoff = len(data)
    phnum = 0xffff if extended_counts else len(segments)
    shnum = 0 if extended_counts else len(sections)
    for index, (sh_type, offset, size, align) in enumerate(sections):
        if index == 0 and extended_counts:
            size = len(sections)
            info = len(segments)
        else:
            info = 0
        if is_64:
            data.extend(
                struct.pack(f"{order}IIQQQQIIQQ", 0, sh_type, 0, 0, offset,
                            size, 0, info, align, 0))
        else:
            data.extend(
                struct.pack(f"{order}IIIIIIIIII", 0, sh_type, 0, 0, offset,
                            size, 0, info, align, 0))
    ident = b"\x7fELF" + bytes([elf_class, 1 if order == "<" else 2, 1
                                ]) + b"\0" * 9
    word = "Q" if is_64 else "I"
    data[0:ehsize] = ident + struct.pack(
        f"{order}HHI{word}{word}{word}IHHHHHH", 2, machine, 1, entry, ehsize,
        shoff, flags, ehsize, phentsize, phnum, shentsize, shnum, 0)
    for index, (segment, offset) in enumerate(zip(segments, offsets)):
        memsz = len(segment.content) if segment.memsz < 0 else segment.memsz
        if is_64:
            header = struct.pack(f"{order}IIQQQQQQ", segment.p_type,
                                 segment.flags, offset, segment.vaddr,
                                 segment.paddr, len(segment.content), memsz, 4)
        else:
            header = struct.pack(f"{order}IIIIIIII", segment.p_type, offset,
                                 segment.vaddr, segment.paddr,
                                 len(segment.content), memsz, segment.flags, 4)
        begin = ehsize + index * phentsize
        data[begin:begin + phentsize] = header
    return bytes(data)
