# SPDX-License-Identifier: BSD-2-Clause
""" Tests for the spamrbuilder module. """

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

from specmake import SpamrBuilder
import specmake.spamrbuilder
from specmake.spamrbuilder import _METRICS, _load_code_metrics

from .util import build_document, get_document_text


def test_spamrbuilder(caplog, tmpdir, monkeypatch):
    package, text = build_document(caplog, tmpdir, "doc-paf-spamr",
                                   ["aggregate-test-results", "paf-spamr"])
    spamr_builder = package.director["/pkg/deployment/doc-paf-spamr"]
    assert isinstance(spamr_builder, SpamrBuilder)

    # The builder evaluates each metric of the quality model
    assert set(key for key, _ in _METRICS) == set(spamr_builder._thresholds)
    assert text.replace("\u200b",
                        "") == r""".. SPDX-License-Identifier: CC-BY-SA-4.0

.. Copyright (C) 2026 embedded brains GmbH & Co. KG

.. table::
    :class: longtable
    :widths: 34,36,15,15

    +-+-+-+-+
    | Metric | Value | Threshold | Result |
    +=+=+=+=+
    | Requirement implementation coverage | 3 of 23 requirements | 1 | **NOK** |
    +-+-+-+-+
    | Requirement completeness | 1 of 23 requirements | 0 | **NOK** |
    +-+-+-+-+
    | V&V coverage | 0 of 1 function | 1 | **NOK** |
    +-+-+-+-+
    | Requirement clarity | 0.08 | 0 | OK |
    +-+-+-+-+
    | Documentation suitability | Y or NA only | 1 | OK |
    +-+-+-+-+
    | Cyclomatic complexity (VG) | 1 of 5 functions | 10 | **NOK** |
    +-+-+-+-+
    | Nesting level | 1 of 5 functions | 5 | **NOK** |
    +-+-+-+-+
    | Lines of code (LOC) | 1 of 2 files | 500 | **NOK** |
    +-+-+-+-+
    | Comment frequency | 2 of 5 functions | 30 % | **NOK** |
    +-+-+-+-+
    | Requirement testability | 34.8 % (8 of 23 requirements) | 80 % | **NOK** |
    +-+-+-+-+
    | SPR/NCR status | 3 open issues | n.a. | n.a. |
    +-+-+-+-+
    | Safety activities adequacy | Y or NA only | 1 | OK |
    +-+-+-+-+
    | User documentation clarity | 0.02 | 0 | **NOK** |
    +-+-+-+-+
    | User documentation completeness | 1 document file, 2 items | 0 | **NOK** |
    +-+-+-+-+
    | User manual suitability | Y or NA only | 1 | OK |
    +-+-+-+-+
    | Milestone tracking | \- | n.a. | n.a. |
    +-+-+-+-+
    | RID/action status | 1 open action | n.a. | n.a. |
    +-+-+-+-+

The package has 23 related requirements. 3 of them have an associated
validation.

The following requirements have no validation:

- /req/glossary

- /req/perf-runtime

- /req/perf-runtime-environment

- /req/perf-runtime-environment-dirty-cache

- /req/perf-runtime-environment-full-cache

- /req/perf-runtime-environment-hot-cache

- /req/perf-runtime-environment-load

- /req/root

- /rtems/req/action

- /rtems/req/action-2

- /rtems/req/define-not-defined

- /rtems/req/func

- /rtems/req/group

- /rtems/req/group-no-identifier

- /rtems/req/perf

- /rtems/req/perf-no-results

- /rtems/target-a

- /testsuites/unit

- /testsuites/validation

- /testsuites/validation-refinement

The quality scanner found an open TBD or TBC in 1 of 23 related requirements.

- /rtems/req/action

Section :ref:`AnnexTBDTBCFindings` lists each finding and each suppression of
the quality scanner.

The package has 1 pre-qualified API function. 0 of them have a requirement with
an associated validation.

The following pre-qualified API functions have no requirement with a validation:

- /rtems/if/func

The package has 23 related requirements. 8 of them are verified by test.

The table counts the open and the closed issues of this package version by
issue database. The package status gives the status of each issue. An issue
which does not apply to this package version is not counted.

.. table::
    :class: longtable
    :widths: 60,20,20

    +-+-+-+
    | Issue database | Open | Closed |
    +=+=+=+
    | Issue | 2 | 1 |
    +-+-+-+
    | RTEMS Ticket | 1 | 1 |
    +-+-+-+

The following RIDs are open:

- `Issue issue 44 <https://www.foo.org/bar?id=44>`_

The actions are the issues of this package version with the label MAI.

- Actions issued: 1

- Actions closed: 0

- Actions open: 1

The RIDs are the issues of this package version with the label RID.

- RIDs issued: 2

- RIDs closed: 1

- RIDs open: 1

The pre-qualified source code has 618 lines of code and preprocessor
directives.

.. table::
    :class: longtable
    :widths: 40,20,20,20

    +-+-+-+-+
    | Metric | Threshold | Exceeded | Total |
    +=+=+=+=+
    | Cyclomatic complexity (VG) | 10 | 1 | 5 functions |
    +-+-+-+-+
    | Nesting level | 5 | 1 | 5 functions |
    +-+-+-+-+
    | Lines of code (LOC) | 500 | 1 | 2 files |
    +-+-+-+-+
    | Comment frequency | 30 % | 2 | 5 functions |
    +-+-+-+-+

Section :ref:`AnnexCodeMetrics` lists each function and file which exceeds a
threshold. The file
:file:`build/src/spamr/metrixplusplus/metrixplusplus.csv` of the package
contains the values of all regions.

The quality scanner found an open TBD or TBC in 1 document file and in 2 items.
Section :ref:`AnnexTBDTBCFindings` lists each finding and each suppression.

The quality scanner scanned these documents:

- /pkg/source/doc-a

- /pkg/source/doc-b

The tool reported 7 findings. Section :ref:`AnnexCppcheckFindings` lists each
finding.

.. table::
    :class: longtable
    :widths: 80,20

    +-+-+
    | Rule | Findings |
    +=+=+
    | ``checkersReport`` | 1 |
    +-+-+
    | ``missingIncludeSystem`` | 1 |
    +-+-+
    | ``syntaxError`` | 1 |
    +-+-+
    | ``unusedFunction`` | 2 |
    +-+-+
    | ``variableScope`` | 2 |
    +-+-+

The tool reported 2 findings. Section :ref:`AnnexClangFindings` lists each
finding.

.. table::
    :class: longtable
    :widths: 80,20

    +-+-+
    | Rule | Findings |
    +=+=+
    | ``core.NullDereference`` | 1 |
    +-+-+
    | ``deadcode.DeadStores`` | 1 |
    +-+-+

.. raw:: latex

    \begin{footnotesize}

.. table::
    :class: longtable
    :widths: 24,38,38

    +-+-+-+
    | Rule | Location | Message |
    +=+=+=+
    | variableScope | :file:`cpukit/a.c`:3 | The scope of the variable 'x' can be reduced. |
    +-+-+-+
    | syntaxError | :file:`/elsewhere/c.c`:7 | syntax error |
    +-+-+-+
    | variableScope | :file:`cpukit/b.c`:9 | The scope of the variable 'y' can be reduced. |
    +-+-+-+
    | checkersReport | \- | Active checkers: 160/592 |
    +-+-+-+
    | missingIncludeSystem | :file:`cpukit/b.c` | Include file: <stdio.h> not found. |
    +-+-+-+
    | unusedFunction | :file:`cpukit/driver#1.c`:1 | The function 'f' is never used. |
    +-+-+-+
    | unusedFunction | :file:`cpukit/dev ice.c`:2 | The function 'g' is never used. |
    +-+-+-+

.. raw:: latex

    \end{footnotesize}

.. raw:: latex

    \begin{footnotesize}

.. table::
    :class: longtable
    :widths: 24,38,38

    +-+-+-+
    | Rule | Location | Message |
    +=+=+=+
    | deadcode.DeadStores | :file:`cpukit/dev/iovprintf.c`:117 | Value stored to 'num' is never read |
    +-+-+-+
    | core.NullDereference | :file:`cpukit/score/src/heap.c`:42 | Dereference of null pointer |
    +-+-+-+

.. raw:: latex

    \end{footnotesize}

.. raw:: latex

    \begin{footnotesize}

.. table::
    :class: longtable
    :widths: 15,85

    +-+-+
    | Marker | Location |
    +=+=+
    | TBD | /rtems/req/action:/text |
    +-+-+
    | TBC | /pkg/component:/name |
    +-+-+
    | TBD | /pkg/source/doc-a: source/a.rst:5 |
    +-+-+

.. raw:: latex

    \end{footnotesize}

.. raw:: latex

    \begin{footnotesize}

.. table::
    :class: longtable
    :widths: 15,40,45

    +-+-+-+
    | Marker | Location | Reason |
    +=+=+=+
    | TBC | /pkg/source/doc-a: source/a.rst:9 | The glossary term \*TBC\* names the marker. |
    +-+-+-+

.. raw:: latex

    \end{footnotesize}

:file:`cpukit/a.c`

.. table::
    :class: longtable
    :widths: 44,14,14,14,14

    +-+-+-+-+-+
    | Function | Line | VG | Nesting | Comments |
    +=+=+=+=+=+
    | complex | 563 | **12** | 2 | 0 % |
    +-+-+-+-+-+
    | deep | 580 | 6 | **7** | **41 %** |
    +-+-+-+-+-+

:file:`cpukit/b.c`

.. table::
    :class: longtable
    :widths: 44,14,14,14,14

    +-+-+-+-+-+
    | Function | Line | VG | Nesting | Comments |
    +=+=+=+=+=+
    | chatty | 12 | 0 | 1 | **33 %** |
    +-+-+-+-+-+

.. table::
    :class: longtable
    :widths: 80,20

    +-+-+
    | File | Lines of code |
    +=+=+
    | :file:`cpukit/a.c` | 605 |
    +-+-+"""

    # Check that LaTeX can break the locations of the annex tables
    assert ":file:`cpukit/\u200ba.\u200bc`:3" in text
    assert "/\u200bpkg/\u200bsource/\u200bdoc-\u200ba: source/\u200ba.\u200brst:5" in text

    # Check that a run discards the cached values of a previous run
    spamr_builder.__dict__["_issues"] = []
    spamr_builder.run()
    assert "No RID is open." not in spamr_builder.mapper.substitute(
        "${.:/sprs-and-ncrws}")

    # Check that a changed package status or issue rebuilds the document
    director = package.director
    changes = director["/pkg/spamr/package-changes"]
    digest = changes.digest()
    description = "${/pkg/component:/cite-group:spamr}"
    changes.item["change-list"][0]["description"] = description
    assert changes.digest() != digest
    digest = changes.digest()
    issue = director.item_cache["/pkg/issue/spamr-rid"]
    issue.data["subject"] = "Other subject"
    assert changes.digest() != digest
    digest = changes.digest()
    database = issue.parent("issue-member")
    database.data["url"] = "https://www.foo.org/other?id=${.:/identifier}"
    assert changes.digest() != digest
    digest = changes.digest()
    status = director.item_cache["/pkg/spamr/package-status"]
    for link in status.data["links"]:
        if link["uid"] == "../issue/spamr-rid":
            link["status"] = "closed"
    assert changes.digest() != digest
    director.build_package(only=["/pkg/deployment/doc-paf-spamr"])
    index_rst = Path(director["/pkg/build/doc-paf-spamr"].directory
                     ) / "source" / "index.rst"
    text = get_document_text(tmpdir, index_rst)
    assert "No RID is open." in text
    assert "- RIDs open: 0" in text

    # Check the content without findings and thresholds
    tools = ("clang-analyzer", "cppcheck", "quality-scanner")
    spamr_builder.__dict__["_findings"] = dict((tool, []) for tool in tools)
    thresholds = dict((key, None) for key in spamr_builder._thresholds)
    spamr_builder.__dict__["_thresholds"] = thresholds
    mapper = spamr_builder.mapper
    for name, text in (
        ("annex-cppcheck-findings", "The tool reported no finding."),
        ("annex-clang-analyzer-findings", "The tool reported no finding."),
        ("annex-quality-scanner-findings",
         "The quality scanner found no open TBD or TBC."),
        ("annex-quality-scanner-suppressions",
         "No finding of the quality scanner is suppressed."),
        ("annex-functions", "No function exceeds a threshold."),
        ("annex-files", "No file exceeds the threshold."),
    ):
        assert mapper.substitute(f"${{.:/{name}}}") == text
    spamr_builder.__dict__["_issues"] = []
    assert mapper.substitute("${.:/sprs-and-ncrws}") == "No RID is open."
    spamr_builder.__dict__["_requirements"] = []
    assert mapper.substitute(
        "${.:/requirement-implementation-and-vv-coverage}"
    ) == """The package has 0 related requirements. 0 of them have an associated
validation."""
    assert mapper.substitute("${.:/requirements-completeness}") == \
        "The quality scanner found an open TBD or TBC in 0 of 0 related " \
        "requirements.\n\nSection :ref:`AnnexTBDTBCFindings` lists each " \
        "finding and each suppression of\nthe quality scanner."
    assert mapper.substitute("${.:/cppcheck-results}") == """The tool \
reported 0 findings. Section :ref:`AnnexCppcheckFindings` lists each
finding."""
    requirement = spamr_builder.input("spec").item_cache["/rtems/req/func"]
    requirement.view["validated"] = True
    spamr_builder.__dict__["_requirements"] = [requirement]
    del spamr_builder.__dict__["_functions_without_validation"]
    assert mapper.substitute("${.:/vv-coverage-unit-integration-level}") == \
        "The package has 1 pre-qualified API function. 1 of them have a " \
        "requirement with\nan associated validation."
    function = spamr_builder.input("spec").item_cache["/rtems/if/func"]
    function.view["pre-qualified"] = False
    del spamr_builder.__dict__["_api_functions"]
    del spamr_builder.__dict__["_functions_without_validation"]
    assert mapper.substitute("${.:/vv-coverage-unit-integration-level}") == \
        "The package has 0 pre-qualified API functions. 0 of them have a " \
        "requirement\nwith an associated validation."
    assert "suppressed" not in mapper.substitute(
        "${.:/user-documentation-completeness}")
    monkeypatch.setattr(specmake.spamrbuilder, "_load_scanned_documents",
                        lambda _paths: [])
    assert "scanned these documents" not in mapper.substitute(
        "${.:/user-documentation-completeness}")
    assert mapper.substitute("${.:/metrics-overview}").count("n.a.") == 34

    # Check that a metric with a threshold needs a verdict
    thresholds["requirement-clarity"] = 0
    del spamr_builder.item.data["metric-verdicts"]["requirement-clarity"]
    with pytest.raises(ValueError):
        mapper.substitute("${.:/metrics-overview}")


def test_spamrbuilder_code_metrics_without_file_lines(tmpdir):
    path = Path(tmpdir) / "metrixplusplus.csv"
    path.write_text(
        "file,region,type,modified,line start,line end,"
        "std.code.complexity:cyclomatic,std.code.complexity:maxindent,"
        "std.code.lines:code,std.code.lines:comments,"
        "std.code.lines:preprocessor\n",
        encoding="utf-8")
    with pytest.raises(ValueError, match="--std.code.filelines.code"):
        _load_code_metrics(str(path), [])
