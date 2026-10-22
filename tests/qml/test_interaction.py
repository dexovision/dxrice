#!/usr/bin/env python3
"""Shared interaction language: press feedback, reduce_motion, accent use,
busy and empty states, the lock card's states, and content transitions.

    python3 tests/qml/test_interaction.py
"""
import json
import sys
import unittest
from pathlib import Path

try:
    import PySide6  # noqa: F401
except ImportError:  # pragma: no cover
    print("SKIP: PySide6 not installed (pip install PySide6-Essentials)")
    sys.exit(0)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import Scene  # noqa: E402
from test_customization import TE, with_theme  # noqa: E402

# Walks any object's data/children, so it reaches into components the
# scene's own findNamed() doesn't index (the lock surface, a Loader's item).
# (visited objects are skipped: a stub window's contentItem is the window
# itself, and following it again and again once ran this out of memory)
FIND = """const find = (root, pred) => { const st = [root]; const seen = new Set(); while (st.length) { const o = st.pop(); if (!o || seen.has(o)) continue;
    seen.add(o); if (pred(o)) return o; const k = o.data !== undefined ? o.data : []; for (let i = 0; i < k.length; i++) st.push(k[i]);
    if (o.contentItem) st.push(o.contentItem); if (o.item) st.push(o.item); } return null; };"""


class MotionTokensTest(unittest.TestCase):
    def test_reduce_motion_stops_everything_that_moves(self):
        for reduce in (False, True):
            with self.subTest(reduce_motion=reduce):
                s = Scene(width=1280, height=720, setup=with_theme(reduce_motion=reduce))
                try:
                    press = s.ev("theme.pressScale(true)")
                    self.assertEqual(press == 1.0, reduce, f"pressed scale {press}")
                    self.assertEqual(s.ev("theme.durationMove") <= 1, reduce)
                    self.assertEqual(s.ev("theme.contentShift") == 0, reduce)
                    # Colour fades are not motion: kept either way.
                    self.assertGreater(s.ev("theme.durationFast"), 1)
                finally:
                    s.close()


class AccentUseTest(unittest.TestCase):
    """Accent marks small things only. A Theme-editor slider used to be a
    full-height accent-tinted slab; it is now the shell's one slider
    language: a neutral track, the accent only as the thin progress."""

    def test_fill_slider_is_a_neutral_track_with_thin_accent_progress(self):
        s = Scene(width=1920, height=1080, setup=with_theme(accent="e67878"))
        try:
            s.ev("panels.open('theme')")
            s.wait(700)
            s.ev(f"{TE}.currentCategory = 'layout'")
            s.wait(700)
            c = json.loads(s.ev(f"""(function(){{ {FIND}
                const sl = find({TE}, o => String(o).indexOf('FillSlider') === 0);
                const track = find(sl, o => o.objectName === 'fillSliderTrack');
                const prog = find(sl, o => o.objectName === 'fillSliderProgress');
                return JSON.stringify({{track: [track.color.r, track.color.g, track.color.b], prog: [prog.color.r, prog.color.g, prog.color.b],
                                        progH: prog.height, sliderH: sl.height}}); }})()"""))
            r, g, b = c["track"]
            self.assertLess(max(r, g, b) - min(r, g, b), 0.04, f"slider track is tinted: {c['track']}")
            pr, pg, pb = c["prog"]
            self.assertGreater(pr - pg, 0.2, "the progress should carry the accent")
            self.assertLessEqual(c["progH"], 6, "the accent should be a thin line, not a slab")
            self.assertLess(c["progH"] * 4, c["sliderH"])
        finally:
            s.close()


class BusyAndEmptyStatesTest(unittest.TestCase):
    def test_apply_shows_busy_and_takes_no_second_click(self):
        s = Scene(width=1920, height=1080)
        try:
            s.ev("panels.open('theme')")
            s.wait(700)
            s.ev(f"{TE}.applying = true")
            s.wait(100)
            btn = "findNamed('themeApply')"
            self.assertEqual(s.ev(f"{btn}.text"), "Apply", "the label changed and the header would jump")
            self.assertTrue(s.ev(f"""(function(){{ {FIND} const d = find({btn}, o => String(o).indexOf('LoadingDots') === 0); return d !== null && d.visible; }})()"""))
            self.assertFalse(s.ev(f"""(function(){{ {FIND} const a = find({btn}, o => String(o).indexOf('QQuickMouseArea') === 0); return a.enabled; }})()"""),
                             "a busy Apply still takes clicks")
        finally:
            s.close()

    def test_network_list_says_it_is_looking_while_scanning(self):
        s = Scene(width=1920, height=1080)
        try:
            s.ev("panels.open('quicksettings')")
            s.wait(500)
            # Before the backend's first scan reports back.
            st = json.loads(s.ev(f"""(function(){{ {FIND}
                const qs = findPanel('currentTab');
                const wifi = find(qs, o => o.hasScanned !== undefined && o.networks !== undefined);
                wifi.hasScanned = false; wifi.networks = [];
                const empty = find(qs, o => o.busy !== undefined && o.fillHeight !== undefined && o.visible);
                const dots = empty ? find(empty, o => String(o).indexOf('LoadingDots') === 0) : null;
                return JSON.stringify({{text: empty ? empty.text : null, dots: dots ? dots.visible : false, h: empty ? empty.height : 0}}); }})()"""))
            self.assertEqual(st["text"], "Looking for networks")
            self.assertTrue(st["dots"])
            self.assertGreater(st["h"], 60, "the empty state should fill the list, not sit in a 36px line")
        finally:
            s.close()


