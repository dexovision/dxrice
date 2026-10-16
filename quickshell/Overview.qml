import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import Quickshell.Hyprland

// Desktop overview (SUPER+Tab): the current workspace zoomed out until every
// window -- the whole Galaxy Spiral, including the parts past the screen
// edges -- fits on the monitor.
//
// A VIEW, never a layout: each window is drawn as a live picture of itself
// (ScreencopyView over Hyprland's toplevel-export protocol) on an overlay
// layer-shell surface over the whole monitor. The windows are fitted into
// the usable area (clear of where the bar and dock sit), but the surface
// covers the bar's and dock's strips too: the bar is islands with the
// desktop showing between them, and windows reaching into those strips
// would otherwise show through around the overview. The bar and dock fade
// out with the opening fade and back in with the closing one. Opening the overview starts every picture
// exactly on top of its real window, over the real wallpaper, then animates
// them all down to the rects dxrice_overview.py computes; closing plays it
// back to the real positions and only then lets the surface go. No window is
// moved, resized or refocused, so the view you come back to is exactly the
// one you left. Clicking a window focuses it and closes the overview; Esc,
// a click on empty space or the keybind again closes without changing
// focus.
//
// Hyprland itself cannot zoom the desktop out (see dxrice_overview.py's
// docstring for why its magnifier, a monitor-scale change and the overview
// plugins were ruled out).
//
// Toggle: qs -p <repo>/quickshell/shell.qml ipc call overview toggle
PanelWindow {
    id: root

    // ---- state ----
    // `open` is what was asked for; `progress` (0 = the real desktop, 1 =
    // zoomed out) and `fade` (the surface's opacity) are what is on screen.
    property bool open: false
    property real progress: 0
    property real fade: 0
    // dxrice_overview.py's output for the monitor being shown
    property var layout: null
    property bool _pendingEnter: false

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
        PanelManager.closeCurrent();
        root._pendingEnter = true;
        root.refresh();
    }
    function hide() {
        if (!root.open) return;
        root.open = false;
        root._pendingEnter = false;
        enterAnim.stop();
        exitAnim.start();
    }
    function toggle() {
        if (root.open) root.hide();
        else root.show();
    }

    // Fresh window/monitor state straight from Hyprland on every open and
    // on every window event while open -- never a timer.
    function refresh() {
        layoutProc.running = false;
        layoutProc.running = true;
    }
    Process {
        id: layoutProc
        command: ["python3", Quickshell.shellDir + "/../scripts/dxrice_overview.py"]
        stdout: StdioCollector {
            onStreamFinished: {
                let parsed = null;
                try { parsed = JSON.parse(this.text); } catch (e) { parsed = null; }
                if (!parsed || !parsed.monitor) {
                    // No compositor answer: there is nothing to show; give
                    // the keybind back instead of holding an empty overlay.
                    if (root._pendingEnter) { root._pendingEnter = false; root.open = false; }
                    return;
                }
                root.layout = parsed;
                if (root._pendingEnter) {
                    root._pendingEnter = false;
                    exitAnim.stop();
                    enterAnim.start();
                }
            }
        }
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

    // Focus the clicked window (on this same workspace, so the workspace
    // never changes) and leave the overview.
    function focusWindow(address) {
        const a = String(address).startsWith("0x") ? String(address) : "0x" + address;
        Hyprland.dispatch(Hyprland.usingLua ? 'hl.dsp.focus({ window = "address:' + a + '" })'
                                            : "focuswindow address:" + a);
        root.hide();
    }
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
    // In: the surface fades in with every picture still exactly over its
    // window (nothing visibly changes but the bar and dock tucking under),
    // then the composition zooms out. Out: the reverse, so the last frame
    // before the surface goes is the real desktop again. Each step animates
    // from wherever it is, so toggling mid-way reverses without a jump.
    SequentialAnimation {
        id: enterAnim
        NumberAnimation { target: root; property: "fade"; to: 1; duration: Theme.durationFast; easing.type: Easing.OutCubic }
        NumberAnimation {
            target: root; property: "progress"; to: 1; duration: Theme.durationEnter
            easing.type: Theme.easingType; easing.bezierCurve: Theme.curveEnter
        }
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
        // closed: let the tiles (and their capture sessions) go entirely
        ScriptAction { script: if (!root.open) root.layout = null }
    }

    // ---- the surface ----
    visible: root.showing && root.layout !== null
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
        const name = root.layout && root.layout.monitor ? root.layout.monitor.name : "";
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
        width: root.monitorWidth
        height: root.monitorHeight
        clip: true
        opacity: root.fade
        focus: true
        Keys.onEscapePressed: root.hide()

        // The real wallpaper, drawn as hyprpaper draws it (cover), so the
        // first and last frames match the desktop underneath exactly.
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
                // and class, never an empty hole.
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
                    onClicked: root.focusWindow(tile.modelData.address)
                }
            }
        }

        }

        Text {
            anchors.centerIn: parent
            visible: root.windows.length === 0
            opacity: root.progress
            color: Theme.text
            font.pixelSize: 18
            text: "No windows on this workspace"
        }
    }

    readonly property string wallpaperUrl: {
        let p = Theme.wallpaper || "";
        if (p.startsWith("~/")) p = Quickshell.env("HOME") + p.substring(1);
        return p ? "file://" + p : "";
    }
}
