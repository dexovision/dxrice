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
import signal
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
        fcw.TERM_GRACE = 0.5
        fcw.KILL_WAIT = 0.5
        # Never a real notification from a test.
        self.notes = []
        fcw._notify = lambda summary, body: self.notes.append((summary, body))
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


FAKE_APP = r"""
import os, signal, sys, time
marker, mode = sys.argv[1], sys.argv[2]
def on_term(*_):
    if mode == "ignore-term":
        with open(marker + ".term", "w") as f:
            f.write(repr(time.monotonic()))
        return
    with open(marker, "w") as f:
        f.write("clean-exit")
    sys.exit(0)
signal.signal(signal.SIGTERM, on_term)
if mode == "with-child":
    import subprocess
    child = subprocess.Popen(["sleep", "300"])
    with open(marker + ".child", "w") as f:
        f.write(str(child.pid))
if mode == "launch":
    # another app (argv[3]) started by this one, with the same interpreter
    import subprocess
    child = subprocess.Popen([sys.executable, sys.argv[3], marker + "k", "normal"])
    with open(marker + ".child", "w") as f:
        f.write(str(child.pid))
    while not os.path.exists(marker + "k.ready"):
        time.sleep(0.02)
with open(marker + ".ready", "w") as f:
    f.write("1")
while True:
    time.sleep(0.05)
"""


