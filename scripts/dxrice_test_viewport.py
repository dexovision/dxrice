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

    def test_the_daemon_reports_its_pan_steps(self):
        src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "dxrice_infinite_desktop_core.py")).read()
        self.assertIn("_viewport.record(workspace_id, idx, idy)", src)
        self.assertIn("_viewport.flush()", src)


if __name__ == "__main__":
    unittest.main()
