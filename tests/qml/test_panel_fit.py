#!/usr/bin/env python3
"""Panels show their whole content when the screen has room for it.

Quick Settings had a fixed 420px viewport; on a machine with more than one
audio device the Overview (with its Output/Input pickers) is taller, so
its cards were cut off mid-row with half the screen free. The Taskbar's
list was capped at 360px and cut off at the 6th shortcut. Found by looking
at the real shell in a nested compositor; pinned offscreen here.

    python3 tests/qml/test_panel_fit.py
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
from harness import Scene, DEFAULT_DOCK  # noqa: E402

FLICK_JS = """(function(){
    const p = findPanel('%s');
    const st = [p]; let f = null;
    while (st.length) { const o = st.pop(); if (!o) continue;
        if (o.contentHeight !== undefined && o.contentY !== undefined && o.height > 50) { f = o; break; }
        for (let i = 0; i < o.children.length; i++) st.push(o.children[i]); }
    return JSON.stringify({ content: f.contentHeight, viewport: f.height });
})()"""


def ten_shortcut_dock():
    dock = json.loads(json.dumps(DEFAULT_DOCK))
    for i in range(6):
        dock[f"custom/app{i}"] = {"dxrice_label": f"App {i}", "dxrice_cmd": f"app{i}", "dxrice_icon_mode": "auto",
                                  "format": "", "on-click": f"sh -c 'app{i} >/dev/null 2>&1 &'", "tooltip-format": f"App {i}"}
        dock["modules-left"].append(f"custom/app{i}")
    return dock


class PanelFitTest(unittest.TestCase):
    def test_quick_settings_overview_fits_with_several_audio_devices(self):
        s = Scene(width=1920, height=1080)
        try:
            s.ev("addAudioDevices()")
            s.ev("panels.open('quicksettings')")
            s.wait(1200)
            m = json.loads(s.ev(FLICK_JS % "currentTab"))
            self.assertLessEqual(m["content"], m["viewport"] + 1,
                                 f"Overview cut off: {m['content']:.0f}px of content in a {m['viewport']:.0f}px viewport")
        finally:
            s.close()

    def test_quick_settings_still_scrolls_on_a_short_screen(self):
        """Growing to fit stops at the screen: on a short display the pane
        scrolls rather than running off the bottom."""
        s = Scene(width=1024, height=600)
        try:
            s.ev("addAudioDevices()")
            s.ev("panels.open('quicksettings')")
            s.wait(1200)
            island = json.loads(s.ev("(function(){ const i = findNamed('statusIsland'); const p = i.mapToItem(null, 0, 0);"
                                     " return JSON.stringify([p.y, i.height]); })()"))
            self.assertLessEqual(island[0] + island[1], 600, f"Quick Settings ran off a 600px screen: {island}")
        finally:
            s.close()

    def test_taskbar_lists_ten_shortcuts_without_scrolling(self):
        s = Scene(width=1920, height=1080, dock_config=ten_shortcut_dock())
        try:
            s.ev("panels.open('taskbar')")
            s.wait(1000)
            # The shortcut list itself must be fully visible; the panel may
            # still scroll for the sections below it.
            m = json.loads(s.ev("""(function(){
                const p = findPanel('addPanelOpen');
                const st = [p]; let f = null, rows = [];
                while (st.length) { const o = st.pop(); if (!o) continue;
                    if (!f && o.contentHeight !== undefined && o.contentY !== undefined && o.height > 50) f = o;
                    if (String(o.text) === 'App 5') rows.push(o);
                    for (let i = 0; i < o.children.length; i++) st.push(o.children[i]); }
                const last = rows[0].mapToItem(f, 0, rows[0].height);
                return JSON.stringify({ lastRowBottom: last.y, viewport: f.height });
            })()"""))
            self.assertLessEqual(m["lastRowBottom"], m["viewport"], f"10th shortcut is below the fold: {m}")
        finally:
            s.close()


class NoScrollingTest(unittest.TestCase):
    """Panels don't scroll (only the Theme editor and the Wi-Fi list in
    Quick Settings may): they size to their content."""

    def flick(self, s, prop):
        return json.loads(s.ev(FLICK_JS.replace("return JSON.stringify({ content: f.contentHeight, viewport: f.height });",
                                                "return JSON.stringify({ content: f.contentHeight, viewport: f.height, interactive: f.interactive });") % prop))

    def test_taskbar_shows_all_its_content_and_does_not_scroll(self):
        s = Scene(width=1920, height=1080, dock_config=ten_shortcut_dock())
        try:
            s.ev("panels.open('taskbar')")
            s.wait(1000)
            m = self.flick(s, "addPanelOpen")
            self.assertLessEqual(m["content"], m["viewport"] + 1, f"Taskbar content doesn't fit: {m}")
            self.assertFalse(m["interactive"], "Taskbar scrolls although everything fits")
        finally:
            s.close()

    def test_quick_settings_does_not_scroll_when_it_fits(self):
        s = Scene(width=1920, height=1080)
        try:
            s.ev("addAudioDevices()")
            s.ev("panels.open('quicksettings')")
            s.wait(1200)
            self.assertFalse(self.flick(s, "currentTab")["interactive"], "Quick Settings scrolls although it fits")
        finally:
            s.close()

    def test_no_empty_system_modules_section(self):
        dock = ten_shortcut_dock()
        dock["modules-center"] = []
        dock["modules-right"] = []
        s = Scene(width=1920, height=1080, dock_config=dock)
        try:
            s.ev("panels.open('taskbar')")
            s.wait(1000)
            shown = s.ev("""(function(){ const st = [findPanel('addPanelOpen')];
                while (st.length) { const o = st.pop(); if (!o) continue;
                    if (String(o.text) === 'System Modules') { let v = o; while (v) { if (!v.visible) return false; v = v.parent; } return true; }
                    for (let i = 0; i < o.children.length; i++) st.push(o.children[i]); } return false; })()""")
            self.assertFalse(shown, "an empty 'System Modules' heading is shown")
        finally:
            s.close()


class PanelsStayOnScreenTest(unittest.TestCase):
    """Sized to their content, panels still stop short of the screen's
    bottom edge, and hang from the bar's lower edge -- never over the bar.
    (There was a dock at the bottom with its own 52px strip; with it gone,
    the bound is the screen edge less the shell's gap.)"""

    GAP = 8
    BAR_BOTTOM = 44

    def body_span(self, s, island):
        return json.loads(s.ev(f"(function(){{ const b = findNamed('{island}Body'); const p = b.mapToItem(null, 0, 0);"
                               " return JSON.stringify([p.y, p.y + b.height]); })()"))

    def test_the_shortcut_editor_hangs_from_the_bar_and_fits_the_screen(self):
        for w, h in ((1366, 768), (1280, 720), (1024, 768)):
            with self.subTest(size=f"{w}x{h}"):
                s = Scene(width=w, height=h, dock_config=ten_shortcut_dock())
                try:
                    s.ev("panels.open('taskbar')")
                    s.wait(1000)
                    top, bottom = self.body_span(s, "activityIsland")
                    self.assertEqual(top, self.BAR_BOTTOM, f"the editor starts at {top}px, not at the bar's edge")
                    self.assertLessEqual(bottom, h - self.GAP, f"the editor runs off the screen ({bottom}px)")
                finally:
                    s.close()

    def test_quick_settings_fits_a_short_screen(self):
        s = Scene(width=1024, height=600)
        try:
            s.ev("addAudioDevices()")
            s.ev("panels.open('quicksettings')")
            s.wait(1200)
            top, bottom = self.body_span(s, "statusIsland")
            self.assertEqual(top, self.BAR_BOTTOM)
            self.assertLessEqual(bottom, 600 - self.GAP, f"Quick Settings bottom at {bottom}px runs off the screen")
        finally:
            s.close()


class ThemeEditorFitTest(unittest.TestCase):
    def test_editor_stays_on_a_short_screen(self):
        """A taller editor reached over the (former) dock at 1024x768, and
        the colour picker then put its buttons under it; with the dock gone
        the editor must still end inside the screen's margin."""
        s = Scene(width=1024, height=768)
        try:
            s.ev("panels.open('theme')")
            s.wait(900)
            bottom = s.ev("""(function(){ const te = surfaces().filter(w => _name(w).indexOf('ThemeEditor') === 0)[0];
                const st = [te]; while (st.length) { const i = st.pop(); if (i.revealProgress !== undefined) {
                    const p = i.mapToItem(null, 0, 0); return p.y + i.height; }
                    for (let k = 0; k < i.children.length; k++) st.push(i.children[k]); } return -1; })()""")
            self.assertGreater(bottom, 0)
            self.assertLessEqual(bottom, 768 - 8, f"Theme editor bottom {bottom} runs off the screen")
        finally:
            s.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
