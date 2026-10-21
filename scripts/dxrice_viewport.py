#!/usr/bin/env python3
"""How far each workspace's infinite desktop has been panned, for anything
that should move with it (world-attached desktop widgets).

The pan daemon (dxrice_infinite_desktop_core.py) moves the windows itself;
it also reports every step here, and this keeps a running total per
workspace and writes it to $XDG_RUNTIME_DIR/dxrice/viewport.json --
at most every `interval` seconds while panning, and once more when the pan
stops -- as {"offsets": {"<workspace id>": [dx, dy], ...}}. Runtime state
only: it starts at zero with the session, and nothing else writes it.
"""
import json
import os
import time



def default_path():
    base = os.environ.get("XDG_RUNTIME_DIR") or os.path.join("/tmp", f"dxrice-{os.getuid()}")
    return os.path.join(base, "dxrice", "viewport.json")


class Viewport:
    def __init__(self, path=None, interval=1 / 30, clock=time.monotonic):
        self.path = path or default_path()
        self.interval = interval
        self.clock = clock
        self.offsets = {}
        self._last = None
        self._dirty = False

    def record(self, workspace_id, dx, dy):
        """One pan step on a workspace; written if it has been `interval`."""
        if not dx and not dy:
            return
        key = str(workspace_id)
        x, y = self.offsets.get(key, (0, 0))
        self.offsets[key] = (x + dx, y + dy)
        self._dirty = True
        now = self.clock()
        if self._last is None or now - self._last >= self.interval:
            self.flush()

    def flush(self):
        """Write now if anything changed since the last write (the end of a pan)."""
        if not self._dirty:
            return
        self._dirty = False
        self._last = self.clock()
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w") as f:
                json.dump({"offsets": {k: [v[0], v[1]] for k, v in self.offsets.items()}}, f)
            os.replace(tmp, self.path)
        except OSError:
            pass
