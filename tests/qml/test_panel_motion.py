#!/usr/bin/env python3
"""Panel open/close motion: content never outlives its surface.

The reported bug: click an open menu again (then the dock's cog with the
Taskbar open; now the bar's search pill with Applications open) and it
retracts into its small form with its text still fully drawn, then the text
vanishes in one frame.
Cause: island panels (ShellIsland) had no content fade at all -- closing
was only the surface shrinking around fully opaque content (clip: true).
Rows nearest the header stayed drawn until the clip edge passed them in the
last frames; the bottom-pinned Taskbar's content even rode down into the
dock row and stayed there until the panel was destroyed, then popped.

Invariants, sampled every frame of every close path (clicking the island
again, the X, Escape, clicking outside, switching panels):
  * content is fully faded before the surface has given up half its morph;
  * nothing is still visible when the panel is torn down (no pop);
  * content takes no input once a close has started;
and rapid open/close/open sequences always settle in the last requested
state with nothing stuck, doubled or blocking input. Offscreen (harness.py).

    python3 tests/qml/test_panel_motion.py
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

PANELS = {"calendar": "clockIsland", "quicksettings": "statusIsland", "taskbar": "activityIsland", "apps": "activityIsland"}
ESCAPE = {p: "topBarEscape" for p in PANELS}

STATE_JS = """(function(){
    const i = findNamed('%s');
    const p = i.panelItem;
    let op = 0, en = false;
    if (p) {
        op = 1; let it = p;
        while (it && it !== i) { op *= it.opacity; if (!it.visible) op = 0; it = it.parent; }
        en = p.enabled;
    }
    const b = i.bodyItem;
    const at = b.mapToItem(null, 0, 0);
    return JSON.stringify({ morph: i.morph, alive: !!p, op: op, enabled: en,
                            x: at.x, y: at.y, w: b.width, h: b.height,
                            cw: i.collapsedWidth, full: i.expandedHeight - i.collapsedHeight, pinX: i.pinX });
})()"""


def record_morph(s, island):
    """Every morph value the island takes, recorded inside QML (polling
    from Python is too coarse to catch a 100 ms overshoot)."""
    qml = ("import QtQuick; Item { id: r; objectName: 'morphRec'; property var seen: []; "
           "Connections { target: r.parent; function onMorphChanged() { r.seen.push(r.parent.morph); } } }")
    s.ev("(function(){ const old = findNamed('morphRec'); if (old) old.destroy(); })()")
    s.ev(f"Qt.createQmlObject({json.dumps(qml)}, findNamed('{island}'), 'rec')")


class PanelMotionTest(unittest.TestCase):
    size = (1920, 1080)

    @classmethod
    def setUpClass(cls):
        cls.s = Scene(width=cls.size[0], height=cls.size[1])
        cls.s.wait(500)

    @classmethod
    def tearDownClass(cls):
        cls.s.close()

    def setUp(self):
        self.s.ev("panels.closeCurrent()")
        self.s.wait(700)

    def state(self, island):
        return json.loads(self.s.ev(STATE_JS % island))

    def open_fully(self, panel):
        self.s.ev(f"panels.open('{panel}')")
        self.s.wait(900)
        st = self.state(PANELS[panel])
        self.assertAlmostEqual(st["morph"], 1, places=2, msg=f"{panel} did not finish opening")
        self.assertGreater(st["op"], 0.99, f"{panel} content not fully shown once open: {st}")
        self.assertTrue(st["enabled"], f"{panel} content not interactive once open")
        return st

    def center_of(self, name):
        return json.loads(self.s.ev(f"(function(){{ const t = findNamed('{name}');"
                                    " const p = t.mapToItem(null, t.width / 2, t.height / 2);"
                                    " return JSON.stringify([Math.round(p.x), Math.round(p.y)]); })()"))

    def outside_point(self):
        # Bottom-right corner: outside the bar and every panel at any size.
        return self.size[0] - 20, self.size[1] - 20

    def watch_close(self, panel, ctx, ms=900):
        island = PANELS[panel]
        frames = []
        for _ in range(ms // 16):
            frames.append(self.state(island))
            self.s.wait(16)
        frames.append(self.state(island))
        closing = [f for f in frames if f["alive"]]
        # Content fully faded before the surface is half closed.
        for f in closing:
            if f["morph"] < 0.5:
                self.assertLessEqual(f["op"], 0.02,
                                     f"{ctx}: {panel} content still {f['op']:.2f} opaque at morph {f['morph']:.2f} "
                                     "-- text visible while the surface retracts")
        # No pop: the last frame before teardown already showed nothing.
        if closing and len(closing) < len(frames):
            self.assertLessEqual(closing[-1]["op"], 0.01,
                                 f"{ctx}: {panel} content disappeared in one frame from {closing[-1]['op']:.2f}")
        # No input once the close has begun.
        for f in closing:
            self.assertFalse(f["enabled"] and f["morph"] < 0.999, f"{ctx}: {panel} content still takes input while closing: {f}")
        end = frames[-1]
        self.assertAlmostEqual(end["morph"], 0, places=3, msg=f"{ctx}: {panel} never finished closing")
        self.assertFalse(end["alive"], f"{ctx}: {panel} content was never torn down")
        return frames

    # ---- the exact reported bug: click the open menu's own button again ----
    def test_clicking_the_search_pill_again_fades_applications_before_it_retracts(self):
        self.open_fully("apps")
        owner = self.s.click(*self.center_of("barLauncher"))
        self.assertEqual(owner, "TopBar")
        self.assertEqual(self.s.ev("panels.current"), "", "clicking the pill with Applications open didn't close it")
        frames = self.watch_close("apps", "click the pill again")
        # while its content is still visible at all, the body has barely
        # started back into the bar
        for f in frames:
            if f["alive"] and f["op"] > 0.02:
                self.assertGreater(f["h"], f["full"] * 0.5, f"Applications content visible in a half-retracted body: {f}")

    def test_every_close_path_fades_content_first(self):
        paths = {
            "toggle": lambda p: self.s.ev(f"panels.toggle('{p}')"),
            "closeCurrent (X / SUPER+C)": lambda p: self.s.ev("panels.closeCurrent()"),
            # Each window's own Escape handler, invoked directly: in the harness
            # every surface shares one view, so TopBar's and Dock's (separate
            # windows in reality) would collide here and nowhere else.
            "escape": lambda p: self.s.ev("findNamed('%s').activated()" % ESCAPE[p]),
            "outside click": lambda p: self.s.click(*self.outside_point()),
        }
        for panel in PANELS:
            for name, close in paths.items():
                with self.subTest(panel=panel, path=name):
                    self.open_fully(panel)
                    close(panel)
                    self.s.wait(1)
                    self.assertNotEqual(self.s.ev("panels.current"), panel, f"{name} didn't close {panel}")
                    self.watch_close(panel, name)

    def test_open_and_close_are_animated_without_jumps(self):
        """Geometry moves continuously both ways: several intermediate
        frames, no single frame covering most of the distance. (A morph
        still bound to `expanded` snapped straight to its target -- on each
        island's FIRST open and close only, before any animation had ever
        replaced the binding, so this runs on a fresh scene.)"""
        shared, self.s = self.s, Scene(width=self.size[0], height=self.size[1])
        self.s.wait(500)
        try:
            self._check_continuity()
        finally:
            self.s.close()
            self.s = shared

    def _check_continuity(self):
        for panel in PANELS:
            for direction in ("open", "close"):
                with self.subTest(panel=panel, direction=direction):
                    if direction == "close":
                        self.s.ev(f"panels.open('{panel}')")
                        self.s.wait(900)
                        self.s.ev("panels.closeCurrent()")
                    else:
                        self.s.ev(f"panels.open('{panel}')")
                    morphs = []
                    for _ in range(40):
                        morphs.append(self.state(PANELS[panel])["morph"])
                        self.s.wait(16)
                    between = [m for m in morphs if 0.02 < m < 0.98]
                    self.assertGreaterEqual(len(between), 4, f"{direction} {panel} barely animated: {morphs[:12]}")
                    steps = [abs(b - a) for a, b in zip(morphs, morphs[1:])]
                    self.assertLess(max(steps), 0.5, f"{direction} {panel} jumped: {morphs[:12]}")
                    self.s.ev("panels.closeCurrent()")
                    self.s.wait(700)

    def test_switching_panels_fades_the_outgoing_one(self):
        self.open_fully("calendar")
        self.s.ev("panels.open('quicksettings')")
        self.watch_close("calendar", "switch to quicksettings")
        self.assertGreater(self.state("statusIsland")["op"], 0.99)

    # ---- rapid sequences ----
    def test_reopen_during_close_reverses_cleanly(self):
        for panel in PANELS:
            for delay in (30, 120, 250):
                with self.subTest(panel=panel, reopen_after_ms=delay):
                    self.open_fully(panel)
                    self.s.ev(f"panels.close('{panel}')")
                    self.s.wait(delay)
                    self.s.ev(f"panels.open('{panel}')")
                    self.s.wait(900)
                    st = self.state(PANELS[panel])
                    self.assertAlmostEqual(st["morph"], 1, places=2)
                    self.assertGreater(st["op"], 0.99, f"content stuck faded after reopening: {st}")
                    self.assertTrue(st["enabled"], "content stuck non-interactive after reopening")

    def test_opening_springs_past_its_size_and_settles_exactly(self):
        for panel, island in PANELS.items():
            with self.subTest(panel=panel):
                self.s.ev("panels.closeCurrent()")
                self.s.wait(700)
                record_morph(self.s, island)
                self.s.ev(f"panels.open('{panel}')")
                self.s.wait(1000)
                seen = json.loads(self.s.ev("JSON.stringify(findNamed('morphRec').seen)"))
                self.assertGreater(max(seen), 1.01, f"{panel} opened without a spring: peak {max(seen):.3f}")
                self.assertLess(max(seen), 1.12, f"{panel} bounced too far: peak {max(seen):.3f}")
                self.assertAlmostEqual(seen[-1], 1, places=3, msg=f"{panel} did not settle")
                # and closing never bounces
                record_morph(self.s, island)
                self.s.ev("panels.closeCurrent()")
                self.s.wait(800)
                seen = json.loads(self.s.ev("JSON.stringify(findNamed('morphRec').seen)"))
                self.assertLessEqual(max(seen), 1.0 + 1e-6)
                self.assertGreaterEqual(min(seen), -1e-6)

    def test_rapid_toggle_spam_settles_in_the_last_state(self):
        for panel in PANELS:
            for n, final_open in ((7, True), (10, False)):
                with self.subTest(panel=panel, toggles=n):
                    for _ in range(n):
                        self.s.ev(f"panels.toggle('{panel}')")
                        self.s.wait(35)
                    self.s.wait(1000)
                    st = self.state(PANELS[panel])
                    self.assertEqual(self.s.ev("panels.current") == panel, final_open)
                    if final_open:
                        self.assertAlmostEqual(st["morph"], 1, places=2)
                        self.assertGreater(st["op"], 0.99)
                        self.assertTrue(st["enabled"])
                    else:
                        self.assertAlmostEqual(st["morph"], 0, places=3)
                        self.assertFalse(st["alive"], "panel left constructed after settling closed")
                    self.s.ev("panels.closeCurrent()")
                    self.s.wait(700)

    def test_settled_closed_leaves_no_input_blocker(self):
        for panel in PANELS:
            self.open_fully(panel)
            self.s.ev("panels.closeCurrent()")
            self.s.wait(900)
        for x, y in (self.outside_point(), (self.size[0] // 2, self.size[1] // 2)):
            self.assertIsNone(self.s.input_owner(x, y), f"something still takes clicks at {x},{y}")

    def test_no_qml_warnings(self):
        for panel in PANELS:
            self.open_fully(panel)
            self.s.ev("panels.closeCurrent()")
            self.s.wait(900)
        bad = [w for w in self.s.warnings if "ShellIsland" in w or "Binding loop" in w]
        self.assertEqual(bad, [])


class NarrowPanelMotionTest(PanelMotionTest):
    size = (1024, 768)


class ExpandableMotionTest(unittest.TestCase):
    """Quick Settings' accordion (Expandable): its rows fade with the fold
    instead of being clipped away fully drawn."""

    def test_rows_fade_before_the_fold_is_half_shut_and_take_no_input(self):
        s = Scene("ExpandableScene.qml", width=480, height=400)
        try:
            js = ("(function(){ const e = exp; const clip = e.children[1]; const body = clip.children[0];"
                  " return JSON.stringify({h: clip.height, full: body.y + body.implicitHeight, op: body.opacity, en: body.enabled}); })()")
            s.ev("exp.expanded = true"); s.wait(700)
            st = json.loads(s.ev(js))
            self.assertGreater(st["full"], 100)
            self.assertAlmostEqual(st["h"], st["full"], delta=0.5)
            self.assertEqual(st["op"], 1)
            self.assertTrue(st["en"])
            s.ev("exp.expanded = false")
            frames = []
            for _ in range(40):
                frames.append(json.loads(s.ev(js)))
                s.wait(12)
            for f in frames:
                if f["h"] < 0.5 * f["full"]:
                    self.assertLessEqual(f["op"], 0.02, f"rows still {f['op']:.2f} opaque with the fold {f['h'] / f['full']:.0%} open")
                self.assertFalse(f["en"], "rows still take input while folding away")
            self.assertEqual(frames[-1]["h"], 0)
            # Expanding again: shown by the end, never stuck.
            s.ev("exp.expanded = true"); s.wait(700)
            self.assertEqual(json.loads(s.ev(js))["op"], 1)
        finally:
            s.close()


LOCK_JS = """(function(){
    const lock = findNamed('lockScreen');
    const find = (root, name) => { const st = [root]; while (st.length) { const o = st.pop(); if (!o) continue;
        if (o.objectName === name) return o; const k = o.data !== undefined ? o.data : []; for (let i = 0; i < k.length; i++) st.push(k[i]); } return null; };
    lock.locked = true;
    const s = lock.surfaceItem;
    find(s, 'lockPam').completed(1);  // PamResult.Failed
    return find(s, 'lockShake').running;
})()"""


class LockShakeTest(unittest.TestCase):
    """A wrong password shakes the lock card -- unless reduce_motion."""

    def _shakes(self, reduce):
        def setup(bridge):
            path = Path(bridge.config_home) / "dxrice" / "theme.json"
            data = json.loads(path.read_text())
            data["reduce_motion"] = reduce
            path.write_text(json.dumps(data))
        s = Scene(width=1280, height=720, setup=setup)
        try:
            return s.ev(LOCK_JS)
        finally:
            s.ev("findNamed('lockScreen').locked = false")
            s.close()

    def test_wrong_password_shakes(self):
        self.assertTrue(self._shakes(False))

    def test_no_shake_under_reduce_motion(self):
        self.assertFalse(self._shakes(True), "the lock card shook with reduce_motion on")


class ReducedMotionTest(unittest.TestCase):
    """theme.json "reduce_motion": true -- panels appear and disappear in
    place: no growing/shrinking geometry, only a short fade of the content."""

    def test_reduced_motion_never_bounces(self):
        def reduce(bridge):
            path = Path(bridge.config_home) / "dxrice" / "theme.json"
            data = json.loads(path.read_text())
            data["reduce_motion"] = True
            path.write_text(json.dumps(data))
        s = Scene(width=1920, height=1080, setup=reduce)
        try:
            record_morph(s, "statusIsland")
            s.ev("panels.open('quicksettings')")
            s.wait(600)
            seen = json.loads(s.ev("JSON.stringify(findNamed('morphRec').seen)"))
            self.assertLessEqual(max(seen), 1.0 + 1e-6)
            self.assertEqual(s.ev("theme.curveSpring.toString()"), s.ev("theme.curveStandard.toString()"))
        finally:
            s.close()

    def test_panels_change_size_at_once_and_still_fade_cleanly(self):
        def reduce(bridge):
            path = Path(bridge.config_home) / "dxrice" / "theme.json"
            data = json.loads(path.read_text())
            data["reduce_motion"] = True
            path.write_text(json.dumps(data))
        s = Scene(width=1920, height=1080, setup=reduce)
        try:
            self.assertTrue(s.ev("theme.reduceMotion"), "reduce_motion not picked up")
            for panel, island in PANELS.items():
                with self.subTest(panel=panel):
                    s.ev(f"panels.open('{panel}')")
                    s.wait(40)
                    st = json.loads(s.ev(STATE_JS % island))
                    self.assertAlmostEqual(st["morph"], 1, places=2, msg=f"{panel} still growing under reduced motion")
                    s.wait(600)
                    self.assertGreater(json.loads(s.ev(STATE_JS % island))["op"], 0.99)
                    s.ev("panels.closeCurrent()")
                    s.wait(40)
                    st = json.loads(s.ev(STATE_JS % island))
                    self.assertAlmostEqual(st["morph"], 0, places=2, msg=f"{panel} still shrinking under reduced motion")
                    self.assertFalse(st["enabled"])
                    s.wait(600)
                    self.assertFalse(json.loads(s.ev(STATE_JS % island))["alive"])
        finally:
            s.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
