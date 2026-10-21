import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Widgets
import Quickshell.Wayland
import Quickshell.Hyprland
import Quickshell.Services.SystemTray
import Quickshell.Services.Pipewire

// The shell's top edge -- three islands with an actual hierarchy, not a bar
// and not five equal-weight nubs either.
//
// What this replaces, twice over: first a full-width translucent rectangle
// (what Waybar looks like), then a "fixed" version of that which was
// technically five separate floating islands but every one of them was a
// tiny, equally-weighted nub with a big empty gap to its neighbor -- workspace
// dots alone, a clock alone, tray icons alone, a volume readout alone. Nothing
// was substantial, so nothing read as a deliberate shell surface; it read as
// "many small widgets happened to be placed near each other."
//
// The fix is composition, not size: decide what actually belongs together and
// bundle it into ONE island, so the islands that remain have real reasons to
// be as wide as they are and real reasons to be separate from each other.
//   - LEFT, substantial: workspaces + the focused window's icon/title. Two
//     pieces of genuinely related "where am I / what am I doing" information
//     sharing one capsule with an internal divider. This is the shell's
//     anchor -- the one island a viewer's eye should land on first -- and it
//     summons no panel; not everything needs to expand.
//   - CENTRE, medium: the clock alone, deliberately not bundled with anything
//     else. It is a morph trigger (becomes the Calendar); diluting it with
//     unrelated siblings would blur what is about to visibly become a panel.
//   - RIGHT, compact: tray icons + the status readout bundled into ONE
//     island (previously two separate islands sitting side by side for no
//     reason other than history). Becomes Quick Settings.
//
// The window is full-height and almost entirely transparent, with an explicit
// exclusiveZone reserving only the strip the islands occupy, and an input
// mask limiting clicks to the islands themselves so the desktop below stays
// clickable. It is full-height because the panels live in here too: the
// clock IS the calendar and the status island IS Quick Settings (see
// ShellIsland.qml) -- a panel in its own window could only ever be positioned
// under its control; sharing this item tree is what lets one surface morph.
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
    // Only grab keys while something is actually open, so the bar doesn't hold
    // focus away from the focused application the rest of the time.
    focusable: PanelManager.current !== "" && PanelManager.openedBy === "click"
    Shortcut { objectName: "topBarEscape"; sequence: "Escape"; enabled: root.focusable; onActivated: PanelManager.closeCurrent() }

    // Whether Quick Settings' Wifi-password dialog is open -- a real,
    // separate top-level window (FloatingWindow) that this window's own
    // full-screen dismiss catcher below has no way to see. Without this,
    // clicking into its password field to type was being caught as "a
    // click outside every island" and closing Quick Settings (destroying
    // the dialog with it) instead of ever reaching the field -- same
    // architectural gap, and same fix, as Dock.qml's taskbarModalOpen.
    readonly property bool statusModalOpen: statusIsland.panelItem && statusIsland.panelItem.wifiDialogOpen

    // Whether one of THIS window's own panels (not Taskbar, that's Dock's)
    // is open -- the click-outside-to-dismiss region below only ever
    // expands while this is true.
    readonly property bool statusOpen: PanelManager.isOpen("quicksettings") || PanelManager.current.indexOf("status:") === 0
    readonly property bool anyIslandOpen: (PanelManager.isOpen("calendar") || root.statusOpen)
                                           && !root.statusModalOpen

    // Without this the transparent full-screen surface would swallow every
    // click on the desktop. The mask follows the islands' live geometry, so it
    // grows with them as they expand into panels -- no manual bookkeeping.
    // The 4th region is click-outside-to-dismiss: while a panel here is
    // open, it extends input to the whole window so a click that misses
    // every island reaches `dismissArea` below and closes it; the instant
    // anyIslandOpen goes false it collapses back to 0x0, same as OSD.qml's
    // fix -- there is no state in which this can sit there as a permanent
    // invisible click-blocker.
    mask: Region {
        Region { item: root.activityYields ? null : activityIsland }
        Region { item: root.clockYields ? null : clockIsland }
        Region { item: root.statusYields ? null : statusIsland }
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
        onClicked: PanelManager.closeCurrent()
    }

    // ---- an island yields while another island's panel needs its space ----
    // All three islands share one row, and two of them grow into panels. On
    // a narrow screen an open panel claims space a collapsed island still
    // occupies: Quick Settings (panelWidthWide, growing leftward from the
    // right edge) runs straight over the clock at 1366px, and narrower
    // screens give the same conflict between other pairs. Rather than
    // shrinking the panel until it no longer works, the covered island
    // yields: it fades out, stops taking clicks and leaves this window's
    // input mask -- for exactly as long as the panel would cover it (its
    // final rect once it is opening) or still does (its live rect while it
    // retracts), so it reappears only once there is room again. How faded
    // it is follows the panel's live edge, not a timer: opacity is the
    // island's remaining clearance from that edge over FADE px, so it is
    // exactly 0 at contact and comes back as the panel pulls away, locked
    // to the panel's own animation (a time-based fade lost the race to a
    // fast-growing panel on a narrow screen and was still faintly visible
    // under its edge). Quick Settings already shows the time and date
    // itself. Horizontal spans only: every island sits on one row.
    function _span(x, w) { return [x, x + w]; }
    function _overlaps(a, b) { return a[0] < b[1] + root.edgeMargin && b[0] < a[1] + root.edgeMargin; }
    function _covered(span, island, finalSpan) {
        const growing = island.expanded && root._overlaps(span, finalSpan);
        const stillWide = island.width > island.collapsedWidth + 0.5 && root._overlaps(span, root._span(island.x, island.width));
        return growing || stillWide;
    }
    readonly property real _fadeSpan: 48
    function _fade(span, island, finalSpan) {
        if (!root._covered(span, island, finalSpan)) return 1;
        const live = root._span(island.x, island.width);
        const clearance = Math.max(span[0] - live[1], live[0] - span[1]) - root.edgeMargin;
        return Math.max(0, Math.min(1, clearance / root._fadeSpan));
    }
    readonly property var _activityRest: root._span(root.edgeMargin, activityIsland.collapsedWidth)
    readonly property var _clockRest: root._span((root.width - clockIsland.collapsedWidth) / 2, clockIsland.collapsedWidth)
    readonly property var _statusRest: root._span(root.width - root.edgeMargin - statusIsland.collapsedWidth, statusIsland.collapsedWidth)
    readonly property var _calendarFinal: root._span((root.width - clockIsland.expandedWidth) / 2, clockIsland.expandedWidth)
    readonly property var _quickSettingsFinal: root._span(root.width - root.edgeMargin - statusIsland.expandedWidth, statusIsland.expandedWidth)
    readonly property bool activityYields: root._covered(root._activityRest, statusIsland, root._quickSettingsFinal)
                                           || root._covered(root._activityRest, clockIsland, root._calendarFinal)
    readonly property bool clockYields: root._covered(root._clockRest, statusIsland, root._quickSettingsFinal)
    readonly property bool statusYields: root._covered(root._statusRest, clockIsland, root._calendarFinal)
    readonly property real activityOpacity: Math.min(root._fade(root._activityRest, statusIsland, root._quickSettingsFinal),
                                                     root._fade(root._activityRest, clockIsland, root._calendarFinal))
    readonly property real clockOpacity: root._fade(root._clockRest, statusIsland, root._quickSettingsFinal)
    readonly property real statusOpacity: root._fade(root._statusRest, clockIsland, root._calendarFinal)

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
    Timer {
        id: hoverOpenTimer
        interval: 150
        onTriggered: if (root._hoverWant && PanelManager.current === "") PanelManager.open(root._hoverWant, "hover")
    }
    function elementHovered(name, on, island) {
        if (on) {
            const cur = PanelManager.current;
            const sameIsland = (island === "status" && root.statusOpen) || (island === "clock" && cur === "calendar");
            if (sameIsland) {
                hoverOpenTimer.stop();
                root._hoverWant = "";
                if (cur !== name && island === "status") PanelManager.open(name, PanelManager.openedBy);
                return;
            }
            if (!root.hoverOpens || cur !== "") return;
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
        }
    }
    // Closing a panel shifts the row (its close button goes), which can slide
    // an element under a pointer that never moved -- that is not a hover, and
    // reopening there made a panel come straight back after its close button
    // was clicked. So a hover opens nothing until the pointer has moved since
    // the last close; an element it is already resting on opens once it does.
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
            if (root._hoverWant && PanelManager.current === "" && !hoverOpenTimer.running) hoverOpenTimer.restart();
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
        // See `activityYields` above.
        opacity: root.activityOpacity
        enabled: !root.activityYields
        property string appGlyph: ""
        x: root.edgeMargin
        y: root.edgeMargin
        pinX: "left"
        collapsedWidth: activityRow.implicitWidth + ShellSurface.pad * 2
        collapsedHeight: root.islandHeight
        elevation: 2

        Row {
            id: activityRow
            anchors.centerIn: parent
            spacing: ShellSurface.pad

            // The launcher and the saved shortcuts (the same list as the
            // dock: Shortcuts), each with its open/focused mark; hovering one
            // names it in the title beside. theme.json "bar_shortcuts": false
            // leaves only the launcher.
            Row {
                id: barApps
                objectName: "barApps"
                anchors.verticalCenter: parent.verticalCenter
                spacing: 2
                BarAppButton {
                    objectName: "barLauncher"
                    glyph: "\uf135"
                    label: "Applications"
                    onActivated: root.launcherRequested()
                }
                Repeater {
                    // (the app-launcher shortcut is the launcher button above;
                    // one with no command would do nothing)
                    model: root.shortcutsFit ? root.barShortcuts : []
                    delegate: BarAppButton {
                        required property var modelData
                        objectName: "barShortcut:" + modelData.label
                        glyph: modelData.glyph
                        label: modelData.label
                        appKey: Shortcuts.appKeyOf(modelData.onClick)
                        onActivated: {
                            const what = Shortcuts.launch(modelData.onClick, "bar");
                            if (what === "launcher") root.launcherRequested();
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
                        width: active ? 22 : 8
                        height: 8
                        radius: Theme.roundingFull
                        anchors.verticalCenter: parent.verticalCenter
                        color: active ? Theme.accent : (wsArea.containsMouse ? Theme.layer2Hover : Theme.borderIdle)

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
                    color: root.hoveredApp.length > 0 ? Theme.accent : Theme.text
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

    // ---- centre island: the clock, which IS the calendar ----
    ShellIsland {
        id: clockIsland
        objectName: "clockIsland"
        // See `clockYields` above.
        opacity: root.clockOpacity
        enabled: !root.clockYields
        anchors.horizontalCenter: parent.horizontalCenter
        y: root.edgeMargin
        pinX: "center"
        pinY: "top"
        expanded: PanelManager.isOpen("calendar")
        collapsedWidth: clockText.implicitWidth + ShellSurface.pad * 2
        collapsedHeight: root.islandHeight
        expandedWidth: ShellSurface.panelWidthCompact
        // The clock itself IS the calendar's header now (see ShellIsland.qml),
        // occupying `collapsedHeight` of the final surface -- so the total
        // is that plus however tall the calendar's own body (nav row + week
        // grid) needs to be, not the panel's self-report taken as the whole.
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

    // ---- right island: tray + status, bundled -- which IS Quick Settings.
    // Previously two separate islands sitting side by side (trayIsland and
    // statusIsland) for no reason other than history: both are "ambient
    // system state", neither substantial alone, and there was nothing a
    // divider between them couldn't already say more honestly than a gap of
    // bare wallpaper. ----
    ShellIsland {
        id: statusIsland
        objectName: "statusIsland"
        // See `statusYields` above.
        opacity: root.statusOpacity
        enabled: !root.statusYields
        anchors.right: parent.right
        anchors.rightMargin: root.edgeMargin
        y: root.edgeMargin
        pinX: "right"
        pinY: "top"
        expanded: root.statusOpen
        readonly property bool dashboard: PanelManager.isOpen("quicksettings")
        // the indicators are hover targets: keep them still under the pointer
        closeButtonShown: statusIsland.dashboard
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
                BarIndicator {
                    name: "status:network"
                    glyph: root.netKind === "ethernet" ? "\u{f0200}" : (root.netKind === "wifi" ? "\uf1eb" : "\u{f092e}")
                    dim: root.netKind === ""
                }
                BarIndicator { name: "status:bluetooth"; glyph: "\uf294" }
                BarIndicator {
                    name: "status:audio"
                    glyph: root.muted ? "\u{f075f}" : "\uf028"
                    label: root.volumePercent + "%"
                }
                BarIndicator {
                    name: "status:power"
                    glyph: BatteryService.available ? (BatteryService.charging ? "\u{f0084}" : "\u{f0079}") : "\uf011"
                    label: BatteryService.available ? BatteryService.percent + "%" : ""
                }
                BarIndicator { name: "status:notifications"; glyph: "\uf0f3" }
                BarIndicator { name: "quicksettings"; glyph: "\u{f0570}"; objectName: "barIndicator:dashboard" }
            }
        }
        onPointerInsideChanged: root.islandLeft("status", pointerInside)
    }

    // what a hovered shortcut launches, shown in the title beside it
    property string hoveredApp: ""
    // The shortcuts show in the bar only when the left island still clears
    // the clock with them (a narrow screen keeps just the launcher; the dock
    // has them all anyway). Measured from parts that don't depend on them.
    readonly property var barShortcuts: Theme.data.bar_shortcuts === false ? []
        : Shortcuts.list.filter((s) => { const c = Shortcuts.commandOf(s.onClick).trim(); return c.length > 0 && c !== "wofi --show drun"; })
    readonly property real _leftRoom: (root.width - clockIsland.collapsedWidth) / 2 - root.edgeMargin * 3
    readonly property real _leftBase: ShellSurface.pad * 6 + ShellSurface.chip + wsRow.implicitWidth + 2
                                      + (root.activeTitle.length > 0 ? 260 + 24 : 0)
    readonly property bool shortcutsFit: root._leftBase + root.barShortcuts.length * (ShellSurface.chip + 2) <= root._leftRoom
    // A launcher or shortcut button in the left island.
    component BarAppButton: Rectangle {
        id: app
        property string glyph: ""
        property string label: ""
        property string appKey: ""
        signal activated()
        readonly property bool running: Shortcuts.isRunning(app.appKey)
        readonly property bool focusedApp: app.running && Shortcuts.matches(root.activeAppId, app.appKey)
        property real lift: 0
        function hop() { hopAnim.restart(); }
        width: ShellSurface.chip; height: ShellSurface.chip
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
            anchors.centerIn: parent
            anchors.verticalCenterOffset: app.lift - (app.running ? 1 : 0)
            text: app.glyph
            color: Theme.textActive
            font.family: Theme.iconFamily; font.pixelSize: Theme.fontSizeNormal
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
        readonly property bool open: PanelManager.current === ind.name
        objectName: "barIndicator:" + ind.name.replace("status:", "")
        height: ShellSurface.chip
        width: indRow.implicitWidth + ShellSurface.pad
        radius: ShellSurface.chipRadius
        color: ind.open ? Theme.mix(Theme.layer1, Theme.accent, 0.22) : (indArea.containsMouse ? Theme.layer1Hover : "transparent")
        Behavior on color { ColorAnimation { duration: Theme.durationFast; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveStandard } }
        Row {
            id: indRow
            anchors.centerIn: parent
            spacing: Theme.padXs
            Text {
                anchors.verticalCenter: parent.verticalCenter
                text: ind.glyph
                color: ind.open ? Theme.accent : Theme.textActive
                opacity: ind.dim ? 0.45 : 1
                font.family: Theme.iconFamily; font.pixelSize: Theme.fontSizeSmall
            }
            Text {
                visible: ind.label.length > 0
                anchors.verticalCenter: parent.verticalCenter
                text: ind.label
                color: Theme.textActive
                font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSmaller
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

    Component {
        id: quickSettingsComponent
        QuickSettings { onCloseRequested: PanelManager.close("quicksettings") }
    }
    Component {
        id: statusPanelComponent
        StatusPanel {
            section: PanelManager.current.indexOf("status:") === 0 ? PanelManager.current.slice(7) : section
            onCloseRequested: PanelManager.closeCurrent()
            onDashboardRequested: PanelManager.open("quicksettings", "click")
        }
    }
}
