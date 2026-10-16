#!/usr/bin/env python3
"""Removes DXrice's shell-function block from a shell rc file.

  dxrice_rc_block.py strip FILE

Strips the current BEGIN/END-bracketed block and the two unmarked forms older
installers wrote, leaves everything else exactly as it was (trailing blank
lines collapse to one newline, so repeated install/strip cycles don't grow the
file), and writes atomically with the file's own permissions. install.sh
re-appends the current block after stripping on install/update.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dxrice_manifest import atomic_write_bytes

_BLOCKS = (
    re.compile(r"\n?# BEGIN dxrice shell functions \(added by DXrice's install\.sh\)\n"
               r"(?:.*\n)*?"
               r"# END dxrice shell functions\n?"),
    re.compile(r"\n?# dxrice-update \(added by DXrice's install\.sh\)\n"
               r"dxrice-update\(\) \{\n(?:.*\n)*?\}\n"),
    re.compile(r"\n?# dxrice-update / dx \(added by DXrice's install\.sh\)\n"
               r"dxrice-update\(\) \{\n(?:.*\n)*?\}\n"
               r"dx\(\) \{\n(?:.*\n)*?\}\n"),
)


def strip(content):
    for block in _BLOCKS:
        content = block.sub("\n", content, count=1)
    return content.rstrip("\n") + "\n"


def main(argv):
    if len(argv) != 3 or argv[1] != "strip":
        print(__doc__, file=sys.stderr)
        return 2
    path = argv[2]
    with open(path) as f:
        content = f.read()
    new = strip(content)
    if new != content:
        atomic_write_bytes(path, new.encode())
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
