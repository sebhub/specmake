# SPDX-License-Identifier: BSD-2-Clause
""" Reads the loadable image and the notes of an ELF file. """

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

# The functions of this module use the standard library alone.  The run
# executable command copies the source of the functions in
# ELF_SCRIPT_FUNCTIONS into a stand-alone script.

import base64
import hashlib
import struct

__all__ = [
    "ELF_SCRIPT_FUNCTIONS", "elf_loadable_sha512", "elf_notes", "is_elf_file"
]


def is_elf_file(data: bytes) -> bool:
    """ Tell whether the data starts with the ELF magic number. """
    return data[:4] == b"\x7fELF"


def _elf_unpack(data: bytes, fmt: str, offset: int, what: str) -> tuple:
    size = struct.calcsize(fmt)
    if offset < 0 or offset + size > len(data):
        raise ValueError(f"the ELF file is truncated in the {what}")
    return struct.unpack_from(fmt, data, offset)


def _elf_header(data: bytes) -> dict:
    """
    Get the fields of the ELF header which this module uses.

    The section count and the program header count come from section 0 if
    the header has no room for them.
    """
    if not is_elf_file(data):
        raise ValueError("the file has no ELF magic number")
    ident = _elf_unpack(data, "16B", 0, "identification")
    elf_class = ident[4]
    elf_data = ident[5]
    if elf_class not in (1, 2):
        raise ValueError(f"the ELF class {elf_class} is invalid")
    if elf_data not in (1, 2):
        raise ValueError(f"the ELF data encoding {elf_data} is invalid")
    order = "<" if elf_data == 1 else ">"
    if elf_class == 1:
        fields = _elf_unpack(data, f"{order}HHIIIIIHHHHHH", 16, "ELF header")
        section_fmt = f"{order}IIIIIIIIII"
        segment_fmt = f"{order}IIIIIIII"
    else:
        fields = _elf_unpack(data, f"{order}HHIQQQIHHHHHH", 16, "ELF header")
        section_fmt = f"{order}IIQQQQIIQQ"
        segment_fmt = f"{order}IIQQQQQQ"
    header = {
        "class": elf_class,
        "data": elf_data,
        "order": order,
        "machine": fields[1],
        "entry": fields[3],
        "phoff": fields[4],
        "shoff": fields[5],
        "flags": fields[6],
        "phentsize": fields[8],
        "phnum": fields[9],
        "shentsize": fields[10],
        "shnum": fields[11],
        "section-fmt": section_fmt,
        "segment-fmt": segment_fmt
    }
    if header["shoff"] != 0 and (header["shnum"] == 0
                                 or header["phnum"] == 0xffff):
        if header["shentsize"] < struct.calcsize(section_fmt):
            raise ValueError("the ELF section header size is too small")
        section_0 = _elf_unpack(data, section_fmt, header["shoff"],
                                "section header 0")
        if header["shnum"] == 0:
            header["shnum"] = section_0[5]
        if header["phnum"] == 0xffff:
            header["phnum"] = section_0[7]
    return header


def _elf_segments(data: bytes, header: dict) -> list:
    """
    Get the loadable segments.

    Each segment is a tuple of the virtual address, the physical address,
    the memory size, the flags and the file content.
    """
    segments: list = []
    if header["phoff"] == 0 or header["phnum"] == 0:
        return segments
    fmt = header["segment-fmt"]
    if header["phentsize"] < struct.calcsize(fmt):
        raise ValueError("the ELF program header size is too small")
    for index in range(header["phnum"]):
        fields = _elf_unpack(data, fmt,
                             header["phoff"] + index * header["phentsize"],
                             f"program header {index}")
        if header["class"] == 1:
            (p_type, offset, vaddr, paddr, filesz, memsz, flags,
             _align) = fields
        else:
            (p_type, flags, offset, vaddr, paddr, filesz, memsz,
             _align) = fields
        if p_type != 1:
            continue
        if offset + filesz > len(data):
            raise ValueError(
                f"the ELF file is truncated in the segment {index}")
        segments.append(
            (vaddr, paddr, memsz, flags, data[offset:offset + filesz]))
    return segments


def elf_loadable_sha512(data: bytes) -> str | None:
    """
    Get the SHA512 digest of the loadable image of the ELF file data.

    The digest covers the class, the data encoding, the machine, the flags,
    the entry point and each loadable segment in the order of the physical
    address.  For each segment, it covers the virtual address, the physical
    address, the memory size, the flags and the file content.  The digest is
    None if the data is no ELF file.
    """
    if not is_elf_file(data):
        return None
    header = _elf_header(data)
    state = hashlib.sha512()
    state.update(
        struct.pack("<BBHIQ", header["class"], header["data"],
                    header["machine"], header["flags"], header["entry"]))
    for vaddr, paddr, memsz, flags, content in sorted(_elf_segments(
            data, header),
                                                      key=lambda x:
                                                      (x[1], x[0])):
        state.update(
            struct.pack("<QQQIQ", vaddr, paddr, memsz, flags, len(content)))
        state.update(content)
    return base64.urlsafe_b64encode(state.digest()).decode("ascii")


def _elf_section_notes(data: bytes, header: dict, index: int,
                       fields: tuple) -> list[tuple[int, bytes, bytes]]:
    offset = fields[4]
    end = offset + fields[5]
    if end > len(data):
        raise ValueError(f"the ELF file is truncated in the section {index}")
    align = 8 if fields[8] == 8 else 4
    notes: list[tuple[int, bytes, bytes]] = []
    while offset < end:
        namesz, descsz, note_type = _elf_unpack(data, f"{header['order']}III",
                                                offset,
                                                f"note of section {index}")
        desc_begin = offset + (12 + namesz + align - 1) // align * align
        desc_end = desc_begin + descsz
        if desc_end > end:
            raise ValueError(
                f"the ELF note of section {index} exceeds the section")
        notes.append((note_type, data[offset + 12:offset + 12 + namesz],
                      data[desc_begin:desc_end]))
        offset += (desc_end - offset + align - 1) // align * align
    return notes


def elf_notes(data: bytes, owner: bytes) -> list[tuple[int, bytes]]:
    """
    Get the type and the descriptor of each note of the owner.

    The notes come from the note sections of the ELF file data.  A note
    section with an alignment of eight bytes aligns the descriptor and the
    next record to eight bytes from the start of the record.  Other note
    sections align them to four bytes.
    """
    header = _elf_header(data)
    notes: list[tuple[int, bytes]] = []
    if header["shoff"] == 0:
        return notes
    fmt = header["section-fmt"]
    if header["shentsize"] < struct.calcsize(fmt):
        raise ValueError("the ELF section header size is too small")
    for index in range(header["shnum"]):
        fields = _elf_unpack(data, fmt,
                             header["shoff"] + index * header["shentsize"],
                             f"section header {index}")
        if fields[1] != 7:
            continue
        notes.extend((note_type, desc)
                     for note_type, name, desc in _elf_section_notes(
                         data, header, index, fields)
                     if name.rstrip(b"\0") == owner)
    return notes


ELF_SCRIPT_FUNCTIONS = (is_elf_file, _elf_unpack, _elf_header, _elf_segments,
                        elf_loadable_sha512)
