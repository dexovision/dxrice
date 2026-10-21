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

    def test_the_daemon_reports_its_pan_steps(self):
        src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "dxrice_infinite_desktop_core.py")).read()
        self.assertIn("_viewport.record(workspace_id, idx, idy)", src)
        self.assertIn("_viewport.flush()", src)


if __name__ == "__main__":
    unittest.main()
