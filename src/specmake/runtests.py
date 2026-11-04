# SPDX-License-Identifier: BSD-2-Clause
""" Runs test executables in subprocesses and retries invalid test runs. """

# Copyright (C) 2022, 2026 embedded brains GmbH & Co. KG
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

import logging
import math
import multiprocessing
from pathlib import Path
import queue
import re
import subprocess
import threading
import time
from typing import Any, Callable, NamedTuple, Optional

from specitems import is_enabled

from .testoutputparser import augment_report
from .util import now_utc

RunnerReport = dict[str, Any]

# The prefix of the error of a run which matched a discard pattern
DISCARDED = "discarded due to match with: "

# A run of a test in one of these states gives the same result every time
_NO_RETRY_STATES = frozenset(("EXPECTED_FAIL", "USER_INPUT"))


def select_command(command: list,
                   is_enabled_condition: Callable[[Any], bool]) -> list:
    """
    Return the arguments of the command which are enabled.

    An element which defines a condition contributes its value only if
    is_enabled_condition() accepts the condition.  A value which is a list
    contributes one argument for each element.  The arguments keep their
    variables.
    """
    arguments: list = []
    for element in command:
        if isinstance(element, dict):
            if not is_enabled_condition(element["enabled-by"]):
                continue
            element = element["value"]
        if isinstance(element, list):
            arguments.extend(element)
        else:
            arguments.append(element)
    return arguments


class RunnerExecutable(NamedTuple):
    """ Represents a test executable. """
    path: str
    digest: str
    timeout: float
    test_state: str = ""


class _Job:
    # pylint: disable=too-few-public-methods
    def __init__(self, executable: RunnerExecutable, command: list[str]):
        self.report: RunnerReport = {
            "executable": executable.path,
            "executable-sha512": executable.digest,
            "command-line": command
        }
        self.timeout = executable.timeout


class _StreamReader(threading.Thread):
    """
    Read a stream of a test runner and keep at most a limit of it.

    The stream must be read while the process runs, since a full pipe blocks
    the process.  A simulator may write an unbounded amount to its standard
    error, so everything beyond the limit is read and discarded instead of
    being stored.
    """

    # pylint: disable=too-few-public-methods
    def __init__(self, stream: Any, limit: Optional[int]):
        super().__init__(daemon=True)
        self._stream = stream
        self._limit = limit
        self._parts: list[bytes] = []
        self._kept = 0
        self.size = 0

    def run(self) -> None:
        while True:
            data = self._stream.read(65536)
            if not data:
                break
            self.size += len(data)
            if self._limit is not None:
                data = data[:max(0, self._limit - self._kept)]
            if data:
                self._parts.append(data)
                self._kept += len(data)

    def get_text(self) -> str:
        """ Return the kept part of the stream. """
        return b"".join(self._parts).decode("latin-1")


def _run_executable(command: list[str],
                    timeout: float) -> tuple[str, str, int, Optional[str]]:
    """
    Run the command and return its standard output, the kept part of its
    standard error, the size of its standard error, and an error message.
    """
    error: Optional[str] = None
    with subprocess.Popen(command,
                          stdin=subprocess.DEVNULL,
                          stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE) as process:
        assert process.stdout is not None
        assert process.stderr is not None
        out = _StreamReader(process.stdout, None)
        err = _StreamReader(process.stderr, 4096)
        out.start()
        err.start()
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            error = "timeout"
            process.kill()
            process.wait()
        out.join()
        err.join()
    return out.get_text(), err.get_text(), err.size, error


def _worker(work_queue: queue.Queue, discard_patterns: list, uid: str) -> None:
    while True:
        try:
            job = work_queue.get_nowait()
        except queue.Empty:
            return
        logging.info("%s: run: '%s'", uid,
                     "' '".join(job.report["command-line"]))
        job.report["start-time"] = now_utc()
        begin = time.monotonic()
        try:
            stdout, stderr, stderr_size, error = _run_executable(
                job.report["command-line"], job.timeout)
            if error is not None:
                job.report["error"] = error
            if stderr_size > 0:
                job.report["standard-error"] = stderr
                if stderr_size > len(stderr):
                    job.report["standard-error-size"] = stderr_size
        except Exception as err:  # pylint: disable=broad-exception-caught
            job.report["error"] = str(err)
            stdout = ""
        for pattern in discard_patterns:
            if is_enabled([Path(job.report["executable"]).name],
                          pattern["enabled-by"]) and re.search(
                              pattern["pattern"], stdout, re.DOTALL):
                job.report["error"] = f"{DISCARDED}{pattern['pattern']}"
        output = stdout.rstrip().replace("\r\n", "\n").split("\n")
        job.report["output"] = output
        job.report["duration"] = time.monotonic() - begin
        logging.debug("%s: done: %s", uid, job.report["executable"])
        work_queue.task_done()


