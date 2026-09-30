# SPDX-License-Identifier: BSD-2-Clause
""" Tests for the runactions module. """

# Copyright (C) 2023, 2025 embedded brains GmbH & Co. KG
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

from specware import run_command

from .util import create_package, get_and_clear_log


def _format_path(tmp_dir: Path) -> str:
    path_2 = str(tmp_dir)
    for char in "/-_.":
        path_2 = path_2.replace(char, f"{char}\u200b")
    return path_2


def _format_path_2(tmp_dir: Path) -> str:
    return "\u200b".join(char for char in str(tmp_dir))


def test_runactions(caplog, tmpdir):
    tmp_dir = Path(tmpdir)
    package = create_package(caplog, tmp_dir, Path("spec-packagebuild"),
                             ["run-actions"])

    prefix_dir = Path(package["prefix-directory"])
    status = run_command(["git", "init"], str(prefix_dir))
    assert status == 0

    director = package.director
    director.build_package()
    log = get_and_clear_log(caplog)
    assert f"/pkg/make/run-actions: make directory: {tmp_dir}/pkg/build/some/more/dirs" in log
    assert f"/pkg/make/run-actions: remove empty directory: {tmp_dir}/pkg/build/some/more/dirs" in log
    assert f"/pkg/make/run-actions: remove empty directory: {tmp_dir}/pkg/build/some/more" in log
    assert f"/pkg/make/run-actions: remove empty directory: {tmp_dir}/pkg/build/some" in log
    assert f"/pkg/make/run-actions: remove directory tree: {tmp_dir}/pkg/build/some" in log
    assert f"/pkg/make/run-actions: run in '{tmp_dir}/pkg/build': 'git' 'foobar'" in log
    assert f"/pkg/make/run-actions: run in '{tmp_dir}/pkg/build': 'git' 'status'" in log
    description = director["/pkg/output/run-actions"][
        "build-description"].replace(str(tmp_dir), "").replace(
            _format_path(tmp_dir), "").replace(_format_path_2(tmp_dir), "")
    assert description == """Run the following actions:

.. code-block:: none
    :linenos:

    ​m​k​d​i​r​ ​-​p​ ​​/​p​k​g​/​b​u​i​l​d​/​s​o​m​e​/​m​o​r​e​/​d​i​r​s
    ​t​o​u​c​h​ ​​/​p​k​g​/​b​u​i​l​d​/​s​o​m​e​/​m​o​r​e​/​d​i​r​s​/​f​i​l​e
    ​t​o​u​c​h​ ​​/​p​k​g​/​b​u​i​l​d​/​s​o​m​e​/​m​o​r​e​/​d​i​r​s​/​f​i​l​e
    ​r​m​ ​​/​p​k​g​/​b​u​i​l​d​/​s​o​m​e​/​m​o​r​e​/​d​i​r​s​/​f​i​l​e
    ​r​m​ ​-​r​ ​​/​p​k​g​/​b​u​i​l​d​/​s​o​m​e​/​m​o​r​e​/​d​i​r​s
    ​m​k​d​i​r​ ​-​p​ ​​/​p​k​g​/​b​u​i​l​d​/​s​o​m​e​/​m​o​r​e​/​d​i​r​s
    ​t​o​u​c​h​ ​​/​p​k​g​/​b​u​i​l​d​/​s​o​m​e​/​m​o​r​e​/​d​i​r​s​/​f​i​l​e
    ​f​i​n​d​ ​​/​p​k​g​/​b​u​i​l​d​/​s​o​m​e​ ​-​t​y​p​e​ ​d​ ​-​e​m​p​t​y​ ​-​e​x​e​c​ ​r​m​d​i​r​ ​{​}​ ​\​;
    ​r​m​ ​​/​p​k​g​/​b​u​i​l​d​/​s​o​m​e​/​m​o​r​e​/​d​i​r​s​/​f​i​l​e
    ​f​i​n​d​ ​​/​p​k​g​/​b​u​i​l​d​/​s​o​m​e​ ​-​t​y​p​e​ ​d​ ​-​e​m​p​t​y​ ​-​e​x​e​c​ ​r​m​d​i​r​ ​{​}​ ​\​;
    ​m​k​d​i​r​ ​-​p​ ​​/​p​k​g​/​b​u​i​l​d​/​s​o​m​e​/​m​o​r​e​/​d​i​r​s
    ​t​o​u​c​h​ ​​/​p​k​g​/​b​u​i​l​d​/​s​o​m​e​/​m​o​r​e​/​d​i​r​s​/​f​i​l​e
    ​r​m​ ​-​r​f​ ​​/​p​k​g​/​b​u​i​l​d​/​s​o​m​e​/​m​o​r​e
    ​r​m​ ​-​r​f​ ​​/​p​k​g​/​b​u​i​l​d​/​s​o​m​e​/​m​o​r​e
    ​r​m​ ​-​r​ ​​/​p​k​g​/​b​u​i​l​d​/​s​o​m​e
    ​m​k​d​i​r​ ​-​p​ ​​/​p​k​g​/​b​u​i​l​d​/​s​o​m​e​/​m​o​r​e​/​d​i​r​s
    ​t​o​u​c​h​ ​​/​p​k​g​/​b​u​i​l​d​/​s​o​m​e​/​m​o​r​e​/​d​i​r​s​/​f​i​l​e
    ​r​m​ ​​/​p​k​g​/​b​u​i​l​d​/​s​o​m​e​/​m​o​r​e​/​d​i​r​s​/​f​i​l​e
    ​t​o​u​c​h​ ​​/​p​k​g​/​b​u​i​l​d​/​s​o​m​e​/​m​o​r​e​/​d​i​r​s​/​f​i​l​e
    ​r​m​ ​-​r​ ​​/​p​k​g​/​b​u​i​l​d​/​s​o​m​e​/​m​o​r​e
    ​r​m​ ​-​r​ ​​/​p​k​g​/​b​u​i​l​d​/​s​o​m​e
    ​#​ ​d​i​s​c​a​r​d​ ​d​i​r​e​c​t​o​r​y​ ​s​t​a​t​e​ ​s​p​e​c​:​/​p​k​g​/​o​u​t​p​u​t​/​r​u​n​-​a​c​t​i​o​n​s
    ​#​ ​d​i​s​c​a​r​d​ ​d​i​r​e​c​t​o​r​y​ ​s​t​a​t​e​ ​s​p​e​c​:​/​p​k​g​/​o​u​t​p​u​t​/​r​u​n​-​a​c​t​i​o​n​s
    ​#​ ​c​l​e​a​r​ ​d​i​r​e​c​t​o​r​y​ ​s​t​a​t​e​ ​s​p​e​c​:​/​p​k​g​/​o​u​t​p​u​t​/​r​u​n​-​a​c​t​i​o​n​s
    ​#​ ​c​l​e​a​r​ ​d​i​r​e​c​t​o​r​y​ ​s​t​a​t​e​ ​s​p​e​c​:​/​p​k​g​/​o​u​t​p​u​t​/​r​u​n​-​a​c​t​i​o​n​s
    ​#​ ​a​d​d​ ​f​i​l​e​s​ ​f​r​o​m​ ​​/​a​r​c​h​i​v​e​.​t​a​r​.​x​z​ ​t​o​ ​d​i​r​e​c​t​o​r​y​ ​s​t​a​t​e​ ​s​p​e​c​:​/​p​k​g​/​o​u​t​p​u​t​/​r​u​n​-​a​c​t​i​o​n​s
    ​#​ ​c​l​e​a​r​ ​d​i​r​e​c​t​o​r​y​ ​s​t​a​t​e​ ​s​p​e​c​:​/​p​k​g​/​o​u​t​p​u​t​/​r​u​n​-​a​c​t​i​o​n​s
    ​m​k​d​i​r​ ​-​p​ ​​/​p​k​g​/​b​u​i​l​d​/​s​o​m​e​/​m​o​r​e​/​d​i​r​s
    ​t​o​u​c​h​ ​​/​p​k​g​/​b​u​i​l​d​/​s​o​m​e​/​m​o​r​e​/​d​i​r​s​/​f​i​l​e
    ​#​ ​a​d​d​ ​f​i​l​e​s​ ​t​o​ ​d​i​r​e​c​t​o​r​y​ ​s​t​a​t​e​ ​s​p​e​c​:​/​p​k​g​/​o​u​t​p​u​t​/​r​u​n​-​a​c​t​i​o​n​s
    ​#​ ​a​d​d​ ​f​i​l​e​s​ ​o​f​ ​d​i​r​e​c​t​o​r​y​ ​​/​p​k​g​/​b​u​i​l​d​/​s​o​m​e​/​m​o​r​e​ ​t​o​ ​d​i​r​e​c​t​o​r​y​ ​s​t​a​t​e​ ​s​p​e​c​:​/​p​k​g​/​o​u​t​p​u​t​/​r​u​n​-​a​c​t​i​o​n​s
    ​m​k​d​i​r​ ​-​p​ ​​/​p​k​g​/​b​u​i​l​d​/​r​u​n​-​a​c​t​i​o​n​s​/​d​i​r​s
    ​t​o​u​c​h​ ​​/​p​k​g​/​b​u​i​l​d​/​r​u​n​-​a​c​t​i​o​n​s​/​d​i​r​s​/​f​i​l​e
    ​m​k​d​i​r​ ​-​p​ ​​/​p​k​g​/​b​u​i​l​d​/​r​u​n​-​a​c​t​i​o​n​s​/​u
    ​#​ ​a​d​d​ ​f​i​l​e​s​ ​o​f​ ​b​e​l​o​w​ ​c​o​p​y​ ​t​o​ ​d​i​r​e​c​t​o​r​y​ ​s​t​a​t​e​ ​s​p​e​c​:​/​p​k​g​/​o​u​t​p​u​t​/​r​u​n​-​a​c​t​i​o​n​s
    ​c​p​ ​-​r​ ​​/​p​k​g​/​b​u​i​l​d​/​s​o​m​e​/​m​o​r​e​ ​​/​p​k​g​/​b​u​i​l​d​/​r​u​n​-​a​c​t​i​o​n​s​/​u
    ​#​ ​a​d​d​ ​f​i​l​e​s​ ​o​f​ ​b​e​l​o​w​ ​m​o​v​e​ ​t​o​ ​d​i​r​e​c​t​o​r​y​ ​s​t​a​t​e​ ​s​p​e​c​:​/​p​k​g​/​o​u​t​p​u​t​/​r​u​n​-​a​c​t​i​o​n​s
    ​r​s​y​n​c​ ​-​a​ ​-​-​r​e​m​o​v​e​-​s​o​u​r​c​e​-​f​i​l​e​s​ ​​/​p​k​g​/​b​u​i​l​d​/​r​u​n​-​a​c​t​i​o​n​s​/​u​/​d​i​r​s​/​*​ ​​/​p​k​g​/​b​u​i​l​d​/​r​u​n​-​a​c​t​i​o​n​s​/​v
    ​t​o​u​c​h​ ​​/​p​k​g​/​b​u​i​l​d​/​r​u​n​-​a​c​t​i​o​n​s​/​u​/​d​i​r​s​/​f​i​l​e
    ​#​ ​c​l​e​a​r​ ​d​i​r​e​c​t​o​r​y​ ​s​t​a​t​e​ ​s​p​e​c​:​/​p​k​g​/​o​u​t​p​u​t​/​r​u​n​-​a​c​t​i​o​n​s
    ​#​ ​c​r​e​a​t​e​ ​I​N​I​ ​f​i​l​e​ ​​/​p​k​g​/​b​u​i​l​d​/​r​u​n​-​a​c​t​i​o​n​s​/​f​o​o​.​i​n​i
    ​#​ ​c​r​e​a​t​e​ ​I​N​I​ ​f​i​l​e​ ​​/​p​k​g​/​b​u​i​l​d​/​r​u​n​-​a​c​t​i​o​n​s​/​f​o​o​.​i​n​i
    ​#​ ​c​r​e​a​t​e​ ​K​c​o​n​f​i​g​ ​f​i​l​e​ ​​/​p​k​g​/​b​u​i​l​d​/​r​u​n​-​a​c​t​i​o​n​s​/​f​o​o​.​i​n​i
    ​#​ ​s​u​b​s​t​i​t​u​t​e​ ​c​o​n​t​e​n​t
    ​c​p​ ​​/​d​i​r​/​a​.​t​x​t​ ​​/​p​k​g​/​b​u​i​l​d​/​r​u​n​-​a​c​t​i​o​n​s​/​.​/​d​i​r​/​a​.​t​x​t
    ​c​p​ ​​/​d​i​r​/​s​u​b​d​i​r​/​c​.​t​x​t​ ​​/​p​k​g​/​b​u​i​l​d​/​r​u​n​-​a​c​t​i​o​n​s​/​.​/​d​i​r​/​s​u​b​d​i​r​/​c​.​t​x​t
    ​c​p​ ​​/​d​i​r​/​s​u​b​d​i​r​/​d​.​t​x​t​ ​​/​p​k​g​/​b​u​i​l​d​/​r​u​n​-​a​c​t​i​o​n​s​/​.​/​d​i​r​/​s​u​b​d​i​r​/​d​.​t​x​t
    ​#​ ​s​u​b​s​t​i​t​u​t​e​ ​c​o​n​t​e​n​t
    ​c​p​ ​​/​d​i​r​/​s​u​b​d​i​r​/​c​.​t​x​t​ ​​/​p​k​g​/​b​u​i​l​d​/​r​u​n​-​a​c​t​i​o​n​s​/​d​i​r​/​a​.​t​x​t
    ​#​ ​s​u​b​s​t​i​t​u​t​e​ ​c​o​n​t​e​n​t
    ​c​p​ ​​/​d​i​r​/​a​.​t​x​t​ ​​/​p​k​g​/​b​u​i​l​d​/​r​u​n​-​a​c​t​i​o​n​s​/​s​o​m​e​/​o​t​h​e​r​/​d​i​r​/​a​.​t​x​t
    ​c​p​ ​​/​d​i​r​/​s​u​b​d​i​r​/​c​.​t​x​t​ ​​/​p​k​g​/​b​u​i​l​d​/​r​u​n​-​a​c​t​i​o​n​s​/​s​o​m​e​/​o​t​h​e​r​/​d​i​r​/​s​u​b​d​i​r​/​c​.​t​x​t
    ​c​p​ ​​/​d​i​r​/​s​u​b​d​i​r​/​d​.​t​x​t​ ​​/​p​k​g​/​b​u​i​l​d​/​r​u​n​-​a​c​t​i​o​n​s​/​s​o​m​e​/​o​t​h​e​r​/​d​i​r​/​s​u​b​d​i​r​/​d​.​t​x​t
    ​#​ ​s​u​b​s​t​i​t​u​t​e​ ​c​o​n​t​e​n​t
    ​c​p​ ​​/​d​i​r​/​s​u​b​d​i​r​/​c​.​t​x​t​ ​​/​p​k​g​/​b​u​i​l​d​/​r​u​n​-​a​c​t​i​o​n​s​/​s​o​m​e​/​o​t​h​e​r​/​f​i​l​e​.​t​x​t
    ​c​d​ ​​/​p​k​g​/​b​u​i​l​d​ ​&​&​ ​g​i​t​ ​f​o​o​b​a​r
    ​e​n​v​ ​-​i​ ​-​u​ ​F​O​O​B​A​R​ ​B​L​U​B​=​b​l​u​b​-​p​r​e​p​e​n​d​:​b​l​u​b​:​b​l​u​b​-​a​p​p​e​n​d​ ​g​i​t​ ​s​t​a​t​u​s
    ​c​d​ ​​/​p​k​g​/​b​u​i​l​d​ ​&​&​ ​g​i​t​ ​s​t​a​t​u​s
    ​e​c​h​o​ ​f​o​o​ ​b​a​r​ ​>​ ​​/​p​k​g​/​b​u​i​l​d​/​s​t​d​o​u​t​-​a​b​s​o​l​u​t​e​.​t​x​t
    ​c​d​ ​​/​p​k​g​/​b​u​i​l​d​ ​&​&​ ​e​c​h​o​ ​b​a​r​ ​f​o​o​ ​>​ ​s​t​d​o​u​t​-​r​e​l​a​t​i​v​e​.​t​x​t

Represent the files:

- :file:`/​pkg/​build/​run-​actions/​dir/​a.​txt`

- :file:`/​pkg/​build/​run-​actions/​dir/​subdir/​c.​txt`

- :file:`/​pkg/​build/​run-​actions/​dir/​subdir/​d.​txt`

- :file:`/​pkg/​build/​run-​actions/​foo.​ini`

- :file:`/​pkg/​build/​run-​actions/​some/​other/​file.​txt`"""
    build_dir = tmp_dir / "pkg" / "build"
    assert (build_dir / "stdout-absolute.txt").read_text() == "foo bar\n"
    assert (build_dir / "stdout-relative.txt").read_text() == "bar foo\n"
    assert not Path("stdout-relative.txt").exists()
