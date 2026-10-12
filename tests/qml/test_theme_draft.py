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
        self.assertEqual(self.message(), "")
        self.close_via("closeCurrent")
        self.open()
        self.assertEqual(self.s.ev(f"{TE}.accent"), "123456")
        self.assertFalse(self.s.ev(f"{TE}.dirty"))
        self.assertEqual(self.message(), "")

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
