#!/usr/bin/env python3
"""dxrice_viewport.py: the running pan offset per workspace, written for
world-attached widgets -- throttled while panning, flushed when it stops."""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dxrice_viewport import Viewport  # noqa: E402


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


class TestViewport(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "dxrice", "viewport.json")
        self.clock = Clock()
        self.v = Viewport(self.path, interval=0.05, clock=self.clock)

    def tearDown(self):
        self.tmp.cleanup()

    def read(self):
        with open(self.path) as f:
            return json.load(f)["offsets"]

    def test_steps_add_up_per_workspace(self):
        self.v.record(1, 10, -4)
        self.clock.t = 0.1
        self.v.record(1, 5, 2)
        self.clock.t = 0.2
        self.v.record(2, -7, 0)
        self.assertEqual(self.read(), {"1": [15, -2], "2": [-7, 0]})

    def test_writes_are_throttled_and_the_end_is_flushed(self):
        self.v.record(1, 10, 0)              # written (first)
        self.clock.t = 0.01
        self.v.record(1, 10, 0)              # too soon: not written yet
        self.assertEqual(self.read(), {"1": [10, 0]})
        self.v.flush()                       # the pan ended
        self.assertEqual(self.read(), {"1": [20, 0]})

    def test_a_zero_step_writes_nothing(self):
        self.v.record(1, 0, 0)
        self.assertFalse(os.path.exists(self.path))

    def test_two_writers_add_up_instead_of_overwriting(self):
        # the daemon, the overview and the window mover all move the camera
        other = Viewport(self.path, interval=0.05, clock=self.clock)
        self.v.record(1, 10, 0)
        other.record(1, 0, 7)
        self.clock.t = 1
        self.v.record(1, 5, 0)
        other.record(2, 3, 3)
        self.assertEqual(self.read(), {"1": [15, 7], "2": [3, 3]})

    def test_the_command_line_adds_a_step(self):
        import subprocess
        script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dxrice_viewport.py")
        env = {**os.environ, "XDG_RUNTIME_DIR": self.tmp.name}
        self.v.record(4, 100, 0)
        for _ in range(2):
            subprocess.run([sys.executable, script, "add", "4", "-30", "12.5"], env=env, check=True)
        self.assertEqual(self.read(), {"4": [40, 25]})
        self.assertNotEqual(subprocess.run([sys.executable, script, "add", "4", "x", "1"], env=env, capture_output=True).returncode, 0)

    def test_a_damaged_file_starts_again_from_zero(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w") as f:
            f.write("{ half written")
        self.v.record(1, 6, 6)
        self.assertEqual(self.read(), {"1": [6, 6]})

    def test_every_camera_move_is_reported(self):
        here = os.path.dirname(os.path.abspath(__file__))
        src = open(os.path.join(here, "dxrice_move_window.py")).read()
        self.assertIn("dxrice_viewport.add_steps", src)
        qml = open(os.path.join(here, "..", "quickshell", "Overview.qml")).read()
        self.assertIn("dxrice_viewport.py", qml)

    def test_keyboard_navigation_reports_its_pan(self):
        # SUPER+arrows moved every window to centre the next one and never
        # said so: widgets that follow the desktop stayed where they were
        import dxrice_navigate_windows as nav
        sent = []
        old = (nav.batch_async, nav.focus_window, nav.dxrice_viewport.default_path)
        nav.batch_async = lambda exprs: sent.extend(exprs)
        nav.focus_window = lambda a: None
        nav.dxrice_viewport.default_path = lambda: self.path
        try:
            wins = [{"address": "0xa", "at": [100, 200], "size": [400, 300], "class": "kitty"},
                    {"address": "0xb", "at": [1500, 200], "size": [400, 300], "class": "kitty"}]
            nav.pan_to_window(wins, "0xb", 960, 540, workspace_id=3)
        finally:
            nav.batch_async, nav.focus_window, nav.dxrice_viewport.default_path = old
        self.assertEqual(len(sent), 2)
        self.assertEqual(self.read(), {"3": [960 - 1700, 540 - 350]})

    def test_a_rigid_shift_is_a_camera_move_and_a_rearrangement_is_not(self):
        from dxrice_viewport import uniform_shift
        self.assertEqual(uniform_shift([(0, 0, 40, -10), (500, 300, 540, 290)]), (40, -10))
        self.assertIsNone(uniform_shift([(0, 0, 40, -10), (500, 300, 520, 290)]))
        self.assertIsNone(uniform_shift([(0, 0, 0.4, 0)]), "sub-pixel noise is no move")
        self.assertIsNone(uniform_shift([]))

    def test_super_g_reports_a_pure_recentre_and_a_rearrangement_brings_the_widgets_home(self):
        src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "dxrice_auto_arrange.py")).read()
        self.assertIn("dxrice_viewport.uniform_shift(", src)
        self.assertIn("dxrice_viewport.home(dxrice_viewport.default_path(), workspace_id)", src)

    def test_home_starts_one_workspace_over(self):
        from dxrice_viewport import add_steps, home
        add_steps(self.path, {1: (-4774, 154), 2: (30, 0)})
        home(self.path, 1)
        self.assertEqual(self.read(), {"2": [30, 0]})
        home(self.path, 9)            # nothing there: nothing changes
        self.assertEqual(self.read(), {"2": [30, 0]})

    def test_the_daemon_reports_its_pan_steps(self):
        src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "dxrice_infinite_desktop_core.py")).read()
        self.assertIn("_viewport.record(workspace_id, idx, idy)", src)
        self.assertIn("_viewport.flush()", src)


if __name__ == "__main__":
    unittest.main()
