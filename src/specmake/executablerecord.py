# SPDX-License-Identifier: BSD-2-Clause
""" Provides the record of a test executable and the reuse of its report. """

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

# The functions in REUSE_SCRIPT_FUNCTIONS use the standard library alone.  The
# run executable command copies their source into a stand-alone script.

import os
from typing import Any, NamedTuple

from .elf import elf_loadable_sha512, elf_notes

__all__ = [
    "ExecutableRecord", "REUSE_SCRIPT_FUNCTIONS", "RTEMS_NOTE_KEYS",
    "add_executable_record", "find_report", "index_reports",
    "read_executable_record", "reuse_report", "rtems_notes"
]

RTEMS_NOTE_KEYS = {
    1: "version",
    2: "build",
    3: "tools",
    4: "bsp",
    5: "build-label",
    6: "test-state"
}


class ExecutableRecord(NamedTuple):
    """ Represents the digests and the notes of a test executable. """
    path: str
    sha512: str
    loadable_sha512: str | None
    elf_notes: dict[str, Any] | None


def rtems_notes(notes: list[tuple[int, bytes]]) -> dict[str, Any] | None:
    """
    Get the RTEMS notes by their key.

    A note of an unknown type goes into the "unknown" list.  A note of a
    known type with a value other than the first note of the type goes into
    the "conflicts" list.  The result is None if there is no note.
    """
    if not notes:
        return None
    result: dict[str, Any] = {}
    for note_type, desc in notes:
        value = desc.rstrip(b"\0").decode("utf-8", errors="replace")
        key = RTEMS_NOTE_KEYS.get(note_type, None)
        if key is None:
            result.setdefault("unknown", []).append({
                "type": note_type,
                "desc": value
            })
        elif key not in result:
            result[key] = value
        elif result[key] != value:
            result.setdefault("conflicts", []).append({
                "type": note_type,
                "desc": value
            })
    return result


def read_executable_record(path: str, sha512: str) -> ExecutableRecord:
    """
    Read the record of the executable with the file digest.

    A symbolic link and a file which is no ELF file have no loadable digest
    and no notes.
    """
    if os.path.islink(path):
        return ExecutableRecord(path, sha512, None, None)
    with open(path, "rb") as src:
        data = src.read()
    try:
        loadable_sha512 = elf_loadable_sha512(data)
        notes = None if loadable_sha512 is None else rtems_notes(
            elf_notes(data, b"RTEMS"))
    except ValueError as err:
        raise ValueError(f"{path}: {err}") from err
    return ExecutableRecord(path, sha512, loadable_sha512, notes)


def index_reports(reports: list) -> dict:
    """
    Index the reports by the loadable digest and by the file digest.

    The first report of a digest wins.
    """
    by_loadable: dict = {}
    by_file: dict = {}
    for report in reports:
        loadable = report.get("loadable-sha512", None)
        if loadable is not None:
            by_loadable.setdefault(loadable, report)
        by_file.setdefault(report["executable-sha512"], report)
    return {"loadable": by_loadable, "file": by_file}


def find_report(index: dict, sha512: str,
                loadable_sha512: str | None) -> dict | None:
    """
    Find the report of an executable with the digests.

    The loadable digest takes precedence over the file digest.
    """
    if loadable_sha512 is not None:
        report = index["loadable"].get(loadable_sha512, None)
        if report is not None:
            return report
    return index["file"].get(sha512, None)


def _set_record(report: dict[str, Any], record: ExecutableRecord) -> None:
    report["executable"] = record.path
    report["executable-sha512"] = record.sha512
    report.pop("loadable-sha512", None)
    report.pop("elf-notes", None)
    if record.loadable_sha512 is not None:
        report["loadable-sha512"] = record.loadable_sha512
    if record.elf_notes is not None:
        report["elf-notes"] = record.elf_notes


def add_executable_record(report: dict[str, Any],
                          record: ExecutableRecord) -> None:
    """ Add the record to the report of a run of the executable. """
    _set_record(report, record)
    report["run-executable-sha512"] = record.sha512


def reuse_report(report: dict[str, Any], record: ExecutableRecord) -> None:
    """
    Reuse the report for the executable of the record.

    The report keeps the file digest of the executable which produced the
    output.
    """
    report["run-executable-sha512"] = report.get("run-executable-sha512",
                                                 report["executable-sha512"])
    _set_record(report, record)


REUSE_SCRIPT_FUNCTIONS = (index_reports, find_report)
