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
    readonly property var offset: root.workspace !== null && root.offsets[String(root.workspace)] ? root.offsets[String(root.workspace)] : [0, 0]
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
    }

    // one step of the spring, in small sub-steps (semi-implicit Euler: stable
    // at any frame rate, within a fraction of a pixel of the exact motion)
    function step(dt) {
        const s = root.spring;
        let x = root.x, y = root.y, vx = root._vx, vy = root._vy;
        let left = Math.min(dt, 0.1);       // a stalled frame doesn't fling it
        while (left > 0) {
            const h = Math.min(0.00025, left);
            vx += h * (-s.stiffness * (x - root.goalX) - s.damping * vx) / s.mass;
            vy += h * (-s.stiffness * (y - root.goalY) - s.damping * vy) / s.mass;
            x += h * vx; y += h * vy;
            left -= h;
        }
        const settled = Math.abs(x - root.goalX) < 0.25 && Math.abs(y - root.goalY) < 0.25
                        && Math.abs(vx) < 2 && Math.abs(vy) < 2;
        if (settled) { x = root.goalX; y = root.goalY; vx = 0; vy = 0; follow.running = false; }
        root._vx = vx; root._vy = vy;
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

    property FileView file: FileView {
        path: root.path
        watchChanges: true
        printErrors: false
        onFileChanged: this.reload()
        onLoaded: {
            try {
                const o = JSON.parse(this.text()).offsets || {};
                if (!root._read) { root._read = true; root._cut = true; }   // (the shell starting: no slide)
                root.offsets = o;
                root._cut = false;
            }
            catch (e) { /* half-written or gone: keep the last good one */ }
        }
    }
}
