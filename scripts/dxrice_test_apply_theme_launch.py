#!/usr/bin/env python3
"""dxrice_apply_theme.reload_apps() restarts swaybg through
dxrice_launch.sh. Apply runs as a child of the shell, so a wallpaper started
directly lived in dxrice-quickshell.service's cgroup and vanished whenever
the shell restarted. Nothing is executed: Popen and the guarded reload
commands are mocked.

    python3 scripts/dxrice_test_apply_theme_launch.py
"""
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
