"""The Theme editor's colour picker (ColorPopover.qml), driven through the
real shell QML offscreen (see harness.py).

It used to be a QtQuick.Dialogs ColorDialog, which opened as its own
top-level window -- a separate Hyprland client. It is now a child surface
of the Theme panel inside the Theme editor's own window. These pin that
relationship (one surface, attached geometry, on-screen), its input and
focus behaviour (Escape and click-outside peel the picker first, clicks
inside the picker or the panel dismiss nothing), its lifecycle under
rapid open/close, and that the editor itself still closes cleanly.

    python3 tests/qml/test_theme_palette.py
"""
import os
import subprocess
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

TE = "surfaces().filter(w => _name(w).indexOf('ThemeEditor') === 0)[0]"
POP = "findNamed('colorPopover')"
GAP = 12
MARGIN = 8
SETTLE_MS = 700


def v(x):
    return x.toVariant() if hasattr(x, "toVariant") else x


class ThemePaletteTest(unittest.TestCase):
    size = (1920, 1080)

    def setUp(self):
        self.s = Scene(width=self.size[0], height=self.size[1])
        self.s.ev("panels.open('theme')")
        self.s.wait(1000)

    def tearDown(self):
        self.s.close()

    # ---- helpers ----
    def center(self, name):
        return v(self.s.ev(f"(function(){{ const i = findNamed('{name}'); const p = i.mapToItem(null, i.width/2, i.height/2); return [p.x, p.y]; }})()"))

    def rect_of(self, js):
        return v(self.s.ev(f"(function(){{ const i = {js}; const p = i.mapToItem(null, 0, 0); return [p.x, p.y, i.width, i.height]; }})()"))

    def panel(self):
        return self.rect_of(f"(function(){{ const st=[{TE}]; while (st.length) {{ const i = st.pop(); if (i.revealProgress !== undefined) return i; for (let k=0;k<i.children.length;k++) st.push(i.children[k]); }} }})()")

    def flick_of(self, key):
        return f"(function(){{ let i = findNamed('swatch_{key}'); while (i && !(i.contentY !== undefined && i.contentHeight !== undefined)) i = i.parent; return i; }})()"

    def scroll_into_view(self, key):
        """Smaller panels show fewer rows: a swatch scrolled out of view
        cannot be clicked (the click lands outside the panel)."""
        moved = self.s.ev(f"""(function(){{ const f = {self.flick_of(key)}; const sw = findNamed('swatch_{key}');
            const y = sw.mapToItem(f, 0, sw.height / 2).y;
            if (y > 40 && y < f.height - 40) return false;
            f.contentY = Math.max(0, Math.min(f.contentHeight - f.height, f.contentY + y - f.height / 2)); return true; }})()""")
        if moved:
            self.s.wait(400)

    def click_swatch(self, key):
        self.scroll_into_view(key)
        x, y = self.center(f"swatch_{key}")
        self.assertEqual(self.s.click(int(x), int(y)), "ThemeEditor")
        self.s.wait(SETTLE_MS)

    def covered_by_picker(self, key):
        if not self.picker_open():
            return False
        x, y = self.center(f"swatch_{key}")
        px, py, pw, ph = self.rect_of(POP)
        return px <= x <= px + pw and py <= y <= py + ph

    def pick(self, key, label):
        """Click the swatch when it is reachable; if the open picker happens
        to sit over it, drive the same pickColor() path the swatch's own
        handler calls (a covered control is not clickable by design)."""
        self.scroll_into_view(key)
        if self.covered_by_picker(key):
            self.s.ev(f"{TE}.pickColor('{key}', findNamed('swatch_{key}'), '{label}')")
            self.s.wait(SETTLE_MS)
        else:
            self.click_swatch(key)

    def picker_open(self):
        return bool(self.s.ev(f"{TE}.pickerOpen"))

    def theme_open(self):
        return self.s.ev("panels.current") == "theme"

    def expected_side(self):
        # Right of the swatch while the screen leaves 260px there; on a
        # narrow screen, left of it -- over the panel's own labels.
        return "left" if self.size[0] <= 1024 else "right"

    def swatch_rect(self, key):
        return self.rect_of(f"findNamed('swatch_{key}')")

    # ---- tests ----
    def test_01_swatch_opens_an_attached_picker(self):
        self.click_swatch("glass_bg")
        self.assertTrue(self.picker_open())
        self.assertEqual(self.s.ev(f"{POP}.reveal"), 1)
        self.assertTrue(self.theme_open(), "opening the picker closed the Theme editor")
        side = self.s.ev(f"{POP}.side")
        self.assertEqual(side, self.expected_side())
        px, py, pw, ph = self.rect_of(POP)
        bx, by, bw, bh = self.panel()
        tx, ty, tw, th = self.swatch_rect("glass_bg")
        # Attached to the SWATCH's own edge, not the panel's.
        if side == "right":
            self.assertAlmostEqual(px - (tx + tw), GAP, delta=0.6, msg="not attached to the swatch's right edge")
        else:
            self.assertAlmostEqual(tx - (px + pw), GAP, delta=0.6, msg="not attached to the swatch's left edge")
        self.assertTrue(py <= ty + th / 2 <= py + ph, "the swatch is not level with the picker")
        self.assertGreaterEqual(py, by - 0.6, "picker rides up over the bar")
        self.assertLessEqual(py + ph, by + bh + 0.6, "picker hangs below the Theme editor")
        # The connector spans the gap from the swatch's edge to the picker,
        # level with the swatch.
        nx, ny, nw, nh = self.rect_of("findNamed('colorPopoverNeck')")
        near = tx + tw if side == "right" else tx
        self.assertTrue(min(abs(nx - near), abs(nx + nw - near)) <= 1.6, f"connector does not start at the swatch: neck={nx,nw} swatch edge={near}")
        self.assertTrue(ny <= ty + th / 2 <= ny + nh, "connector is not level with the swatch")
        self.assertGreater(self.s.ev("findNamed('colorPopoverNeck').opacity"), 0.99)
        self.assertEqual(self.s.ev(f"{POP}.title"), "Panel background")

    def test_02_one_surface_not_a_separate_window(self):
        before = sorted(v(self.s.ev("surfaces().map(w => _name(w))")))
        self.click_swatch("glass_bg")
        after = sorted(v(self.s.ev("surfaces().map(w => _name(w))")))
        self.assertEqual(before, after, "opening the picker created a new surface/window")
        self.assertFalse(any(self.s.ev("surfaces().some(w => w.isToplevelWindow === true)") for _ in [0]))
        owner = self.s.ev(f"(function(){{ let i = {POP}; const t = {TE}; while (i) {{ if (i === t) return true; i = i.parent; }} return false; }})()")
        self.assertTrue(owner, "the picker is not a child of the Theme editor's own window")
        src = (Path(__file__).resolve().parents[2] / "quickshell" / "ThemeEditor.qml").read_text()
        self.assertNotIn("ColorDialog {", src, "a ColorDialog (a separate top-level window) is back")

    def test_02b_opens_from_the_swatch(self):
        """The surface's first frame is the swatch's own footprint on the
        facing edge, level with it -- it grows out of the swatch rather
        than appearing at its final place and scaling."""
        self.click_swatch("glass_bg")
        s = self.s
        tx, ty, tw, th = self.swatch_rect("glass_bg")
        px, py, pw, ph = self.rect_of(POP)
        st = v(s.ev(f"(function(){{ const r = {POP}.startRect; return [r.x, r.y, r.width, r.height]; }})()"))
        self.assertAlmostEqual(st[3], th, delta=0.6, msg="stem is not the swatch's height")
        self.assertAlmostEqual(py + st[1] + st[3] / 2, ty + th / 2, delta=1.0, msg="stem is not level with the swatch")
        edge = px if s.ev(f"{POP}.side") == "right" else px + pw - st[2]
        self.assertAlmostEqual(px + st[0], edge, delta=0.6, msg="stem is not on the edge facing the swatch")

    def test_03_stays_on_screen(self):
        for key in ("glass_bg", "glass_bg_active", "glass_text"):
            self.s.ev(f"{TE}.closePicker()"); self.s.wait(SETTLE_MS)
            self.click_swatch(key)
            px, py, pw, ph = self.rect_of(POP)
            W, H = self.size
            self.assertGreaterEqual(px, MARGIN - 0.6, key)
            self.assertGreaterEqual(py, MARGIN - 0.6, key)
            self.assertLessEqual(px + pw, W - MARGIN + 0.6, key)
            self.assertLessEqual(py + ph, H - MARGIN + 0.6, key)

    def test_04_done_writes_cancel_and_x_do_not(self):
        s = self.s
        old = s.ev(f"{TE}.glass_bg")
        self.click_swatch("glass_bg")
        s.ev(f"{POP}.hue = 0.0; {POP}.sat = 1.0; {POP}.val = 1.0")
        x, y = self.center("colorPopoverCancel"); s.click(int(x), int(y)); s.wait(SETTLE_MS)
        self.assertFalse(self.picker_open())
        self.assertEqual(s.ev(f"{TE}.glass_bg"), old, "Cancel changed the colour")
        self.click_swatch("glass_bg")
        s.ev(f"{POP}.hue = 0.0; {POP}.sat = 1.0; {POP}.val = 1.0")
        x, y = self.center("colorPopoverClose"); s.click(int(x), int(y)); s.wait(SETTLE_MS)
        self.assertFalse(self.picker_open())
        self.assertEqual(s.ev(f"{TE}.glass_bg"), old, "X changed the colour")
        self.click_swatch("glass_bg")
        s.ev(f"{POP}.hue = 0.0; {POP}.sat = 1.0; {POP}.val = 1.0")
        x, y = self.center("colorPopoverDone"); s.click(int(x), int(y)); s.wait(SETTLE_MS)
        self.assertFalse(self.picker_open())
        self.assertEqual(s.ev(f"{TE}.glass_bg"), "ff0000")
        self.assertTrue(s.ev(f"{TE}.dirty"))
        self.assertTrue(self.theme_open())

    def test_05_hex_entry_and_focus(self):
        s = self.s
        self.click_swatch("glass_text")
        s.ev("findNamed('colorPopoverHex').forceActiveFocus()")
        s.ev("findNamed('colorPopoverHex').text = '#3a7bd5'")
        s.ev("findNamed('colorPopoverHex').accepted()")
        s.wait(SETTLE_MS)
        self.assertEqual(s.ev(f"{TE}.glass_text"), "3a7bd5")
        self.assertFalse(self.picker_open())
        self.assertFalse(s.ev("findNamed('colorPopoverHex').activeFocus"), "closed picker kept keyboard focus")

    def test_06_reopen_retarget_and_toggle(self):
        s = self.s
        self.click_swatch("glass_bg")
        self.pick("glass_bg_active", "Active panel background")
        self.assertTrue(self.picker_open(), "picking a second swatch closed the picker instead of retargeting")
        self.assertEqual(s.ev(f"{TE}.editingColorKey"), "glass_bg_active")
        self.assertEqual(s.ev(f"{POP}.initialHex"), s.ev(f"{TE}.glass_bg_active"))
        self.assertEqual(s.ev(f"{POP}.title"), "Active panel background")
        self.pick("glass_bg_active", "Active panel background")
        self.assertFalse(self.picker_open(), "the same swatch again should close it")
        self.click_swatch("glass_bg")
        self.assertTrue(self.picker_open(), "reopen after close failed")
        self.assertEqual(s.ev(f"{POP}.reveal"), 1)

    def test_07_rapid_open_close_reopen(self):
        s = self.s
        for i in range(24):
            if i % 2 == 0:
                s.ev(f"(function(){{ const sw = findNamed('swatch_glass_bg'); {TE}.pickColor('glass_bg', sw, 'Panel background'); }})()")
            else:
                s.ev(f"{TE}.closePicker()")
            s.wait(10 + (i * 11) % 70)
        final = self.picker_open()
        s.wait(SETTLE_MS)
        self.assertEqual(s.ev(f"{POP}.reveal"), 1 if final else 0, "reveal did not settle to the final state")
        self.assertEqual(bool(s.ev(f"{POP}.visible")), final)
        # reopen during a close reverses mid-flight
        if not final:
            self.click_swatch("glass_bg")
        s.ev(f"{TE}.closePicker()"); s.wait(90)
        mid = s.ev(f"{POP}.reveal")
        self.assertTrue(0 < mid < 1, f"expected a mid-flight close, reveal={mid}")
        self.click_swatch("glass_bg")
        self.assertEqual(s.ev(f"{POP}.reveal"), 1)
        self.assertTrue(self.theme_open())

    def test_08_escape_closes_the_picker_first(self):
        s = self.s
        self.click_swatch("glass_bg")
        claims = v(s.ev("escapeClaims()"))
        self.assertLessEqual(claims.get("ThemeEditor", 0), 1, f"duplicate Escape shortcuts in the Theme window: {claims}")
        s.ev("findNamed('themeEscape').activated()"); s.wait(SETTLE_MS)
        self.assertFalse(self.picker_open(), "Escape did not close the picker")
        self.assertTrue(self.theme_open(), "Escape closed the Theme editor instead of just the picker")
        s.ev("findNamed('themeEscape').activated()"); s.wait(1100)
        self.assertFalse(self.theme_open(), "second Escape did not close the Theme editor")

    def test_09_clicks_inside_the_picker_dismiss_nothing(self):
        s = self.s
        self.click_swatch("glass_bg")
        px, py, pw, ph = self.rect_of(POP)
        # bare header area (beside the title), then a drag in the SV square
        s.click(int(px + 20), int(py + 14)); s.wait(300)
        self.assertTrue(self.picker_open(), "clicking the picker's own background closed it")
        sx, sy, sw, sh = self.rect_of("findNamed('colorPopoverSV')")
        s.click(int(sx + sw * 0.8), int(sy + sh * 0.2)); s.wait(300)
        self.assertTrue(self.picker_open())
        self.assertTrue(self.theme_open())
        self.assertGreater(s.ev(f"{POP}.sat"), 0.6, "clicking the SV square did not set the colour")

    def test_10_clicks_inside_the_panel_dismiss_nothing(self):
        s = self.s
        bx, by, bw, bh = self.panel()
        bare = (int(bx + 200), int(by + 28))  # beside the "Theme" title, no control
        self.click_swatch("glass_bg")
        s.click(*bare); s.wait(400)
        self.assertTrue(self.picker_open(), "clicking the Theme panel closed the picker")
        self.assertTrue(self.theme_open(), "clicking the Theme panel closed the Theme editor")
        s.ev(f"{TE}.closePicker()"); s.wait(SETTLE_MS)
        s.click(*bare); s.wait(400)
        self.assertTrue(self.theme_open(), "a bare click inside the Theme panel closed it")

    def test_11_click_outside_peels_picker_then_editor(self):
        s = self.s
        self.click_swatch("glass_bg")
        outside = (20, int(self.size[1] * 0.6))
        self.assertEqual(s.click(*outside), "ThemeEditor")
        s.wait(SETTLE_MS)
        self.assertFalse(self.picker_open(), "click outside did not close the picker")
        self.assertTrue(self.theme_open(), "the first outside click closed the whole editor")
        s.click(*outside); s.wait(1100)
        self.assertFalse(self.theme_open(), "the second outside click did not close the editor")

    def test_12_closed_picker_leaves_no_input(self):
        s = self.s
        self.click_swatch("glass_bg")
        px, py, pw, ph = self.rect_of(POP)
        spot = (int(px + pw / 2), int(py + ph / 2))
        s.ev(f"{TE}.closePicker()"); s.wait(SETTLE_MS)
        self.assertFalse(s.ev(f"{POP}.visible"))
        bx, by, bw, bh = self.panel()
        if bx <= spot[0] <= bx + bw and by <= spot[1] <= by + bh:
            # Over the panel (narrow screen): the click reaches the panel
            # again -- it neither reopens a ghost picker nor closes anything.
            s.click(*spot); s.wait(400)
            self.assertTrue(self.theme_open())
            self.assertFalse(self.picker_open())
            self.assertFalse(s.ev(f"{POP}.visible"))
        else:
            # Outside the panel: plain Theme click-outside again -- it closes
            # the editor (existing behaviour), nothing invisible swallows it.
            s.click(*spot); s.wait(1100)
            self.assertFalse(self.theme_open(), "a click where the closed picker was did not reach click-outside")
            self.assertIsNone(s.input_owner(*spot), "input still owned where the picker was after the editor closed")

    def test_13_editor_closes_with_the_picker_open(self):
        s = self.s
        self.click_swatch("glass_bg")
        px, py, pw, ph = self.rect_of(POP)
        s.ev("panels.closeCurrent()"); s.wait(60)
        self.assertFalse(self.picker_open(), "picker stayed open while the editor closed")
        self.assertIsNone(s.input_owner(int(px + pw / 2), int(py + ph / 2)), "picker area still takes input mid-close")
        s.wait(1100)
        self.assertEqual(v(s.ev("surfaces().filter(w => _name(w).indexOf('ThemeEditor') === 0).length")), 0)
        # and it opens again cleanly, picker closed
        s.ev("panels.open('theme')"); s.wait(1000)
        self.assertFalse(self.picker_open())
        self.click_swatch("glass_bg")
        self.assertTrue(self.picker_open())

    def test_14_category_switch_and_revert_close_it(self):
        s = self.s
        self.click_swatch("glass_bg")
        s.ev(f"{TE}.currentCategory = 'blur'"); s.wait(SETTLE_MS)
        self.assertFalse(self.picker_open(), "picker outlived its swatch's category")
        s.ev(f"{TE}.currentCategory = 'colors'"); s.wait(SETTLE_MS)
        self.click_swatch("glass_bg")
        s.ev(f"{TE}.revert()"); s.wait(SETTLE_MS)
        self.assertFalse(self.picker_open(), "picker survived Revert")

    def test_15_follows_the_swatch_when_the_pane_scrolls(self):
        s = self.s
        self.click_swatch("glass_bg")
        tx0, ty0, _, th = self.swatch_rect("glass_bg")
        delta = 30 if s.ev(f"{self.flick_of('glass_bg')}.contentY") + 30 <= s.ev(f"(function(){{ const f = {self.flick_of('glass_bg')}; return f.contentHeight - f.height; }})()") else -30
        s.ev(f"(function(){{ const f = {self.flick_of('glass_bg')}; f.contentY = f.contentY + {delta}; }})()"); s.wait(400)
        tx1, ty1, _, _ = self.swatch_rect("glass_bg")
        self.assertAlmostEqual(ty1 - ty0, -delta, delta=0.6, msg="fixture: the swatch did not move")
        self.assertTrue(self.picker_open(), "a small scroll closed the picker")
        t = v(s.ev(f"(function(){{ const r = {POP}.targetRect; return [r.x, r.y]; }})()"))
        self.assertAlmostEqual(t[1], ty1, delta=0.6, msg="picker is still attached to the swatch's OLD position")
        nx, ny, nw, nh = self.rect_of("findNamed('colorPopoverNeck')")
        self.assertTrue(ny <= ty1 + th / 2 <= ny + nh, "connector did not follow the swatch")

    def test_15b_swatch_scrolled_out_of_view_closes_it(self):
        """The lowest swatch is only reachable scrolled down; opening its
        picker there and scrolling back to the top carries the swatch out
        of the pane -- there is nothing left to be attached to."""
        s = self.s
        key = "hypr_inactive_border"
        self.click_swatch(key)
        self.assertTrue(self.picker_open())
        f = self.flick_of(key)
        s.ev(f"{f}.contentY = 0"); s.wait(500)
        y = s.ev(f"(function(){{ const sw = findNamed('swatch_{key}'); return sw.mapToItem({f}, 0, sw.height / 2).y; }})()")
        h = s.ev(f"{f}.height")
        self.assertGreater(y, h, "fixture: the swatch is still inside the pane")
        self.assertFalse(self.picker_open(), "picker stayed attached to a swatch scrolled out of view")

    def test_16_no_new_warnings(self):
        self.click_swatch("glass_bg")
        self.s.ev(f"{POP}.hue = 0.5"); self.s.wait(100)
        self.s.ev(f"{TE}.closePicker()"); self.s.wait(SETTLE_MS)
        bad = [w for w in self.s.warnings if "propertyCache" not in w]
        self.assertEqual(bad, [])


def main():
    size = os.environ.get("DXRICE_TEST_SIZE")
    if size:
        ThemePaletteTest.size = tuple(int(x) for x in size.split("x"))
        unittest.main(argv=[sys.argv[0], "-v"] + sys.argv[1:])
        return
    failed = []
    for sz in ["1920x1080", "1366x768", "1024x768"]:
        print(f"===== {sz} =====", flush=True)
        if subprocess.call([sys.executable, __file__] + sys.argv[1:], env={**os.environ, "DXRICE_TEST_SIZE": sz}):
            failed.append(sz)
    print("FAILED sizes: " + ", ".join(failed) if failed else "ALL SIZES PASSED")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
