pragma Singleton
import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Hyprland

// How far the focused workspace's infinite desktop has been panned -- the
// one source of truth for everything that moves with the desktop.
//
// Whatever moves the camera reports it to scripts/dxrice_viewport.py, which
// keeps a running total per workspace in $XDG_RUNTIME_DIR/dxrice/viewport.json:
// the pan daemon while you SUPER+ALT drag (60 times a second), SUPER+arrows,
// SUPER+G when it only recentres, the window mover at a screen edge, and the
// overview (which also tells this file directly, see add()).
//
// `goalX`/`goalY` are that total. `x`/`y` are where the desktop's widgets
// draw it, and they reach the goal the way Hyprland moves the windows: the
// windows travel on hyprland.lua's "easy" spring, re-aimed at every step of
// a pan with their velocity kept, so a widget that jumped straight to the
// total would run ahead of its windows by about 0.2 s of a drag, and a
// keyboard jump would land before the windows had started to slide. So one
// spring runs here, with the same constants (`spring`), in real time as
// Hyprland's does (hyprutils advances a spring by wall-clock time; the
// `speed` of the animation does not scale it), and every widget reads the
// same x/y -- they cannot drift apart from each other.
//
// Two things are not slid: a workspace switch (the new workspace's total is
// simply where its widgets are; they fade with the workspace), and the
// overview's pan, which moves the windows with no animation.
QtObject {
    id: root
    readonly property string path: (Quickshell.env("XDG_RUNTIME_DIR") || "/tmp") + "/dxrice/viewport.json"
    property var offsets: ({})
    readonly property var workspace: {
        const list = Hyprland.workspaces ? Hyprland.workspaces.values : [];
        for (let i = 0; i < list.length; i++) if (list[i].focused) return list[i].id;
        return null;
    }
    // The totals as they stood when the shell started count as home: a pan
    // total built up before (the shell restarting mid-session, a total from
    // before the widgets followed the desktop) must not throw them off the
    // screen. Only what moves from here on moves them.
    property var _baseline: ({})
    readonly property var offset: {
        const k = root.workspace !== null ? String(root.workspace) : "";
        const t = root.offsets[k] || [0, 0], b = root._baseline[k] || [0, 0];
        return [Number(t[0]) - Number(b[0]), Number(t[1]) - Number(b[1])];
    }
    readonly property real goalX: Number(root.offset[0]) || 0
    readonly property real goalY: Number(root.offset[1]) || 0

    // hyprland.lua: hl.curve("easy", { type = "spring", mass = 1,
    // stiffness = 71.2633, dampening = 15.8273644 }), the windows' curve
    // (tests/qml/test_widget_layout.py checks the two stay the same)
    readonly property var spring: ({ mass: 1, stiffness: 71.2633, damping: 15.8273644 })

    property real x: 0
    property real y: 0
    property real _vx: 0
    property real _vy: 0
    // the next goal change lands at once instead of sliding
    property bool _cut: false
    property bool _read: false

    function _retarget() {
        if (root._cut || Theme.reduceMotion) {
            root._cut = false;
            root.jump();
            return;
        }
        follow.running = true;
    }
    onGoalXChanged: root._retarget()
    onGoalYChanged: root._retarget()
    // (after the bindings that follow from the switch have settled: the new
    // workspace's goal isn't there yet when this is told)
    onWorkspaceChanged: Qt.callLater(root.jump)
    function jump() {
        follow.running = false;
        root.x = root.goalX; root.y = root.goalY;
        root._vx = 0; root._vy = 0;
        // no sway from a jump: nothing on screen moved continuously
        root._fx = root.x; root._fy = root.y; root._fvx = 0; root._fvy = 0;
    }

    // ---- the widgets' sway ----
    // The desktop's widgets stay on the screen, but while the desktop pans
    // they are dragged a little along with it and spring back when it
    // stops -- as if hung on the screen by something slightly elastic. A
    // second, softer spring (`sway`) chases the windows' motion (x/y above);
    // a widget's offset is how far that chaser lags behind, eased by a soft
    // limit (`swayMax` px, times theme.json "widget_sway", default 1; 0 turns
    // it off). At a steady pan the lag is steady, so the widgets hold a
    // small displacement in the direction the desktop moves; when the pan
    // stops the chaser catches up, overshooting a little, and the offset
    // settles back to exactly 0. It can't accumulate: it is always the gap
    // between two springs heading for the same place, and the widgets' saved
    // places are never touched. Updates arriving at any rate are fine: it
    // chases the windows' already-smooth motion, not the raw pan steps.
    // damping ratio 0.35: a fast pan holds the widgets ~54 px back and they
    // overshoot ~5 px on the way home; a slow one ~15 px with no visible
    // overshoot; settled within ~0.9 s of the pan stopping (worked out
    // against the windows' own spring, which this chases)
    readonly property var sway: ({ stiffness: 200, damping: 9.9, mass: 1 })
    readonly property real swayStrength: Math.max(0, Math.min(2, Number(Theme.data.widget_sway === undefined ? 1 : Theme.data.widget_sway) || 0))
    readonly property real swayMax: 64 * root.swayStrength
    property real _fx: 0
    property real _fy: 0
    property real _fvx: 0
    property real _fvy: 0
    function _soft(d) { return root.swayMax <= 0 ? 0 : root.swayMax * Math.tanh(d / root.swayMax); }
    readonly property real swayX: Theme.reduceMotion ? 0 : root._soft(root.x - root._fx)
    readonly property real swayY: Theme.reduceMotion ? 0 : root._soft(root.y - root._fy)

    // one step of the spring, in small sub-steps (semi-implicit Euler: stable
    // at any frame rate, within a fraction of a pixel of the exact motion)
    function step(dt) {
        const s = root.spring;
        const w = root.sway;
        let x = root.x, y = root.y, vx = root._vx, vy = root._vy;
        let fx = root._fx, fy = root._fy, fvx = root._fvx, fvy = root._fvy;
        let left = Math.min(dt, 0.1);       // a stalled frame doesn't fling it
        while (left > 0) {
            const h = Math.min(0.00025, left);
            vx += h * (-s.stiffness * (x - root.goalX) - s.damping * vx) / s.mass;
            vy += h * (-s.stiffness * (y - root.goalY) - s.damping * vy) / s.mass;
            x += h * vx; y += h * vy;
            fvx += h * (-w.stiffness * (fx - x) - w.damping * fvx) / w.mass;
            fvy += h * (-w.stiffness * (fy - y) - w.damping * fvy) / w.mass;
            fx += h * fvx; fy += h * fvy;
            left -= h;
        }
        const settled = Math.abs(x - root.goalX) < 0.25 && Math.abs(y - root.goalY) < 0.25
                        && Math.abs(vx) < 2 && Math.abs(vy) < 2
                        && Math.abs(fx - x) < 0.25 && Math.abs(fy - y) < 0.25 && Math.abs(fvx) < 2 && Math.abs(fvy) < 2;
        if (settled) { x = root.goalX; y = root.goalY; vx = 0; vy = 0; fx = x; fy = y; fvx = 0; fvy = 0; follow.running = false; }
        root._vx = vx; root._vy = vy;
        root._fvx = fvx; root._fvy = fvy;
        root._fx = fx; root._fy = fy;
        root.x = x; root.y = y;
    }
    property FrameAnimation follow: FrameAnimation {
        running: false
        onTriggered: root.step(frameTime)
    }

    // The overview moves the windows itself, unanimated, and reports the step
    // through dxrice_viewport.py; it calls this as well so the widgets are
    // already there when it closes (the file's total arrives a moment later
    // and is the same number).
    function add(ws, dx, dy) {
        if (ws === null || ws === undefined || (!dx && !dy)) return;
        const o = Object.assign({}, root.offsets);
        const cur = o[String(ws)] || [0, 0];
        o[String(ws)] = [Number(cur[0]) + dx, Number(cur[1]) + dy];
        root._cut = true;
        root.offsets = o;
    }

    // ---- a pan in progress (scripts/dxrice_pan_presence.py) ----
    // "1 <unix time>" while the pan daemon has the bar stepped aside, kept
    // fresh every half second; "0" otherwise. A "1" that has gone stale (a
    // daemon killed outright) counts as over, so the bar always comes back.
    readonly property string panPath: (Quickshell.env("XDG_RUNTIME_DIR") || "/tmp") + "/dxrice/panning"
    property bool _panFlag: false
    property real _panStamp: 0
    property real _now: Date.now() / 1000
    readonly property bool panning: root._panFlag && root._now - root._panStamp < 2.0
    function _readPan(text) {
        const f = String(text).trim().split(/\s+/);
        root._panFlag = f[0] === "1";
        root._panStamp = Number(f[1]) || 0;
        root._now = Date.now() / 1000;
    }
    property Timer _panStale: Timer {
        running: root._panFlag
        interval: 400; repeat: true
        onTriggered: root._now = Date.now() / 1000
    }
    property FileView panFile: FileView {
        path: root.panPath
        watchChanges: true
        printErrors: false
        onFileChanged: this.reload()
        onLoaded: root._readPan(this.text())
    }

    // the widgets back on screen, here: this workspace's total starts over
    // (arrange mode's button, and `qs ipc call widgets home`)
    function home() {
        if (root.workspace === null) return;
        const k = String(root.workspace);
        const o = Object.assign({}, root.offsets); delete o[k];
        const b = Object.assign({}, root._baseline); delete b[k];
        root._cut = true;
        root._baseline = b;
        root.offsets = o;
        Quickshell.execDetached(["python3", Quickshell.shellDir + "/../scripts/dxrice_viewport.py", "home", k]);
    }

    property FileView file: FileView {
        path: root.path
        watchChanges: true
        printErrors: false
        onFileChanged: this.reload()
        onLoaded: {
            try {
                const o = JSON.parse(this.text()).offsets || {};
                if (!root._read) { root._read = true; root._cut = true; root._baseline = o; }   // (the shell starting: home, no slide)
                root.offsets = o;
                root._cut = false;
            }
            catch (e) { /* half-written or gone: keep the last good one */ }
        }
    }
}
