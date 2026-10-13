#!/usr/bin/env python3
"""dxrice_apply_theme.reload_apps() restarts swaybg through
dxrice_launch.sh. Apply runs as a child of the shell, so a wallpaper started
directly lived in dxrice-quickshell.service's cgroup and vanished whenever
the shell restarted. Nothing is executed: Popen and the guarded reload
commands are mocked.

    python3 scripts/dxrice_test_apply_theme_launch.py
"""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dxrice_apply_theme as apply_theme  # noqa: E402


class SwaybgRestartTest(unittest.TestCase):
    def test_wallpaper_restart_goes_through_the_scope_launcher(self):
        with tempfile.NamedTemporaryFile(suffix=".png") as wp, \
                mock.patch.object(apply_theme, "theme_data", {"wallpaper": wp.name}, create=True), \
                mock.patch.object(apply_theme, "quickshell_owns_bar", return_value=True), \
                mock.patch.object(apply_theme, "_run_guarded") as guarded, \
                mock.patch.object(apply_theme.subprocess, "Popen") as popen:
            apply_theme.reload_apps(reload_wallpaper=True)
        guarded.assert_any_call(["pkill", "-x", "swaybg"])
        self.assertEqual(popen.call_count, 1)
        argv = popen.call_args.args[0]
        self.assertEqual(argv[0], os.path.join(apply_theme.SCRIPTS_DIR, "dxrice_launch.sh"))
        self.assertEqual(argv[1:], ["swaybg", "swaybg", "-i", wp.name, "-m", "fill"])
        self.assertTrue(os.access(argv[0], os.X_OK), "dxrice_launch.sh is not executable")

    def test_no_wallpaper_reload_starts_nothing(self):
        with mock.patch.object(apply_theme, "quickshell_owns_bar", return_value=True), \
                mock.patch.object(apply_theme, "_run_guarded"), \
                mock.patch.object(apply_theme.subprocess, "Popen") as popen:
            apply_theme.reload_apps(reload_wallpaper=False)
        popen.assert_not_called()


class PatchHyprlandLuaTest(unittest.TestCase):
    """Apply rewrites the user's own hyprland.lua (gaps, borders, blur):
    atomically, and not at all when nothing changed."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        os.makedirs(os.path.join(self._tmp.name, "hypr"))
        self.lua = os.path.join(self._tmp.name, "hypr", "hyprland.lua")
        repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(repo, "hypr", "hyprland.lua")) as f:
            self.original = f.read()
        with open(self.lua, "w") as f:
            f.write(self.original)
        os.chmod(self.lua, 0o600)
        with open(os.path.join(repo, "theme", "theme.json")) as f:
            self.theme = json.load(f)
        self._p = mock.patch.object(apply_theme, "CONFIG_HOME", self._tmp.name)
        self._p.start()

    def tearDown(self):
        self._p.stop()
        self._tmp.cleanup()

    def test_failed_write_leaves_the_config_intact(self):
        real_open = open

        def half_then_fail(path, mode="r", *a, **kw):
            f = real_open(path, mode, *a, **kw)
            if "w" in mode:
                real_write = f.write

                def write(text):
                    real_write(text[: len(text) // 2])
                    raise OSError(28, "No space left on device")
                f.write = write
            return f
        theme = dict(self.theme, hypr_gaps_in=17)
        with mock.patch("builtins.open", half_then_fail):
            with self.assertRaises(OSError):
                apply_theme.patch_hyprland_lua(theme)
        with open(self.lua) as f:
            self.assertEqual(f.read(), self.original, "hyprland.lua was left half-written")
        self.assertEqual([n for n in os.listdir(os.path.dirname(self.lua)) if n.endswith(".tmp")], [])

    def test_change_is_written_with_the_files_mode(self):
        apply_theme.patch_hyprland_lua(dict(self.theme, hypr_gaps_in=17))
        with open(self.lua) as f:
            self.assertRegex(f.read(), r"gaps_in\s*=\s*17")
        self.assertEqual(os.stat(self.lua).st_mode & 0o777, 0o600)

    def test_unchanged_config_is_not_rewritten(self):
        apply_theme.patch_hyprland_lua(self.theme)  # settle to the theme's values
        os.utime(self.lua, (1_000_000_000, 1_000_000_000))
        apply_theme.patch_hyprland_lua(self.theme)
        self.assertEqual(os.stat(self.lua).st_mtime, 1_000_000_000, "rewrote an unchanged config")


if __name__ == "__main__":
    unittest.main(verbosity=2)
