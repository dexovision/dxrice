#!/usr/bin/env python3
"""How often each app has been launched from the launcher, so the ones you
use come first.

    dxrice_launcher_history.py bump NAME     one more launch of NAME
    dxrice_launcher_history.py dump          the counts, as JSON

Kept in $XDG_STATE_HOME/dxrice/launcher_history.json: {name: count}. A
missing or damaged file is an empty history, never an error.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dxrice_manifest  # noqa: E402
import dxrice_xdg  # noqa: E402

MAX_ENTRIES = 500
MAX_COUNT = 99999


def path():
    return os.path.join(dxrice_xdg.state_dir(), "launcher_history.json")


def load(p=None):
    try:
        with open(p or path()) as f:
            data = json.load(f)
        return {str(k): int(v) for k, v in data.items() if isinstance(v, (int, float))} if isinstance(data, dict) else {}
    except (OSError, ValueError, AttributeError):
        return {}


def bump(name, p=None):
    p = p or path()
    data = load(p)
    data[name] = min(MAX_COUNT, data.get(name, 0) + 1)
    if len(data) > MAX_ENTRIES:         # forget the least used
        keep = sorted(data.items(), key=lambda kv: -kv[1])[:MAX_ENTRIES]
        data = dict(keep)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    dxrice_manifest.atomic_write_bytes(p, (json.dumps(data) + "\n").encode())
    return data


def main(argv):
    if len(argv) >= 3 and argv[1] == "bump":
        bump(" ".join(argv[2:]))
        return 0
    if len(argv) >= 2 and argv[1] == "dump":
        print(json.dumps(load()))
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
