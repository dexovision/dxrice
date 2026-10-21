#!/usr/bin/env python3
"""How far each workspace's infinite desktop has been panned, for anything
that should move with it (world-attached desktop widgets).

Whatever moves the desktop's camera -- the pan daemon
(dxrice_infinite_desktop_core.py) while you drag, the overview when it
brings a window into view, the window mover pushing the rest aside at a
screen edge -- reports the step here, and the running total per workspace
lives in $XDG_RUNTIME_DIR/dxrice/viewport.json as
{"offsets": {"<workspace id>": [dx, dy], ...}}. Runtime state only: it
starts at zero with the session.

Several processes add to it, so no one of them keeps the total: each
collects its own steps and adds them to the file under a lock (read, add,
write atomically) -- at most every `interval` seconds while a pan goes on,
and once more when it stops.

    dxrice_viewport.py add <workspace> <dx> <dy>     one step, from a script
"""
import fcntl
import json
import os
import sys
import time


def default_path():
    base = os.environ.get("XDG_RUNTIME_DIR") or os.path.join("/tmp", f"dxrice-{os.getuid()}")
    return os.path.join(base, "dxrice", "viewport.json")


def _read(path):
    try:
        with open(path) as f:
            offsets = json.load(f).get("offsets", {})
        return {str(k): [float(v[0]), float(v[1])] for k, v in offsets.items()}
    except (OSError, ValueError, TypeError, IndexError, AttributeError):
        return {}


def add_steps(path, steps):
    """Adds {workspace: (dx, dy)} to the totals in `path`, under a lock."""
    if not steps:
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        offsets = _read(path)
        for key, (dx, dy) in steps.items():
            x, y = offsets.get(str(key), [0, 0])
            offsets[str(key)] = [x + dx, y + dy]
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump({"offsets": offsets}, f)
        os.replace(tmp, path)


class Viewport:
    def __init__(self, path=None, interval=1 / 30, clock=time.monotonic):
        self.path = path or default_path()
        self.interval = interval
        self.clock = clock
        self.pending = {}
        self._last = None

    def record(self, workspace_id, dx, dy):
        """One pan step on a workspace; written if it has been `interval`."""
        if not dx and not dy:
            return
        key = str(workspace_id)
        x, y = self.pending.get(key, (0, 0))
        self.pending[key] = (x + dx, y + dy)
        now = self.clock()
        if self._last is None or now - self._last >= self.interval:
            self.flush()

    def flush(self):
        """Write now if anything is waiting (the end of a pan)."""
        if not self.pending:
            return
        steps, self.pending = self.pending, {}
        self._last = self.clock()
        try:
            add_steps(self.path, steps)
        except OSError:
            pass


def main(argv):
    if len(argv) == 4 and argv[0] == "add":
        try:
            ws, dx, dy = argv[1], float(argv[2]), float(argv[3])
        except ValueError:
            print("usage: dxrice_viewport.py add <workspace> <dx> <dy>", file=sys.stderr)
            return 2
        if dx or dy:
            add_steps(default_path(), {ws: (dx, dy)})
        return 0
    print("usage: dxrice_viewport.py add <workspace> <dx> <dy>", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
