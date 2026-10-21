#!/usr/bin/env python3
"""The desktop's layout and its motion, through the real shell QML offscreen:

- the widgets follow the infinite desktop by default, on the same spring
  Hyprland moves the windows with (hyprland.lua's "easy"), all of them as
  one -- and cut, not slide, on a workspace switch or the overview's pan;
- the audio visualizer's band along the bottom is kept clear of them while
  it can show, at any screen size, and given back when it can't;
- a corner that runs out of height wraps into a new column instead of
  overlapping the facing corner.

    python3 tests/qml/test_widget_layout.py
"""
import json
import re
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

REPO = Path(__file__).resolve().parents[2]
ALL_ON = dict(widget_clock=True, widget_music=True, widget_system=True, widget_timer=True, widget_reminders=True,
              widget_weather=True, widget_cpu=True, widget_memory=True, widget_disk=True, widget_visualizer=True)


FRAME = ";".join(["300"] * 48) + ";"


def scene(w=1920, h=1080, **theme):
    s = Scene(width=w, height=h, setup=with_theme(**theme))
    s.set_command("cava -p", FRAME)      # cava works on this "machine"
    return s


def rect(s, name):
    return json.loads(s.ev(f"(function(){{ const c = findNamed('widgetCard:{name}'); if (!c || !c.visible || c.opacity < 0.5) return 'null';"
                           " const p = c.mapToItem(null, 0, 0), q = c.mapToItem(null, c.width, c.height);"
                           " return JSON.stringify([p.x, p.y, q.x - p.x, q.y - p.y]); })()"))


def shown_rects(s):
    names = ["clock", "music", "system", "timer", "reminders", "weather", "cpu", "memory", "disk", "battery"]
    return {n: r for n in names if (r := rect(s, n))}


def overlap(a, b):
    return a[0] < b[0] + b[2] and b[0] < a[0] + a[2] and a[1] < b[1] + b[3] and b[1] < a[1] + a[3]


def spring_after(t, x0, goal, k=71.2633, c=15.8273644, m=1.0):
    """Hyprland's window spring from rest at x0 toward goal, t seconds on
    (fine Euler steps: the reference the shell's follower must match)."""
    x, v, h = x0, 0.0, 1e-4
    for _ in range(int(round(t / h))):
        v += h * (-k * (x - goal) - c * v) / m
        x += h * v
    return x


