#!/usr/bin/env python3
"""The infinite-desktop daemon, run for real against fake input devices and a
fake Hyprland.

Each fake device is a FIFO the test writes raw evdev events into; `evdev` is
replaced by a stand-in that lists those FIFOs and reports their
capabilities. Hyprland is a Unix socket served by this test: it answers the
daemon's JSON queries and records every dispatch.

Checks that SUPER+ALT+mouse pans every floating window by the same amount,
that SUPER+drag against a screen edge pushes the other windows, that motion
from before a pan doesn't leak into it, and that the daemon doesn't wake up
while nothing is held (it used to poll at 60 Hz in two threads).

  python3 scripts/dxrice_test_infinite_desktop.py
"""
import json
import os
import re
import socket
import struct
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
DAEMON = os.path.join(HERE, "dxrice_infinite_desktop_core.py")

EV_KEY, EV_REL = 1, 2
REL_X, REL_Y = 0, 1
KEY_LEFTMETA, KEY_LEFTALT, BTN_LEFT = 125, 56, 272
FMT = "llHHi"

FAKE_EVDEV = textwrap.dedent('''
    import json, os
    _devs = json.loads(os.environ["FAKE_EVDEV"])
    class ecodes:
        EV_KEY = 1; EV_REL = 2; REL_X = 0; REL_Y = 1; BTN_LEFT = 272
        KEY_A = 30; KEY_Z = 44; KEY_LEFTSHIFT = 42; KEY_LEFTMETA = 125; KEY_RIGHTMETA = 126
    def list_devices():
        return list(_devs)
    class InputDevice:
        def __init__(self, path):
            self.kind = _devs[path]
        def capabilities(self):
            if self.kind == "mouse":
                return {ecodes.EV_KEY: [ecodes.BTN_LEFT], ecodes.EV_REL: [ecodes.REL_X, ecodes.REL_Y]}
            if self.kind == "keyboard":
                return {ecodes.EV_KEY: [30, 44, 42, 125]}
            return {ecodes.EV_KEY: [1]}
        def close(self):
            pass
''')


class FakeHyprland(threading.Thread):
    def __init__(self, path, clients, monitor, active):
        super().__init__(daemon=True)
        self.clients, self.monitor, self.active = clients, monitor, active
        self.dispatches = []
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.bind(path)
        self.sock.listen(64)

    def run(self):
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            with conn:
                cmd = conn.recv(1 << 20).decode()
                reply = b""
                if cmd == "j/activeworkspace":
                    reply = json.dumps({"id": 1}).encode()
                elif cmd == "j/clients":
                    reply = json.dumps(self.clients).encode()
                elif cmd == "j/monitors":
                    reply = json.dumps([self.monitor]).encode()
                elif cmd == "j/activewindow":
                    reply = json.dumps(self.active).encode()
                else:
                    self.dispatches.append(cmd)
                try:
                    conn.sendall(reply)
                except OSError:
                    pass


def window(addr, x, y, w=400, h=300):
    return {"address": addr, "at": [x, y], "size": [w, h], "floating": True, "workspace": {"id": 1}}


