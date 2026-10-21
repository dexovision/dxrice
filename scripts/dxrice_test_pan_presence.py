#!/usr/bin/env python3
"""dxrice_pan_presence.py: the bar and the cursor step aside during a pan
and always come back -- on release, after a stall (a missed key-up), when
the daemon starts and when it exits."""
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from dxrice_pan_presence import PanPresence  # noqa: E402


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


class PresenceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "dxrice", "panning")
        self.clock = Clock()
        self.cursor = []
        self.p = PanPresence(self.path, cursor=self.cursor.append, clock=self.clock, wall=lambda: 5000.0 + self.clock.t)

    def tearDown(self):
        self.tmp.cleanup()

    def flag(self):
        with open(self.path) as f:
            return f.read()

    def test_holding_the_keys_alone_hides_nothing(self):
        for _ in range(30):
            self.clock.t += 0.016
            self.p.tick(True)
        self.assertFalse(self.p.hidden)
        self.assertEqual(self.cursor, [])

    def test_a_real_pan_hides_both_and_letting_go_shows_both(self):
        self.p.motion(3, 0)
        self.assertFalse(self.p.hidden, "a 3 px nudge is not a pan yet")
        self.p.motion(4, 3)
        self.assertTrue(self.p.hidden)
        self.assertEqual(self.cursor, [True])
        self.assertTrue(self.flag().startswith("1 "))
        self.p.tick(False)
        self.assertFalse(self.p.hidden)
        self.assertEqual(self.cursor, [True, False])
        self.assertEqual(self.flag(), "0")

    def test_the_flag_stays_fresh_while_the_pan_goes_on(self):
        self.p.motion(20, 0)
        first = float(self.flag().split()[1])
        self.clock.t += 0.6
        self.p.motion(5, 0)
        self.assertGreater(float(self.flag().split()[1]), first)
        self.assertEqual(self.cursor, [True], "the cursor is set once, not every frame")

    def test_a_stall_with_the_keys_still_held_shows_both_again(self):
        # a key-up the reader missed must not leave the cursor hidden
        self.p.motion(20, 0)
        self.clock.t += 1.0
        self.p.tick(True)
        self.assertTrue(self.p.hidden)
        self.clock.t += 0.3
        self.p.tick(True)
        self.assertFalse(self.p.hidden)
        self.assertEqual(self.cursor, [True, False])
        # moving again hides them again
        self.p.motion(20, 0)
        self.assertTrue(self.p.hidden)

    def test_restore_shows_both_whatever_it_thought(self):
        self.p.restore()
        self.assertEqual(self.cursor, [False])
        self.assertEqual(self.flag(), "0")

    def test_a_failing_cursor_command_never_stops_the_pan(self):
        def broken(_hidden):
            raise RuntimeError("hyprctl gone")
        p = PanPresence(self.path, cursor=broken, clock=self.clock)
        p.motion(30, 0)
        self.assertTrue(p.hidden)
        p.end()
        self.assertFalse(p.hidden)

    def test_the_daemon_restores_on_start_and_exit(self):
        src = open(os.path.join(HERE, "dxrice_infinite_desktop_core.py")).read()
        self.assertIn("_presence.restore()", src)
        self.assertIn("atexit.register(_presence.restore)", src)
        self.assertIn("_presence.tick(active_drag)", src)
        self.assertIn("_presence.motion(idx, idy)", src)
        unit = open(os.path.join(HERE, "..", "install.sh")).read()
        self.assertIn("ExecStopPost=$python_bin $REPO_DIR/scripts/dxrice_pan_presence.py restore", unit)

    def test_the_command_line_restores(self):
        # with a fake hyprctl first on PATH: it records what it was asked
        bindir = os.path.join(self.tmp.name, "bin")
        os.makedirs(bindir)
        log = os.path.join(self.tmp.name, "calls")
        with open(os.path.join(bindir, "hyprctl"), "w") as f:
            f.write('#!/bin/sh\necho "$*" >> "%s"\n' % log)
        os.chmod(os.path.join(bindir, "hyprctl"), 0o755)
        env = dict(os.environ, PATH=bindir + ":" + os.environ.get("PATH", ""), XDG_RUNTIME_DIR=self.tmp.name)
        r = subprocess.run([sys.executable, os.path.join(HERE, "dxrice_pan_presence.py"), "restore"], env=env)
        self.assertEqual(r.returncode, 0)
        self.assertIn("invisible = false", open(log).read())
        self.assertEqual(self.flag(), "0")


if __name__ == "__main__":
    unittest.main()
