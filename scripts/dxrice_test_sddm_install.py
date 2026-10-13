#!/usr/bin/env python3
"""dxrice_sync_sddm_theme.install_theme_dir: a failed copy never leaves the
login screen pointing at a half-installed theme. Temporary directories
only -- nothing under /usr/share/sddm is touched.

    python3 scripts/dxrice_test_sddm_install.py
"""
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dxrice_sync_sddm_theme as sddm  # noqa: E402


class InstallThemeDirTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = self._tmp.name
        self.target = os.path.join(root, "themes", "dxrice")
        self.staging = os.path.join(root, "staging")
        os.makedirs(self.target)
        os.makedirs(self.staging)
        for name in ("Main.qml", "theme.conf", "bg.png"):
            with open(os.path.join(self.target, name), "w") as f:
                f.write(f"old {name}")
            with open(os.path.join(self.staging, name), "w") as f:
                f.write(f"new {name}")

    def tearDown(self):
        self._tmp.cleanup()

    def contents(self):
        return {n: open(os.path.join(self.target, n)).read() for n in sorted(os.listdir(self.target))}

    def test_replaces_the_theme(self):
        sddm.install_theme_dir(self.staging, self.target)
        self.assertEqual(self.contents(), {"Main.qml": "new Main.qml", "bg.png": "new bg.png", "theme.conf": "new theme.conf"})
        self.assertEqual(sorted(os.listdir(os.path.dirname(self.target))), ["dxrice"], "temp dirs left behind")

    def test_copy_failing_half_way_leaves_the_old_theme_intact(self):
        real_copyfile = shutil.copyfile
        calls = {"n": 0}

        def copy_then_fail(src, dst, *a, **kw):
            calls["n"] += 1
            if calls["n"] == 2:
                raise OSError(28, "No space left on device")
            return real_copyfile(src, dst, *a, **kw)
        before = self.contents()
        with mock.patch.object(shutil, "copyfile", copy_then_fail):
            with self.assertRaises(Exception):
                sddm.install_theme_dir(self.staging, self.target)
        self.assertEqual(self.contents(), before, "the live theme was damaged by a failed install")
        self.assertEqual(sorted(os.listdir(os.path.dirname(self.target))), ["dxrice"], "temp dirs left behind")

    def test_first_install_with_no_previous_theme(self):
        shutil.rmtree(self.target)
        sddm.install_theme_dir(self.staging, self.target)
        self.assertEqual(len(self.contents()), 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
