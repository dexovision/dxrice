#!/usr/bin/env python3
"""Phase-2 design system: the typeface split (and how an existing font
choice is kept), one text-field / card language, the OSD never taking
input, the Wi-Fi password dialog, Apply's success state.

    python3 tests/qml/test_design_system.py
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
from test_interaction import FIND  # noqa: E402


def theme_json(s):
    return json.loads((Path(s.bridge.config_home) / "dxrice" / "theme.json").read_text())


class TypefaceTest(unittest.TestCase):
    """Interface text is a proportional face; font_family stays the
    terminal/bar font and the shell's fixed-width face."""

    CASES = [
        # (font_family, ui_font_family, expected UI face, expected mono face)
        ("JetBrainsMono Nerd Font", None, "Noto Sans", "JetBrainsMono Nerd Font"),   # shipped default -> new UI face
        ("Iosevka", None, "Iosevka", "Iosevka"),                                     # a choice made before the split is kept
        ("JetBrainsMono Nerd Font", "Inter", "Inter", "JetBrainsMono Nerd Font"),    # explicit interface font
        ("JetBrainsMono Nerd Font", "  ", "Noto Sans", "JetBrainsMono Nerd Font"),   # blank = automatic
        (None, None, "Noto Sans", "JetBrainsMono Nerd Font"),                        # neither key at all
    ]

    def test_resolution(self):
        for mono, ui, want_ui, want_mono in self.CASES:
            with self.subTest(font_family=mono, ui_font_family=ui):
                s = Scene(width=1280, height=720, setup=with_theme(font_family=mono, ui_font_family=ui))
                try:
                    self.assertEqual(s.ev("theme.fontFamily"), want_ui)
                    self.assertEqual(s.ev("theme.fontMono"), want_mono)
                    self.assertEqual(s.ev("theme.iconFamily"), want_mono)
                finally:
                    s.close()

    def test_interface_font_is_saved_by_apply_and_restored_by_revert(self):
        s = Scene(width=1920, height=1080, setup=with_theme(ui_font_family=None, my_custom_key=7))
        try:
            s.ev("panels.open('theme')")
            s.wait(700)
            self.assertEqual(s.ev(f"{TE}.ui_font_family"), "")
            s.ev(f"{TE}.ui_font_family = 'Inter'; {TE}.dirty = true")
            s.ev(f"{TE}.revert()")
            self.assertEqual(s.ev(f"{TE}.ui_font_family"), "", "Revert kept the edit")
            s.ev(f"{TE}.ui_font_family = 'Inter'; {TE}.dirty = true; {TE}.apply()")
            s.wait(300)
            data = theme_json(s)
            self.assertEqual(data.get("ui_font_family"), "Inter")
            self.assertEqual(data.get("font_family"), "JetBrainsMono Nerd Font", "the terminal font was changed")
            self.assertEqual(data.get("my_custom_key"), 7)
        finally:
            s.close()


class SurfaceLanguageTest(unittest.TestCase):
    def test_cards_are_tonal_not_outlined(self):
        s = Scene(width=1920, height=1080)
        try:
            s.ev("panels.open('taskbar')")
            s.wait(900)
            widths = json.loads(s.ev(f"""(function(){{ {FIND}
                const out = []; const st = [findPanel('addPanelOpen')]; while (st.length) {{ const o = st.pop(); if (!o) continue;
                    if (String(o).indexOf('Card_') === 0 || String(o).indexOf('Card(') === 0) out.push(o.children[0].border.width);
                    const k = o.data !== undefined ? o.data : []; for (let i = 0; i < k.length; i++) st.push(k[i]); }}
                return JSON.stringify(out); }})()"""))
            self.assertTrue(widths, "no cards found")
            self.assertEqual(set(widths), {0})
        finally:
            s.close()


class OsdTest(unittest.TestCase):
    def test_osd_never_takes_input(self):
        s = Scene(width=1920, height=1080)
        try:
            s.ev("findNamed('osd').trigger('\\uf028', 0.62, '62%')")
            s.wait(500)
            pos = json.loads(s.ev("(function(){ const c = findNamed('osdCard'); const p = c.mapToItem(null, c.width / 2, c.height / 2);"
                                  " return JSON.stringify([Math.round(p.x), Math.round(p.y), c.opacity]); })()"))
            self.assertNotEqual(s.input_owner(pos[0], pos[1]), "OSD", "the visible OSD swallows clicks")
        finally:
            s.close()


class WifiDialogTest(unittest.TestCase):
    PW = "correct-horse-battery"

    def open_dialog(self, s):
        s.ev("panels.open('quicksettings')")
        s.wait(600)
        s.ev("(function(){ const qs = findPanel('currentTab');"
             " const st = [qs]; let wifi = null; while (st.length && !wifi) { const o = st.pop(); if (!o) continue;"
             "   if (o.hasScanned !== undefined && o.networks !== undefined && o.passwordNeeded) wifi = o;"
             "   const k = o.data !== undefined ? o.data : []; for (let i = 0; i < k.length; i++) st.push(k[i]); }"
             " wifi.passwordNeeded('CoffeeShop Guest'); })()")
        return "findPanel('currentTab')._activeWifiDialog"

    def test_reveal_submit_and_no_password_in_logs(self):
        s = Scene(width=1920, height=1080)
        try:
            d = self.open_dialog(s)
            inp = f"(function(){{ {FIND} return find({d}, o => o.objectName === 'wifiPasswordInput'); }})()"
            btn = f"(function(){{ {FIND} return find({d}, o => o.objectName === 'wifiConnect'); }})()"
            reveal = f"(function(){{ {FIND} return find({d}, o => o.objectName === 'wifiPasswordReveal'); }})()"
            self.assertFalse(s.ev(f"{btn}.enabled"), "Connect is enabled with no password")
            s.ev(f"{inp}.text = '{self.PW}'")
            self.assertTrue(s.ev(f"{btn}.enabled"))
            self.assertEqual(s.ev(f"{inp}.echoMode"), 2, "password shown before asked")  # TextInput.Password
            s.ev(f"{reveal}.revealed = true")
            self.assertEqual(s.ev(f"{inp}.echoMode"), 0)                                   # TextInput.Normal
            got = s.ev(f"(function(){{ let pw = null; const d = {d}; d.submitted.connect(p => pw = p); d.submit(); return pw; }})()")
            self.assertEqual(got, self.PW)
            self.assertNotIn(self.PW, "\n".join(s.warnings), "the password reached a log line")
            # (Known and reported, not fixed here: WifiBackend hands the
            # password to nmcli as an argument, readable in the process list
            # while nmcli runs. Changing that needs a live network to verify.)
        finally:
            s.close()


class ApplyFeedbackTest(unittest.TestCase):
    def test_success_is_shown_briefly_then_clears(self):
        s = Scene(width=1920, height=1080)
        try:
            s.ev("panels.open('theme')")
            s.wait(700)
            s.ev(f"{TE}.text_scale = 1.1; {TE}.dirty = true; {TE}.apply()")
            s.wait(500)
            self.assertTrue(s.ev(f"{TE}.justApplied"), "a successful Apply showed nothing")
            self.assertIn("Applied", s.ev("findNamed('themeHeaderMessage').text"))
            s.ev(f"{TE}.text_scale = 1.2; {TE}.dirty = true")
            self.assertFalse(s.ev(f"{TE}.justApplied"), "'Applied' stayed up over a new edit")
        finally:
            s.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
