# SPDX-License-Identifier: BSD-2-Clause
""" Provides package change descriptions. """

# Copyright (C) 2023, 2026 embedded brains GmbH & Co. KG
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

import itertools
from typing import Any

from specitems import Item, TextContent, data_digest

from .pkgitems import BuildItem, BuildItemMapper


def _issue_prologue(status: str) -> str:
    return ("At the time when the package of this version was produced, "
            f"the following {status} were present.")


def _add_issues(content: TextContent, mapper: BuildItemMapper,
                issues: set[Item], header: str, prologue: str,
                which: str) -> None:
    # pylint: disable=too-many-arguments
    # pylint: disable=too-many-positional-arguments
    with content.section(header):
        if issues:
            content.add(prologue)
            rows: list[tuple[str,
                             ...]] = [("Database", "Identifier", "Subject")]
            for item in sorted(issues):
                database = item.parent("issue-member")
                url = mapper.substitute(database["url"], item=item)
                identifier = mapper.format_link(item["identifier"], url)
                subject = item["subject"].replace("`", "\\`")
                rows.append((database["name"], identifier, subject))
            content.add_grid_table(rows, widths=[27, 14, 59], font_size=-2)
        else:
            content.add(f"""At the time when the package was produced,
there were no {which} associated.""")


def _item_data(item: Item) -> dict[str, Any]:
    data = dict(item.data)
    data.pop("workspace-hash", None)
    return data


class PackageChanges(BuildItem):
    """ Provides package change descriptions. """

    def digest(self) -> str:
        # The change descriptions depend on the package status items, on the
        # issue items which they link to, and on the issue databases.
        data: list[Any] = [super().digest()]
        databases: dict[str, Item] = {}
        for change in self.item["change-list"]:
            # Only a document builder can substitute the descriptions
            package_status = self.item.map(
                self.mapper.substitute(change["package-status"], self.item))
            data.append(_item_data(package_status))
            for link in package_status.links_to_parents("issue"):
                data.append(_item_data(link.item))
                for database in link.item.parents("issue-member"):
                    databases[database.uid] = database
        data.extend(_item_data(databases[uid]) for uid in sorted(databases))
        return data_digest({"data": data})

    def _get_issues(self, change: dict[str,
                                       str]) -> tuple[set[Item], set[Item]]:
        issues: tuple[set[Item], set[Item]] = (set(), set())
        package_status = self.item.map(change["package-status"])
        for link in package_status.links_to_parents("issue"):
            status = link["status"]
            if status != "N/A":
                issues[int(status == "open")].add(link.item)
        return issues

    def _get_change_list(self, mapper: BuildItemMapper, section_level: int,
                         with_description: bool) -> list[TextContent]:
        # pylint: disable=too-many-locals
        change_list: list[TextContent] = []
        past_issues: tuple[set[Item], set[Item]] = (set(), set())
        previous_issues: tuple[set[Item], set[Item]] = (set(), set())
        for index, change in enumerate(
                mapper.substitute_data(self.item["change-list"],
                                       item=self.item)):
            for past, previous in zip(past_issues, previous_issues):
                past.update(previous)
            content = mapper.create_content(section_level=section_level)
            if with_description:
                content.add_blank_line()
                content.open_section(change["name"])
                content.add(change["description"])
            current_issues = self._get_issues(change)
            new_issues = current_issues[1].difference(previous_issues[1])
            open_issues = current_issues[1].intersection(previous_issues[1])
            closed_issues = current_issues[0].difference(past_issues[0])
            if index == 0:
                assert not open_issues
                _add_issues(
                    content, mapper, new_issues, "Initially open issues",
                    "For the initial package version, "
                    "the following issues were open.", "open")
            else:
                status = ("newly open issues with respect to "
                          "the previous package version")
                _add_issues(content, mapper, new_issues, "Newly open issues",
                            _issue_prologue(status), status)
                status = ("open issues which were newly or already open "
                          "in the previous package version")
                _add_issues(content, mapper,
                            open_issues, "Already open issues",
                            _issue_prologue(status), status)
                _add_issues(
                    content, mapper, closed_issues, "Closed issues",
                    "For this package version, the following "
                    "issues which were newly or already open in "
                    "the previous package version were closed.", "closed")
            if with_description:
                content.close_section()
            change_list.insert(0, content)
            previous_issues = current_issues
        return change_list

    def get_change_list(self, mapper: BuildItemMapper,
                        section_level: int) -> str:
        """ Get the change list using the section level. """
        change_list = self._get_change_list(mapper, section_level, True)
        return "\n".join(itertools.chain.from_iterable(change_list))

    def get_current_issue_status(
            self, mapper: BuildItemMapper) -> tuple[set[Item], set[Item]]:
        """
        Get the closed and the open issues of the current package version.

        An issue with the status N/A is in neither set.
        """
        return self._get_issues(
            mapper.substitute_data(self.item["change-list"][-1],
                                   item=self.item))

    def get_open_issues(self, mapper: BuildItemMapper,
                        section_level: int) -> str:
        """ Get the open issues using the section level. """
        content = mapper.create_content(section_level=section_level)
        _, open_issues = self.get_current_issue_status(mapper)
        _add_issues(content, mapper, open_issues, "Open issues",
                    _issue_prologue("open issues"), "open")
        return "\n".join(content)

    def get_current_changes(self, mapper: BuildItemMapper) -> str:
        """ Get the current changes. """
        return mapper.substitute(self.item["change-list"][-1]["description"],
                                 item=self.item)

    def get_current_issues(self, mapper: BuildItemMapper,
                           section_level: int) -> str:
        """ Get the current issues using the section level. """
        change_list = self._get_change_list(mapper, section_level, False)
        return "\n".join(change_list[0])