class Rig:
    def __init__(self, clients, active):
        self.tmp = tempfile.mkdtemp()
        sig = "testsig"
        os.makedirs(os.path.join(self.tmp, "hypr", sig))
        self.hypr = FakeHyprland(os.path.join(self.tmp, "hypr", sig, ".socket.sock"), clients,
                                 {"x": 0, "y": 0, "width": 1920, "height": 1080, "focused": True,
                                  "refreshRate": 60.0}, active)
        self.hypr.start()
        self.kbd = os.path.join(self.tmp, "kbd")
        self.mouse = os.path.join(self.tmp, "mouse")
        os.mkfifo(self.kbd)
        os.mkfifo(self.mouse)
        shim = os.path.join(self.tmp, "shim")
        os.makedirs(shim)
        with open(os.path.join(shim, "evdev.py"), "w") as f:
            f.write(FAKE_EVDEV)
        env = dict(os.environ, XDG_RUNTIME_DIR=self.tmp, HYPRLAND_INSTANCE_SIGNATURE=sig,
                   PYTHONPATH=shim, FAKE_EVDEV=json.dumps({self.kbd: "keyboard", self.mouse: "mouse"}))
        self.proc = subprocess.Popen([sys.executable, DAEMON, "1.0"], env=env,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        # opening a FIFO's write end blocks until the daemon opens it to read
        self.kbd_w = open(self.kbd, "wb", buffering=0)
        self.mouse_w = open(self.mouse, "wb", buffering=0)
        time.sleep(0.3)

    def send(self, dev, etype, code, value):
        (self.kbd_w if dev == "kbd" else self.mouse_w).write(struct.pack(FMT, 0, 0, etype, code, value))

    def key(self, code, down):
        self.send("kbd", EV_KEY, code, 1 if down else 0)

    def move(self, dx, dy, steps=10):
        for _ in range(steps):
            self.send("mouse", EV_REL, REL_X, dx)
            self.send("mouse", EV_REL, REL_Y, dy)
            time.sleep(0.01)

    def moves(self):
        """{address: last (x, y) dispatched}"""
        out = {}
        for cmd in self.hypr.dispatches:
            for m in re.finditer(r'window = "address:(\w+)", x = (-?\d+), y = (-?\d+)', cmd):
                out[m.group(1)] = (int(m.group(2)), int(m.group(3)))
        return out

    def switches(self):
        total = 0
        for tid in os.listdir(f"/proc/{self.proc.pid}/task"):
            with open(f"/proc/{self.proc.pid}/task/{tid}/status") as f:
                for line in f:
                    if "ctxt_switches" in line:
                        total += int(line.split()[1])
        return total

    def close(self):
        self.proc.kill()
        self.proc.wait()
        self.hypr.sock.close()
        for f in (self.kbd_w, self.mouse_w):
            try:
                f.close()
            except OSError:
                pass


class TestInfiniteDesktop(unittest.TestCase):
    def setUp(self):
        self.clients = [window("0xa", 100, 100), window("0xb", 900, 400), window("0xc", -600, 200)]
        self.rig = Rig(self.clients, active=self.clients[0])

    def tearDown(self):
        self.rig.close()

    def test_super_alt_pans_every_floating_window_by_the_same_amount(self):
        r = self.rig
        r.key(KEY_LEFTMETA, True)
        r.key(KEY_LEFTALT, True)
        time.sleep(0.1)
        r.move(5, -3, steps=20)
        time.sleep(0.3)
        r.key(KEY_LEFTALT, False)
        r.key(KEY_LEFTMETA, False)
        moves = r.moves()
        self.assertEqual(set(moves), {"0xa", "0xb", "0xc"})
        deltas = {(x - c["at"][0], y - c["at"][1]) for c in self.clients for a, (x, y) in moves.items()
                  if a == c["address"]}
        self.assertEqual(deltas, {(100, -60)})

    def test_motion_before_a_pan_is_not_part_of_it(self):
        r = self.rig
        r.move(50, 50, steps=10)        # nothing held: no pan
        time.sleep(0.2)
        self.assertEqual(r.moves(), {})
        r.key(KEY_LEFTMETA, True)
        r.key(KEY_LEFTALT, True)
        time.sleep(0.1)
        r.move(2, 0, steps=5)
        time.sleep(0.3)
        x, y = r.moves()["0xa"]
        self.assertEqual((x, y), (110, 100))

    def test_super_drag_at_the_edge_pushes_the_other_windows(self):
        # the dragged window sits against the right edge
        r = self.rig
        r.hypr.active = window("0xa", 1920 - 400, 100)
        r.hypr.clients[0] = r.hypr.active
        r.key(KEY_LEFTMETA, True)
        r.send("mouse", EV_KEY, BTN_LEFT, 1)
        time.sleep(0.15)
        r.move(10, 0, steps=10)
        time.sleep(0.3)
        r.send("mouse", EV_KEY, BTN_LEFT, 0)
        r.key(KEY_LEFTMETA, False)
        moves = r.moves()
        self.assertNotIn("0xa", moves, "the dragged window itself is Hyprland's to move")
        self.assertIn("0xb", moves)
        self.assertLess(moves["0xb"][0], 900, "pushed the others left, away from the edge")

    def test_idle_daemon_does_not_wake_up(self):
        r = self.rig
        time.sleep(1.0)
        before = r.switches()
        time.sleep(5.0)
        rate = (r.switches() - before) / 5.0
        # the device rescan every 3 s and the readers blocked on their FIFOs
        # are all that's left; the old loops alone made ~120/s
        self.assertLess(rate, 5, f"{rate:.1f} wakeups/s while idle")
        self.assertEqual(r.hypr.dispatches, [])


if __name__ == "__main__":
    try:
        import evdev  # noqa: F401  (only to know the real daemon could run)
    except ImportError:
        pass
    unittest.main(verbosity=2)
