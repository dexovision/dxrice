#!/usr/bin/env python3
"""What the screen shows while the infinite desktop is being panned
(SUPER+ALT and moving the mouse): the bar steps aside and the cursor hides,
so the desktop moves under nothing, and both come back the moment the pan
ends.

The pan daemon (dxrice_infinite_desktop_core.py) reports motion and its
state here; this decides:

  - it hides only once the pointer has really moved with the keys held
    (`threshold` px), never on SUPER+ALT alone -- that is also how other
    shortcuts start;
  - it shows again when the keys are let go, or when no motion has come for
    `idle` seconds with them still held (a key-up the reader missed -- a VT
    switch, an unplugged keyboard -- must not leave either hidden);
  - restore() shows both unconditionally: the daemon calls it when it starts
    (so a crash mid-pan is undone by the restart) and when it exits, and the
    systemd unit runs `dxrice_pan_presence.py restore` after it stops.

The shell reads $XDG_RUNTIME_DIR/dxrice/panning ("1 <unix time>" while
hidden, refreshed every `refresh` s; "0" otherwise) and treats a "1" older
than 2 s as "0", so a daemon killed outright can't keep the bar away either.
The cursor goes through Hyprland's own option (cursor:invisible), set with
`hyprctl eval`.

    dxrice_pan_presence.py restore      show the bar and the cursor now
"""
import os
import subprocess
import sys
import time


def default_path():
    base = os.environ.get("XDG_RUNTIME_DIR") or os.path.join("/tmp", f"dxrice-{os.getuid()}")
    return os.path.join(base, "dxrice", "panning")


def hyprctl_cursor(hidden):
    """Hyprland's cursor:invisible, at runtime (a failure is ignored: the
    pan must never stop on it)."""
    try:
        subprocess.run(["hyprctl", "eval", "hl.config({ cursor = { invisible = %s } })" % ("true" if hidden else "false")],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
    except (OSError, subprocess.SubprocessError):
        pass


class PanPresence:
    def __init__(self, path=None, cursor=hyprctl_cursor, clock=time.monotonic, wall=time.time,
                 threshold=8.0, idle=1.2, refresh=0.5):
        self.path = path or default_path()
        self.cursor = cursor
        self.clock = clock
        self.wall = wall
        self.threshold = threshold
        self.idle = idle
        self.refresh = refresh
        self.hidden = False
        self._moved = 0.0
        self._last_motion = None
        self._last_write = None

    def _write(self, text):
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w") as f:
                f.write(text)
            os.replace(tmp, self.path)
        except OSError:
            pass
        self._last_write = self.clock()

    def _set(self, hidden):
        self.hidden = hidden
        self._write("1 %.3f" % self.wall() if hidden else "0")
        try:
            self.cursor(hidden)
        except Exception:
            pass

    def motion(self, dx, dy):
        """The desktop moved by (dx, dy) during a pan."""
        now = self.clock()
        self._last_motion = now
        if not self.hidden:
            self._moved += abs(dx) + abs(dy)
            if self._moved >= self.threshold:
                self._set(True)
        elif now - self._last_write >= self.refresh:
            self._write("1 %.3f" % self.wall())

    def tick(self, active):
        """Called every frame of the pan loop; `active` is the keys' state."""
        if not active:
            self.end()
            return
        if self.hidden and self._last_motion is not None and self.clock() - self._last_motion > self.idle:
            self._set(False)
            self._moved = 0.0

    def end(self):
        """The pan is over (the keys were let go)."""
        self._moved = 0.0
        self._last_motion = None
        if self.hidden:
            self._set(False)

    def restore(self):
        """Show both now, whatever the state was thought to be."""
        self._moved = 0.0
        self._last_motion = None
        self._set(False)


def main(argv):
    if argv == ["restore"]:
        PanPresence().restore()
        return 0
    print("usage: dxrice_pan_presence.py restore", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
