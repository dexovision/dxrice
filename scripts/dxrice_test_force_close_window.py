#!/usr/bin/env python3
"""Regression tests for dxrice_force_close_window.py (SUPER+C).

Covers two real bugs, in the order they were found:

1. (pre-existing) A Quickshell panel (Theme/Taskbar/Quick Settings/
   Calendar) can hold keyboard focus, and since every panel belongs to
   the SAME process as the bars/dock, naively walking up to that
   process's root and killing the whole subtree takes down the entire
   shell instead of closing one panel -- with no automatic recovery.

2. (this pass) SUPER+C must close exactly the FOCUSED WINDOW/TOPLEVEL,
   never "whatever process owns it" -- a multi-window single-process app
   (two Brave windows sharing one browser process) previously lost BOTH
   windows when only one was targeted, because the only close mechanism
   that existed was PID-based process-tree killing. The fix tries the
   compositor's own per-window close dispatch (address-based, never
   process-scoped) first, and only falls back to process termination
   when hyprctl's own client list proves no OTHER window shares that
   process tree.

These tests exercise the real, committed functions against real child
processes (never anything on the live desktop) and a fake hyprctl JSON
layer that distinguishes `activewindow` from `clients` queries, so a
future edit to this file can't silently reintroduce either bug.

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


class FakeHypr:
    """Mimics hyprctl_json(["activewindow"]) / hyprctl_json(["clients"])
    against a hand-built client list, and close_window(address) against a
    set of addresses that "honor" a close by disappearing from that list
    -- matching how a well-behaved app's window actually vanishes from
    hyprctl's own client list once it closes, without needing a second
    real IPC layer underneath."""

    def __init__(self, clients, focused_address, honors_close=True):
        self.clients = list(clients)
        self.focused_address = focused_address
        self.honors_close = honors_close
        self.close_calls = []

    def hyprctl_json(self, args):
        if args == ["activewindow"]:
            return next((c for c in self.clients if c.get("address") == self.focused_address), None)
        if args == ["clients"]:
            return list(self.clients)
        return None

    def close_window(self, address, timeout=2):
        self.close_calls.append(address)
        if self.honors_close:
            self.clients = [c for c in self.clients if c.get("address") != address]


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
        fcw.CLOSE_WAIT_TIMEOUT = 0.2
        fcw.CLOSE_WAIT_POLL = 0.02
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

    def _install(self, fake):
        fcw.hyprctl_json = fake.hyprctl_json
        fcw.close_window = fake.close_window
        return fake

    # ------------------------------------------------------------------
    # Pre-existing regression: Quickshell's own panels must never be
    # killed as a process.
    # ------------------------------------------------------------------

    def test_quickshell_owned_window_is_never_killed(self):
        """The exact live incident: the active window's process resolves
        to the real quickshell binary name -- must redirect to the IPC
        close-current call and must never touch the process."""
        qs_proc = self._spawn(self.fake_qs, "300")
        calls = []
        fcw.hyprctl_json = lambda args: {"address": "0x1", "pid": qs_proc.pid} if args == ["activewindow"] else []
        fcw.subprocess.run = lambda cmd, **kw: calls.append(cmd)

        fcw.main()

        self.assertIsNone(qs_proc.poll(), "quickshell's own process was killed")
        self.assertEqual(len(calls), 1, f"expected exactly one IPC call, got: {calls}")
        self.assertEqual(calls[0][:2], ["qs", "-p"], f"not a qs ipc invocation: {calls[0]}")
        self.assertEqual(calls[0][-3:], ["call", "shell", "closeCurrent"], f"wrong IPC target: {calls[0]}")

    # ------------------------------------------------------------------
    # Test matrix case 1: one application, one window.
    # ------------------------------------------------------------------

    def test_01_single_app_single_window_closes_via_address(self):
        victim = self._spawn("sleep", "300")
        fake = self._install(FakeHypr(
            clients=[{"address": "0xA", "pid": victim.pid}],
            focused_address="0xA",
        ))

        fcw.main()

        self.assertEqual(fake.close_calls, ["0xA"], "did not close via the per-window address dispatch")
        self.assertIsNone(victim.poll(), "a process was killed even though the window honored the close request")

    # ------------------------------------------------------------------
    # Test matrix cases 2-3, 5-6: shared PID, multiple windows -- the
    # user's own reported bug (Brave window A + window B).
    # ------------------------------------------------------------------

    def test_02_two_windows_same_pid_closing_one_leaves_other_alive(self):
        """THE reported bug, reproduced and proven fixed: two windows
        (e.g. two Brave windows) sharing one process. Closing window A
        must leave window B alive AND must never send any signal to the
        shared process."""
        shared = self._spawn("sleep", "300")
        fake = self._install(FakeHypr(
            clients=[
                {"address": "0xA", "pid": shared.pid, "class": "brave-browser"},
                {"address": "0xB", "pid": shared.pid, "class": "brave-browser"},
            ],
            focused_address="0xA",
        ))

        fcw.main()

        self.assertEqual(fake.close_calls, ["0xA"])
        self.assertIn("0xB", [c["address"] for c in fake.clients], "window B disappeared -- it was never targeted")
        self.assertIsNone(shared.poll(), "the shared process was killed -- this would have taken window B with it")

    def test_03_three_windows_same_pid_closing_one_leaves_other_two_alive(self):
        shared = self._spawn("sleep", "300")
        fake = self._install(FakeHypr(
            clients=[
                {"address": "0xA", "pid": shared.pid},
                {"address": "0xB", "pid": shared.pid},
                {"address": "0xC", "pid": shared.pid},
            ],
            focused_address="0xB",
        ))

        fcw.main()

        remaining = {c["address"] for c in fake.clients}
        self.assertEqual(remaining, {"0xA", "0xC"})
        self.assertIsNone(shared.poll(), "the shared process was killed")

    def test_04_two_different_applications_are_independent(self):
        app1 = self._spawn("sleep", "300")
        app2 = self._spawn("sleep", "300")
        fake = self._install(FakeHypr(
            clients=[{"address": "0xA", "pid": app1.pid}, {"address": "0xB", "pid": app2.pid}],
            focused_address="0xA",
        ))

        fcw.main()

        self.assertIsNone(app1.poll())
        self.assertIsNone(app2.poll())
        self.assertNotIn("0xA", [c["address"] for c in fake.clients])
        self.assertIn("0xB", [c["address"] for c in fake.clients])

    def test_05_electron_style_windows_share_a_renderer_pid_tree(self):
        """Electron/Chromium: a window's own reported pid may be a
        renderer process that is a CHILD of the app's main process, not
        the main process itself -- the sibling check must walk the whole
        subtree, not just compare pids for exact equality."""
        main_proc = self._spawn("sleep", "300")
        renderer_a = self._spawn("sleep", "300")  # stands in for a per-window renderer pid
        fake = self._install(FakeHypr(
            clients=[
                {"address": "0xA", "pid": renderer_a.pid},
                {"address": "0xB", "pid": main_proc.pid},
            ],
            focused_address="0xA",
        ))
        # Make renderer_a resolve to the same subtree as main_proc for the
        # purposes of the sibling check, without needing a real parent/
        # child relationship between two independently-spawned processes.
        fcw._find_root = lambda pid: main_proc.pid
        fcw._collect_subtree = lambda root: [main_proc.pid, renderer_a.pid]
        fake.honors_close = False  # force the fallback path to even be considered

        fcw.main()

        self.assertIsNone(main_proc.poll(), "the shared subtree was killed despite a sibling window (0xB) existing")
        self.assertIsNone(renderer_a.poll())
        self.assertIn("0xB", [c["address"] for c in fake.clients])

    # ------------------------------------------------------------------
    # Fallback path: genuine tray-hide apps (the ORIGINAL problem this
    # file was built for) must still be force-closed when truly alone.
    # ------------------------------------------------------------------

    def test_normal_single_window_app_falls_back_to_kill_if_close_ignored(self):
        """A tray-hide app (Discord/Steam/Slack-style): the per-window
        close is ignored, and since it owns no other windows, the
        conservative fallback must still actually terminate it -- the
        ORIGINAL bug this file exists to fix must remain fixed."""
        victim = self._spawn("sleep", "300")
        fake = self._install(FakeHypr(
            clients=[{"address": "0xA", "pid": victim.pid}],
            focused_address="0xA",
            honors_close=False,
        ))
        fcw._find_root = lambda pid: pid
        fcw._collect_subtree = lambda root: [root]

        fcw.main()
        victim.wait(timeout=2)

        self.assertIsNotNone(victim.poll(), "a tray-hide app was not force-closed when it had no sibling windows")

    def test_shared_pid_app_is_never_force_killed_even_if_close_ignored(self):
        """The conservative half of the fix: if the app ALSO ignores the
        per-window close AND shares its process with another window, the
        fallback must refuse to run at all -- "cannot safely close this
        one window" is the correct outcome, not "kill them both.\""""
        shared = self._spawn("sleep", "300")
        fake = self._install(FakeHypr(
            clients=[{"address": "0xA", "pid": shared.pid}, {"address": "0xB", "pid": shared.pid}],
            focused_address="0xA",
            honors_close=False,
        ))
        fcw._find_root = lambda pid: pid
        fcw._collect_subtree = lambda root: [root]

        fcw.main()

        self.assertIsNone(shared.poll(), "the shared process was killed despite an unclosed sibling window")

    # ------------------------------------------------------------------
    # Test matrix cases 7-10: missing/invalid identifiers.
    # ------------------------------------------------------------------

    def test_07_process_lookup_fails_is_a_safe_noop(self):
        """The reported pid does not correspond to any real, readable
        process (already exited) -- must not raise, must not hang."""
        fake = self._install(FakeHypr(
            clients=[{"address": "0xA", "pid": 999999}],
            focused_address="0xA",
            honors_close=False,
        ))

        fcw.main()  # must not raise

        self.assertEqual(fake.close_calls, ["0xA"],
                          "close_window was not attempted even though a valid address existed")

    def test_08_pid_unavailable_still_closes_via_address(self):
        """A window with no pid at all (case 8) must still be closable --
        the primary close path is address-based and never needed a pid in
        the first place."""
        fake = self._install(FakeHypr(
            clients=[{"address": "0xA"}],  # no "pid" key
            focused_address="0xA",
        ))

        fcw.main()

        self.assertEqual(fake.close_calls, ["0xA"])
        self.assertEqual(fake.clients, [], "window with no pid was not closed via its address")

    def test_09_already_closing_window_is_a_safe_noop(self):
        """The window is already gone from hyprctl's client list by the
        time SUPER+C is processed (a closing-animation race) -- must not
        raise and must not touch any process."""
        victim = self._spawn("sleep", "300")
        fake = self._install(FakeHypr(
            clients=[{"address": "0xA", "pid": victim.pid}],
            focused_address="0xA",
        ))
        # Simulate the race: activewindow still reports it, but it has
        # already vanished from the general client list by the time the
        # close is dispatched.
        orig_hyprctl = fake.hyprctl_json

        def racing(args):
            if args == ["clients"]:
                return []
            return orig_hyprctl(args)
        fcw.hyprctl_json = racing

        fcw.main()  # must not raise

        self.assertIsNone(victim.poll(), "a real process was touched for a window that had already closed")

    def test_10_stale_address_is_a_safe_noop_not_a_process_kill(self):
        """hyprctl reports a focused window whose address no longer
        matches anything in the live client list (stale/invalid address)
        -- the safe failure mode is doing nothing further, never
        escalating to a process kill based on a pid that might belong to
        a window the user never targeted."""
        other = self._spawn("sleep", "300")
        fake = self._install(FakeHypr(
            clients=[{"address": "0xSTALE", "pid": other.pid}],
            focused_address="0xSTALE",
        ))
        # activewindow reports a DIFFERENT, no-longer-valid address than
        # what's actually in the client list.
        real_clients = fake.hyprctl_json
        fcw.hyprctl_json = lambda args: (
            {"address": "0xDEAD", "pid": other.pid} if args == ["activewindow"] else real_clients(args)
        )

        fcw.main()  # must not raise

        self.assertIsNone(other.poll(), "a process was killed based on a stale/invalid window address")

    # ------------------------------------------------------------------
    # Test matrix cases 11-12: fixed/system and fullscreen windows close
    # through the same ordinary path -- no special-casing needed or
    # wanted beyond the Quickshell-panel check above.
    # ------------------------------------------------------------------

    def test_11_pinned_system_window_closes_normally(self):
        victim = self._spawn("sleep", "300")
        fake = self._install(FakeHypr(
            clients=[{"address": "0xA", "pid": victim.pid, "pinned": True}],
            focused_address="0xA",
        ))

        fcw.main()

        self.assertEqual(fake.close_calls, ["0xA"])
        self.assertIsNone(victim.poll())

    def test_12_fullscreen_window_closes_normally(self):
        victim = self._spawn("sleep", "300")
        fake = self._install(FakeHypr(
            clients=[{"address": "0xA", "pid": victim.pid, "fullscreen": 2}],
            focused_address="0xA",
        ))

        fcw.main()

        self.assertEqual(fake.close_calls, ["0xA"])
        self.assertIsNone(victim.poll())

    def test_no_active_window_is_a_safe_noop(self):
        fcw.hyprctl_json = lambda args: None
        fcw.main()  # must not raise


if __name__ == "__main__":
    unittest.main(verbosity=2)
