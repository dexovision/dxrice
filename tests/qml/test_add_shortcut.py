"""Taskbar Manager's Add Shortcut branch, driven through the real shell QML
offscreen (see harness.py): behaviour preserved from the old dialog (search,
installed-app list, custom shortcut, Add, close), its attachment to the
taskbar panel, and lifecycle under rapid open/close.

    python3 tests/qml/test_add_shortcut.py
"""
import json
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

B = "findNamed('addShortcutBranch')"
TB = "findPanel('addPanelOpen')"


def center(scene, name):
    js = f"(function(){{ const b = findNamed('{name}'); const p = b.mapToItem(null, b.width/2, b.height/2); return [p.x, p.y]; }})()"
    v = scene.ev(js).toVariant()
    return v[0], v[1]


def drag_handle(test, modid, to_modid, steps=12):
    """Press the grip of `modid`, drag it over `to_modid`'s row in small
    steps, release -- real mouse events into the offscreen shell."""
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    s = test.s
    x0, y0 = center(s, f"shortcutDragHandle:{modid}")
    _x1, y1 = center(s, f"shortcutDragHandle:{to_modid}")
    if y1 != y0:
        # the item trails the pointer by Qt's drag threshold; go that much
        # past the target's centre, as a hand does
        y1 += 14 if y1 > y0 else -14
    QTest.mousePress(s.view, Qt.LeftButton, Qt.NoModifier, QPoint(int(x0), int(y0)))
    for i in range(1, steps + 1):
        QTest.mouseMove(s.view, QPoint(int(x0), int(y0 + (y1 - y0) * i / steps)))
        s.wait(15)
    QTest.mouseRelease(s.view, Qt.LeftButton, Qt.NoModifier, QPoint(int(x0), int(y1)))
    s.wait(300)


class TaskbarOrderAndCommandTest(unittest.TestCase):
    """The Taskbar Manager's rows: drag to reorder (it never moved before:
    the grip was anchored, and Qt ignores a drag target while it is
    anchored), and the command each shortcut runs."""

    def setUp(self):
        self.s = Scene(width=1920, height=1080)
        self.s.ev("panels.open('taskbar')")
        self.s.wait(800)

    def tearDown(self):
        self.s.close()

    def order(self):
        return json.loads((self.s.bridge.config_home / "waybar" / "config-dock").read_text())["modules-left"]

    def test_dragging_a_row_down_moves_it_and_saves_the_order(self):
        before = self.order()
        movable = [m for m in before if m != "custom/launcher"][:3]
        a, b = movable[0], movable[2]
        drag_handle(self, a, b)
        after = self.order()
        self.assertNotEqual(after, before, "the drag changed nothing")
        self.assertEqual(sorted(after), sorted(before), "an item was lost or duplicated")
        self.assertEqual(after.index(a), before.index(b), (before, after))

    def test_dragging_up_and_dropping_on_itself(self):
        before = self.order()
        movable = [m for m in before if m != "custom/launcher"]
        drag_handle(self, movable[-1], movable[0])
        self.assertEqual(self.order()[before.index(movable[0])], movable[-1])
        again = self.order()
        drag_handle(self, movable[1], movable[1])       # onto itself: nothing
        self.assertEqual(self.order(), again)

    def test_the_pinned_launcher_stays_first(self):
        before = self.order()
        launcher = [m for m in before if m == "custom/launcher"]
        if not launcher:
            self.skipTest("this fixture has no pinned launcher")
        movable = [m for m in before if m != "custom/launcher"]
        drag_handle(self, movable[1], launcher[0])
        self.assertEqual(self.order().index("custom/launcher"), before.index("custom/launcher"))

    def test_rapid_repeated_drags_keep_every_item(self):
        before = self.order()
        movable = [m for m in before if m != "custom/launcher"]
        for i in range(4):
            drag_handle(self, movable[i % len(movable)], movable[(i + 2) % len(movable)], steps=6)
        after = self.order()
        self.assertEqual(sorted(after), sorted(before))

    def test_editing_a_command_is_saved_and_the_dock_runs_it(self):
        mod = [m for m in self.order() if m != "custom/launcher"][0]
        tm = "findPanel('addPanelOpen')"
        self.s.ev(f"{tm}.setShortcutCmd('{mod}', \"sh -c 'echo \\\"hi there\\\"' --x 'a b'\", (m) => {{ }})")
        self.s.wait(1500)
        cfg = json.loads((self.s.bridge.config_home / "waybar" / "config-dock").read_text())
        self.assertEqual(cfg[mod]["dxrice_cmd"], "sh -c 'echo \"hi there\"' --x 'a b'")
        import re
        m = re.match(r"^sh -c '(.*) >/dev/null 2>&1 &'$", cfg[mod]["on-click"])
        self.assertIsNotNone(m, cfg[mod]["on-click"])
        # what the dock runs, run for real: arguments with spaces survive
        out = subprocess.run(["sh", "-c", m.group(1).replace("'\\''", "'")], capture_output=True, text=True)
        self.assertEqual(out.stdout.strip(), "hi there")

    def test_a_bad_command_is_refused_with_a_reason_and_not_saved(self):
        mod = [m for m in self.order() if m != "custom/launcher"][0]
        before = json.loads((self.s.bridge.config_home / "waybar" / "config-dock").read_text())[mod]["dxrice_cmd"]
        tm = "findPanel('addPanelOpen')"
        # what dxrice_check_command.py answers for it (the harness stubs processes)
        self.s.set_command("dxrice_check_command.py", "no-such-program-xyz isn't installed (not found in your PATH).")
        self.s.ev(f"{tm}.setShortcutCmd('{mod}', 'no-such-program-xyz', (m) => {{ }})")
        self.s.wait(1200)
        after = json.loads((self.s.bridge.config_home / "waybar" / "config-dock").read_text())[mod]["dxrice_cmd"]
        self.assertEqual(after, before)


