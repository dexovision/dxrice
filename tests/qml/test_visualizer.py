#!/usr/bin/env python3
"""The desktop audio visualizer: cava runs only while something plays and the
setting is on, its frames become the bars, it never takes input, and a
machine without cava shows nothing.

    python3 tests/qml/test_visualizer.py
"""
import sys
import unittest
from pathlib import Path

try:
    import PySide6  # noqa: F401
except ImportError:  # pragma: no cover
    print("SKIP: PySide6 not installed")
    sys.exit(0)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import Scene  # noqa: E402
from test_customization import with_theme  # noqa: E402

V = "findNamed('visualizer')"
FRAME = ";".join(str(v) for v in [0, 250, 500, 1000] + [100] * 44) + ";"


def cava_runs(s):
    return [r for r in s.bridge.run_log if r and r[0] == "cava"]


class VisualizerTest(unittest.TestCase):
    def scene(self, frames=FRAME, **theme):
        s = Scene(width=1920, height=1080, setup=with_theme(**theme))
        s.set_command("cava -p", frames)
        return s

    def play(self, s, playing=True):
        s.ev(f"setPlayer({{ trackTitle: 'x', isPlaying: {str(playing).lower()} }})")
        s.wait(500)

    def test_nothing_runs_while_nothing_plays(self):
        s = self.scene()
        try:
            s.wait(500)
            self.assertFalse(s.ev(f"{V}.active"))
            self.assertFalse(s.ev(f"{V}.visible"))
            self.assertEqual(cava_runs(s), [])
            self.play(s, playing=False)
            self.assertEqual(cava_runs(s), [], "a paused player must not start cava")
        finally:
            s.close()

    def test_playing_starts_cava_with_the_shells_own_config(self):
        s = self.scene()
        try:
            self.play(s)
            runs = cava_runs(s)
            self.assertGreaterEqual(len(runs), 1)
            self.assertEqual(runs[0][1], "-p")
            self.assertTrue(runs[0][2].endswith("/cava.conf"), runs[0])
            self.assertTrue(s.ev(f"{V}.active"))
        finally:
            s.close()

    def test_a_frame_becomes_the_bars(self):
        s = self.scene()
        try:
            self.play(s)
            s.wait(300)
            vals = s.ev(f"JSON.stringify({V}.values.slice(0, 4))")
            self.assertEqual(vals, "[0,0.25,0.5,1]")
            self.assertEqual(s.ev(f"{V}.values.length"), 48)
            h = [s.ev(f"findNamed('visualizerBars').children[{i}].height") for i in (2, 3)]
            self.assertAlmostEqual(h[1] / h[0], 2.0, delta=0.1)   # 1000 is twice 500
        finally:
            s.close()

    def test_lines_that_are_not_frames_are_ignored_and_values_clamped(self):
        s = self.scene()
        try:
            self.play(s)
            s.ev(f"{V}.feed('cava: warning, something')")
            self.assertEqual(s.ev(f"{V}.values[3]"), 1)
            s.ev(f"{V}.feed('2000;-5;500;')")
            self.assertEqual(s.ev(f"JSON.stringify({V}.values)"), "[1,0,0.5]")
        finally:
            s.close()

    def test_switched_off_it_never_runs(self):
        s = self.scene(widget_visualizer=False)
        try:
            self.play(s)
            self.assertFalse(s.ev(f"{V}.active"))
            self.assertEqual(cava_runs(s), [])
        finally:
            s.close()

    def test_pausing_stops_cava_and_clears_the_bars(self):
        s = self.scene()
        try:
            self.play(s)
            s.ev("setPlayer({ trackTitle: 'x', isPlaying: false })")
            s.wait(600)
            self.assertFalse(s.ev(f"{V}.active"))
            self.assertEqual(s.ev(f"{V}.values.length"), 0)
            self.assertFalse(s.ev("findNamed('visualizerCava').running"))
        finally:
            s.close()

    def test_without_cava_it_stays_hidden(self):
        s = self.scene(frames="__NOSTART__")
        try:
            self.play(s)
            s.wait(300)
            self.assertFalse(s.ev(f"{V}.available"))
            self.assertFalse(s.ev(f"{V}.active"))
            s.wait(2500)
            self.assertEqual(len(cava_runs(s)), 1, "a missing cava must not be retried")
        finally:
            s.close()

    def test_a_cava_that_exits_after_drawing_is_started_again(self):
        s = self.scene()
        try:
            self.play(s)
            n = len(cava_runs(s))
            s.wait(2600)
            self.assertGreater(len(cava_runs(s)), n)
            self.assertTrue(s.ev(f"{V}.available"))
        finally:
            s.close()

    def test_it_is_a_strip_not_a_whole_screen_surface(self):
        s = self.scene()
        try:
            self.play(s)
            self.assertEqual(s.ev(f"{V}.implicitHeight"), s.ev(f"{V}.barHeight"))
            self.assertLess(s.ev(f"{V}.height"), 200)
        finally:
            s.close()

    def test_it_never_takes_input(self):
        s = self.scene()
        try:
            self.play(s)
            self.assertIsNone(s.input_owner(300, 1060))
        finally:
            s.close()

    def test_the_blocks_style_prints_the_spectrum(self):
        s = self.scene(visualizer_style="blocks")
        try:
            self.play(s)
            s.wait(300)
            self.assertTrue(s.ev("findNamed('visualizerBlocks').visible"))
            self.assertFalse(s.ev("findNamed('visualizerBars').visible"))
            self.assertTrue(s.ev("findNamed('visualizerBlocks').text").startswith("  ▂ ▄ █"))
        finally:
            s.close()


if __name__ == "__main__":
    unittest.main()
