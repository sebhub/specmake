# SPDX-License-Identifier: BSD-2-Clause
""" Tests for the stdtailoring module. """

# Copyright (C) 2025, 2026 embedded brains GmbH & Co. KG
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

from specitems import ContentContext

from specmake import DocumentBuilder, ECSSClause

from .util import create_package


def test_stdtailoring(caplog, tmpdir):
    package = create_package(caplog, Path(tmpdir), Path("stdtailoring/spec"))
    director = package.director
    builder = director["/pkg/doc"]
    assert isinstance(builder, DocumentBuilder)
    builder_2 = director["/pkg/doc-2"]
    assert isinstance(builder_2, DocumentBuilder)

    # Check standard and clause references
    assert builder.substitute(
        "${/standard/clause-0:/clause}") == ":ref:`4.3.1.1x <StandardClause0>`"
    # The label drops the bullet, the target does not: a standard cites a
    # clause by its section, and the reference still points at the individual
    # requirement.
    assert builder.substitute("${/standard/clause-0:/clause-section}"
                              ) == ":ref:`4.3.1.1 <StandardClause0>`"
    assert builder.substitute(
        "${/standard/clause-0:/clause-long}"
    ) == ":ref:`4.3.1.1x (Clause 0 name) <StandardClause0>`"
    assert builder.substitute(
        "${/standard/clause-0:/standard-and-clause}"
    ) == ":ref:`ABCD-X-ST-01Y Rev. 42 - 4.3.1.1x <StandardClause0>`"
    assert builder.substitute(
        "${/standard/clause-0:/standard-and-clause-long}"
    ) == ":ref:`ABCD-X-ST-01Y Rev. 42 - 4.3.1.1x (Clause 0 name) <StandardClause0>`"

    # Check standard and clause links
    assert builder_2.substitute(
        "${/standard/clause-0:/clause}"
    ) == "`4.3.1.1x <../doc/path/to/ecss/tailoring#standardclause0>`__"
    assert builder_2.substitute(
        "${/standard/clause-0:/standard-and-clause}"
    ) == "`ABCD-X-ST-01Y Rev. 42 - 4.3.1.1x <../doc/path/to/ecss/tailoring#standardclause0>`__"
    with builder_2.component_scope(director["/pkg/component-2"]):
        assert builder_2.substitute(
            "${/standard/clause-0:/clause}"
        ) == "`4.3.1.1x <../doc/path/to/ecss/tailoring-2#standardclause0>`__"
        assert builder_2.substitute(
            "${/standard/clause-0:/standard-and-clause}"
        ) == "`ABCD-X-ST-01Y Rev. 42 - 4.3.1.1x <../doc/path/to/ecss/tailoring-2#standardclause0>`__"

    # A citation takes no content of the clause, a clause name does.  The
    # document registers a mapped part once it has a content context.
    assert isinstance(builder.content_context, ContentContext)
    clause = director["/standard/clause-0"].item
    clause["SPDX-License-Identifier"] = "LicenseRef-X"
    for key in ("clause", "clause-section", "standard-and-clause"):
        builder.substitute(f"${{/standard/clause-0:/{key}}}")
    for key in ("clause-long", "standard-and-clause-long"):
        with pytest.raises(ValueError, match="permits neither"):
            builder.substitute(f"${{/standard/clause-0:/{key}}}")
    clause["SPDX-License-Identifier"] = "CC-BY-SA-4.0"

    # Check standard tailoring
    assert builder.substitute(
        "${.:/standard-tailoring}") == """.. _StandardStandard:

Tailoring of ABCD-X-ST-01Y Rev. 42
----------------------------------

.. list-table:: Compliance matrix of ABCD-X-ST-01Y Rev. 42
    :widths: 13, 12, 13, 12, 13, 12, 13, 12
    :header-rows: 1

    * - Clause
      - Status
      - Clause
      - Status
      - Clause
      - Status
      - Clause
      - Status
    * - 1.2.3.4y
      - .. _CMStandardClause1:

        :ref:`N <StandardClause1>`
      - 4.3.1.1x
      - .. _CMStandardClause0:

        :ref:`Y <StandardClause0>`
      - ​
      - ​
      - ​
      - ​

.. _StandardClause1:

Clause 1 name (1.2.3.4y)
^^^^^^^^^^^^^^^^^^^^^^^^

.. topic:: ABCD-X-ST-01Y Rev. 42 - Clause 1.2.3.4y - ABCD-X-ST-01_clause-1

    The clause shall be 1.

.. topic:: Aim

    Aim.

.. topic:: Note

    Note.

.. topic:: Expected Output

    Expected output.

Tailoring Status: N
    No.

For an overview of all clauses, see the :ref:`tailoring table <CMStandardClause1>`.

.. _StandardClause0:

Clause 0 name (4.3.1.1x)
^^^^^^^^^^^^^^^^^^^^^^^^

.. topic:: ABCD-X-ST-01Y Rev. 42 - Clause 4.3.1.1x - ABCD-X-ST-01_clause-0

    The clause shall be 0.

.. topic:: Note 1

    Note 1

.. topic:: Note 2

    Note 2

Tailoring Status: Y
    Yes.

For an overview of all clauses, see the :ref:`tailoring table <CMStandardClause0>`."""

    clause = director["/standard/clause-0"]
    assert isinstance(clause, ECSSClause)
    assert director.factory.export_data(clause.item, True, 0) == {
        "SPDX-License-Identifier": "CC-BY-SA-4.0",
        "aim": None,
        "bullet": "x",
        "copyrights": [
            "Copyright (C) 2025 embedded brains GmbH & Co. KG",
        ],
        "enabled-by": True,
        "expected-output": None,
        "links": [
            {
                "role": "requirement-refinement",
                "uid": "standard",
            },
        ],
        "name": "Text removed due to license issues",
        "non-functional-type": "ecss",
        "notes": None,
        "rationale": None,
        "references": [],
        "requirement-type": "non-functional",
        "section": "4.3.1.1",
        "text": "Text removed due to license issues.",
        "type": "requirement",
    }
