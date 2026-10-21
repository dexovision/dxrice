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
    """Settings > Experience > Window layout: ONE three-way choice (Galaxy
    Spiral, Compact, Expansion) for new windows and SUPER+G alike, read by
    the shared migration rule, written as "window_layout" on Apply."""

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

    def test_there_is_one_picker_with_exactly_three_methods(self):
        s = Scene(width=1920, height=1080, setup=with_theme())
        try:
            self.open_experience(s)
            for mode in ("galaxy", "compact", "expansion"):
                self.assertIsNotNone(s.ev(f"findNamed('layout:{mode}')"), mode)
            self.assertIsNone(s.ev("findNamed('layout:spiral')"))
            for old in ("layoutAuto:galaxy", "layoutSuperG:galaxy"):
                self.assertIsNone(s.ev(f"findNamed('{old}')"), f"{old}: the second selector is gone")
        finally:
            s.close()

    def test_a_fresh_config_is_the_galaxy_spiral(self):
        s = Scene(width=1920, height=1080, setup=with_theme(window_layout=None, layout_auto_place=None, layout_super_g=None))
        try:
            self.open_experience(s)
            self.assertEqual(s.ev(f"{TE}.window_layout"), "galaxy")
            self.assertTrue(s.ev("findNamed('layout:galaxy').picked"))
            self.assertFalse(s.ev(f"{TE}.dirty"))
        finally:
            s.close()

    def test_old_settings_are_read_by_the_migration_rule_without_writing(self):
        s = Scene(width=1920, height=1080, setup=with_theme(window_layout=None, layout_auto_place="compact", layout_super_g="expansion"))
        try:
            before = theme_json(s)
            self.open_experience(s)
            self.assertTrue(s.ev("findNamed('layout:compact').picked"), "new windows' old setting comes first")
            self.assertFalse(s.ev(f"{TE}.dirty"))
            self.assertEqual(theme_json(s), before, "opening Settings must not rewrite theme.json")
        finally:
            s.close()

    def test_picking_and_applying_saves_one_key_and_drops_the_old_ones(self):
        s = Scene(width=1920, height=1080, setup=with_theme(window_layout=None, layout_auto_place="galaxy",
                                                           layout_super_g="galaxy", my_custom_key=[1, 2]))
        try:
            self.open_experience(s)
            self.assertTrue(self.click_card(s, "layout:compact").startswith("ThemeEditor"))
            self.assertEqual(s.ev(f"{TE}.window_layout"), "compact")
            self.assertTrue(s.ev("findNamed('layout:compact').picked"))
            self.assertFalse(s.ev("findNamed('layout:galaxy').picked"))
            self.assertTrue(s.ev(f"{TE}.dirty"))
            s.ev(f"{TE}.apply()")
            s.wait(500)
            saved = theme_json(s)
            self.assertEqual(saved.get("window_layout"), "compact")
            self.assertNotIn("layout_auto_place", saved)
            self.assertNotIn("layout_super_g", saved)
            self.assertEqual(saved.get("my_custom_key"), [1, 2], "Apply lost an unrelated key")
        finally:
            s.close()

    def test_revert_puts_the_saved_method_back(self):
        s = Scene(width=1920, height=1080, setup=with_theme(window_layout="expansion"))
        try:
            self.open_experience(s)
            self.click_card(s, "layout:galaxy")
            self.assertEqual(s.ev(f"{TE}.window_layout"), "galaxy")
            s.ev(f"{TE}.revert()")
            s.wait(200)
            self.assertEqual(s.ev(f"{TE}.window_layout"), "expansion")
        finally:
            s.close()

    def test_applying_other_settings_keeps_the_method(self):
        s = Scene(width=1920, height=1080, setup=with_theme(window_layout="expansion"))
        try:
            self.open_experience(s)
            s.ev(f"{TE}.widget_system = true; {TE}.dirty = true")
            s.ev(f"{TE}.apply()")
            s.wait(500)
            self.assertEqual(theme_json(s).get("window_layout"), "expansion")
        finally:
            s.close()

    def test_apply_writes_only_what_was_changed(self):
        """A minimal theme.json: changing one switch adds exactly that key --
        no editor default for anything untouched (window_layout included)."""
        def minimal(bridge):
            path = Path(bridge.config_home) / "dxrice" / "theme.json"
            full = json.loads(path.read_text())
            keep = {k: full[k] for k in ("glass_bg", "glass_bg_active", "glass_text", "glass_text_active",
                                         "glass_border", "accent", "font_family", "wallpaper") if k in full}
            path.write_text(json.dumps(keep))
        s = Scene(width=1920, height=1080, setup=minimal)
        try:
            before = theme_json(s)
            self.open_experience(s)
            s.ev(f"{TE}.widget_system = true; {TE}.dirty = true")
            s.ev(f"{TE}.apply()")
            s.wait(500)
            after = theme_json(s)
            added = {k: after[k] for k in after if k not in before}
            self.assertEqual(added, {"widget_system": True})
            self.assertEqual({k: after[k] for k in before}, before)
        finally:
            s.close()

    def test_the_shell_and_the_scripts_read_old_files_the_same_way(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
        import dxrice_layout_apply as lap
        cases = [{}, {"window_layout": "compact"}, {"window_layout": "spiral"}, {"window_layout": "grid", "layout_auto_place": "compact"},
                 {"layout_auto_place": "expansion", "layout_super_g": "galaxy"}, {"layout_super_g": "compact"},
                 {"layout_auto_place": "spiral"}, {"layout_auto_place": " Compact "}, {"window_layout": 7}]
        s = Scene(width=1920, height=1080)
        try:
            for d in cases:
                self.assertEqual(s.ev(f"theme.windowLayoutOf({json.dumps(d)})"), lap.mode_from(d), d)
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