LOCK = """(function(){ %s
    const lock = findNamed('lockScreen');
    const s = lock.surfaceItem; it = s;
    %s })()"""


class LockCardTest(unittest.TestCase):
    def ev(self, s, body):
        return s.ev(LOCK % (FIND + " let it;", body))

    def test_states(self):
        s = Scene(width=1280, height=720)
        try:
            # The harness has no screens: make this surface the primary one.
            s.ev("findNamed('lockScreen').locked = true; findNamed('lockScreen').surfaceItem.screen = undefined")
            pam = "find(s, o => o.objectName === 'lockPam')"
            submit = "find(s, o => o.objectName === 'lockSubmit')"
            # Nothing typed: the submit arrow is not "ready".
            self.assertFalse(self.ev(s, f"return {submit}.ready;"))
            # Typed: ready; clicking it starts PAM (tryUnlock).
            self.ev(s, "find(s, o => o.echoMode !== undefined && o.passwordCharacter !== undefined).text = 'hunter2';")
            self.assertTrue(self.ev(s, f"return {submit}.ready;"))
            # Checking: dots instead of the arrow.
            self.ev(s, f"{pam}.active = true;")
            self.assertTrue(self.ev(s, f"return find({submit}, o => String(o).indexOf('LoadingDots') === 0).visible;"))
            # Wrong password: red message, field emptied, then typing clears it.
            self.ev(s, f"{pam}.active = false; {pam}.completed(1);")
            msg = self.ev(s, "return find(s, o => o.text === 'Incorrect password') !== null;")
            self.assertTrue(msg)
            color = json.loads(self.ev(s, "const m = find(s, o => o.text === 'Incorrect password'); return JSON.stringify([m.color.r, m.color.g, m.color.b]);"))
            self.assertGreater(color[0] - color[1], 0.15, "the error isn't shown as an error")
            self.ev(s, "find(s, o => o.echoMode !== undefined && o.passwordCharacter !== undefined).text = 'x';")
            self.assertFalse(self.ev(s, "return find(s, o => o.text === 'Incorrect password') !== null;"),
                             "the error stayed up after typing again")
        finally:
            s.ev("findNamed('lockScreen').locked = false")
            s.close()


class ContentTransitionTest(unittest.TestCase):
    def test_category_switch_settles_fully_visible_at_the_top(self):
        s = Scene(width=1920, height=1080)
        try:
            s.ev("panels.open('theme')")
            s.wait(700)
            flick = f"""(function(){{ {FIND} return find({TE}, o => o.contentY !== undefined && o.contentHeight > o.height + 50); }})()"""
            s.ev(f"(function(){{ const f = {flick}; f.contentY = 200; }})()")
            s.ev(f"{TE}.currentCategory = 'experience'")
            s.wait(900)
            st = json.loads(s.ev(f"""(function(){{ {FIND}
                const l = find({TE}, o => o.sourceComponent !== undefined && o.item && o.item.width > 300);
                return JSON.stringify({{op: l.opacity, y: l.transform[0].y, flickY: l.parent.parent.contentY}}); }})()"""))
            self.assertEqual(st["op"], 1)
            self.assertEqual(st["y"], 0)
            self.assertEqual(st["flickY"], 0, "a new category opened scrolled half-way down")
        finally:
            s.close()




class HoverAffordanceTest(unittest.TestCase):
    def test_a_bar_shortcut_names_itself(self):
        # (the dock's delayed tooltip is gone with the dock: the bar shows a
        # hovered shortcut's name in its title at once, and every shortcut
        # carries it as its accessible name)
        from PySide6.QtCore import QPoint
        from PySide6.QtTest import QTest
        s = Scene(width=1920, height=1080)
        try:
            src = (Path(__file__).resolve().parents[2] / "quickshell" / "TopBar.qml").read_text()
            self.assertIn("Accessible.name: app.label", src)
            pos = json.loads(s.ev("(function(){ const t = findNamed('barShortcut:Firefox'); const p = t.mapToItem(null, t.width / 2, t.height / 2); return JSON.stringify([Math.round(p.x), Math.round(p.y)]); })()"))
            QTest.mouseMove(s.view, QPoint(pos[0] - 6, pos[1]))
            QTest.mouseMove(s.view, QPoint(pos[0], pos[1]))
            s.wait(80)
            self.assertEqual(s.ev("findNamed('barTitle').text"), "Firefox")
        finally:
            s.close()

    def test_bar_islands_brighten_under_the_pointer(self):
        s = Scene(width=1920, height=1080)
        try:
            # a section of the one bar lightens under the pointer (its state
            # layer: the sections have no surface of their own any more)
            for name in ("clockIsland", "statusIsland"):
                s.ev(f"findNamed('{name}').hovered = true")
                s.wait(400)
                self.assertGreater(s.ev(f"findNamed('{name}Hover').opacity"), 0.99, name)
                self.assertGreater(s.ev(f"findNamed('{name}Hover').color.hslLightness"), s.ev("theme.panel.hslLightness") + 0.01, name)
                s.ev(f"findNamed('{name}').hovered = false")
                s.wait(400)
                self.assertEqual(s.ev(f"findNamed('{name}Hover').opacity"), 0, name)
        finally:
            s.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
