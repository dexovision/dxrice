#!/usr/bin/env python3
"""Checks a dock shortcut's command before it is saved.

    dxrice_check_command.py COMMAND

Prints nothing and exits 0 when the command looks runnable; otherwise prints
one plain sentence saying what's wrong and exits 1. The dock runs the command
with `sh -c`, so pipes and && are fine; only the first word is looked up
(after any leading VAR=value words and `env`).
"""
import os
import shlex
import shutil
import sys


def problem(cmd):
    cmd = cmd.strip()
    if not cmd:
        return "Enter a command."
    try:
        words = shlex.split(cmd, posix=True)
    except ValueError:
        return "A quote isn't closed."
    while words and "=" in words[0] and not words[0].startswith(("/", "~", ".", "=")):
        words = words[1:]
    if words and words[0] == "env":
        words = words[1:]
        while words and ("=" in words[0] or words[0].startswith("-")):
            words = words[1:]
    if not words:
        return "There's no program in that command."
    first = os.path.expandvars(os.path.expanduser(words[0]))
    if os.sep in first:
        if not os.path.isfile(first):
            return f"{first} doesn't exist."
        if not os.access(first, os.X_OK):
            return f"{first} isn't executable."
    elif first in ("cd", "exec", "export", "true", "false", ":", "set", "eval", "."):
        return None
    elif shutil.which(first) is None:
        return f"{first} isn't installed (not found in your PATH)."
    return None


def main(argv):
    msg = problem(" ".join(argv[1:]) if len(argv) > 1 else "")
    if msg:
        print(msg)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
