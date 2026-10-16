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
//   then      -> the composition zooms out to fit the usable area; the
//                wallpaper fades in under it over the first third
// Closing plays it back: the last frames are the real desktop again.
//
// Clicking a window focuses it (by its Hyprland address) and closes. A window
// entirely off screen can't be shown without moving windows, so it is never
// focused silently (keystrokes would go to a window nobody can see): the
// first click says so, a second click on the same window pans the desktop
// there -- every window moved together, the arrow keys' camera pan
// (dxrice_navigate_windows.py --to) -- and then focuses it. Esc, a click on
// empty space or the keybind again closes without changing focus.
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
    // when the last open began (ms since epoch), for the latency test
    property real openedAt: 0
    property real dataAt: 0

    readonly property bool showing: root.open || root.fade > 0
    readonly property var windows: root.layout && root.layout.windows ? root.layout.windows : []
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
        root._confirmPan = "";
        root._hideAfterRefresh = false;
        offScreenNote.shown = false;
        PanelManager.closeCurrent();
        // Immediate feedback: the surface comes up now, dimming the real
        // desktop, while the window data is read.
        exitAnim.stop();
        scrimIn.restart();
        root._pendingEnter = true;
        root.refresh();
    }
    function hide() {
        if (!root.open) return;
        root.open = false;
        root._pendingEnter = false;
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
        root.dataAt = Date.now();
        if (root._hideAfterRefresh) {
            // after a pan: close onto the windows where they now are
            root._hideAfterRefresh = false;
            root.hide();
            focusSoon.restart();
            return;
        }
        if (root._pendingEnter) {
            root._pendingEnter = false;
            enterAnim.restart();
        }
    }
    function _parse(text) {
        try { return JSON.parse(text); } catch (e) { return null; }
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
    // Debounced: one burst of events (a window opening sends several) is
    // one refresh.
    Timer { id: refreshSoon; interval: 60; onTriggered: if (root.open) root.refresh() }
    Connections {
        target: Hyprland
        function onRawEvent(event) {
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
    property string _confirmPan: ""   // an off-screen window clicked once
    property bool _hideAfterRefresh: false
    function activate(w) {
        if (!root.open || !w || panProc.running) return;
        if (!Geo.onScreen(w, root.layout)) {
            if (root._confirmPan !== w.address) {
                root._confirmPan = w.address;
                offScreenNote.text = (w.title || w["class"] || "This window") + " is off screen. "
                    + "Click it again to pan the desktop there (every window moves together, "
                    + "as with SUPER+arrow keys) and focus it.";
                offScreenNote.shown = true;
                noteTimer.restart();
                return;
            }
            // confirmed: pan, re-read the (moved) windows, close onto them
            root._confirmPan = "";
            offScreenNote.shown = false;
            root._focusAfterClose = w.address;
            panProc.command = ["python3", Quickshell.shellDir + "/../scripts/dxrice_navigate_windows.py", "--to", w.address];
            panProc.running = true;
            return;
        }
        root._focusAfterClose = w.address;
        root.hide();
        focusSoon.restart();
    }
    Process {
        id: panProc
        onExited: {
            root._hideAfterRefresh = true;
            root.refresh();
        }
    }
    Timer { id: focusSoon; interval: 30; onTriggered: if (root._focusAfterClose) Hyprland.dispatch(root.focusLua(root._focusAfterClose)) }
    Timer {
        id: focusAgain; interval: 40
        onTriggered: {
            if (root._focusAfterClose && !root.open) Hyprland.dispatch(root.focusLua(root._focusAfterClose));
            root._focusAfterClose = "";
        }
    }
    Timer { id: noteTimer; interval: 4000; onTriggered: { offScreenNote.shown = false; root._confirmPan = ""; } }
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
    // Each step animates from wherever it is, so toggling mid-way reverses
    // without a jump.
    NumberAnimation {
        id: scrimIn
        target: root; property: "fade"; to: 1; duration: Theme.durationFast; easing.type: Easing.OutCubic
    }
    // the zoom runs alongside the keypress's dim (scrimIn), which is
    // already under way by the time the window data is in
    NumberAnimation {
        id: enterAnim
        target: root; property: "progress"; to: 1; duration: Theme.durationEnter
        easing.type: Theme.easingType; easing.bezierCurve: Theme.curveEnter
    }
    SequentialAnimation {
        id: exitAnim
        // ease in AND out: the way back starts gently even when it reverses
        // a zoom still in flight, and settles onto the real windows
        NumberAnimation {
            target: root; property: "progress"; to: 0; duration: Theme.durationExit + 60
            easing.type: Easing.InOutCubic
        }
        NumberAnimation { target: root; property: "fade"; to: 0; duration: Theme.durationFadeOut; easing.type: Easing.InCubic }
        // closed: let the tiles (and their capture sessions) go entirely,
        // then give a clicked window its focus once more (see focusLua)
        ScriptAction {
            script: {
                if (!root.open) root.layout = null;
                if (root._focusAfterClose) focusAgain.restart();
            }
        }
    }

    // ---- the surface ----
    visible: root.showing
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

        // The real wallpaper, drawn as hyprpaper draws it (cover). It fades
        // in over the first third of the zoom, covering the real windows as
        // their pictures move away from them -- and out over the last third
        // of the way back, so the final frames are the real desktop.
        Item {
            id: backdrop
            anchors.fill: parent
            opacity: Math.min(1, root.progress * 3)
            visible: opacity > 0
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
            model: root.windows
            delegate: Item {
                id: tile
                required property var modelData
                objectName: "overviewTile:" + tile.modelData.address
                readonly property real p: root.progress
                readonly property var toplevel: root.toplevelFor(tile.modelData.address)
                x: tile.modelData.x + (tile.modelData.tx - tile.modelData.x) * tile.p
                y: tile.modelData.y + (tile.modelData.ty - tile.modelData.y) * tile.p
                width: Math.max(1, tile.modelData.w + (tile.modelData.tw - tile.modelData.w) * tile.p)
                height: Math.max(1, tile.modelData.h + (tile.modelData.th - tile.modelData.h) * tile.p)
                z: tile.modelData.z
                // A fullscreen window keeps its real place at the top of the
                // stack -- the first frame is the real desktop -- but turns
                // half see-through as the view zooms out, so the windows it
                // covers on this workspace can be seen too.
                opacity: tile.modelData.fullscreen ? 1 - 0.5 * tile.p : 1

                // Placeholder when a window can't be captured (no live
                // picture yet, or the compositor declines): its card, title
                // and class, never an empty hole. Not before the zoom is
                // under way -- until then the real window shows through.
                Rectangle {
                    objectName: "overviewPlaceholder"
                    anchors.fill: parent
                    visible: !capture.hasContent && tile.p > 0.3
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
                        text: tile.modelData.title || tile.modelData["class"] || ""
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
                    onClicked: root.activate(tile.modelData)
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
