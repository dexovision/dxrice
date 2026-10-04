#!/usr/bin/env python3
"""Regression suite for dxrice_taskbar_gui.py's/TaskbarManager.qml's shared
sh -c '...' wrap/unwrap convention for taskbar shortcut commands.

Found during a full-codebase audit: the old wrap used naive string
concatenation (`f"sh -c '{cmd} >/dev/null 2>&1 &'"`), which breaks the
instant a user's shortcut command contains a single quote with a space
inside it -- e.g. `flatpak run --title='My Cool App'`. Confirmed live via
a disposable fake binary: the old construction ran the command with only
`--title=My` as its argument, silently truncating everything after the
first space inside the quoted segment. A command with a single-word quoted
value (no spaces) happened to still work by accident, due to bash's
adjacent-quote-concatenation rule -- which is exactly what let this bug
hide for a plausible, not-even-adversarial case (any Flatpak branch/channel
argument, any app title with a space, etc.).

This also caught a second bug while fixing the first: Quickshell's
Dock.qml has its own independent, duplicated copy of the unwrap regex (not
calling TaskbarManager.unwrapShellCmd) that did not know about the new
escaping -- fixing only the write side would have made EVERY shortcut
containing any quote throw a shell syntax error on click, worse than the
original bug. Both the Python and QML wrap/unwrap pairs are covered here;
the QML side is verified by mirroring its exact JS logic in Python (both
use the identical '\\''-based POSIX nested-quote escape) since this
project's QML has no standalone JS test runner.
"""
import re
import subprocess
import sys
import unittest

sys.path.insert(0, "scripts" if __name__ != "__main__" else ".")
import dxrice_taskbar_gui as gui


def qml_wrap(cmd):
    """Mirrors TaskbarManager.qml's wrapShellCmd exactly."""
    escaped = cmd.replace("'", "'\\''")
    return f"sh -c '{escaped} >/dev/null 2>&1 &'"


def qml_unwrap(on_click):
    """Mirrors TaskbarManager.qml's unwrapShellCmd exactly."""
    m = re.match(r"^sh -c '(.*) >/dev/null 2>&1 &'$", on_click or "")
    if not m:
        return on_click or ""
    return m.group(1).replace("'\\''", "'")


def dock_click_extract(on_click):
    """Mirrors Dock.qml's onClicked handler exactly -- regex extract, then
    the SAME un-escape (this is the independent, duplicated copy that must
    stay in sync with TaskbarManager's wrap/unwrap pair)."""
    m = re.match(r"^sh -c '(.*) >/dev/null 2>&1 &'$", on_click)
    return m.group(1).replace("'\\''", "'") if m else on_click


class TestPythonWrapUnwrapRoundTrip(unittest.TestCase):
    def test_simple_command_round_trips(self):
        cmd = "firefox"
        self.assertEqual(gui._unwrap_shell_cmd(gui._wrap_shell_cmd(cmd)), cmd)

    def test_command_with_args_round_trips(self):
        cmd = "flatpak run com.example.App --flag value"
        self.assertEqual(gui._unwrap_shell_cmd(gui._wrap_shell_cmd(cmd)), cmd)

    def test_command_with_single_quoted_argument_round_trips(self):
        cmd = "flatpak run --branch='stable' com.example.App"
        self.assertEqual(gui._unwrap_shell_cmd(gui._wrap_shell_cmd(cmd)), cmd)

    def test_command_with_quoted_argument_containing_a_space_round_trips(self):
        cmd = "fake_app --title='My Cool App' arg2"
        self.assertEqual(gui._unwrap_shell_cmd(gui._wrap_shell_cmd(cmd)), cmd)

    def test_command_with_multiple_quotes_round_trips(self):
        cmd = "app --a='one' --b='two three' --c='four'"
        self.assertEqual(gui._unwrap_shell_cmd(gui._wrap_shell_cmd(cmd)), cmd)

    def test_old_unescaped_format_still_unwraps_unchanged_backward_compat(self):
        # A shortcut saved under the OLD (pre-fix) format, where cmd never
        # had any quotes -- must still round-trip identically so existing
        # users' shortcuts aren't disturbed by the fix.
        old_on_click = "sh -c 'firefox --private-window >/dev/null 2>&1 &'"
        self.assertEqual(gui._unwrap_shell_cmd(old_on_click), "firefox --private-window")


