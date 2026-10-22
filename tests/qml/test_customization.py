#!/usr/bin/env python3
"""Theme settings reach the shell, and the editor handles them correctly.

Before: the Theme editor's "Panel corner radius" changed nothing in the
Quickshell shell (its radius was a constant), the Fonts page only reached
Waybar/wofi/mako (the shell's type scale was constants too), and Revert
left an edit in place for any setting theme.json didn't contain yet.

    python3 tests/qml/test_customization.py
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


def with_theme(**changes):
    def setup(bridge):
        path = Path(bridge.config_home) / "dxrice" / "theme.json"
        data = json.loads(path.read_text())
        for k, v in changes.items():
            if v is None:
                data.pop(k, None)
            else:
                data[k] = v
        path.write_text(json.dumps(data))
    return setup


class ThemeReachesTheShellTest(unittest.TestCase):
    def test_text_scale_scales_the_shell_type(self):
        s = Scene(width=1920, height=1080, setup=with_theme(text_scale=1.25))
        try:
            self.assertEqual(s.ev("theme.fontSizeNormal"), 16)   # 13 * 1.25
            self.assertEqual(s.ev("theme.fontSizeSmall"), 14)    # 11 * 1.25
        finally:
            s.close()

    def test_default_text_scale_keeps_the_original_sizes(self):
        s = Scene(width=1920, height=1080, setup=with_theme(text_scale=None))
        try:
            self.assertEqual(s.ev("theme.fontSizeNormal"), 13)
        finally:
            s.close()

    def test_corner_roundness_reaches_the_islands(self):
        for radius, expected in ((12, 18), (8, 12), (16, 24)):
            with self.subTest(radius=radius):
                s = Scene(width=1920, height=1080, setup=with_theme(radius=radius))
                try:
                    self.assertEqual(s.ev("findNamed('clockIsland').maxRadius"), expected)
                finally:
                    s.close()


class EditorTest(unittest.TestCase):
    def open(self, s):
        s.ev("panels.open('theme')")
        s.wait(900)

    def test_revert_restores_a_setting_theme_json_does_not_have_yet(self):
        s = Scene(width=1920, height=1080, setup=with_theme(shadow_intensity=None, text_scale=None))
        try:
            self.open(s)
            s.ev(f"{TE}.shadow_intensity = 0.3; {TE}.dirty = true")
            s.ev(f"{TE}.revert()")
            self.assertAlmostEqual(s.ev(f"{TE}.shadow_intensity"), 1.0, msg="Revert kept the edited shadow strength")
            s.ev(f"{TE}.text_scale = 1.3; {TE}.dirty = true")
            s.ev(f"{TE}.revert()")
            self.assertAlmostEqual(s.ev(f"{TE}.text_scale"), 1.0, msg="Revert kept the edited text size")
        finally:
            s.close()

    def test_shell_text_size_is_saved_by_apply(self):
        s = Scene(width=1920, height=1080)
        try:
            self.open(s)
            s.ev(f"{TE}.text_scale = 1.15; {TE}.dirty = true; {TE}.apply()")
            s.wait(300)
            data = json.loads((Path(s.bridge.config_home) / "dxrice" / "theme.json").read_text())
            self.assertAlmostEqual(data.get("text_scale"), 1.15)
        finally:
            s.close()


class RoundingExtremesTest(unittest.TestCase):
    """(at the largest rounding the Theme editor's corners grew to 80 px and
    its content ran past the curve: content stays clear of rounded corners)"""

    def test_editor_content_stays_inside_its_rounded_corners(self):
        for r in (0, 12, 30):
            s = Scene(width=1920, height=1080, setup=with_theme(radius=r))
            try:
                s.ev("panels.open('theme')")
                s.wait(1300)
                m = json.loads(s.ev("""(function(){
                    const surf = findNamed('themePanelSurface'), c = findNamed('themeContent');
                    const sp = surf.mapToItem(null, 0, 0), cp = c.mapToItem(null, 0, 0);
                    return JSON.stringify({ surfBottom: sp.y + surf.height, contentBottom: cp.y + c.height,
                                            corner: surf.bottomLeftRadius, inset: theme.cornerInset(surf.bottomLeftRadius) }); })()"""))
                self.assertLessEqual(m["contentBottom"], m["surfBottom"] - m["inset"] + 1.5,
                                     f"radius {r}: content reaches into the rounded corner: {m}")
            finally:
                s.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
