"""Theme editor: unapplied edits survive closing it, and Apply reports how
it went. Driven through the real shell QML offscreen (see harness.py).

    python3 tests/qml/test_theme_draft.py
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

TE = "surfaces().filter(w => _name(w).indexOf('ThemeEditor') === 0)[0]"
OPEN_MS = 1000
CLOSE_MS = 1100


class ThemeDraftTest(unittest.TestCase):
    def setUp(self):
        self.s = Scene(width=1920, height=1080)
        self.theme_json = Path(self.s.bridge.config_home) / "dxrice" / "theme.json"
        self.original = json.loads(self.theme_json.read_text())

    def tearDown(self):
        self.s.close()

    # ---- helpers ----
    def open(self):
        self.s.ev("panels.open('theme')")
        self.s.wait(OPEN_MS)
        self.assertTrue(self.s.ev(f"!!{TE}"), "Theme editor did not open")

    def edit_accent(self, hex_):
        # The same path a preset click or a picker Done takes.
        self.s.ev(f"{TE}.applyPreset({{ accent: '{hex_}' }})")
        self.assertTrue(self.s.ev(f"{TE}.dirty"))

    def close_via(self, how):
        s = self.s
        if how == "closeCurrent":  # SUPER+C / IPC
            s.ev("panels.closeCurrent()")
        elif how == "outside":
            s.click(20, 700)
        elif how == "escape":
            s.ev("findNamed('themeEscape').activated()")
        s.wait(CLOSE_MS)
        self.assertEqual(s.ev(f"{TE} === undefined"), True, f"editor still open after {how}")

    def disk_theme(self):
        return json.loads(self.theme_json.read_text())

    def message(self):
        return self.s.ev("findNamed('themeHeaderMessage').text")

    # ---- drafts ----
    def test_draft_survives_every_close_path(self):
        for how in ("closeCurrent", "outside", "escape"):
            with self.subTest(close=how):
                self.open()
                self.edit_accent("123456")
                self.s.ev(f"{TE}.currentCategory = 'blur'")
                self.close_via(how)
                self.open()
                self.assertEqual(self.s.ev(f"{TE}.accent"), "123456", f"draft lost after closing via {how}")
                self.assertTrue(self.s.ev(f"{TE}.dirty"), "restored draft is not marked unapplied")
                self.assertEqual(self.s.ev(f"{TE}.currentCategory"), "blur")
                self.assertEqual(self.disk_theme().get("accent"), self.original.get("accent"),
                                 "closing wrote the draft to theme.json")
                self.s.ev(f"{TE}.revert()")
                self.close_via("closeCurrent")

    def test_revert_discards_the_draft(self):
        self.open()
        self.edit_accent("123456")
        self.close_via("closeCurrent")
        self.open()
        self.s.ev(f"{TE}.revert()")
        self.assertEqual(self.s.ev(f"{TE}.accent"), self.original["accent"])
        self.close_via("closeCurrent")
        self.open()
        self.assertEqual(self.s.ev(f"{TE}.accent"), self.original["accent"], "Revert did not discard the kept draft")
        self.assertFalse(self.s.ev(f"{TE}.dirty"))

    def test_external_theme_change_drops_the_draft(self):
        self.open()
        self.edit_accent("123456")
        self.close_via("closeCurrent")
        changed = dict(self.original, accent="abcdef")
        self.theme_json.write_text(json.dumps(changed, indent=4))
        self.s.ev("theme.reload()")  # what Theme.qml's file watcher does live
        self.open()
        self.assertEqual(self.s.ev(f"{TE}.accent"), "abcdef", "a stale draft was restored over a newer theme")
        self.assertFalse(self.s.ev(f"{TE}.dirty"))
        self.assertIn("discarded", self.message())
        self.close_via("closeCurrent")
        self.open()
        self.assertEqual(self.message(), "", "the notice outlived the reopen after it")

    def test_successful_apply_leaves_nothing_to_restore(self):
        self.open()
        self.edit_accent("123456")
        self.s.ev(f"{TE}.apply()")
        self.s.wait(300)
        self.s.ev("theme.reload()")
        self.assertFalse(self.s.ev(f"{TE}.applying"))
        self.assertFalse(self.s.ev(f"{TE}.dirty"), "still marked unapplied after a successful Apply")
        self.assertEqual(self.disk_theme()["accent"], "123456")
        # No error and no draft notice -- only the brief success line.
        self.assertIn(self.message(), ("", "\u2713  Applied"))
        self.close_via("closeCurrent")
        self.open()
        self.assertEqual(self.s.ev(f"{TE}.accent"), "123456")
        self.assertFalse(self.s.ev(f"{TE}.dirty"))
        self.assertEqual(self.message(), "")

    def test_apply_keeps_keys_the_editor_does_not_model(self):
        """Saving wrote only the editor's own fields, dropping schema_version
        (and anything else in theme.json): every Apply then made the apply
        script "migrate" the file again, with a fresh backup each time."""
        data = dict(self.original, my_own_setting="keep me")
        self.assertIn("schema_version", data, "fixture: the shipped theme.json is versioned")
        self.theme_json.write_text(json.dumps(data, indent=4))
        self.s.ev("theme.reload()")
        self.open()
        self.edit_accent("123456")
        self.s.ev(f"{TE}.apply()")
        self.s.wait(300)
        saved = self.disk_theme()
        self.assertEqual(saved["accent"], "123456")
        self.assertEqual(saved.get("schema_version"), data["schema_version"], "Apply dropped schema_version")
        self.assertEqual(saved.get("my_own_setting"), "keep me", "Apply dropped a key the editor doesn't model")

    # ---- Apply outcome ----
    def test_apply_failure_is_reported(self):
        self.s.set_command("dxrice_apply_theme.py",
                           "__EXIT__1\nTraceback (most recent call last):\n  File \"x\", line 1\n"
                           "ValueError: template waybar_style.css.template: bad colour")
        self.open()
        self.edit_accent("123456")
        self.s.ev(f"{TE}.apply()")
        self.s.wait(300)
        self.assertFalse(self.s.ev(f"{TE}.applying"))
        err = self.s.ev(f"{TE}.applyError")
        self.assertIn("bad colour", err)
        self.assertEqual(self.message(), err, "the failure is not shown in the header")
        self.assertTrue(self.s.ev("findNamed('themeHeaderMessage').visible"))
        # A new edit clears it; nothing modal stands in the way.
        self.edit_accent("654321")
        self.assertEqual(self.s.ev(f"{TE}.applyError"), "")

    def test_apply_that_cannot_start_does_not_hang(self):
        self.s.set_command("dxrice_apply_theme.py", "__NOSTART__")
        self.open()
        self.edit_accent("123456")
        self.s.ev(f"{TE}.apply()")
        self.s.wait(300)
        self.assertFalse(self.s.ev(f"{TE}.applying"), "stuck on 'Applying...' when the script could not start")
        self.assertIn("couldn't run", self.s.ev(f"{TE}.applyError"))

    def test_successful_apply_clears_a_previous_error(self):
        self.s.set_command("dxrice_apply_theme.py", "__EXIT__2\nCould not read theme.json")
        self.open()
        self.edit_accent("123456")
        self.s.ev(f"{TE}.apply()")
        self.s.wait(300)
        self.assertIn("Could not read theme.json", self.s.ev(f"{TE}.applyError"))
        self.s.set_command("dxrice_apply_theme.py", "Theme applied.")
        self.s.ev(f"{TE}.apply()")
        self.s.wait(300)
        self.assertEqual(self.s.ev(f"{TE}.applyError"), "")

    def test_no_new_warnings(self):
        self.open()
        self.edit_accent("123456")
        self.close_via("closeCurrent")
        self.open()
        bad = [w for w in self.s.warnings if "propertyCache" not in w]
        self.assertEqual(bad, [])

    def test_apply_is_a_neutral_button_with_an_unapplied_badge(self):
        """The accent marks small things (a selection, a dot), never the fill
        of a whole button -- Apply was an accent-filled slab. Unapplied
        edits show as a small accent dot instead of "Apply*"."""
        self.open()
        js = """(function(){ const b = findNamed('themeApply'); const dot = b.children.filter(c => c.width === 6)[0];
            return JSON.stringify({ fill: String(b.color), accent: String(theme.accent), text: b.text, dot: dot ? dot.visible : null }); })()"""
        st = json.loads(self.s.ev(js))
        self.assertNotEqual(st["fill"], st["accent"], "Apply is filled with the accent colour")
        self.assertEqual(st["text"], "Apply")
        self.assertFalse(st["dot"], "unapplied-changes dot shown with nothing unapplied")
        self.edit_accent("123456")
        st = json.loads(self.s.ev(js))
        self.assertTrue(st["dot"], "no unapplied-changes dot after an edit")
        self.assertEqual(st["text"], "Apply", "label changed instead of showing the dot")

    # Generate from wallpaper fills the draft only, like a preset: the
    # script used to write theme.json itself, so Revert "restored" the
    # generated colours and the shell recoloured before Apply.
    def test_generate_then_revert_restores_the_draft_and_disk(self):
        self.s.set_command("dxrice_wallpaper_theme.py",
                           json.dumps({"accent": "a1b2c3", "glass_bg": "0f0f12"}) + "\n")
        self.open()
        before = self.s.ev(f"{TE}.accent")
        disk = self.theme_json.read_text()
        self.s.ev(f"{TE}.wallpaper = '/tmp/wall.png'")
        self.s.ev(f"{TE}.generateFromWallpaper()")
        self.s.wait(200)
        argv = [a for a in self.s.bridge.run_log if any("dxrice_wallpaper_theme.py" in x for x in a)]
        self.assertTrue(argv, "the generate script never ran")
        self.assertIn("--print-only", argv[-1], "the editor let the script write theme.json")
        self.assertEqual(self.s.ev(f"{TE}.accent"), "a1b2c3")
        self.assertTrue(self.s.ev(f"{TE}.dirty"))
        self.s.ev(f"{TE}.revert()")
        self.assertEqual(self.s.ev(f"{TE}.accent"), before, "Revert didn't restore the pre-generate accent")
        self.assertEqual(self.theme_json.read_text(), disk, "theme.json changed without Apply")

if __name__ == "__main__":
    unittest.main(verbosity=2)