class AddShortcutTest(unittest.TestCase):
    size = (1920, 1080)

    def setUp(self):
        self.s = Scene(width=self.size[0], height=self.size[1])
        self.s.ev("panels.open('taskbar')")
        self.s.wait(800)

    def tearDown(self):
        self.s.close()

    def open_branch(self):
        x, y = center(self.s, "taskbarAddToggle")
        self.assertEqual(self.s.click(x, y), "Dock")
        self.s.wait(700)
        self.assertTrue(self.s.ev(f"{TB}.addPanelOpen"))

    def config(self):
        return json.loads((self.s.bridge.config_home / "waybar" / "config-dock").read_text())

    def test_add_toggle_opens_and_closes(self):
        self.open_branch()
        self.assertEqual(self.s.ev(f"{B}.reveal"), 1)
        x, y = center(self.s, "taskbarAddToggle")
        self.s.click(x, y)
        self.s.wait(700)
        self.assertFalse(self.s.ev(f"{TB}.addPanelOpen"))
        self.assertEqual(self.s.ev(f"{B}.reveal"), 0)
        self.assertFalse(self.s.ev(f"{B}.visible"))

    def test_header_controls_share_one_line(self):
        _, add_y = center(self.s, "taskbarAddToggle")
        close_y = self.s.ev("(function(){ for (const c of surfaces()) if (String(c).startsWith('Dock')) { const st=[c]; while (st.length) { const it=st.pop(); if (String(it).startsWith('CloseButton') && it.visible) return it.mapToItem(null, 0, it.height/2).y; for (let i=0;i<it.children.length;i++) st.push(it.children[i]); } } })()")
        self.assertAlmostEqual(add_y, close_y, delta=1.0, msg="Add toggle and close X are not vertically aligned")

    def test_search_filters_and_pick_writes_config(self):
        self.open_branch()
        self.s.wait(100)
        self.s.ev(f"{TB}.query = 'stud'")
        self.s.wait(100)
        apps = self.s.ev(f"{TB}.filteredApps").toVariant()
        self.assertEqual([a["name"] for a in apps], ["Visual Studio Code"])
        self.s.ev(f"{TB}.query = 'zzz-nothing'")
        self.s.wait(100)
        self.assertEqual(len(self.s.ev(f"{TB}.filteredApps").toVariant()), 0)
        self.s.ev(f"{TB}.query = ''")
        before = len(self.config()["modules-left"])
        self.s.ev(f"{B}.pick('GIMP', 'gimp')")
        self.s.wait(400)
        cfg = self.config()
        self.assertEqual(len(cfg["modules-left"]), before + 1)
        self.assertIn("custom/gimp", cfg["modules-left"])
        self.assertEqual(cfg["custom/gimp"]["dxrice_cmd"], "gimp")
        self.assertFalse(self.s.ev(f"{TB}.addPanelOpen"), "branch should close after adding")

    def test_custom_shortcut_with_quoted_args(self):
        self.open_branch()
        self.s.ev("(function(){ const b = " + B + "; b.children; })()")
        # Fill the custom fields through the real TextInputs.
        self.s.ev("""(function(){
            const st=[findNamed('addShortcutBranch')]; const ins=[];
            while (st.length) { const it=st.pop(); if (String(it).startsWith('QQuickTextInput')) ins.push(it); for (let i=0;i<it.children.length;i++) st.push(it.children[i]); }
            ins.sort(function(a,b){ return a.mapToItem(null,0,0).y - b.mapToItem(null,0,0).y; });
            ins[1].text = 'My App'; ins[2].text = "fake_app --title='My Cool App' arg2";
        })()""")
        self.s.ev(f"{B}.addCustom()")
        self.s.wait(400)
        cfg = self.config()
        self.assertIn("custom/myapp", cfg)
        self.assertEqual(cfg["custom/myapp"]["dxrice_cmd"], "fake_app --title='My Cool App' arg2")

    def test_click_outside_peels_branch_then_panel(self):
        self.open_branch()
        self.assertEqual(self.s.click(60, 400), "Dock")   # far left, over the app
        self.s.wait(600)
        self.assertFalse(self.s.ev(f"{TB}.addPanelOpen"), "click outside did not close the branch")
        self.assertEqual(self.s.ev("panels.current"), "taskbar", "click outside closed the whole taskbar")
        self.s.click(60, 400)
        self.s.wait(900)
        self.assertEqual(self.s.ev("panels.current"), "")

    def test_click_inside_branch_background_keeps_it_open(self):
        self.open_branch()
        bx = self.s.ev(f"{B}.mapToItem(null, 0, 0).x"); by = self.s.ev(f"{B}.mapToItem(null, 0, 0).y")
        h = self.s.ev(f"{B}.height")
        self.s.click(bx + 4, by + h - 6)   # bare corner of the branch
        self.s.wait(300)
        self.assertTrue(self.s.ev(f"{TB}.addPanelOpen"), "click on the branch's own background closed it")

    def test_rapid_toggle_stress(self):
        s = self.s
        for i in range(25):
            s.ev(f"{TB}.addPanelOpen = !{TB}.addPanelOpen")
            s.wait(15 + (i * 7) % 60)
        final = s.ev(f"{TB}.addPanelOpen")
        s.wait(800)
        self.assertEqual(s.ev(f"{B}.reveal"), 1 if final else 0, "reveal did not settle to match state")
        self.assertEqual(s.ev(f"{B}.inputActive"), bool(final))
        content_opacity = s.ev(f"{B}.sub({B}.reveal, 0.6, 1.0)")
        self.assertEqual(content_opacity, 1 if final else 0)
        # interrupt a close with an open, mid-flight
        s.ev(f"{TB}.addPanelOpen = true"); s.wait(800)
        s.ev(f"{TB}.addPanelOpen = false"); s.wait(120)
        mid = s.ev(f"{B}.reveal")
        self.assertTrue(0 < mid < 1, f"expected a mid-flight close, reveal={mid}")
        s.ev(f"{TB}.addPanelOpen = true"); s.wait(800)
        self.assertEqual(s.ev(f"{B}.reveal"), 1)
        self.assertEqual(s.input_owner(s.ev(f"{B}.mapToItem(null, 0, 0).x") + 5, s.ev(f"{B}.mapToItem(null, 0, 0).y") + 5), "Dock")

    def test_attached_to_panel(self):
        self.open_branch()
        side = self.s.ev(f"{B}.side")
        island_top = self.s.ev("findPanel('addPanelOpen').mapToItem(null, 0, 0).y")
        by = self.s.ev(f"{B}.mapToItem(null, 0, 0).y")
        if side in ("right", "left"):
            self.assertAlmostEqual(by, island_top, delta=1.0, msg="side branch not top-aligned with the panel")
        # follows the panel if it resizes while open (e.g. a shortcut added)
        self.s.ev("panels.close('taskbar')"); self.s.wait(60)
        self.assertFalse(self.s.ev(f"{B}.open"), "branch stayed open while the taskbar closed")

    def _focus_in_branch(self):
        it = self.s.view.activeFocusItem()
        while it is not None:
            if it.objectName() == "addShortcutBranch":
                return True
            it = it.parentItem()
        return False

    def test_closed_branch_releases_keyboard_focus(self):
        self.open_branch()
        self.assertTrue(self._focus_in_branch(), "search field should take focus on open")
        self.s.ev(f"{TB}.addPanelOpen = false"); self.s.wait(700)
        self.assertFalse(self._focus_in_branch(), "a hidden branch field kept keyboard focus after close")

    def test_closing_the_taskbar_dissolves_the_branch_in_place(self):
        """Taskbar closed while the branch is open. The branch used to keep
        re-placing itself against the collapsing panel: it slid down after
        it and, as the centred panel narrowed, flipped to the other side
        mid-fold; it also outlived the TaskbarManager it reads."""
        self.open_branch()
        geom = lambda: (self.s.ev(f"{B}.side"), self.s.ev(f"{B}.x"), self.s.ev(f"{B}.y"),
                        self.s.ev(f"{B}.width"), self.s.ev(f"{B}.height"))
        start = geom()
        self.s.ev("panels.closeCurrent()")
        gone_before_manager = None
        for _ in range(20):
            self.s.wait(20)
            g = geom()
            self.assertEqual(g, start, "the branch moved or re-placed itself while its parent collapsed")
            if self.s.ev(f"{B}.manager") is None and gone_before_manager is None:
                gone_before_manager = self.s.ev(f"{B}.reveal") == 0
        self.assertTrue(gone_before_manager, "the branch was still on screen when its TaskbarManager was destroyed")
        self.assertFalse(self.s.ev(f"{B}.visible"))

    def test_no_new_warnings(self):
        self.open_branch()
        self.s.ev(f"{TB}.query = 'x'"); self.s.wait(200)
        self.s.ev(f"{TB}.addPanelOpen = false"); self.s.wait(700)
        bad = [w for w in self.s.warnings if "propertyCache" not in w]
        self.assertEqual(bad, [])


def main():
    size = os.environ.get("DXRICE_TEST_SIZE")
    if size:
        AddShortcutTest.size = tuple(int(v) for v in size.split("x"))
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