class SpringTest(unittest.TestCase):
    def test_the_spring_is_hyprlands_window_spring(self):
        lua = (REPO / "hypr" / "hyprland.lua").read_text()
        m = re.search(r'hl\.curve\("easy",\s*\{[^}]*mass\s*=\s*([\d.]+)[^}]*stiffness\s*=\s*([\d.]+)[^}]*dampening\s*=\s*([\d.]+)', lua)
        self.assertIsNotNone(m, "hyprland.lua has no \"easy\" spring")
        self.assertRegex(lua, r'leaf = "windows",[^)]*spring = "easy"', "the windows no longer move on \"easy\"")
        s = scene()
        try:
            sp = s.ev("JSON.stringify(viewport.spring)")
            sp = json.loads(sp)
            self.assertAlmostEqual(sp["mass"], float(m.group(1)), places=4)
            self.assertAlmostEqual(sp["stiffness"], float(m.group(2)), places=4)
            self.assertAlmostEqual(sp["damping"], float(m.group(3)), places=4)
        finally:
            s.close()

    def test_one_step_moves_as_the_spring_does(self):
        s = scene()
        try:
            s.wait(400)
            w = s.ev("viewport.workspace")
            s.ev(f"viewport.offsets = ({{ '{w}': [400, -200] }}); viewport.follow.running = false;"
                 " viewport.x = 0; viewport.y = 0; viewport._vx = 0; viewport._vy = 0")
            for t in (0.05, 0.1):       # two steps, as two frames would
                s.ev("viewport.step(0.05)")
                self.assertAlmostEqual(s.ev("viewport.x"), spring_after(t, 0, 400), delta=1.0)
                self.assertAlmostEqual(s.ev("viewport.y"), spring_after(t, 0, -200), delta=1.0)
        finally:
            s.close()

    def test_widgets_follow_by_default_gradually_and_together(self):
        s = scene(widget_clock=True, widget_music=True, widget_system=True)
        try:
            s.wait(700)
            home = {n: rect(s, n) for n in ("clock", "music", "system")}
            w = s.ev("viewport.workspace")
            s.ev(f"viewport.offsets = ({{ '{w}': [-500, 0] }})")
            s.wait(60)
            mid = {n: rect(s, n) for n in home}
            moved = [mid[n][0] - home[n][0] for n in home]
            self.assertLess(moved[0], -5, "it didn't start following")
            self.assertGreater(moved[0], -480, "it jumped instead of travelling with the windows")
            for d in moved[1:]:
                self.assertAlmostEqual(d, moved[0], delta=0.5, msg="widgets drifted apart mid-pan")
            s.wait(1600)
            for n in home:
                self.assertAlmostEqual(rect(s, n)[0], home[n][0] - 500, delta=0.5)
                self.assertAlmostEqual(rect(s, n)[1], home[n][1], delta=0.5)
            self.assertFalse(s.ev("viewport.follow.running"), "the spring kept running after settling")
        finally:
            s.close()

    def test_one_set_to_stay_on_the_screen_stays(self):
        s = scene(widget_clock=True, widget_clock_world=False, widgets_world=True)
        try:
            s.wait(600)
            x = rect(s, "clock")[0]
            w = s.ev("viewport.workspace")
            s.ev(f"viewport.offsets = ({{ '{w}': [-500, 0] }})")
            s.wait(900)
            self.assertAlmostEqual(rect(s, "clock")[0], x, delta=0.5)
        finally:
            s.close()

    def test_all_can_be_kept_on_the_screen(self):
        s = scene(widget_clock=True, widgets_world=False)
        try:
            s.wait(600)
            x = rect(s, "clock")[0]
            w = s.ev("viewport.workspace")
            s.ev(f"viewport.offsets = ({{ '{w}': [-500, 0] }})")
            s.wait(900)
            self.assertAlmostEqual(rect(s, "clock")[0], x, delta=0.5)
        finally:
            s.close()

    def test_a_workspace_switch_cuts_to_that_workspaces_pan(self):
        s = scene(widget_clock=True)
        try:
            s.wait(600)
            x = rect(s, "clock")[0]
            s.ev("viewport.offsets = ({ '2': [300, 0] })")
            s.wait(100)
            self.assertAlmostEqual(rect(s, "clock")[0], x, delta=0.5, msg="another workspace's pan moved it")
            s.ev("hypr.workspaces = ({ values: [{ id: 1, focused: false, activate: function() {} },"
                 " { id: 2, focused: true, activate: function() {} }] })")
            s.wait(30)
            self.assertAlmostEqual(rect(s, "clock")[0], x + 300, delta=0.5, msg="it slid across on a workspace switch")
        finally:
            s.close()

    def test_the_overviews_unanimated_pan_lands_at_once(self):
        s = scene(widget_clock=True)
        try:
            s.wait(600)
            x = rect(s, "clock")[0]
            s.ev("viewport.add(viewport.workspace, -240, 0)")
            s.wait(30)
            self.assertAlmostEqual(rect(s, "clock")[0], x - 240, delta=0.5)
        finally:
            s.close()


