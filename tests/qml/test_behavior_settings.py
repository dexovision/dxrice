#!/usr/bin/env python3
"""Settings > Experience > "Automatic window placement" (and "Reduce
motion"): what the user sees, what a click does, what Apply writes.

The placement daemon reads theme.json "auto_place_windows" (missing = on);
see scripts/dxrice_test_auto_place_cloud.py for what it does with it.

    python3 tests/qml/test_behavior_settings.py
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


def centre(s, name):
    return json.loads(s.ev(f"(function(){{ const b = findNamed('{name}'); if (!b || !b.visible) return 'null';"
                           f" const p = b.mapToItem(null, b.width / 2, b.height / 2);"
                           f" return JSON.stringify([Math.round(p.x), Math.round(p.y)]); }})()"))


def theme_json(s):
    return json.loads((Path(s.bridge.config_home) / "dxrice" / "theme.json").read_text())


class LayoutPickerTest(unittest.TestCase):
    """Settings > Experience > Window layout: two pickers (windows opening on
    their own, SUPER+G), Expansion selected for a fresh config, a click
    selects, Apply saves each separately, and the two never affect each other."""

    def open_experience(self, s):
        s.ev("panels.open('theme')")
        s.wait(700)
        s.ev(f"{TE}.currentCategory = 'experience'")
        s.wait(900)

    def click_card(self, s, name):
        # the page scrolls: bring the card into view, then click where it is
        s.ev(f"(function(){{ const b = findNamed('{name}'); let it = b; while (it) {{ if (it.contentY !== undefined && it.contentHeight !== undefined) {{"
             f" const p = b.mapToItem(it.contentItem, 0, 0); it.contentY = Math.max(0, p.y - 80); break; }} it = it.parent; }} }})()")
        s.wait(300)
        x, y = centre(s, name)
        owner = s.click(x, y)
        s.wait(250)
        return owner

    def test_a_fresh_config_selects_expansion_in_both(self):
        s = Scene(width=1920, height=1080, setup=with_theme(layout_auto_place=None, layout_super_g=None))
        try:
            self.open_experience(s)
            self.assertEqual(s.ev(f"{TE}.layout_auto_place"), "expansion")
            self.assertEqual(s.ev(f"{TE}.layout_super_g"), "expansion")
            for prefix in ("layoutAuto:", "layoutSuperG:"):
                for mode in ("expansion", "spiral", "compact"):
                    self.assertTrue(s.ev(f"findNamed('{prefix}{mode}') !== null"), prefix + mode)
            self.assertTrue(s.ev("findNamed('layoutAuto:expansion').picked"))
            self.assertFalse(s.ev("findNamed('layoutAuto:spiral').picked"))
            self.assertFalse(s.ev(f"{TE}.dirty"))
        finally:
            s.close()

    def test_clicking_selects_one_picker_only_and_apply_saves_it(self):
        s = Scene(width=1920, height=1080, setup=with_theme(layout_auto_place=None, layout_super_g=None, my_custom_key=[1, 2]))
        try:
            self.open_experience(s)
            self.assertTrue(self.click_card(s, "layoutSuperG:spiral").startswith("ThemeEditor"))
            self.assertEqual(s.ev(f"{TE}.layout_super_g"), "spiral")
            self.assertEqual(s.ev(f"{TE}.layout_auto_place"), "expansion", "one picker changed the other")
            self.assertTrue(s.ev(f"{TE}.dirty"))
            self.click_card(s, "layoutAuto:compact")
            self.assertEqual(s.ev(f"{TE}.layout_auto_place"), "compact")
            self.assertEqual(s.ev(f"{TE}.layout_super_g"), "spiral")
            s.ev(f"{TE}.apply()")
            s.wait(500)
            saved = theme_json(s)
            self.assertEqual((saved.get("layout_auto_place"), saved.get("layout_super_g")), ("compact", "spiral"))
            self.assertEqual(saved.get("my_custom_key"), [1, 2], "Apply lost an unrelated key")
        finally:
            s.close()

    def test_saved_choices_are_shown_after_reopening(self):
        s = Scene(width=1920, height=1080, setup=with_theme(layout_auto_place="spiral", layout_super_g="compact"))
        try:
            self.open_experience(s)
            self.assertTrue(s.ev("findNamed('layoutAuto:spiral').picked"))
            self.assertTrue(s.ev("findNamed('layoutSuperG:compact').picked"))
        finally:
            s.close()

    def test_an_unknown_saved_value_picks_nothing_and_breaks_nothing(self):
        s = Scene(width=1920, height=1080, setup=with_theme(layout_auto_place="grid"))
        try:
            self.open_experience(s)
            for mode in ("expansion", "spiral", "compact"):
                self.assertFalse(s.ev(f"findNamed('layoutAuto:{mode}').picked"))
        finally:
            s.close()


class AutoPlacementSwitchTest(unittest.TestCase):
    def open_experience(self, s):
        s.ev("panels.open('theme')")
        s.wait(700)
        s.ev(f"{TE}.currentCategory = 'experience'")
        s.wait(600)

    def test_old_theme_json_without_the_key_shows_on(self):
        """Placement has always been on; a theme.json from before the switch
        existed must read as on, not off."""
        s = Scene(width=1920, height=1080, setup=with_theme(auto_place_windows=None, reduce_motion=None))
        try:
            self.open_experience(s)
            self.assertIsNotNone(centre(s, "autoPlaceSwitch"), "switch not shown on the Experience page")
            self.assertTrue(s.ev("findNamed('autoPlaceSwitch').checked"))
            self.assertFalse(s.ev("findNamed('reduceMotionSwitch').checked"))
            self.assertFalse(s.ev(f"{TE}.dirty"), "merely opening the page made an unapplied edit")
        finally:
            s.close()

    def test_click_then_apply_writes_it_and_keeps_everything_else(self):
        s = Scene(width=1920, height=1080, setup=with_theme(auto_place_windows=None, my_custom_key=[1, 2]))
        try:
            before = theme_json(s)
            self.open_experience(s)
            x, y = centre(s, "autoPlaceSwitch")
            self.assertTrue(s.click(x, y).startswith("ThemeEditor"))
            s.wait(200)
            self.assertFalse(s.ev("findNamed('autoPlaceSwitch').checked"), "the click did not switch it off")
            self.assertTrue(s.ev(f"{TE}.dirty"), "switching it off did not mark an unapplied change")
            s.ev(f"{TE}.apply()")
            s.wait(300)
            after = theme_json(s)
            self.assertIs(after.get("auto_place_windows"), False)
            self.assertEqual(after.get("my_custom_key"), [1, 2], "Apply dropped a key the editor doesn't model")
            self.assertEqual(after.get("schema_version"), before.get("schema_version"))
            self.assertNotIn("auto_place_windows", {k for k, v in after.items() if isinstance(v, str)})
        finally:
            s.close()

    def test_revert_and_presets_leave_it_alone(self):
        s = Scene(width=1920, height=1080, setup=with_theme(auto_place_windows=False))
        try:
            self.open_experience(s)
            self.assertFalse(s.ev("findNamed('autoPlaceSwitch').checked"))
            s.ev(f"{TE}.auto_place_windows = true; {TE}.dirty = true; {TE}.revert()")
            self.assertFalse(s.ev(f"{TE}.auto_place_windows"), "Revert kept the edit")
            # A colour preset is a theme, not a behaviour: it must not flip it.
            s.ev(f"{TE}.applyPreset({TE}.presets[Object.keys({TE}.presets)[0]])")
            self.assertFalse(s.ev(f"{TE}.auto_place_windows"), "a colour preset changed window placement")
        finally:
            s.close()

    def test_reduce_motion_switch_reaches_the_shell_after_apply(self):
        s = Scene(width=1920, height=1080, setup=with_theme(reduce_motion=None))
        try:
            self.open_experience(s)
            x, y = centre(s, "reduceMotionSwitch")
            s.click(x, y)
            s.ev(f"{TE}.apply()")
            s.wait(500)
            self.assertIs(theme_json(s).get("reduce_motion"), True)
            # The real FileView watches theme.json (watchChanges); the
            # harness stub doesn't, so do what the watcher would.
            s.ev("theme.reload()")
            s.wait(200)
            self.assertTrue(s.ev("theme.reduceMotion"), "the shell did not pick up reduce_motion")
        finally:
            s.close()

    def test_descriptions_wrap_instead_of_being_cut_off(self):
        for w, h in ((1920, 1080), (1366, 768), (1024, 768)):
            with self.subTest(size=f"{w}x{h}"):
                s = Scene(width=w, height=h)
                try:
                    self.open_experience(s)
                    truncated = s.ev("""(function(){
                        const out = []; const st = [findNamed('autoPlaceSwitch').parent];
                        while (st.length) { const it = st.pop();
                            if (it.truncated === true) out.push(it.text);
                            for (let i = 0; i < it.children.length; i++) st.push(it.children[i]); }
                        return JSON.stringify(out); })()""")
                    self.assertEqual(json.loads(truncated), [])
                    sw = json.loads(s.ev("(function(){ const b = findNamed('autoPlaceSwitch'); const p = b.mapToItem(null, 0, 0);"
                                         " return JSON.stringify([p.x + b.width, p.y + b.height]); })()"))
                    self.assertLessEqual(sw[0], w)
                    self.assertLessEqual(sw[1], h)
                finally:
                    s.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