def run_subprocess_tests(executables: list[RunnerExecutable],
                         get_command: Callable[[RunnerExecutable], list[str]],
                         discard_patterns: list,
                         max_process_count: int,
                         uid: str = "run-tests") -> list[RunnerReport]:
    """
    Run the test executables in subprocesses and return the reports.

    The command of an executable is obtained by get_command().  A report of an
    executable which matches a discard pattern gets an error attribute.  The
    worker thread count is the processor count divided by the process count
    used by one test run.
    """
    work_queue: queue.Queue[_Job] = queue.Queue()
    jobs: list[_Job] = []
    for executable in executables:
        job = _Job(executable, get_command(executable))
        jobs.append(job)
        work_queue.put(job)
    worker_count = int(
        math.ceil(multiprocessing.cpu_count() / float(max_process_count)))
    logging.info("%s: use %s worker threads", uid, worker_count)
    for _ in range(min(worker_count, len(executables))):
        threading.Thread(target=_worker,
                         args=(work_queue, discard_patterns, uid),
                         daemon=True).start()
    work_queue.join()
    return [job.report for job in jobs]


def _get_test_state(report: RunnerReport, executable: RunnerExecutable) -> str:
    if executable.test_state:
        return executable.test_state
    return report["info"].get("state", "").strip()


def _must_retry(report: Optional[RunnerReport], executable: RunnerExecutable,
                uid: str) -> bool:
    path = executable.path
    if report is None:
        logging.warning("%s: executable '%s': no report", uid, path)
        return True
    outcome_failed = False
    if "error" in report:
        logging.warning("%s: executable '%s': %s", uid, path, report["error"])
        if report["error"].startswith(DISCARDED):
            return True
        outcome_failed = True
    elif ("line-begin-of-test" in report["info"]
          and "line-end-of-test" not in report["info"]):
        logging.warning("%s: executable '%s': missing end of test line", uid,
                        path)
        outcome_failed = True
    if report.get("gcov-info-hash",
                  "") != report.get("gcov-info-hash-calculated", ""):
        logging.warning("%s: executable '%s': gcov info is corrupt", uid, path)
        return True
    test_suite = report.get("test-suite", {})
    if test_suite.get("report-hash",
                      "") != test_suite.get("report-hash-calculated", ""):
        logging.warning("%s: executable '%s': test suite report is corrupt",
                        uid, path)
        return True
    if outcome_failed and _get_test_state(report,
                                          executable) in _NO_RETRY_STATES:
        logging.info("%s: executable '%s': no retry due to expected failure",
                     uid, path)
        return False
    return outcome_failed


def run_tests_with_retries(executables: list[RunnerExecutable],
                           run_tests: Callable[[list[RunnerExecutable]],
                                               list[RunnerReport]],
                           max_run_count: int,
                           uid: str = "run-tests") -> list[RunnerReport]:
    """
    Run the test executables and retry those which produced no valid report.

    A report of a retried executable gets a failed-attempts attribute which
    contains the reports of the previous attempts.
    """
    reports_by_path: dict[str, RunnerReport] = {}
    while executables and max_run_count:
        for new_report in run_tests(executables):
            augment_report(new_report, new_report["output"])
            previous_report = reports_by_path.get(new_report["executable"])
            if previous_report is not None:
                new_report["failed-attempts"] = previous_report.pop(
                    "failed-attempts", []) + [previous_report]
            reports_by_path[new_report["executable"]] = new_report
        executables = [
            executable for executable in executables if _must_retry(
                reports_by_path.get(executable.path, None), executable, uid)
        ]
        max_run_count -= 1
    return list(reports_by_path.values())
