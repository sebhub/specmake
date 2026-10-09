# SPDX-License-Identifier: BSD-2-Clause
""" Directory state with run actions support. """

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

import os
from typing import Optional

from specitems import Item
from specware import run_command

from .dirstatebase import DirectoryStateBase
from .pkgitems import BuildItemMapper, PackageBuildDirector
from .runactions import RunActionsProvider


class DirectoryState(DirectoryStateBase):
    """ Produces a directory state by running actions. """

    def __init__(self,
                 director: PackageBuildDirector,
                 item: Item,
                 mapper: Optional[BuildItemMapper] = None) -> None:
        super().__init__(director, item, mapper)
        self.run_actions_provider = RunActionsProvider(self)

    def run_actions(self) -> None:
        """ Run the optional actions. """
        self.run_actions_provider.run(self.item.get("actions", {}))

    def run_post_actions(self) -> None:
        """ Run the optional post-actions. """
        self.run_actions_provider.run(self.item.get("post-actions", {}))

    def run(self) -> None:
        super().run()
        self.run_actions()


class RepositoryState(DirectoryState):
    """ Maintains a repository state. """

    def __init__(self, director: PackageBuildDirector, item: Item):
        super().__init__(director, item)
        director.add_submodule(self.directory)

    def lazy_verify(self) -> bool:
        stdout: list[str] = []
        status = run_command(["git", "rev-parse", "HEAD"], self.directory,
                             stdout)
        return status == 0 and self["commit"] == stdout[0].strip()

    def discard(self) -> None:
        super().discard()
        directory = self.git_directory
        if directory is None:
            return
        status = run_command([
            "git", "rm", "--cached", "--ignore-unmatch", "--quiet", "--",
            os.path.relpath(self.directory, directory)
        ], directory)
        assert status == 0