class TestQmlWrapUnwrapRoundTrip(unittest.TestCase):
    """Same assertions, against the mirrored QML logic."""

    def test_quoted_argument_with_space_round_trips(self):
        cmd = "fake_app --title='My Cool App' arg2"
        self.assertEqual(qml_unwrap(qml_wrap(cmd)), cmd)

    def test_python_and_qml_wrap_produce_identical_output(self):
        # The two implementations must never drift apart.
        cmd = "app --a='one' --b='two three'"
        self.assertEqual(gui._wrap_shell_cmd(cmd), qml_wrap(cmd))


class TestRealShellExecutionEndToEnd(unittest.TestCase):
    """The actual regression: does the fixed command survive BOTH real
    execution paths -- a direct `sh -c` of the full on_click string (the
    shape waybar itself would run), and Dock.qml's regex-extract-then-
    execDetached path -- with the right argv reaching the target program?
    Uses a disposable fake binary that records its own argv, never a real
    application."""

    @classmethod
    def setUpClass(cls):
        import os
        import tempfile
        cls.tmp = tempfile.mkdtemp(prefix="dxrice-taskbar-wrap-test-")
        cls.fake_bin = os.path.join(cls.tmp, "fake_app")
        cls.log = os.path.join(cls.tmp, "ran.log")
        with open(cls.fake_bin, "w") as f:
            f.write(f'#!/bin/bash\necho "ARGS:$@" >> {cls.log}\n')
        os.chmod(cls.fake_bin, 0o755)
        cls.env = dict(**__import__("os").environ)
        cls.env["PATH"] = cls.tmp + ":" + cls.env.get("PATH", "")

    @classmethod
    def tearDownClass(cls):
        import shutil
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        open(self.log, "w").close()

    def _ran_with(self):
        with open(self.log) as f:
            return f.read().strip()

    def test_waybar_style_direct_execution_preserves_quoted_space_argument(self):
        cmd = "fake_app --title='My Cool App' arg2"
        on_click = gui._wrap_shell_cmd(cmd)
        subprocess.run(["sh", "-c", on_click], env=self.env, timeout=5)
        self.assertEqual(self._ran_with(), "ARGS:--title=My Cool App arg2")

    def test_dock_click_path_preserves_quoted_space_argument(self):
        cmd = "fake_app --title='My Cool App' arg2"
        on_click = gui._wrap_shell_cmd(cmd)
        extracted = dock_click_extract(on_click)
        subprocess.run(["sh", "-c", extracted], env=self.env, timeout=5)
        self.assertEqual(self._ran_with(), "ARGS:--title=My Cool App arg2")

    def test_dock_click_path_still_works_for_simple_commands(self):
        cmd = "fake_app simple args here"
        on_click = gui._wrap_shell_cmd(cmd)
        extracted = dock_click_extract(on_click)
        subprocess.run(["sh", "-c", extracted], env=self.env, timeout=5)
        self.assertEqual(self._ran_with(), "ARGS:simple args here")

    def test_old_broken_construction_actually_was_broken_before_the_fix(self):
        # Documents the exact regression this suite guards against: the
        # OLD naive construction really did truncate the command.
        cmd = "fake_app --title='My Cool App' arg2"
        old_on_click = f"sh -c '{cmd} >/dev/null 2>&1 &'"
        subprocess.run(["sh", "-c", old_on_click], env=self.env, timeout=5)
        self.assertEqual(self._ran_with(), "ARGS:--title=My",
                          "if this assertion fails, the old bug is no longer reproducible -- "
                          "good, but double check the fix is still the one actually in use")


if __name__ == "__main__":
    unittest.main(verbosity=2)
