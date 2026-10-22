#!/usr/bin/env python3
"""What the screen shows while the infinite desktop is being panned
(SUPER+ALT and moving the mouse): the bar steps aside and the cursor hides,
so the desktop moves under nothing, and both come back the moment the pan
ends.

The pan daemon (dxrice_infinite_desktop_core.py) reports motion and its
state here; this decides:

  - it hides on the first movement with the keys held (`threshold` px), so
    the cursor is gone the instant the desktop starts to move -- never on
    SUPER+ALT alone, which is also how other shortcuts start;
  - it shows again when the keys are let go, or when no motion has come for
    `idle` seconds with them still held (a key-up the reader missed -- a VT
    switch, an unplugged keyboard -- must not leave either hidden);
  - restore() shows both unconditionally: the daemon calls it when it starts
    (so a crash mid-pan is undone by the restart) and when it exits, and the
    systemd unit runs `dxrice_pan_presence.py restore` after it stops.

Hidden is not enough: Hyprland still moves the pointer with the mouse, so a
hidden pointer would wander over the windows underneath. So where it was
when the pan began is recorded (`hyprctl cursorpos`), the pan daemon puts it
back there in every frame's batch of window moves (`pin_expr()`), and at the
end it is put back there once more before it is shown again. The pan itself
reads the mouse's raw motion (evdev), which the warps don't touch.

The shell reads $XDG_RUNTIME_DIR/dxrice/panning ("1 <unix time>" while
hidden, refreshed every `refresh` s; "0" otherwise) and treats a "1" older
than 2 s as "0", so a daemon killed outright can't keep the bar away either.
The cursor goes through Hyprland's own option (cursor:invisible), set with
`hyprctl eval`.

    dxrice_pan_presence.py restore      show the bar and the cursor now
"""
import json
import os
import subprocess
import sys
import time


def default_path():
    base = os.environ.get("XDG_RUNTIME_DIR") or os.path.join("/tmp", f"dxrice-{os.getuid()}")
    return os.path.join(base, "dxrice", "panning")


# Straight over Hyprland's socket (a tenth of a millisecond) rather than
# starting `hyprctl` (several ms): these run at the very start of a pan,
# where any delay showed as the cursor moving before it hid. `hyprctl` is the
# fallback when the socket can't be reached -- or answers anything but "ok"
# (an error reply is not empty, and taking it for success would leave the
# cursor shown and loose without a word).
def _socket(cmd):
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import dxrice_hypr_ipc
        return dxrice_hypr_ipc._send(cmd, timeout=1)
    except Exception:
        return b""


def _socket_ok(cmd):
    return _socket(cmd).strip() == b"ok"


def _parse_pos(raw):
    try:
        d = json.loads(raw)
        return int(d["x"]), int(d["y"])
    except (ValueError, KeyError, TypeError):
        return None


def hyprctl_cursor_pos():
    """(x, y) of the pointer in Hyprland's layout coordinates, or None."""
    pos = _parse_pos(_socket("j/cursorpos"))
    if pos is not None:
        return pos
    try:
        raw = subprocess.run(["hyprctl", "cursorpos", "-j"], capture_output=True, text=True, timeout=2).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    return _parse_pos(raw)


def warp_lua(pos):
    return "hl.dsp.cursor.move({ x = %d, y = %d })" % (pos[0], pos[1])


def hyprctl_warp(pos):
    if _socket_ok("dispatch " + warp_lua(pos)):
        return
    try:
        subprocess.run(["hyprctl", "dispatch", warp_lua(pos)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
    except (OSError, subprocess.SubprocessError):
        pass


def hyprctl_cursor(hidden):
    """Hyprland's cursor:invisible, at runtime (a failure is ignored: the
    pan must never stop on it)."""
    lua = "hl.config({ cursor = { invisible = %s } })" % ("true" if hidden else "false")
    if _socket_ok("eval " + lua):
        return
    try:
        subprocess.run(["hyprctl", "eval", lua], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
    except (OSError, subprocess.SubprocessError):
        pass


class PanPresence:
    def __init__(self, path=None, cursor=hyprctl_cursor, clock=time.monotonic, wall=time.time,
                 threshold=1.0, idle=1.2, refresh=0.5, cursor_pos=hyprctl_cursor_pos, warp=hyprctl_warp):
        self.path = path or default_path()
        self.cursor = cursor
        self.clock = clock
        self.wall = wall
        self.threshold = threshold
        self.idle = idle
        self.refresh = refresh
        self.cursor_pos = cursor_pos
        self.warp = warp
        self.anchor = None          # where the pointer was when the pan began
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
        if not hidden and self.anchor is not None:
            # back where it was before it is seen again
            try:
                self.warp(self.anchor)
            except Exception:
                pass
            self.anchor = None
        self.hidden = hidden
        self._write("1 %.3f" % self.wall() if hidden else "0")
        try:
            self.cursor(hidden)
        except Exception:
            pass

    def begin(self):
        """The keys went down: where the pointer is now is where it goes back
        to (read before any movement, so it is exact)."""
        if self.anchor is None and not self.hidden:
            try:
                self.anchor = self.cursor_pos()
            except Exception:
                self.anchor = None

    def motion(self, dx, dy):
        """The desktop moved by (dx, dy) during a pan."""
        now = self.clock()
        self._last_motion = now
        if self.anchor is None and not self.hidden:
            try:
                self.anchor = self.cursor_pos()
            except Exception:
                self.anchor = None
        if not self.hidden:
            self._moved += abs(dx) + abs(dy)
            if self._moved >= self.threshold:
                self._set(True)
        elif now - self._last_write >= self.refresh:
            self._write("1 %.3f" % self.wall())

    def pin_expr(self):
        """The warp that holds the pointer where the pan began, for the pan
        daemon's per-frame batch; None while nothing is held."""
        return warp_lua(self.anchor) if self.hidden and self.anchor is not None else None

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
        self.anchor = None          # (a nudge under the threshold: nothing to put back)

    def restore(self):
        """Show both now, whatever the state was thought to be (no warp:
        where the pointer started is not known any more)."""
        self._moved = 0.0
        self._last_motion = None
        self.anchor = None
        self._set(False)


def main(argv):
    if argv == ["restore"]:
        PanPresence().restore()
        return 0
    print("usage: dxrice_pan_presence.py restore", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
