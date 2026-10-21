import QtQuick
import QtQuick.Effects
import Quickshell
import Quickshell.Io
import Quickshell.Widgets
import Quickshell.Wayland
import Quickshell.Hyprland
import Quickshell.Services.SystemTray
import Quickshell.Services.Pipewire

// The shell's top edge: ONE bar, with three sections.
//
//   - LEFT: the launcher, the saved shortcuts (with open/focused marks),
//     the workspaces and the focused window. Opens Applications.
//   - CENTRE: the clock. Opens the calendar.
//   - RIGHT: tray, then one indicator per thing -- network, Bluetooth,
//     sound, power, notifications, the Dashboard -- each opening its own
//     section of one panel.
//
// The sections are transparent regions of a single strip, not pills of
// their own (an earlier design had three separate islands, which read as
// three things rather than one bar). Every panel hangs from the bar's lower
// edge under the section that opened it, joined to it by concave curves, so
// opening one reads as the bar branching downward (see ShellIsland.qml);
// a panel that reaches an end of the bar squares that corner off and runs
// flush with it. Panels never cover the bar, so every section stays where
// it is and stays usable while any panel is open.
//
// The window is full-height and almost entirely transparent, with an explicit
// exclusiveZone reserving only the bar's strip, and an input mask limited to
// the strip and an open panel's body, so the desktop below stays clickable.
// It is full-height because the panels live in here too: a panel in its own
// window could only ever be positioned near its control, never grow out of
// it.
PanelWindow {
    id: root

    signal calendarRequested()
    signal quickSettingsRequested()
    signal launcherRequested()

    // Straight from the shell's geometry system (ShellSurface.qml) rather
    // than tuned per-file. Measured against the reference bar, capsules sit
    // at roughly 3.5% of screen height (~38px at 1080p) -- the 28 these were
    // shrunk to during earlier passes was too short, and shrinking further
    // was the wrong direction.
    readonly property real islandHeight: ShellSurface.unit
    readonly property real edgeMargin: ShellSurface.gap

    // A hard backstop, independent of whatever each panel's own layout
    // contract computes: this island sits `edgeMargin` from the top and
    // needs the same gap free at the bottom, so nothing expanding from here
    // may ever be taller than the screen minus both. Panels are expected to
    // size themselves correctly on their own (see QuickSettings.qml's own
    // contract) -- this exists so a bug in one panel's math becomes "slightly
    // wrong height" instead of "surface physically runs off the screen."
    function clampToScreen(h) {
        return ShellSurface.clampToScreen(h, root.edgeMargin);
    }

    color: "transparent"
    anchors { top: true; left: true; right: true }
    implicitHeight: root.screen ? root.screen.height : 1080
    // Anchored to a single edge, so layer-shell still honours an exclusive
    // zone even though the surface itself covers the screen: reserve exactly
    // the island strip and nothing more.
    exclusionMode: ExclusionMode.Normal
    exclusiveZone: root.edgeMargin * 2 + root.islandHeight
    WlrLayershell.layer: WlrLayer.Top
    WlrLayershell.namespace: "dxrice-bar-top"
    aboveWindows: true
    // Keys only while one of the bar's panels is open by a click or a
    // keybind (a hover-opened one never takes them from the app you are
    // typing in). Applications takes them outright -- it opens with its
    // search field ready, from SUPER+R too, where no click on the bar gave
    // it focus; the others take them when clicked.
    readonly property bool appsOpen: PanelManager.isOpen("apps") || PanelManager.isOpen("taskbar")
    readonly property bool takesKeys: PanelManager.openedBy === "click"
        && (root.appsOpen || root.statusOpen || PanelManager.isOpen("calendar"))
    readonly property int _keyMode: !root.takesKeys ? WlrKeyboardFocus.None : (root.appsOpen ? WlrKeyboardFocus.Exclusive : WlrKeyboardFocus.OnDemand)
    WlrLayershell.keyboardFocus: root._keyMode
    // Escape peels one layer: the Add Shortcut branch if it is open, else the panel
    function peel() {
        if (root.branchOpen) activityIsland.panelItem.manager.addPanelOpen = false;
        else PanelManager.closeCurrent();
    }
    Shortcut { objectName: "topBarEscape"; sequence: "Escape"; enabled: root.takesKeys; onActivated: root.peel() }

    // Whether Quick Settings' Wifi-password dialog is open -- a real,
    // separate top-level window (FloatingWindow) that this window's own
    // full-screen dismiss catcher below has no way to see. Without this,
    // clicking into its password field to type was being caught as "a
    // click outside every island" and closing Quick Settings (destroying
    // the dialog with it) instead of ever reaching the field -- same
    // architectural gap, and same fix, as Dock.qml's taskbarModalOpen.
    readonly property bool statusModalOpen: statusIsland.panelItem && statusIsland.panelItem.wifiDialogOpen

    // Whether one of the bar's panels is open -- the click-outside-to-dismiss
    // region below only ever expands while this is true.
    readonly property bool statusOpen: PanelManager.isOpen("quicksettings") || PanelManager.current.indexOf("status:") === 0
    readonly property bool anyIslandOpen: (PanelManager.isOpen("calendar") || root.statusOpen || root.appsOpen)
                                           && !root.statusModalOpen
    readonly property bool branchOpen: addBranch.open

    // Without this the transparent full-screen surface would swallow every
    // click on the desktop: input is the bar's strip (all of it -- a bar that
    // looks solid must not pass clicks through its gaps), the open panel's
    // body as it grows (not as it retracts: a closing panel lets go of input
    // at once), and click-outside-to-dismiss: while a panel here is
    // open, input extends to the whole window so a click that misses
    // everything reaches `dismissArea` and closes it; the instant
    // anyIslandOpen goes false it collapses back to 0x0.
    mask: Region {
        Region { item: barStrip }
        Region { item: activityIsland.expanded ? activityIsland.bodyItem : null }
        Region { item: clockIsland.expanded ? clockIsland.bodyItem : null }
        Region { item: statusIsland.expanded ? statusIsland.bodyItem : null }
        // the Add Shortcut branch: explicit bounds, only while it is open (an
        // item region would keep its full rect while it is closed)
        Region {
            x: addBranch.x
            y: addBranch.y
            width: addBranch.inputActive ? addBranch.width : 0
            height: addBranch.inputActive ? addBranch.height : 0
        }
        Region {
            x: 0; y: 0
            width: root.anyIslandOpen ? root.width : 0
            height: root.anyIslandOpen ? root.height : 0
        }
    }

    MouseArea {
        id: dismissArea
        anchors.fill: parent
        enabled: root.anyIslandOpen
        onClicked: root.peel()
    }

    // ---- the bar: one strip under all three sections ----
    // Its lower corner squares off while a panel runs flush with that end
    // of it (over the panel's first `radius` px of drop, so the corner turns
    // as the panel grows rather than snapping).
    readonly property real barRadius: root.islandHeight / 2
    function _cornerFor(island, flush) {
        return flush ? root.barRadius * (1 - Math.min(1, island.bodyHeight / root.barRadius)) : root.barRadius;
    }
    // The bar's shadow, everywhere except below the bar where a panel hangs
    // from it: there the bar and the panel are one shape, and the shadow
    // seen through the translucent panel would draw a dark band across the
    // joint. So it is drawn in three clipped pieces -- down to the bar's
    // lower edge everywhere, and below it only left and right of the open
    // panels' span (the panels cast their own shadow below).
    readonly property var _openSpan: {
        let lo = 1e9, hi = -1e9;
        for (const i of [activityIsland, clockIsland, statusIsland]) {
            if (i.bodyHeight <= 0.5) continue;
            lo = Math.min(lo, i.x + i.bodyX - i.filletRadius);
            hi = Math.max(hi, i.x + i.bodyX + i.bodyWidth + i.filletRadius);
        }
        return lo < hi ? [lo, hi] : [root.width, root.width];
    }
    component BarShadowPiece: Item {
        id: piece
        clip: true
        RectangularShadow {
            x: barStrip.x - piece.x; y: barStrip.y - piece.y
            width: barStrip.width; height: barStrip.height
            radius: root.barRadius
            color: Theme.shadowColor
            blur: Theme.elevationBlur(2)
            spread: Theme.elevationSpread(2)
            offset.y: Theme.elevationOffsetY(2)
        }
    }
    BarShadowPiece { x: 0; y: 0; width: root.width; height: barStrip.y + barStrip.height }
    BarShadowPiece { x: 0; y: barStrip.y + barStrip.height; width: Math.max(0, root._openSpan[0]); height: 80 }
    BarShadowPiece { x: root._openSpan[1]; y: barStrip.y + barStrip.height; width: Math.max(0, root.width - root._openSpan[1]); height: 80 }
    Rectangle {
        id: barStrip
        objectName: "barStrip"
        x: root.edgeMargin
        y: root.edgeMargin
        width: root.width - root.edgeMargin * 2
        height: root.islandHeight
        color: Theme.panel
        topLeftRadius: root.barRadius
        topRightRadius: root.barRadius
        bottomLeftRadius: Math.min(root._cornerFor(activityIsland, activityIsland.flushLeft),
                                   root._cornerFor(statusIsland, statusIsland.flushLeft),
                                   root._cornerFor(clockIsland, clockIsland.flushLeft))
        bottomRightRadius: Math.min(root._cornerFor(statusIsland, statusIsland.flushRight),
                                    root._cornerFor(activityIsland, activityIsland.flushRight),
                                    root._cornerFor(clockIsland, clockIsland.flushRight))
        // takes clicks on the bar's bare stretches, so they don't reach the
        // dismiss catcher (or the desktop)
        MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons }
    }

    Binding { target: ShellSurface; property: "topEdgeHeight"; value: root.exclusiveZone }
    Binding { target: ShellSurface; property: "screenHeight"; value: root.screen ? root.screen.height : 1080 }

    // ---- hover intent: each bar element opens its own panel ----
    // Hovering an element opens its panel after a short pause (so passing
    // over the bar opens nothing); while a panel of the same island is open,
    // moving to a neighbouring element switches it at once (no close and
    // reopen, no flicker). A hover-opened panel closes a moment after the
    // pointer has left both the element and its panel, and never takes the
    // keyboard from the app you are in; a click opens it to stay (and may).
    // theme.json "bar_hover_open": false makes it click-only.
    readonly property bool hoverOpens: Theme.data.bar_hover_open !== false
    property string _hoverWant: ""
    // A hover-opened panel gives way to another section's after the same
    // pause (the bar branches from wherever the pointer settles); a clicked
    // one stays until it is closed.
    readonly property bool _mayHoverOpen: PanelManager.current === "" || PanelManager.openedBy === "hover"
    Timer {
        id: hoverOpenTimer
        interval: 150
        onTriggered: if (root._hoverWant && root._mayHoverOpen && PanelManager.current !== root._hoverWant) PanelManager.open(root._hoverWant, "hover")
    }
    function elementHovered(name, on, island) {
        if (on) {
            const cur = PanelManager.current;
            const sameIsland = (island === "status" && root.statusOpen) || (island === "clock" && cur === "calendar")
                || (island === "activity" && root.appsOpen);
            if (sameIsland) {
                hoverOpenTimer.stop();
                root._hoverWant = "";
                if (cur !== name && island === "status") PanelManager.open(name, PanelManager.openedBy);
                return;
            }
            if (!root.hoverOpens || !root._mayHoverOpen) return;
            root._hoverWant = name;
            if (root._pointerMoved()) hoverOpenTimer.restart();
        } else if (root._hoverWant === name) {
            root._hoverWant = "";
            hoverOpenTimer.stop();
        }
    }
    function elementClicked(name) {
        hoverOpenTimer.stop();
        root._hoverWant = "";
        PanelManager.toggle(name);
    }
    Timer {
        id: hoverCloseTimer
        interval: 320
        property string island: ""
        onTriggered: {
            if (PanelManager.openedBy !== "hover") return;
            if (hoverCloseTimer.island === "status" && root.statusOpen && !statusIsland.pointerInside) PanelManager.closeCurrent();
            if (hoverCloseTimer.island === "clock" && PanelManager.isOpen("calendar") && !clockIsland.pointerInside) PanelManager.closeCurrent();
            if (hoverCloseTimer.island === "activity" && root.appsOpen && !activityIsland.pointerInside) PanelManager.closeCurrent();
        }
    }
    // A panel that closes (Escape, a keybind, a click on its element) can
    // leave the pointer resting on a bar element -- that is not a hover, and
    // reopening there made a panel come straight back after it was closed.
    // So a hover opens nothing until the pointer has moved since the last
    // close; an element it is already resting on opens once it does.
    property point _closedAt: Qt.point(-1e6, -1e6)
    function _pointerMoved() {
        const p = barPointer.point.scenePosition;
        return Math.abs(p.x - root._closedAt.x) > 0.5 || Math.abs(p.y - root._closedAt.y) > 0.5;
    }
    HoverHandler {      // on the window itself, so it sees the pointer over every island
        id: barPointer
        onPointChanged: {
            if (!root._pointerMoved()) return;
            root._closedAt = Qt.point(-1e6, -1e6);
            if (root._hoverWant && root._mayHoverOpen && PanelManager.current !== root._hoverWant && !hoverOpenTimer.running) hoverOpenTimer.restart();
        }
    }
    Connections {
        target: PanelManager
        function onCurrentChanged() { if (PanelManager.current === "") root._closedAt = barPointer.point.scenePosition; }
    }
    function islandLeft(island, inside) {
        if (inside) { if (hoverCloseTimer.island === island) hoverCloseTimer.stop(); return; }
        hoverCloseTimer.island = island;
        hoverCloseTimer.restart();
    }

    // ---- network, for its indicator: nmcli monitor reports every change,
    // so the state is re-read only when something happened (no polling) ----
    property string netKind: ""          // "wifi" | "ethernet" | ""
    property string netName: ""
    Process {
        id: netState
        command: ["nmcli", "-t", "-f", "TYPE,STATE,CONNECTION", "device"]
        stdout: StdioCollector {
            onStreamFinished: {
                let kind = "", name = "";
                for (const line of this.text.split("\n")) {
                    const f = line.split(":");
                    if (f.length < 3 || f[1] !== "connected") continue;
                    if (f[0] === "ethernet") { kind = "ethernet"; name = f.slice(2).join(":"); break; }
                    if (f[0] === "wifi" && !kind) { kind = "wifi"; name = f.slice(2).join(":"); }
                }
                root.netKind = kind;
                root.netName = name;
            }
        }
    }
    Process {
        id: netMonitor
        command: ["nmcli", "monitor"]
        running: true
        stdout: SplitParser { onRead: (line) => netDebounce.restart() }
    }
    Timer { id: netDebounce; interval: 300; onTriggered: netState.running = true }

    // ---- workspaces (native Hyprland IPC -- no hyprctl subprocess) ----
    // Ordinary workspaces only: special ones (scratchpads, negative ids) are
    // toggled, not switched to, and don't belong in the row.
    readonly property var workspaceList: {
        const list = Hyprland.workspaces.values.filter((w) => w.id > 0);
        list.sort((a, b) => a.id - b.id);
        return list;
    }
    // In Lua syntax, like every other DXrice dispatch: this Hyprland runs
    // hyprland.lua and refuses the classic form, which Quickshell's own
    // HyprlandWorkspace.activate() may send (its usingLua has been seen to
    // be wrong; see Overview.qml's focusLua).
    function focusWorkspace(ws) {
        Hyprland.dispatch("hl.dsp.focus({ workspace = " + ws.id + " })");
    }

    // ---- audio, for the status cluster ----
    PwObjectTracker { objects: [Pipewire.defaultAudioSink] }
    readonly property var sink: Pipewire.defaultAudioSink
    readonly property int volumePercent: (sink && sink.audio) ? Math.round(sink.audio.volume * 100) : 0
    readonly property bool muted: (sink && sink.audio) ? sink.audio.muted : false

    // ---- left island: the shell's anchor. Workspaces + focused window,
    // bundled -- see the file header for why this is one island and not two.
    // Summons no panel; it exists to be substantial, not to expand. ----
    // The focused window's class and title. Not Hyprland.activeToplevel:
    // in the Quickshell version this was built against it stays null until
    // the first focus change after the shell starts. So: one
    // `hyprctl activewindow -j` read at startup (and after a config reload),
    // then Hyprland's own events -- activewindow>>CLASS,TITLE on every focus
    // change, windowtitlev2>>ADDRESS,TITLE when a window renames itself (a
    // browser switching tabs). No polling.
    property string activeAppId: ""
    property string activeTitle: ""
    property string _activeAddress: ""

    Process {
        id: activeWindowProc
        command: ["hyprctl", "activewindow", "-j"]
        stdout: StdioCollector {
            onStreamFinished: {
                try {
                    const w = JSON.parse(this.text);
                    root._activeAddress = String(w.address || "").replace(/^0x/, "");
                    root.setActive(w.class || "", w.title || "");
                } catch (e) {
                    // no focused window prints "{}" or an error string
                    root._activeAddress = "";
                    root.setActive("", "");
                }
            }
        }
    }
    Component.onCompleted: { activeWindowProc.running = true; netState.running = true; }

    // Title first: onActiveAppIdChanged reads activeTitle at once.
    function setActive(cls, title) {
        root.activeTitle = title;
        root.activeAppId = cls;
    }
    // "a,b,c" -> ["a", "b,c"]: the payload's last field may contain commas
    function _splitFirst(data) {
        const i = data.indexOf(",");
        return i < 0 ? [data, ""] : [data.substring(0, i), data.substring(i + 1)];
    }
    Connections {
        target: Hyprland
        function onRawEvent(event) {
            const data = String(event.data || "");
            if (event.name === "activewindow") {
                const parts = root._splitFirst(data);
                root.setActive(parts[0], parts[1]);
            } else if (event.name === "activewindowv2") {
                root._activeAddress = data.replace(/^0x/, "");
            } else if (event.name === "windowtitlev2") {
                const parts = root._splitFirst(data);
                if (parts[0].replace(/^0x/, "") === root._activeAddress) root.activeTitle = parts[1];
            } else if (event.name === "configreloaded") {
                activeWindowProc.running = true;
            }
        }
    }

    Process {
        id: activeIconProc
        stdout: StdioCollector {
            onStreamFinished: activityIsland.appGlyph = this.text.trim()
        }
    }
    function refreshActiveIcon() {
        if (!root.activeAppId) { activityIsland.appGlyph = ""; return; }
        // `running = true` is a no-op if it is ALREADY true (setting a
        // property to its current value fires no change, so nothing
        // restarts the process with the new command) -- which happens
        // whenever activeAppIdChanged fires again while a previous lookup
        // for the last window is still in flight, e.g. as Hyprland's IPC
        // data arrives in more than one update. Forcing it false first
        // guarantees a real stop/restart with the new argv every time.
        activeIconProc.running = false;
        activeIconProc.command = ["python3", Quickshell.shellDir + "/../scripts/dxrice_icons.py", root.activeAppId, root.activeTitle];
        activeIconProc.running = true;
    }
    onActiveAppIdChanged: root.refreshActiveIcon()

    ShellIsland {
        id: activityIsland
        objectName: "activityIsland"
        property string appGlyph: ""
        x: barStrip.x
        y: barStrip.y
        barLeft: barStrip.x
        barRight: barStrip.x + barStrip.width
        pinX: "left"
        expanded: root.appsOpen
        collapsedWidth: activityRow.implicitWidth + ShellSurface.pad * 2
        collapsedHeight: root.islandHeight
        expandedWidth: ShellSurface.panelWidthMedium
        expandedHeight: root.clampToScreen(collapsedHeight + ((panelItem && panelItem.contentHeight) ? panelItem.contentHeight : 420))
        panel: appsComponent
        elevation: 2
        onPointerInsideChanged: root.islandLeft("activity", pointerInside)

        Row {
            id: activityRow
            anchors.centerIn: parent
            spacing: ShellSurface.pad

            // The search pill (Applications: search, pinned, open windows,
            // the shortcut editor) and the saved shortcuts, each with its
            // open/focused mark; hovering one names it in the title beside.
            // theme.json "bar_shortcuts": false leaves only the search pill.
            Row {
                id: barApps
                objectName: "barApps"
                anchors.verticalCenter: parent.verticalCenter
                spacing: 2
                Rectangle {
                    id: searchPill
                    objectName: "barLauncher"
                    Accessible.role: Accessible.Button
                    Accessible.name: "Search applications"
                    readonly property bool open: root.appsOpen
                    width: searchRow.implicitWidth + ShellSurface.pad * 2
                    height: ShellSurface.chip
                    radius: height / 2
                    anchors.verticalCenter: parent.verticalCenter
                    color: searchPill.open ? Theme.mix(Theme.layer1, Theme.accent, 0.22)
                         : (searchArea.containsMouse ? Theme.layer1Hover : Theme.layer1)
                    scale: Theme.pressScale(searchArea.pressed, 0.94)
                    Behavior on color { ColorAnimation { duration: Theme.durationFast } }
                    Behavior on scale { NumberAnimation { duration: Theme.durationSpringFast; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveSpringFast } }
                    Row {
                        id: searchRow
                        anchors.centerIn: parent
                        spacing: Theme.padSm
                        Text { text: "\uf002"; color: searchPill.open ? Theme.accentText : Theme.textActive; font.family: Theme.iconFamily; font.pixelSize: Theme.fontSizeSmaller; anchors.verticalCenter: parent.verticalCenter }
                        Text {
                            visible: root.width >= 1000
                            text: "Search apps"
                            color: Theme.text
                            font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSmaller
                            anchors.verticalCenter: parent.verticalCenter
                        }
                    }
                    MouseArea {
                        id: searchArea
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onContainsMouseChanged: root.elementHovered("apps", containsMouse, "activity")
                        onClicked: root.elementClicked(root.appsOpen ? PanelManager.current : "apps")
                    }
                }
                Repeater {
                    // (the app-launcher shortcut is the search pill above;
                    // one with no command would do nothing)
                    model: root.shortcutsFit ? root.barShortcuts : []
                    delegate: BarAppButton {
                        required property var modelData
                        objectName: "barShortcut:" + modelData.label
                        glyph: modelData.glyph
                        image: modelData.image || ""
                        label: modelData.label
                        appKey: Shortcuts.appKeyOf(modelData.onClick)
                        onActivated: {
                            const what = Shortcuts.launch(modelData.onClick, "bar");
                            if (what === "launcher") root.openApps();
                            else if (what === "launched") hop();
                        }
                    }
                }
            }
            Rectangle {
                width: 1
                height: ShellSurface.chip
                anchors.verticalCenter: parent.verticalCenter
                color: Theme.borderIdle
            }

            Row {
                id: wsRow
                anchors.verticalCenter: parent.verticalCenter
                spacing: Theme.padXs

                Repeater {
                    model: root.workspaceList
                    delegate: Rectangle {
                        id: wsPill
                        required property var modelData
                        objectName: "workspacePill:" + modelData.id
                        readonly property bool active: modelData.focused
                        Accessible.role: Accessible.Button
                        Accessible.name: "Workspace " + modelData.id
                        // the focused one is a pill with its number; the others dots
                        width: active ? 24 : 8
                        height: active ? 16 : 8
                        radius: Theme.roundingFull
                        anchors.verticalCenter: parent.verticalCenter
                        color: active ? Theme.accent : (wsArea.containsMouse ? Theme.layer2Hover : Theme.borderIdle)
                        Behavior on height { NumberAnimation { duration: Theme.durationMove; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveExpressiveFast } }
                        Text {
                            objectName: "workspaceNumber"
                            anchors.centerIn: parent
                            text: wsPill.modelData.id
                            opacity: wsPill.active ? 1 : 0
                            Behavior on opacity { NumberAnimation { duration: Theme.durationFast } }
                            color: Theme.panelTone
                            font.family: Theme.fontMono; font.pixelSize: 10; font.weight: Font.Bold
                        }

                        Behavior on width { NumberAnimation { duration: Theme.durationMove; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveExpressiveFast } }
                        Behavior on color { ColorAnimation { duration: Theme.durationFast; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveStandard } }

                        MouseArea {
                            id: wsArea
                            anchors.fill: parent
                            anchors.margins: -4
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: root.focusWorkspace(wsPill.modelData)
                        }
                    }
                }
            }

            // The divider that makes this read as two related things sharing
            // one capsule, not one thing -- present only when there is a
            // second thing to divide from (a focused window to show).
            Rectangle {
                visible: root.activeTitle.length > 0 || root.hoveredApp.length > 0
                width: 1
                height: ShellSurface.chip
                anchors.verticalCenter: parent.verticalCenter
                color: Theme.borderIdle
            }

            Row {
                visible: root.activeTitle.length > 0 || root.hoveredApp.length > 0
                anchors.verticalCenter: parent.verticalCenter
                spacing: Theme.padXs
                Text {
                    visible: root.hoveredApp.length === 0
                    text: activityIsland.appGlyph
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSizeNormal
                    color: Theme.textActive
                    anchors.verticalCenter: parent.verticalCenter
                }
                Text {
                    objectName: "barTitle"
                    text: root.hoveredApp.length > 0 ? root.hoveredApp : root.activeTitle
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSizeSmaller
                    color: root.hoveredApp.length > 0 ? Theme.accentText : Theme.text
                    elide: Text.ElideRight
                    // The one deliberately "substantial" number in this file:
                    // enough width that a real window title reads as content,
                    // not a sliver -- this island's whole purpose is to be
                    // the shell's wide anchor rather than another nub.
                    width: Math.min(implicitWidth, 260)
                    anchors.verticalCenter: parent.verticalCenter
                }
            }
        }
    }

    // ---- centre section: the clock, which opens the calendar ----
    ShellIsland {
        id: clockIsland
        objectName: "clockIsland"
        anchors.horizontalCenter: parent.horizontalCenter
        y: barStrip.y
        barLeft: barStrip.x
        barRight: barStrip.x + barStrip.width
        pinX: "center"
        expanded: PanelManager.isOpen("calendar")
        collapsedWidth: clockText.implicitWidth + ShellSurface.pad * 2
        collapsedHeight: root.islandHeight
        expandedWidth: ShellSurface.panelWidthCompact
        // the bar's row plus however tall the calendar's own body needs
        expandedHeight: root.clampToScreen(collapsedHeight + ((panelItem && panelItem.contentHeight) ? panelItem.contentHeight : 320))
        panel: calendarComponent
        onCloseRequested: PanelManager.close("calendar")

        Text {
            id: clockText
            anchors.centerIn: parent
            color: Theme.textActive
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSizeNormal
            font.features: { "tnum": 1 }
            // The time leads; the date follows, lighter and quieter -- one
            // string of spaced-out text read as a single undifferentiated
            // label in a proportional face.
            textFormat: Text.StyledText
            property string time: ""
            property string date: ""
            text: "<b>" + time + "</b>&nbsp;&nbsp;&nbsp;<font color=\"" + Theme.text + "\">" + date + "</font>"
        }
        // Shows minutes, so it wakes once a minute, just after the minute
        // turns (re-aimed every time, so it never drifts).
        Timer {
            id: clockTick
            interval: 1; running: true; repeat: false
            onTriggered: {
                const now = new Date();
                clockText.time = Qt.formatDateTime(now, "HH:mm");
                clockText.date = Qt.formatDateTime(now, "ddd MMM d");
                clockTick.interval = 60000 - (now.getSeconds() * 1000 + now.getMilliseconds()) + 50;
                clockTick.restart();
            }
        }
        hovered: clockArea.containsMouse
        pressed: clockArea.pressed
        onPointerInsideChanged: root.islandLeft("clock", pointerInside)
        MouseArea {
            id: clockArea
            anchors.fill: parent
            enabled: !clockIsland.expanded
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onContainsMouseChanged: root.elementHovered("calendar", containsMouse, "clock")
            onClicked: root.elementClicked("calendar")
        }
    }

    Component {
        id: calendarComponent
        CalendarPanel { onCloseRequested: PanelManager.close("calendar") }
    }
    Component {
        id: appsComponent
        AppsPanel { onCloseRequested: PanelManager.closeCurrent() }
    }

    // The taskbar editor's Add Shortcut branch: a sibling of the sections,
    // not a child (a section's body clips to its own bounds), placed off the
    // editor's live rect (BranchGeometry.place) -- in practice to its right.
    Item {
        id: editorRect
        readonly property real collapsedHeight: 0      // nothing below the editor
        readonly property real editorTop: activityIsland.panelItem ? activityIsland.panelItem.managerY : 0
        x: activityIsland.x + activityIsland.bodyX
        y: activityIsland.y + activityIsland.collapsedHeight + editorRect.editorTop
        width: activityIsland.bodyWidth
        height: Math.max(0, activityIsland.bodyHeight - editorRect.editorTop)
    }
    AddShortcutBranch {
        id: addBranch
        manager: activityIsland.panelItem ? activityIsland.panelItem.manager : null
        anchorIsland: editorRect
        screenWidth: root.width
        screenHeight: root.height
        edgeMargin: root.edgeMargin
    }

    // ---- right section: tray and the indicators, each opening its own
    // section of one panel (or the whole Dashboard) ----
    ShellIsland {
        id: statusIsland
        objectName: "statusIsland"
        x: barStrip.x + barStrip.width - width
        y: barStrip.y
        barLeft: barStrip.x
        barRight: barStrip.x + barStrip.width
        pinX: "right"
        expanded: root.statusOpen
        readonly property bool dashboard: PanelManager.isOpen("quicksettings")
        collapsedWidth: statusRow.implicitWidth + ShellSurface.pad * 2
        collapsedHeight: root.islandHeight
        // Wider than before (was 640) and paired with a much shorter
        // contentHeight (see QuickSettings.qml): the reference panels this
        // is modeled on are wide, short dashboards, not tall narrow ones --
        // trading width for height gets the aspect ratio closer without
        // cutting real content.
        expandedWidth: statusIsland.dashboard ? ShellSurface.panelWidthWide : Math.max(420, statusIsland.collapsedWidth)
        // The status row IS Quick Settings' header now -- see clockIsland's
        // identical comment just above.
        expandedHeight: root.clampToScreen(collapsedHeight + ((panelItem && panelItem.contentHeight) ? panelItem.contentHeight : 380))
        panel: statusIsland.dashboard ? quickSettingsComponent : statusPanelComponent
        onCloseRequested: PanelManager.closeCurrent()

        Row {
            id: statusRow
            anchors.centerIn: parent
            spacing: ShellSurface.pad

            Row {
                id: trayRow
                visible: SystemTray.items.values.length > 0
                anchors.verticalCenter: parent.verticalCenter
                spacing: Theme.padSm

                Repeater {
                    model: SystemTray.items
                    delegate: IconImage {
                        required property var modelData
                        anchors.verticalCenter: parent.verticalCenter
                        implicitSize: 18
                        source: modelData.icon
                        MouseArea {
                            anchors.fill: parent
                            acceptedButtons: Qt.LeftButton | Qt.RightButton
                            cursorShape: Qt.PointingHandCursor
                            onClicked: (mouse) => {
                                if (mouse.button === Qt.LeftButton) parent.modelData.activate();
                                else parent.modelData.secondaryActivate();
                            }
                        }
                    }
                }
            }

            Rectangle {
                visible: trayRow.visible
                width: 1
                height: ShellSurface.chip
                anchors.verticalCenter: parent.verticalCenter
                color: Theme.borderIdle
            }

            // One indicator per thing, each opening its own panel (see the
            // hover-intent block above). Real state only: an indicator for
            // something this machine doesn't have isn't shown.
            Row {
                id: indicatorRow
                anchors.verticalCenter: parent.verticalCenter
                spacing: 2
                // what is playing: only while there is a player at all
                BarIndicator {
                    name: "status:media"
                    accessibleName: "Media"
                    visible: MediaSession.player !== null
                    glyph: MediaSession.player && MediaSession.player.isPlaying ? "\u{f075a}" : "\u{f03e4}"
                    label: {
                        const p = MediaSession.player;
                        const t = p ? String(p.trackTitle || MediaSession.nameOf(p)) : "";
                        return t.length > 22 ? t.slice(0, 21) + "\u2026" : t;
                    }
                }
                // a running recording shows here, red, with its time
                BarIndicator {
                    name: "status:capture"
                    accessibleName: CaptureService.recording ? "Recording" : "Capture"
                    glyph: CaptureService.recording ? "\u{f044a}" : "\uf030"
                    tint: CaptureService.recording ? "#e5534b" : "transparent"
                    label: CaptureService.recording ? CaptureService.clock(CaptureService.elapsed) : ""
                    keepLabel: true
                }
                BarIndicator { name: "status:performance"; accessibleName: "Performance"; glyph: "\u{f04c5}" }
                BarIndicator {
                    name: "status:network"
                    accessibleName: "Network"
                    glyph: root.netKind === "ethernet" ? "\u{f0200}" : (root.netKind === "wifi" ? "\uf1eb" : "\u{f092e}")
                    dim: root.netKind === ""
                }
                BarIndicator { name: "status:bluetooth"; accessibleName: "Bluetooth"; glyph: "\uf294" }
                BarIndicator {
                    name: "status:audio"
                    accessibleName: "Sound"
                    glyph: root.muted ? "\u{f075f}" : "\uf028"
                    label: root.volumePercent + "%"
                }
                BarIndicator {
                    name: "status:power"
                    accessibleName: "Power"
                    glyph: BatteryService.available ? (BatteryService.charging ? "\u{f0084}" : "\u{f0079}") : "\uf011"
                    label: BatteryService.available ? BatteryService.percent + "%" : ""
                }
                BarIndicator {
                    name: "status:notifications"
                    accessibleName: "Notifications"
                    glyph: "\uf0f3"
                    badge: NotificationService.unread
                }
                BarIndicator { name: "quicksettings"; accessibleName: "Dashboard"; glyph: "\u{f0570}"; objectName: "barIndicator:dashboard" }
            }
        }
        onPointerInsideChanged: root.islandLeft("status", pointerInside)
    }

    // ---- overflow: the right section never runs into the clock ----
    // Estimated from parts that don't depend on it (each indicator a chip,
    // each reading about 7px a character): when the readings would not fit
    // between the clock and the bar's end, the indicators drop them and keep
    // their icons -- every one of them stays, nothing is silently dropped,
    // and each one's section still says everything.
    readonly property real _rightRoom: (barStrip.x + barStrip.width) - (clockIsland.x + clockIsland.width) - root.edgeMargin * 2
    readonly property real _statusIconsWidth: {
        let n = 0;
        for (let i = 0; i < indicatorRow.children.length; i++) if (indicatorRow.children[i].visible) n += 1;
        return n * (ShellSurface.chip + 2) + (trayRow.visible ? trayRow.implicitWidth + ShellSurface.pad * 2 : 0) + ShellSurface.pad * 2;
    }
    readonly property int _statusLabelChars: (MediaSession.player ? Math.min(22, String(MediaSession.player.trackTitle || "").length) : 0)
        + String(root.volumePercent).length + 1 + (BatteryService.available ? String(BatteryService.percent).length + 1 : 0)
    readonly property bool statusCompact: root._statusIconsWidth + root._statusLabelChars * 7 + 3 * Theme.padXs > root._rightRoom

    // what a hovered shortcut launches, shown in the title beside it
    property string hoveredApp: ""
    // The shortcuts show in the bar only when the left section still clears
    // the clock with them (a narrow screen keeps just the search pill; all of
    // them are in Applications anyway). Measured from parts that don't depend
    // on them: an icon is a chip wide, a text label (the editor's "Show
    // icons" off, or a shortcut set to text) about its length.
    readonly property var barShortcuts: Theme.data.bar_shortcuts === false ? []
        : Shortcuts.list.filter((s) => { const c = Shortcuts.commandOf(s.onClick).trim(); return c.length > 0 && c !== "wofi --show drun"; })
    function _shortcutWidth(s) {
        return (s.image || (s.glyph && s.glyph !== s.label)) ? ShellSurface.chip : ShellSurface.chip + String(s.label).length * 7;
    }
    readonly property real _leftRoom: (root.width - clockIsland.collapsedWidth) / 2 - root.edgeMargin * 3
    readonly property real _leftBase: ShellSurface.pad * 6 + searchPill.width + wsRow.implicitWidth + 2
                                      + (root.activeTitle.length > 0 ? 260 + 24 : 0)
    readonly property bool shortcutsFit: root._leftBase + root.barShortcuts.reduce((a, s) => a + root._shortcutWidth(s) + 2, 0) <= root._leftRoom
    function openApps() { root.elementClicked("apps"); }
    // A shortcut button in the left section: its icon glyph, its custom image
    // (the editor's "Custom image", at the editor's icon size up to what the
    // bar holds), or its label as text.
    component BarAppButton: Rectangle {
        id: app
        property string glyph: ""
        property string image: ""
        property string label: ""
        property string appKey: ""
        signal activated()
        Accessible.role: Accessible.Button
        Accessible.name: app.label
        readonly property bool running: Shortcuts.isRunning(app.appKey)
        readonly property bool focusedApp: app.running && Shortcuts.matches(root.activeAppId, app.appKey)
        readonly property bool textOnly: !app.image && (!app.glyph || app.glyph === app.label)
        property real lift: 0
        function hop() { hopAnim.restart(); }
        width: app.textOnly ? appText.implicitWidth + ShellSurface.pad : ShellSurface.chip
        height: ShellSurface.chip
        radius: ShellSurface.chipRadius
        color: appArea.containsMouse ? Theme.layer1Hover : "transparent"
        scale: Theme.pressScale(appArea.pressed, 0.88)
        Behavior on color { ColorAnimation { duration: Theme.durationFast } }
        Behavior on scale { NumberAnimation { duration: Theme.durationSpringFast; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveSpringFast } }
        SequentialAnimation {
            id: hopAnim
            NumberAnimation { target: app; property: "lift"; to: -5; duration: Theme.reduceMotion ? 0 : 90; easing.type: Easing.OutQuad }
            NumberAnimation { target: app; property: "lift"; to: 0; duration: Theme.durationSpring; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveSpringFast }
        }
        Text {
            id: appText
            visible: !appImage.visible
            anchors.centerIn: parent
            anchors.verticalCenterOffset: app.lift - (app.running ? 1 : 0)
            text: app.textOnly ? app.label : app.glyph
            color: Theme.textActive
            font.family: app.textOnly ? Theme.fontFamily : Theme.iconFamily
            font.pixelSize: app.textOnly ? Theme.fontSizeSmaller : Theme.fontSizeNormal
        }
        Image {
            id: appImage
            visible: app.image.length > 0 && status === Image.Ready
            anchors.centerIn: parent
            anchors.verticalCenterOffset: app.lift - (app.running ? 1 : 0)
            readonly property real side: Math.min(ShellSurface.chip - 4, Shortcuts.iconSize)
            width: side; height: side
            sourceSize: Qt.size(side * 2, side * 2)
            source: app.image ? "file://" + app.image : ""
            fillMode: Image.PreserveAspectFit
            asynchronous: true
        }
        Rectangle {
            objectName: "barRunning"
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.bottom: parent.bottom; anchors.bottomMargin: 1
            height: 2; radius: 1
            width: app.focusedApp ? 10 : 3
            color: app.focusedApp ? Theme.accent : Theme.textActive
            opacity: app.running ? (app.focusedApp ? 1 : 0.55) : 0
            Behavior on width { NumberAnimation { duration: Theme.durationSpringFast; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveSpringFast } }
            Behavior on opacity { NumberAnimation { duration: Theme.durationFast } }
        }
        MouseArea {
            id: appArea
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onContainsMouseChanged: {
                if (containsMouse) root.hoveredApp = app.label;
                else if (root.hoveredApp === app.label) root.hoveredApp = "";
            }
            onClicked: app.activated()
        }
    }

    // A bar element: an icon (and a short reading), a soft pill under the
    // pointer and while its own panel is open.
    component BarIndicator: Rectangle {
        id: ind
        property string name: ""
        property string glyph: ""
        property string label: ""
        property bool dim: false
        // what it is, for anything that reads the bar aloud (each indicator's
        // section also names itself in its heading)
        property string accessibleName: ""
        Accessible.role: Accessible.Button
        Accessible.name: ind.accessibleName
        // a count, shown as a small accent badge (unread notifications)
        property int badge: 0
        // a state colour of its own (a recording in progress)
        property color tint: "transparent"
        // short of room (statusCompact), indicators show their icon alone,
        // except one whose reading is the point (a recording's time)
        property bool keepLabel: false
        readonly property bool open: PanelManager.current === ind.name
        objectName: "barIndicator:" + ind.name.replace("status:", "")
        height: ShellSurface.chip
        width: visible ? indRow.implicitWidth + ShellSurface.pad : 0
        radius: ShellSurface.chipRadius
        color: ind.open ? Theme.mix(Theme.layer1, Theme.accent, 0.22)
             : (ind.tint.a > 0 ? Qt.rgba(ind.tint.r, ind.tint.g, ind.tint.b, 0.22) : (indArea.containsMouse ? Theme.layer1Hover : "transparent"))
        Behavior on color { ColorAnimation { duration: Theme.durationFast; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveStandard } }
        Row {
            id: indRow
            anchors.centerIn: parent
            spacing: Theme.padXs
            Text {
                anchors.verticalCenter: parent.verticalCenter
                text: ind.glyph
                color: ind.tint.a > 0 ? ind.tint : (ind.open ? Theme.accentText : Theme.textActive)
                opacity: ind.dim ? 0.45 : 1
                font.family: Theme.iconFamily; font.pixelSize: Theme.fontSizeSmall
            }
            Text {
                objectName: "barIndicatorLabel"
                visible: ind.label.length > 0 && (ind.keepLabel || !root.statusCompact)
                anchors.verticalCenter: parent.verticalCenter
                text: ind.label
                color: Theme.textActive
                font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSmaller
                font.features: { "tnum": 1 }
            }
        }
        Rectangle {
            objectName: "barBadge"
            visible: ind.badge > 0
            anchors.right: parent.right; anchors.top: parent.top
            anchors.rightMargin: 1; anchors.topMargin: 1
            width: Math.max(13, badgeText.implicitWidth + 6); height: 13; radius: 6.5
            color: Theme.accent
            Text {
                id: badgeText
                anchors.centerIn: parent
                text: ind.badge > 9 ? "9+" : String(ind.badge)
                color: Theme.panelTone
                font.family: Theme.fontFamily; font.pixelSize: 9; font.weight: Font.Bold
            }
        }
        MouseArea {
            id: indArea
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onContainsMouseChanged: root.elementHovered(ind.name, containsMouse, "status")
            onClicked: root.elementClicked(ind.name)
        }
    }

    // a section's "open the Dashboard on this tab" (Performance's graphs)
    property string pendingDashboardTab: ""
    Component {
        id: quickSettingsComponent
        QuickSettings {
            onCloseRequested: PanelManager.close("quicksettings")
            Component.onCompleted: if (root.pendingDashboardTab) { currentTab = root.pendingDashboardTab; root.pendingDashboardTab = ""; }
        }
    }
    Component {
        id: statusPanelComponent
        StatusPanel {
            section: PanelManager.current.indexOf("status:") === 0 ? PanelManager.current.slice(7) : section
            onCloseRequested: PanelManager.closeCurrent()
            onDashboardRequested: (tab) => { root.pendingDashboardTab = tab; PanelManager.open("quicksettings", "click"); }
        }
    }
}
