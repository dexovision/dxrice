import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import Quickshell.Hyprland
import "OverviewGeometry.js" as Geo

// Desktop overview (SUPER+Tab): the current workspace zoomed out until every
// window -- the whole Galaxy Spiral, including the parts past the screen
// edges -- fits on the monitor.
//
// A VIEW, never a layout: each window is drawn as a live picture of itself
// (ScreencopyView over Hyprland's toplevel-export protocol) on an overlay
// layer-shell surface over the whole monitor. No window is moved, resized or
// refocused by opening or closing it, so the view you come back to is
// exactly the one you left.
//
// Opening, frame by frame:
//   keypress  -> the surface appears at once, dimming the real desktop (the
//                real windows still show through: nothing stale is drawn)
//   ~10 ms    -> fresh window data (two parallel `hyprctl -j` reads; the
//                geometry is OverviewGeometry.js, the same as
//                dxrice_overview.py) puts each window's picture exactly over
//                the real window
//   then      -> once every visible window's live picture is ready (a frame
//                or two; 150 ms at most), the overview takes over in ONE
//                frame -- wallpaper, pictures exactly over the real windows,
//                the same dim: identical to the desktop it replaces, bar and
//                dock aside -- and only then zooms out. Never a crossfade:
//                the real windows and their pictures are never both
//                visible, so nothing is ever seen twice.
// Closing plays it back fully covered, and the overlay lets go only after
// the frame with every picture exactly over its real window (and no dim)
// has been drawn -- the last thing it shows is the desktop under it -- then
// commits two frames of nothing before the surface unmaps.
//
// Hyprland fades every layer surface in and out as a whole (fadeLayersIn /
// fadeLayersOut), however opaque it paints: on a real desktop that showed
// every window twice while the pictures moved. The hyprland.lua template's
// layer rule `overview-no-anim` turns that off for this namespace only
// (WlrLayershell.namespace below); the empty frames before the unmap keep
// the closing clean even without it (see docs/OVERVIEW.md).
//
// One click on any window focuses exactly that window (by its Hyprland
// address) and closes. A window not entirely inside the visible area is
// first brought into view by panning the whole desktop so it lands centred
// in the usable area -- every floating window of the workspace moved by
// that one delta, so the Galaxy Spiral keeps its shape -- and the overview
// closes onto the windows in their new places. Esc, a click on empty space
// or SUPER+Tab again closes without changing anything.
//
// Hyprland itself cannot zoom the desktop out (see dxrice_overview.py's
// docstring for why its magnifier, a monitor-scale change and the overview
// plugins were ruled out).
//
// Toggle: qs -p <repo>/quickshell/shell.qml ipc call overview toggle
PanelWindow {
    id: root

    // ---- state ----
    // `open` is what was asked for; `fade` (the surface: 0 = not there, 1 =
    // fully up) and `progress` (0 = the real desktop, 1 = zoomed out) are
    // what is on screen.
    property bool open: false
    property real progress: 0
    property real fade: 0
    // OverviewGeometry.overview() for the monitor being shown
    property var layout: null
    property bool _pendingEnter: false
    // a clicked window to focus once the overview has let go of the keyboard
    property string _focusAfterClose: ""
    // one quick, readable ease-in-out zoom each way (instant under
    // reduce_motion); the dim runs alongside it, never as a stage of its own
    readonly property int zoomMs: Theme.reduceMotion ? 1 : Math.round(Theme.animMs * 2)
    // How long Hyprland takes to move a window (its `windowsMove` leaf, else
    // `windows`, else `global`; speed is in 100 ms units), read from
    // `hyprctl -j animations` on the first open and after a config reload.
    // A click that pans the desktop moves the real windows under the overlay
    // with that animation, so the closing zoom runs exactly as long: the
    // pictures and the real windows land on the same frame, and the overlay
    // never lets go while a real window is still sliding into place.
    property int compositorMoveMs: 480
    property bool _animationsRead: false
    property int _closeMs: root.zoomMs
    readonly property var zoomCurve: [0.4, 0.0, 0.2, 1.0, 1, 1]
    // settled: zoomed out and not animating -- window changes then glide
    readonly property bool _settled: root.open && root.progress === 1 && !enterAnim.running
    // when the last open began (ms since epoch), for the latency test
    property real openedAt: 0
    property real dataAt: 0
    property int tilesBuilt: 0   // tile delegates ever created (tests: in-place updates)

    readonly property bool showing: root.open || root.fade > 0 || root.covering || root._lingering
    // The surface stays mapped, drawing nothing, for two frames after the
    // overview has let go: Hyprland fades a layer surface out from a snapshot
    // of its last frame, so unmapping straight from a drawn frame would show
    // that frame (the overview, previews and all) fading over the real desktop.
    property bool _lingering: false
    // The overview has taken over the screen: its wallpaper and pictures are
    // drawn, opaque. False before the handover (the real desktop shows,
    // dimmed) and again from the final, aligned frame of closing.
    property bool covering: false
    property real _waitStart: 0
    // the tiles' on-screen rects in the last frame before the overlay went
    // (tests: closing lands exactly on the real windows, panned or not)
    property var lastCloseRects: ({})
    readonly property var windows: root.layout && root.layout.windows ? root.layout.windows : []
    readonly property bool hasFullscreen: root.windows.some(w => w.fullscreen)
    // the usable area (the monitor minus the bar's and dock's strips) the
    // windows are fitted into, and the strips around it
    readonly property real usableWidth: root.layout && root.layout.monitor ? root.layout.monitor.width : 1920
    readonly property real usableHeight: root.layout && root.layout.monitor ? root.layout.monitor.height : 1080
    readonly property var reserved: root.layout && root.layout.reserved ? root.layout.reserved : [0, 0, 0, 0]
    readonly property real monitorWidth: root.usableWidth + root.reserved[0] + root.reserved[2]
    readonly property real monitorHeight: root.usableHeight + root.reserved[1] + root.reserved[3]

    function show() {
        if (root.open) return;
        root.open = true;
        root.openedAt = Date.now();
        root._focusAfterClose = "";
        root._closeMs = root.zoomMs;
        if (!root._animationsRead) { root._animationsRead = true; animationsProc.running = true; }
        offScreenNote.shown = false;
        PanelManager.closeCurrent();
        // Immediate feedback: the surface comes up now, dimming the real
        // desktop, while the window data is read.
        exitAnim.stop();
        release.stop();
        root._lingering = false;
        scrimIn.restart();
        root._pendingEnter = true;
        root.refresh();
    }
    function hide() {
        if (!root.open) return;
        root.open = false;
        root._pendingEnter = false;
        handover.stop();
        scrimIn.stop();
        enterAnim.stop();
        exitAnim.start();
    }
    function toggle() {
        if (root.open) root.hide();
        else root.show();
    }

    // Fresh window/monitor state straight from Hyprland on every open and
    // on every window event while open -- never a timer. Two small `hyprctl
    // -j` reads in parallel (a few ms each), not a Python interpreter.
    property var _clients: null
    property var _monitors: null
    property int _pending: 0
    function refresh() {
        root._clients = null;
        root._monitors = null;
        root._pending = 2;
        clientsProc.running = false;
        monitorsProc.running = false;
        clientsProc.running = true;
        monitorsProc.running = true;
    }
    function _arrived() {
        root._pending -= 1;
        if (root._pending > 0) return;
        if (!root.open) return;  // dismissed before the data came: keep nothing
        const parsed = (root._clients && root._monitors && root._monitors.length)
            ? Geo.overview(root._clients, root._monitors, null, Geo.OVERVIEW_MARGIN) : null;
        if (!parsed || !parsed.monitor) {
            // No compositor answer: there is nothing to show; give the
            // keybind back instead of holding a dimmed screen.
            if (root._pendingEnter) { root._pendingEnter = false; root.hide(); }
            return;
        }
        root.layout = parsed;
        root._syncTiles(parsed.windows);
        root.dataAt = Date.now();
        if (root._pendingEnter) {
            root._pendingEnter = false;
            if (root.covering) { enterAnim.restart(); return; }   // reopened mid-close
            root._waitStart = Date.now();
            handover.start();
        }
    }
    // Hand the screen over to the overview once every window whose real
    // pixels are visible has its live picture (a frame or two); a window
    // that can't be captured within 150 ms shows its card instead.
    Timer {
        id: handover
        interval: 8; repeat: true
        onTriggered: {
            if (!root.open) { stop(); return; }
            if (!root._capturesReady() && Date.now() - root._waitStart < 150) return;
            stop();
            root.covering = true;
            enterAnim.restart();
        }
    }
    function _capturesReady() {
        for (let i = 0; i < tiles.count; i++) {
            const t = tiles.itemAt(i);
            if (t && t.onScreen && !t.hasPicture) return false;
        }
        return true;
    }
    function _parse(text) {
        try { return JSON.parse(text); } catch (e) { return null; }
    }
    // The tiles, keyed by window address and updated in place: a window
    // opening or closing while the overview is up adds or drops its own tile
    // and leaves every other tile -- and its live capture -- untouched.
    ListModel { id: tileModel }
    function _roles(w) {
        return { address: String(w.address), rx: w.x, ry: w.y, rw: w.w, rh: w.h, tx: w.tx, ty: w.ty,
                 tw: w.tw, th: w.th, stack: w.z, title: w.title || "", cls: w["class"] || "",
                 floating: !!w.floating, fullscreen: !!w.fullscreen, pinned: !!w.pinned };
    }
    function _syncTiles(list) {
        const want = {};
        for (let i = 0; i < list.length; i++) want[String(list[i].address)] = list[i];
        for (let i = tileModel.count - 1; i >= 0; i--)
            if (!(tileModel.get(i).address in want)) tileModel.remove(i);
        const have = {};
        for (let i = 0; i < tileModel.count; i++) have[tileModel.get(i).address] = i;
        for (let i = 0; i < list.length; i++) {
            const r = root._roles(list[i]);
            if (r.address in have) tileModel.set(have[r.address], r);
            else tileModel.append(r);
        }
    }
    Process {
        id: clientsProc
        command: ["hyprctl", "-j", "clients"]
        stdout: StdioCollector { onStreamFinished: { root._clients = root._parse(this.text); root._arrived(); } }
    }
    Process {
        id: monitorsProc
        command: ["hyprctl", "-j", "monitors"]
        stdout: StdioCollector { onStreamFinished: { root._monitors = root._parse(this.text); root._arrived(); } }
    }
    Process {
        id: animationsProc
        command: ["hyprctl", "-j", "animations"]
        stdout: StdioCollector {
            onStreamFinished: {
                const ms = Geo.windowMoveMs(root._parse(this.text));
                if (ms !== null) root.compositorMoveMs = ms;
            }
        }
    }
    // Debounced: one burst of events (a window opening sends several) is
    // one refresh.
    Timer { id: refreshSoon; interval: 60; onTriggered: if (root.open) root.refresh() }
    Connections {
        target: Hyprland
        function onRawEvent(event) {
            if (event.name === "configreloaded") root._animationsRead = false;
            if (!root.open) return;
            const relevant = ["openwindow", "closewindow", "movewindow", "movewindowv2", "changefloatingmode",
                              "fullscreen", "workspace", "workspacev2", "focusedmon", "focusedmonv2",
                              "activespecial", "activespecialv2", "pin", "monitorremoved", "monitoradded"];
            if (relevant.indexOf(event.name) >= 0) refreshSoon.restart();
        }
    }

    // Focus the clicked window by its Hyprland address (on this same
    // workspace, so the workspace never changes) and leave the overview.
    //
    // Always in Lua dispatch syntax -- DXrice's Hyprland runs hyprland.lua,
    // and every other DXrice focus path (dxrice_hypr_ipc.focus_window_lua)
    // speaks it; the classic "focuswindow address:" form would be refused.
    // Sent only once the overview has dropped its exclusive keyboard focus
    // (while it holds it, Hyprland keeps the keyboard on the overlay), and
    // once more after the surface is gone: when the overlay unmaps, Hyprland
    // refocuses whatever is under the pointer, which was over the picture,
    // not over the real window.
    function focusLua(address) {
        const a = String(address).startsWith("0x") ? String(address) : "0x" + address;
        return 'hl.dsp.focus({ window = "address:' + a + '" })';
    }
    // How far the whole desktop must pan for window w (a usable-area rect,
    // logical layout coordinates: bar, dock and monitor scale already taken
    // out) to be shown. Zero if it is entirely in view already -- nothing
    // moves; otherwise the one delta that centres it in the usable area (a
    // window larger than the area is centred too, overhanging evenly).
    function panDelta(w) {
        if (w.rx >= 0 && w.ry >= 0 && w.rx + w.rw <= root.usableWidth && w.ry + w.rh <= root.usableHeight)
            return [0, 0];
        return [Math.round((root.usableWidth - w.rw) / 2 - w.rx), Math.round((root.usableHeight - w.rh) / 2 - w.ry)];
    }
    // The desktop's camera, as SUPER+arrow navigation moves it: every
    // floating window of the workspace by the same delta, so the spiral keeps
    // its shape. Pinned and fullscreen windows belong to the screen, not the
    // desktop, and stay put; tiled windows are always in view.
    function _pan(d) {
        const mx = root.layout.monitor.x, my = root.layout.monitor.y;
        for (let i = 0; i < tileModel.count; i++) {
            const t = tileModel.get(i);
            if (!t.floating || t.pinned || t.fullscreen) continue;
            Hyprland.dispatch('hl.dsp.window.move({ window = "address:' + t.address + '", x = '
                + Math.round(t.rx + mx + d[0]) + ', y = ' + Math.round(t.ry + my + d[1]) + ', relative = false })');
            tileModel.setProperty(i, "rx", t.rx + d[0]);
            tileModel.setProperty(i, "ry", t.ry + d[1]);
        }
    }
    function activate(t) {
        if (!root.open || !t) return;
        if (!root.toplevelFor(t.address) && Hyprland.toplevels && Hyprland.toplevels.values.length) {
            // it closed between the last refresh and this click
            offScreenNote.text = (t.title || t.cls || "That window") + " has just closed.";
            offScreenNote.shown = true;
            noteTimer.restart();
            root.refresh();
            return;
        }
        if (t.floating && !t.pinned && !t.fullscreen) {
            const d = root.panDelta(t);
            if (d[0] || d[1]) {
                root._pan(d);
                root._closeMs = Math.max(root.zoomMs, Theme.reduceMotion ? 0 : root.compositorMoveMs);
            }
        }
        root._focusAfterClose = t.address;
        root.hide();
        focusSoon.restart();
    }
    Timer { id: focusSoon; interval: 30; onTriggered: if (root._focusAfterClose) Hyprland.dispatch(root.focusLua(root._focusAfterClose)) }
    Timer {
        id: focusAgain; interval: 40
        onTriggered: {
            if (root._focusAfterClose && !root.open) Hyprland.dispatch(root.focusLua(root._focusAfterClose));
            root._focusAfterClose = "";
        }
    }
    Timer { id: noteTimer; interval: 2500; onTriggered: offScreenNote.shown = false }
    // The live Wayland toplevel for a window, matched by address (Hyprland's
    // JSON writes "0x..." where its event-fed model may not).
    function toplevelFor(address) {
        const want = String(address).replace(/^0x/, "");
        const list = Hyprland.toplevels ? Hyprland.toplevels.values : [];
        for (let i = 0; i < list.length; i++) {
            if (String(list[i].address).replace(/^0x/, "") === want) return list[i];
        }
        return null;
    }

    // ---- motion ----
    // One ease-in-out zoom each way, the dim alongside it. Every animation
    // runs from wherever the value is, so toggling mid-way reverses with no
    // jump: the curve eases back out of the current position.
    NumberAnimation {
        id: scrimIn
        target: root; property: "fade"; to: 1; duration: Theme.durationFast; easing.type: Easing.OutCubic
    }
    NumberAnimation {
        id: enterAnim
        target: root; property: "progress"; to: 1; duration: root.zoomMs
        easing.type: Easing.BezierSpline; easing.bezierCurve: root.zoomCurve
    }
    SequentialAnimation {
        id: exitAnim
        ParallelAnimation {
            NumberAnimation {
                target: root; property: "progress"; to: 0; duration: root._closeMs
                easing.type: Easing.BezierSpline; easing.bezierCurve: root.zoomCurve
            }
            NumberAnimation { target: root; property: "fade"; to: 0; duration: root._closeMs; easing.type: Easing.InQuad }
        }
        // closed: let the tiles (and their capture sessions) go entirely,
        // then give a clicked window its focus once more (see focusLua)
        ScriptAction {
            script: {
                if (root.open) return;
                // the final frame: every picture exactly over its real window
                const rects = {};
                for (let i = 0; i < tiles.count; i++) {
                    const t = tiles.itemAt(i);
                    if (t) rects[t.address] = [t.x, t.y, t.width, t.height];
                }
                root.lastCloseRects = rects;
                release.restart();
            }
        }
    }
    // The animation ends on the value it was heading to, but the frame
    // showing that value hasn't been drawn yet: let go of the screen only
    // once it has (two frames on), so the last thing the overview shows is
    // exactly the desktop it uncovers -- no pop of dim or position. Then a
    // frame of nothing at all is committed before the surface unmaps (see
    // _lingering).
    FrameAnimation {
        id: release
        onTriggered: {
            if (root.open) { stop(); root._lingering = false; return; }
            if (currentFrame < 2) return;
            if (root.covering) {
                root._lingering = true;
                root.covering = false;
                root.layout = null;
                tileModel.clear();
                return;
            }
            if (currentFrame < 4) return;
            stop();
            root._lingering = false;
            if (root._focusAfterClose) focusAgain.restart();
        }
    }

    // ---- the surface ----
    visible: root.showing
    // Input only while open. The surface stays mapped through the closing
    // zoom (and a compositor-length move after a panning click) and the
    // release frames; without a mask it took the pointer over the whole
    // monitor all that time, so a click on the application underneath right
    // after Esc or a click on empty space was swallowed by the stage.
    // Closed, the region is empty: Quickshell then makes the surface
    // input-transparent outright.
    mask: Region {
        width: root.open ? root.width : 0
        height: root.open ? root.height : 0
    }
    color: "transparent"
    exclusionMode: ExclusionMode.Ignore
    aboveWindows: true
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.namespace: "dxrice-overview"
    WlrLayershell.keyboardFocus: root.open ? WlrKeyboardFocus.Exclusive : WlrKeyboardFocus.None
    anchors { top: true; left: true; right: true; bottom: true }
    implicitWidth: root.monitorWidth
    implicitHeight: root.monitorHeight

    // On the monitor the overview describes (the focused one).
    readonly property var matchedScreen: {
        const name = root.layout && root.layout.monitor ? root.layout.monitor.name
                   : (Hyprland.focusedMonitor ? Hyprland.focusedMonitor.name : "");
        const list = Quickshell.screens || [];
        for (let i = 0; i < list.length; i++) if (list[i].name === name) return list[i];
        return null;
    }
    Binding on screen {
        when: root.matchedScreen !== null
        value: root.matchedScreen
    }

    Item {
        id: stage
        width: root.layout ? root.monitorWidth : (root.screen && root.screen.width ? root.screen.width : root.monitorWidth)
        height: root.layout ? root.monitorHeight : (root.screen && root.screen.height ? root.screen.height : root.monitorHeight)
        clip: true
        focus: true
        Keys.onEscapePressed: root.hide()

        // The real wallpaper, drawn as hyprpaper draws it (cover): opaque
        // the whole time the overview is covering, absent otherwise -- the
        // real windows are never seen through it.
        Item {
            id: backdrop
            anchors.fill: parent
            visible: root.covering
        Rectangle { anchors.fill: parent; color: "#0d0f13" }
        Image {
            anchors.fill: parent
            // loaded only while the overview is up: a closed overview costs
            // the shell nothing, not even the decoded wallpaper
            source: root.showing ? root.wallpaperUrl : ""
            fillMode: Image.PreserveAspectCrop
            asynchronous: false
            cache: false
        }
        // Dims as it zooms out, so the windows stand forward.
        Rectangle { anchors.fill: parent; color: "black"; opacity: 0.38 * root.progress }
        }

        MouseArea {
            anchors.fill: parent
            onClicked: root.hide()
        }

        // window rects are relative to the usable area
        Item {
            id: usable
            x: root.reserved[0]; y: root.reserved[1]
            width: root.usableWidth; height: root.usableHeight
        Repeater {
            id: tiles
            model: tileModel
            delegate: Item {
                id: tile
                visible: root.covering
                // whether any of the real window shows on screen right now,
                // and whether its live picture is in (the handover waits)
                readonly property bool onScreen: tile.rx < root.usableWidth + root.reserved[2] && tile.rx + tile.rw > -root.reserved[0]
                                                 && tile.ry < root.usableHeight + root.reserved[3] && tile.ry + tile.rh > -root.reserved[1]
                readonly property bool hasPicture: capture.hasContent
                required property string address
                required property real rx
                required property real ry
                required property real rw
                required property real rh
                required property real tx
                required property real ty
                required property real tw
                required property real th
                required property int stack
                required property string title
                required property string cls
                required property bool floating
                required property bool fullscreen
                required property bool pinned
                objectName: "overviewTile:" + tile.address
                readonly property real p: root.progress
                readonly property var toplevel: root.toplevelFor(tile.address)
                x: tile.rx + (tile.tx - tile.rx) * tile.p
                y: tile.ry + (tile.ty - tile.ry) * tile.p
                width: Math.max(1, tile.rw + (tile.tw - tile.rw) * tile.p)
                height: Math.max(1, tile.rh + (tile.th - tile.rh) * tile.p)
                // A fullscreen window covers its workspace: in the real view
                // the windows behind it can't be seen. So its picture lies at
                // the bottom of the overview's stack, and the others -- not
                // shown at first, exactly as on screen -- fade in over it as
                // the view zooms out. What can be seen is what can be clicked.
                z: tile.fullscreen ? -1 : tile.stack
                opacity: (root.hasFullscreen && !tile.fullscreen) ? Math.min(1, 2 * tile.p) : 1
                // a window opening or closing while zoomed out re-fits the
                // view: the tiles glide to their new places
                Behavior on x { enabled: root._settled; NumberAnimation { duration: Theme.durationDefault; easing.type: Easing.InOutQuad } }
                Behavior on y { enabled: root._settled; NumberAnimation { duration: Theme.durationDefault; easing.type: Easing.InOutQuad } }
                Behavior on width { enabled: root._settled; NumberAnimation { duration: Theme.durationDefault; easing.type: Easing.InOutQuad } }
                Behavior on height { enabled: root._settled; NumberAnimation { duration: Theme.durationDefault; easing.type: Easing.InOutQuad } }
                Component.onCompleted: root.tilesBuilt += 1

                // Placeholder when a window can't be captured (no live
                // picture yet, or the compositor declines): its card, title
                // and class, never an empty hole. Drawn only once the
                // overview covers (the handover waits up to 150 ms for it).
                Rectangle {
                    objectName: "overviewPlaceholder"
                    anchors.fill: parent
                    visible: !capture.hasContent
                    color: Theme.panel
                    radius: 6 * tile.p
                    border.color: Theme.border
                    border.width: 1
                    Text {
                        anchors.centerIn: parent
                        width: parent.width - 16
                        horizontalAlignment: Text.AlignHCenter
                        elide: Text.ElideRight
                        color: Theme.text
                        font.pixelSize: Math.max(9, Math.min(16, parent.height * 0.12))
                        text: tile.title || tile.cls
                    }
                }
                ScreencopyView {
                    id: capture
                    anchors.fill: parent
                    // nothing is captured unless the overview is on screen
                    captureSource: root.showing && tile.toplevel ? tile.toplevel.wayland : null
                    live: root.showing
                    paintCursor: false
                }
                // Hover: a quiet ring, the theme's accent only as a hairline.
                Rectangle {
                    anchors.fill: parent
                    color: "transparent"
                    radius: 6 * tile.p
                    border.width: hover.containsMouse && root.open ? 2 : (tile.p > 0 ? 1 : 0)
                    border.color: hover.containsMouse && root.open ? Theme.accent : Theme.borderIdle
                    opacity: tile.p
                }
                MouseArea {
                    id: hover
                    anchors.fill: parent
                    hoverEnabled: true
                    enabled: root.open
                    onClicked: root.activate(tile)
                }
            }
        }

        }

        Text {
            anchors.centerIn: parent
            visible: root.layout !== null && root.windows.length === 0
            opacity: root.progress
            color: Theme.text
            font.pixelSize: 18
            text: "No windows on this workspace"
        }

        // Shown when a click lands on a window that is entirely off screen.
        Rectangle {
            id: offScreenNote
            objectName: "overviewOffScreenNote"
            property bool shown: false
            property alias text: noteText.text
            anchors.horizontalCenter: parent.horizontalCenter
            y: parent.height - height - 28
            width: Math.min(parent.width - 64, noteText.implicitWidth + 40)
            height: noteText.implicitHeight + 22
            radius: 12
            color: Theme.panel
            border.color: Theme.border
            opacity: shown && root.open ? 1 : 0
            visible: opacity > 0
            Behavior on opacity { NumberAnimation { duration: Theme.durationFast } }
            Text {
                id: noteText
                anchors.centerIn: parent
                width: Math.min(implicitWidth, parent.parent.width - 104)
                wrapMode: Text.WordWrap
                horizontalAlignment: Text.AlignHCenter
                color: Theme.text
                font.pixelSize: 15
            }
        }

        // The keypress's immediate feedback: a dim over everything, the real
        // desktop showing through until the window data is in; it gives way
        // to the backdrop's own dim as the zoom runs.
        Rectangle {
            objectName: "overviewScrim"
            anchors.fill: parent
            color: "black"
            opacity: 0.22 * root.fade * (1 - root.progress)
            visible: opacity > 0
        }
    }

    readonly property string wallpaperUrl: {
        let p = Theme.wallpaper || "";
        if (p.startsWith("~/")) p = Quickshell.env("HOME") + p.substring(1);
        return p ? "file://" + p : "";
    }
}