class TestTermination(unittest.TestCase):
    """The force-quit fallback itself: graceful first, pid-reuse safe,
    validated against the live window list, never touching the desktop's
    own processes. Only fake apps (python/sleep children of this test) are
    ever signalled."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="dxrice_test_term_")
        cls.app = os.path.join(cls.tmp, "fake_app.py")
        with open(cls.app, "w") as f:
            f.write(FAKE_APP)
        # Its own executable name: a plain python3 child of this (python3)
        # test would climb to the test process as its "root", which the
        # closing script rightly refuses to touch as its own ancestor.
        cls.interp = os.path.join(cls.tmp, "fakeapp")
        shutil.copy(os.path.realpath(sys.executable), cls.interp)
        os.chmod(cls.interp, 0o755)
        cls.env = dict(os.environ, PYTHONHOME=sys.base_prefix)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        importlib.reload(fcw)
        fcw.CLOSE_WAIT_TIMEOUT = 0.1
        fcw.CLOSE_WAIT_POLL = 0.02
        fcw.TERM_GRACE = 0.6
        fcw.KILL_WAIT = 0.5
        self.notes = []
        fcw._notify = lambda summary, body: self.notes.append((summary, body))
        self._procs = []

    def tearDown(self):
        for p in self._procs:
            if p.poll() is None:
                p.kill()
                p.wait(timeout=2)
            child = getattr(p, "child_pid", None)
            if child:
                try:
                    os.kill(child, 9)
                except ProcessLookupError:
                    pass

    def _fake_app(self, mode="normal", interp=None, launches=None):
        marker = tempfile.mktemp(prefix="m", dir=self.tmp)
        p = subprocess.Popen([interp or self.interp, self.app, marker, mode] + ([launches] if launches else []),
                             env=self.env)
        self._procs.append(p)
        deadline = time.monotonic() + 5
        while not os.path.exists(marker + ".ready") and time.monotonic() < deadline:
            time.sleep(0.02)
        p.marker = marker
        if mode in ("with-child", "launch"):
            with open(marker + ".child") as f:
                p.child_pid = int(f.read())
        return p

    def _renamed(self, name):
        path = os.path.join(self.tmp, name)
        if not os.path.exists(path):
            shutil.copy(shutil.which("sleep"), path)
            os.chmod(path, 0o755)
        p = subprocess.Popen([path, "300"])
        self._procs.append(p)
        time.sleep(0.1)
        return p

    def _ignores_close(self, pid, address="0xA", extra=()):
        fake = FakeHypr(clients=[{"address": address, "pid": pid}, *extra], focused_address=address,
                        honors_close=False)
        fcw.hyprctl_json = fake.hyprctl_json
        fcw.close_window = fake.close_window
        return fake

    @staticmethod
    def _alive(pid):
        try:
            with open(f"/proc/{pid}/stat") as f:
                return f.read().split(")")[-1].split()[0] != "Z"
        except FileNotFoundError:
            return False

    def test_sigterm_first_and_a_clean_exit_is_allowed(self):
        app = self._fake_app("normal")
        self._ignores_close(app.pid)
        t0 = time.monotonic()
        fcw.main()
        app.wait(timeout=3)
        self.assertEqual(open(app.marker).read(), "clean-exit", "the app never got to handle SIGTERM")
        self.assertEqual(app.returncode, 0, "exited by a signal instead of on its own")
        self.assertLess(time.monotonic() - t0, fcw.TERM_GRACE + 0.5, "waited out the grace period for an app that had exited")

    def test_sigkill_only_after_the_grace_period(self):
        app = self._fake_app("ignore-term")
        self._ignores_close(app.pid)
        fcw.main()
        app.wait(timeout=3)
        killed_at = time.monotonic()
        self.assertEqual(app.returncode, -signal.SIGKILL)
        with open(app.marker + ".term") as f:
            term_at = float(f.read())
        # CLOCK_MONOTONIC is system-wide: the app's own SIGTERM timestamp and
        # this process's clock are comparable.
        self.assertGreaterEqual(killed_at - term_at, fcw.TERM_GRACE - 0.05,
                                "SIGKILL came before the grace period ended")

    def test_child_processes_go_with_the_app(self):
        app = self._fake_app("with-child")
        self._ignores_close(app.pid)
        fcw.main()
        app.wait(timeout=3)
        deadline = time.monotonic() + 2
        while self._alive(app.child_pid) and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertFalse(self._alive(app.child_pid), "the app's child process was left running")

    # ---- targeting: only the selected window's own application ----

    def _quits(self, p, timeout=3):
        try:
            p.wait(timeout=timeout)
            return True
        except subprocess.TimeoutExpired:
            return False

    def test_two_instances_of_one_app_only_the_target_quits(self):
        """Two separately started instances of the same program: forcing
        one closed leaves the other running (each is its own root)."""
        a, b = self._fake_app("normal"), self._fake_app("normal")
        self._ignores_close(a.pid, extra=[{"address": "0xB", "pid": b.pid}])
        fcw.main()
        self.assertTrue(self._quits(a), "the targeted instance is still running")
        self.assertTrue(self._alive(b.pid), "the other instance was killed too")

    def test_instance_started_from_another_instance_takes_nothing_with_it(self):
        """An instance launched by another instance of the same program is
        part of that program's tree; the launcher has its own window, so
        nothing is force-killed (the user is told why) -- neither the
        target's launcher nor its window is touched."""
        a = self._fake_app("launch", launches=self.app)
        kid = a.child_pid
        self._ignores_close(kid, address="0xKID", extra=[{"address": "0xA", "pid": a.pid}])
        fcw.main()
        time.sleep(0.3)
        self.assertTrue(self._alive(a.pid), "the launching instance (with its own window) was killed")
        self.assertTrue(self._alive(kid), "force-killed despite sharing a tree with another window")
        self.assertTrue(self.notes, "no explanation given")
        os.kill(kid, 9)

    def test_python_app_started_by_another_python_program_quits_alone(self):
        """The root-climbing bug: a Python app started by a different Python
        program shares the interpreter executable, and climbing "while the
        parent is the same executable" made the launcher (and everything
        else it runs) part of the app. A runtime counts as the same program
        only when it runs the same script."""
        py = os.path.join(self.tmp, "python3.99")
        if not os.path.exists(py):
            shutil.copy(os.path.realpath(sys.executable), py)
            os.chmod(py, 0o755)
        other = os.path.join(self.tmp, "other_app.py")
        with open(other, "w") as f:
            f.write(FAKE_APP)
        launcher = self._fake_app("launch", interp=py, launches=other)
        kid = launcher.child_pid
        self.assertEqual(fcw._find_root(kid), kid, "climbed into the launcher, a different program")
        self._ignores_close(kid, address="0xKID")
        fcw.main()
        deadline = time.monotonic() + 3
        while self._alive(kid) and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertFalse(self._alive(kid), "the targeted app is still running")
        self.assertTrue(self._alive(launcher.pid), "its launcher -- another program -- was killed with it")

    def test_runtime_detection(self):
        for exe, want in (("/usr/bin/python3.13", True), ("/usr/bin/python3", True), ("/usr/bin/java", True),
                          ("/usr/lib/electron33/electron", True), ("/usr/bin/bash", True),
                          ("/usr/bin/shotwell", False), ("/opt/brave/brave", False), ("/usr/bin/javac", False)):
            self.assertEqual(fcw._is_runtime(exe), want, exe)

    def test_recycled_pid_is_never_signalled(self):
        """The process identified at the start is gone and its pid now
        names a different process (modelled by a changed start time): the
        pinned handle must refuse to signal it."""
        bystander = self._renamed("bystander")
        real = fcw._read_starttime(bystander.pid)
        pinned = fcw._Pinned(bystander.pid, real + 12345)
        self.assertFalse(pinned.valid)
        fcw._terminate([(bystander.pid, real + 12345)])
        time.sleep(0.2)
        self.assertIsNone(bystander.poll(), "a process with a different start time was signalled")

    def test_window_that_changed_process_is_not_killed(self):
        app = self._fake_app("normal")
        other = self._fake_app("normal")
        fake = self._ignores_close(app.pid)
        real = fake.hyprctl_json

        def swapped(args):
            out = real(args)
            if args == ["clients"]:
                return [dict(c, pid=other.pid) for c in out]
            return out
        fcw.hyprctl_json = swapped
        fcw.main()
        time.sleep(0.2)
        self.assertIsNone(app.poll(), "killed although the address now reports another process")
        self.assertIsNone(other.poll(), "killed the process the address now reports")

    def test_window_that_closed_late_is_left_alone(self):
        app = self._fake_app("normal")
        fake = self._ignores_close(app.pid)
        real_collect = fcw._collect_subtree

        def collect_then_window_closes(root):
            # The app honours the close just as the fallback is working out
            # what to kill: by the final check, the window is gone.
            out = real_collect(root)
            fake.clients = []
            return out
        fcw._collect_subtree = collect_then_window_closes
        fcw.main()
        time.sleep(0.2)
        self.assertIsNone(app.poll(), "killed an app whose window had already closed")

    def test_desktop_components_are_never_force_quit(self):
        for name in ("Hyprland", "Xwayland", "pipewire", "polkit-kde-authentication-agent-1", "hyprlock"):
            with self.subTest(name=name):
                proc = self._renamed(name)
                self._ignores_close(proc.pid)
                fcw.main()
                time.sleep(0.15)
                self.assertIsNone(proc.poll(), f"{name} was force-quit")
                self.assertTrue(self.notes and "part of the desktop" in self.notes[-1][1], self.notes)

    def test_protected_process_inside_the_app_tree_is_spared(self):
        app = self._fake_app("normal")
        guarded = self._renamed("pipewire")
        self._ignores_close(app.pid)
        fcw._collect_subtree = lambda root: [app.pid, guarded.pid]
        real_ppid = fcw._read_ppid
        fcw._read_ppid = lambda pid: app.pid if pid == guarded.pid else real_ppid(pid)
        fcw.main()
        app.wait(timeout=3)
        self.assertIsNone(guarded.poll(), "a protected process inside the app's tree was killed")

    def test_another_users_process_is_refused(self):
        app = self._fake_app("normal")
        self._ignores_close(app.pid)
        real_uid = fcw._owner_uid
        fcw._owner_uid = lambda pid: 0 if pid == app.pid else real_uid(pid)
        fcw.main()
        time.sleep(0.15)
        self.assertIsNone(app.poll())
        self.assertIn("another user", self.notes[-1][1])

    def test_this_scripts_own_ancestors_are_refused(self):
        app = self._fake_app("normal")
        self._ignores_close(app.pid)
        fcw._own_ancestors = lambda: {os.getpid(), app.pid}
        fcw.main()
        time.sleep(0.15)
        self.assertIsNone(app.poll(), "an ancestor of the closing script was killed")

    def test_shared_process_is_explained_not_killed(self):
        app = self._fake_app("normal")
        self._ignores_close(app.pid, extra=[{"address": "0xB", "pid": app.pid}, {"address": "0xC", "pid": app.pid}])
        fcw.main()
        time.sleep(0.15)
        self.assertIsNone(app.poll())
        self.assertEqual(len(self.notes), 1)
        self.assertIn("2 other windows", self.notes[0][1])

    def test_never_signals_a_process_group(self):
        """Every signal goes to one pinned process: no os.killpg, and no
        negative pid to os.kill (a group)."""
        app = self._fake_app("ignore-term")
        self._ignores_close(app.pid)
        sent = []
        real_kill = os.kill
        fcw.os.killpg = lambda *a: sent.append(("killpg", a))
        fcw.os.kill = lambda pid, sig: (sent.append(("kill", pid)), real_kill(pid, sig))
        try:
            fcw.main()
        finally:
            fcw.os.kill = real_kill
        app.wait(timeout=3)
        self.assertFalse([s for s in sent if s[0] == "killpg" or s[1] <= 0], sent)


if __name__ == "__main__":
    unittest.main(verbosity=2)
