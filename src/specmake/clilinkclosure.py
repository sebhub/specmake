# SPDX-License-Identifier: BSD-2-Clause
"""
Provides a command line interface to get the link closure of a set of seed
items.
"""

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

import collections
import fnmatch
import logging
import os
import sys

from specitems import (Item, ItemCache, ItemCacheConfig,
                       get_item_cache_arguments, link_is_enabled)

from .util import command_arguments


def _is_below(path: str, root: str) -> bool:
    return os.path.commonpath([path, root]) == root


def _closure(item_cache: ItemCache, seeds: list[str],
             excluded: set[str]) -> dict[str, tuple[Item, str, str]]:
    reached: dict[str, tuple[Item, str, str]] = {}
    queue: collections.deque[Item] = collections.deque()
    for uid in sorted(item_cache):
        item = item_cache[uid]
        if uid not in excluded and any(
                fnmatch.fnmatchcase(item.file, seed) for seed in seeds):
            reached[uid] = (item, "", "")
            queue.append(item)
    while queue:
        item = queue.popleft()
        for link in item.links_to_parents(is_link_enabled=link_is_enabled):
            parent = link.item
            if parent.uid not in reached and parent.uid not in excluded:
                reached[parent.uid] = (parent, item.uid, link.role)
                queue.append(parent)
    return reached


def _files(reached: dict[str, tuple[Item, str, str]], root: str,
           why: bool) -> list[str]:
    files: dict[str, str] = {}
    for item, child, role in reached.values():
        if not _is_below(item.file, root):
            continue
        reason = f"\t<- {child} ({role})" if why and child else ""
        files[os.path.relpath(item.file, root)] = reason
        test_target = item.data.get("test-target")
        if test_target:
            path = os.path.normpath(os.path.join(root, test_target))
            if not _is_below(path, root):
                raise ValueError(f"{item.uid}: test-target '{test_target}' "
                                 f"is not below the root '{root}'")
            files[os.path.relpath(path,
                                  root)] = (f"\t<- {item.uid} "
                                            "(test-target)" if why else "")
    return [f"{path}{files[path]}" for path in sorted(files)]


def clilinkclosure(argv: list[str] | None = None) -> None:
    """
    Get the files of the link closure of a set of seed items.

    The closure contains the seed items and every item reachable from them
    through links to parents.  The command lists the item files and the
    test-target files of the closure which are below the root directory.
    """

    def _add_arguments(parser):
        parser.add_argument("--root",
                            required=True,
                            help="the root directory of the listed files; "
                            "the command lists files below this directory "
                            "with paths relative to it")
        parser.add_argument("--seed",
                            action="append",
                            default=[],
                            help="a glob pattern for the file path of seed "
                            "items; the option can be provided multiple "
                            "times; '*' matches also '/'")
        parser.add_argument("--exclude-uid",
                            action="append",
                            default=[],
                            help="the UID of an item which the closure "
                            "neither contains nor follows; the option can "
                            "be provided multiple times")
        parser.add_argument("--why",
                            action="store_true",
                            help="append the child UID and the link role "
                            "which pulled each item into the closure")
        parser.add_argument("--output",
                            help="the output file (default: standard output)")
        parser.add_argument("--check",
                            help="compare the closure with this file and "
                            "exit with status 1 if they differ")

    args = get_item_cache_arguments(command_arguments(argv),
                                    description=clilinkclosure.__doc__,
                                    add_arguments=(_add_arguments, ))
    item_cache = ItemCache(
        ItemCacheConfig(paths=args.spec_directories,
                        cache_directory=args.cache_directory))
    root = os.path.abspath(args.root)
    seeds = [os.path.abspath(seed) for seed in args.seed]
    reached = _closure(item_cache, seeds, set(args.exclude_uid))
    lines = _files(reached, root, args.why)
    if args.check:
        with open(args.check, "r", encoding="utf-8") as src:
            expected = src.read().splitlines()
        if lines != expected:
            for line in sorted(set(lines) - set(expected)):
                logging.error("missing in %s: %s", args.check, line)
            for line in sorted(set(expected) - set(lines)):
                logging.error("not in the closure: %s", line)
            if set(lines) == set(expected):
                logging.error("%s differs in the order or in duplicate lines",
                              args.check)
            sys.exit(1)
        return
    content = "".join(f"{line}\n" for line in lines)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as dst:
            dst.write(content)
    else:
        sys.stdout.write(content)
