#!/usr/bin/env python3
"""Regression tests for dxrice_force_close_window.py (SUPER+C).

Covers the live incident documented in that module's own docstring: a
Quickshell panel (Theme/Taskbar/Quick Settings/Calendar) can hold keyboard
focus, and since every panel belongs to the SAME process as the bars/dock,
naively walking up to that process's root and killing the whole subtree
takes down the entire shell instead of closing one panel -- with no
automatic recovery. These tests exercise the real, committed functions
against real child processes (never anything on the live desktop), so a
future edit to this file can't silently reintroduce the same crash.

Run: python3 scripts/dxrice_test_force_close_window.py [-v]
"""
import importlib
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dxrice_force_close_window as fcw


class TestForceCloseWindow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # A process whose own /proc/pid/exe basename is literally "qs" --
        # must be an actual copy, not a symlink: a symlink's /proc/pid/exe
        # resolves through to the symlink's TARGET (e.g. /usr/bin/sleep),
        # not to the symlink's own name, so it would silently fail to
        # reproduce the real condition being tested.
        cls.fakebin = tempfile.mkdtemp(prefix="dxrice_test_fakebin_")
        cls.fake_qs = os.path.join(cls.fakebin, "qs")
        shutil.copy(shutil.which("sleep"), cls.fake_qs)
        os.chmod(cls.fake_qs, 0o755)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.fakebin, ignore_errors=True)

    def setUp(self):
        importlib.reload(fcw)
        self._procs = []

    def tearDown(self):
        for p in self._procs:
            if p.poll() is None:
                p.terminate()
                try:
                    p.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    p.kill()

    def _spawn(self, *args):
        p = subprocess.Popen(list(args))
        self._procs.append(p)
        time.sleep(0.15)
        return p

    def test_quickshell_owned_window_is_never_killed(self):
        """The exact live incident: the active window's process resolves
        to the real quickshell binary name -- must redirect to the IPC
        close-current call and must never touch the process."""
        qs_proc = self._spawn(self.fake_qs, "300")
        calls = []
        fcw.hyprctl_json = lambda args: {"pid": qs_proc.pid}
        fcw.subprocess.run = lambda cmd, **kw: calls.append(cmd)

        fcw.main()

        self.assertIsNone(qs_proc.poll(), "quickshell's own process was killed")
        self.assertEqual(len(calls), 1, f"expected exactly one IPC call, got: {calls}")
        self.assertEqual(calls[0][:2], ["qs", "-p"], f"not a qs ipc invocation: {calls[0]}")
        self.assertEqual(calls[0][-3:], ["call", "shell", "closeCurrent"], f"wrong IPC target: {calls[0]}")

    def test_normal_application_is_still_force_closed(self):
        """Unrelated regular app: existing kill behavior must be
        completely unchanged by the quickshell guard."""
        victim = self._spawn("sleep", "300")
        fcw.hyprctl_json = lambda args: {"pid": victim.pid}

        fcw.main()
        victim.wait(timeout=2)

        self.assertIsNotNone(victim.poll(), "a normal application was not force-closed")

    def test_no_active_window_is_a_safe_noop(self):
        fcw.hyprctl_json = lambda args: None
        fcw.main()  # must not raise


if __name__ == "__main__":
    unittest.main(verbosity=2)