class VisualizerBandTest(unittest.TestCase):
    def band(self, s):
        return s.ev("findNamed('visualizer').barHeight")

    def test_bottom_widgets_sit_above_the_band_while_a_player_exists(self):
        s = scene(widget_music=True, widget_music_pos="bottom-left", widget_weather=True, widget_weather_pos="bottom-right",
                  widget_visualizer=True)
        try:
            s.wait(700)
            self.assertEqual(rect(s, "music")[1] + rect(s, "music")[3], 1080 - 28, "no player: the card sits by the edge")
            s.ev("setPlayer({ trackTitle: 'x', isPlaying: false })")
            s.wait(900)
            band = self.band(s)
            self.assertEqual(band, 150)
            for n in ("music", "weather"):
                r = rect(s, n)
                self.assertLessEqual(r[1] + r[3], 1080 - band - 16 + 0.5, f"{n} covers the visualizer: {r}")
            # pausing/playing from the card doesn't move it out from under the pointer
            y = rect(s, "music")[1]
            s.ev("setPlayer({ trackTitle: 'x', isPlaying: true })")
            s.wait(500)
            self.assertAlmostEqual(rect(s, "music")[1], y, delta=0.5)
            # the player goes: the band is given back, smoothly
            s.ev("setPlayer(null)")
            s.wait(80)
            r = rect(s, "music")
            self.assertGreater(r[1] + r[3], y + 148, "it should be on its way down")
            self.assertLess(r[1] + r[3], 1080 - 28, "it jumped down")
            s.wait(900)
            self.assertAlmostEqual(rect(s, "music")[1] + rect(s, "music")[3], 1080 - 28, delta=0.5)
        finally:
            s.close()

    def test_no_band_with_the_visualizer_off(self):
        s = scene(widget_music=True, widget_visualizer=False)
        try:
            s.ev("setPlayer({ trackTitle: 'x', isPlaying: true })")
            s.wait(900)
            self.assertAlmostEqual(rect(s, "music")[1] + rect(s, "music")[3], 1080 - 28, delta=0.5)
        finally:
            s.close()

    def check_screen(self, w, h):
        s = scene(w, h, **ALL_ON)
        try:
            s.ev("setPlayer({ trackTitle: 'x', isPlaying: true })")
            s.wait(1200)
            band = self.band(s)
            rs = shown_rects(s)
            self.assertGreaterEqual(len(rs), 9, rs.keys())
            names = list(rs)
            for i, a in enumerate(names):
                ra = rs[a]
                self.assertLessEqual(ra[1] + ra[3], h - band - 16 + 0.5, f"{a} covers the visualizer at {w}x{h}: {ra}")
                self.assertGreaterEqual(ra[1], 60, f"{a} under the bar at {w}x{h}")
                self.assertGreaterEqual(ra[0], 0)
                self.assertLessEqual(ra[0] + ra[2], w)
                for b in names[i + 1:]:
                    self.assertFalse(overlap(ra, rs[b]), f"{a} {ra} overlaps {b} {rs[b]} at {w}x{h}")
            return band
        finally:
            s.close()

    def test_every_widget_on_a_1080p_screen(self):
        self.assertEqual(self.check_screen(1920, 1080), 150)

    def test_every_widget_on_a_short_screen(self):
        self.assertEqual(self.check_screen(1366, 768), 107)

    def test_every_widget_on_a_tall_screen(self):
        self.check_screen(2560, 1440)


class ScaleTest(unittest.TestCase):
    def test_widgets_keep_their_proportions_on_another_screen(self):
        sizes = {}
        for w, h in ((1920, 1080), (1366, 768), (2560, 1440)):
            s = scene(w, h, widget_music=True, widget_clock=True)
            try:
                s.wait(800)
                sizes[h] = (rect(s, "music"), rect(s, "clock"))
            finally:
                s.close()
        self.assertAlmostEqual(sizes[768][0][2] / sizes[1080][0][2], 0.72, delta=0.01)
        self.assertAlmostEqual(sizes[1440][0][2] / sizes[1080][0][2], 1440 / 1080, delta=0.04)
        # the corner margins don't scale: the edge stays where the bar's is
        for h in sizes:
            self.assertAlmostEqual(sizes[h][0][0], 28, delta=0.5)
            self.assertAlmostEqual(sizes[h][1][0], 28, delta=0.5)


class FlowTest(unittest.TestCase):
    def test_a_full_side_wraps_into_a_new_column(self):
        left = dict(widget_clock=True, widget_reminders=True, widget_reminders_pos="top-left", widget_system=True,
                    widget_system_pos="top-left", widget_music=True, widget_timer=True, widget_timer_pos="bottom-left",
                    widget_weather=True, widget_weather_pos="bottom-left", widget_visualizer=True)
        s = scene(1366, 768, **left)
        try:
            s.ev("setPlayer({ trackTitle: 'x', isPlaying: true })")
            s.wait(1200)
            rs = shown_rects(s)
            names = list(rs)
            for i, a in enumerate(names):
                for b in names[i + 1:]:
                    self.assertFalse(overlap(rs[a], rs[b]), f"{a} {rs[a]} overlaps {b} {rs[b]}")
            # something moved inward rather than on top
            self.assertGreater(max(r[0] for r in rs.values()), 28 + 100)
        finally:
            s.close()

if __name__ == "__main__":
    unittest.main(verbosity=1)
