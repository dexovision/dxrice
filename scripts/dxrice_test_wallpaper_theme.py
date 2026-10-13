#!/usr/bin/env python3
"""dxrice_wallpaper_theme.py: --print-only (the Theme editor's mode) never
touches theme.json; the standalone write keeps every other key and is
atomic. ffmpeg sampling is mocked; every path is a temporary directory.

    python3 scripts/dxrice_test_wallpaper_theme.py
"""
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dxrice_wallpaper_theme as wt  # noqa: E402

PIXELS = [(30, 60, 120), (200, 80, 40), (20, 20, 25), (240, 240, 240)] * 40


class WallpaperThemeTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.theme = os.path.join(self._tmp.name, "theme.json")
        self.wall = os.path.join(self._tmp.name, "wall.png")
        open(self.wall, "wb").close()
        self.original = {"schema_version": 1, "accent": "123456", "radius": 14, "my_custom_key": [1, 2]}
        with open(self.theme, "w") as f:
            json.dump(self.original, f)
        os.chmod(self.theme, 0o640)
        self.patches = [mock.patch.object(wt, "LIVE_THEME_JSON", self.theme),
                        mock.patch.object(wt, "sample_pixels", return_value=PIXELS)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self._tmp.cleanup()

    def run_main(self, *argv):
        out = io.StringIO()
        with redirect_stdout(out), mock.patch.object(sys, "argv", ["dxrice_wallpaper_theme.py", *argv]):
            rc = wt.main()
        return rc, out.getvalue()

    def test_print_only_leaves_theme_json_untouched(self):
        """The editor's mode: before, the script wrote the live file anyway,
        so the shell recoloured before Apply and Revert couldn't undo it."""
        before = open(self.theme).read()
        rc, out = self.run_main("--print-only", self.wall)
        self.assertEqual(rc, 0)
        self.assertIn("accent", json.loads(out))
        self.assertEqual(open(self.theme).read(), before)

    def test_standalone_write_keeps_other_keys_and_mode(self):
        rc, out = self.run_main(self.wall)
        self.assertEqual(rc, 0)
        palette = json.loads(out)
        data = json.load(open(self.theme))
        for k in ("schema_version", "radius", "my_custom_key"):
            self.assertEqual(data[k], self.original[k], f"{k} lost")
        self.assertEqual(data["accent"], palette["accent"])
        self.assertEqual(os.stat(self.theme).st_mode & 0o777, 0o640)

    def test_failed_write_leaves_the_original_intact(self):
        before = open(self.theme).read()

        def boom(obj, f, **kw):
            f.write('{"acc')
            raise OSError(28, "No space left on device")
        with mock.patch.object(wt.json, "dump", side_effect=boom):
            with self.assertRaises(OSError):
                self.run_main(self.wall)
        self.assertEqual(open(self.theme).read(), before)
        self.assertEqual([n for n in os.listdir(self._tmp.name) if n.endswith(".tmp")], [])


class SamplingFailureTest(unittest.TestCase):
    """What the Theme editor shows when sampling can't work: a message that
    says what to do, never a traceback or a hang."""

    def run_with(self, exc):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        wall = os.path.join(tmp.name, "w.png")
        open(wall, "wb").close()
        err = io.StringIO()
        with mock.patch.object(wt.subprocess, "run", side_effect=exc), \
                mock.patch.object(sys, "argv", ["x", "--print-only", wall]), \
                mock.patch.object(sys, "stderr", err), redirect_stdout(io.StringIO()):
            rc = wt.main()
        return rc, err.getvalue()

    def test_missing_ffmpeg_says_so(self):
        rc, err = self.run_with(FileNotFoundError(2, "No such file", "ffmpeg"))
        self.assertEqual(rc, 1)
        self.assertIn("needs ffmpeg", err)

    def test_hung_ffmpeg_times_out(self):
        rc, err = self.run_with(wt.subprocess.TimeoutExpired("ffmpeg", wt.SAMPLE_TIMEOUT))
        self.assertEqual(rc, 1)
        self.assertIn("took over", err)

    def test_sampling_has_a_timeout(self):
        with mock.patch.object(wt.subprocess, "run") as run:
            run.return_value = mock.Mock(stdout=bytes(9))
            wt.sample_pixels("/x.png")
        self.assertIn("timeout", run.call_args.kwargs)


if __name__ == "__main__":
    unittest.main(verbosity=2)
