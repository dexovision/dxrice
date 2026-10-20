#!/usr/bin/env python3
"""Settings > Wallpaper > Your wallpapers: real thumbnails of the pictures
the lister found, picking one sets the draft, and nothing shows when there
are none.

    python3 tests/qml/test_wallpaper_browser.py
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

try:
    import PySide6  # noqa: F401
except ImportError:  # pragma: no cover
    print("SKIP: PySide6 not installed")
    sys.exit(0)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import Scene  # noqa: E402
from test_customization import TE  # noqa: E402
from PySide6.QtGui import QColor, QImage  # noqa: E402

COLOURS = {"dusk": "#4b3f72", "forest": "#2f5d3a", "sand": "#c2a878"}


class WallpaperBrowserTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.files = []
        for name, colour in COLOURS.items():
            img = QImage(640, 360, QImage.Format_RGB32)
            img.fill(QColor(colour))
            path = str(Path(cls.tmp.name) / f"{name}.png")
            img.save(path)
            cls.files.append({"path": path, "name": name})

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def open(self, listing):
        self.s = Scene(width=1920, height=1080)
        self.s.set_command("dxrice_list_wallpapers.py", json.dumps(listing))
        self.s.ev("panels.open('theme')")
        self.s.wait(700)
        self.s.ev(f"{TE}.currentCategory = 'wallpaper'")
        self.s.wait(1000)

    def tearDown(self):
        self.s.close()

    def centre(self, name):
        self.s.ev(f"(function(){{ const b = findNamed('{name}'); let it = b; while (it) {{ if (it.contentY !== undefined && it.contentHeight !== undefined) {{"
                  f" const p = b.mapToItem(it.contentItem, 0, 0); it.contentY = Math.max(0, p.y - 80); break; }} it = it.parent; }} }})()")
        self.s.wait(300)
        return json.loads(self.s.ev(f"(function() {{ var i = findNamed('{name}'); var p = i.mapToItem(null, i.width / 2, i.height / 2); return JSON.stringify([Math.round(p.x), Math.round(p.y)]); }})()"))

    def test_every_found_picture_is_shown_with_its_name(self):
        self.open(self.files)
        for f in self.files:
            self.assertIsNotNone(self.s.ev(f"findNamed('wallpaperChoice:{f['name']}')"))
        self.assertEqual(self.s.ev(f"{TE}.wallpaperChoices.length"), 3)

    def test_the_thumbnails_are_decoded_small(self):
        self.open(self.files)
        status = self.s.ev("(function() { var c = findNamed('wallpaperChoice:dusk'); return c.children[0].children[0].status; })()")
        self.assertEqual(status, 1)   # Image.Ready
        w = self.s.ev("(function() { var c = findNamed('wallpaperChoice:dusk'); return c.children[0].children[0].sourceSize.width; })()")
        self.assertEqual(w, 320)

    def test_clicking_one_makes_it_the_draft_wallpaper(self):
        self.open(self.files)
        self.assertFalse(self.s.ev(f"{TE}.dirty"))
        x, y = self.centre("wallpaperChoice:forest")
        self.s.click(x, y)
        self.s.wait(150)
        self.assertEqual(self.s.ev(f"{TE}.wallpaper"), self.files[1]["path"])
        self.assertTrue(self.s.ev(f"{TE}.dirty"))
        self.assertTrue(self.s.ev("findNamed('wallpaperChoice:forest').picked"))
        self.assertFalse(self.s.ev("findNamed('wallpaperChoice:dusk').picked"))

    def test_nothing_is_offered_when_there_are_no_pictures(self):
        self.open([])
        self.assertIsNone(self.s.ev("findNamed('wallpaperChoice:dusk')"))
        self.assertFalse(self.s.ev("findNamed('wallpaperChoices') !== null && findNamed('wallpaperChoices').visible"))

    def test_a_broken_listing_leaves_the_pane_working(self):
        self.s = Scene(width=1920, height=1080)
        self.s.set_command("dxrice_list_wallpapers.py", "not json")
        self.s.ev("panels.open('theme')")
        self.s.wait(700)
        self.s.ev(f"{TE}.currentCategory = 'wallpaper'")
        self.s.wait(800)
        self.assertEqual(self.s.ev(f"{TE}.wallpaperChoices.length"), 0)

    def test_the_lister_runs_once_when_the_pane_opens(self):
        self.open(self.files)
        runs = [r for r in self.s.bridge.run_log if "dxrice_list_wallpapers.py" in " ".join(r)]
        self.assertEqual(len(runs), 1)


if __name__ == "__main__":
    unittest.main()
