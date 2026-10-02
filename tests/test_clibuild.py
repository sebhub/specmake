# SPDX-License-Identifier: BSD-2-Clause
""" Tests the command to create a package workspace. """

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

import pytest

import specmake.clibuild
from specmake.clibuild import clibuild


class _Stop(Exception):
    pass


@pytest.mark.parametrize("names,enabled_set", [("", []), ("a", ["a"]),
                                               ("a,b", ["a", "b"]),
                                               (" a , b ,, ", ["a", "b"])])
def test_enabled_set(tmp_path, monkeypatch, names, enabled_set):
    configs = []

    def _create_workspace(config):
        configs.append(config)
        raise _Stop

    monkeypatch.setattr(specmake.clibuild, "create_workspace",
                        _create_workspace)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(_Stop):
        clibuild([
            "specbuild", "--config-directory",
            str(tmp_path), "--enabled-set", names, "config.yml"
        ])
    assert configs[0].enabled_set == enabled_set
