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
    focusable: PanelManager.current !== ""
    Shortcut { sequence: "Escape"; enabled: root.focusable; onActivated: PanelManager.closeCurrent() }

    // Whether one of THIS window's own panels (not Taskbar, that's Dock's)
    // is open -- the click-outside-to-dismiss region below only ever
    // expands while this is true.
    readonly property bool anyIslandOpen: PanelManager.isOpen("calendar") || PanelManager.isOpen("quicksettings")

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
        Region { item: activityIsland }
        Region { item: clockIsland }
        Region { item: statusIsland }
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

    Binding { target: ShellSurface; property: "topEdgeHeight"; value: root.exclusiveZone }
    Binding { target: ShellSurface; property: "screenHeight"; value: root.screen ? root.screen.height : 1080 }

    // ---- workspaces (native Hyprland IPC -- no hyprctl subprocess) ----
    readonly property var workspaceList: {
        const list = Hyprland.workspaces.values.slice();
        list.sort((a, b) => a.id - b.id);
        return list;
    }

    // ---- audio, for the status cluster ----
    PwObjectTracker { objects: [Pipewire.defaultAudioSink] }
    readonly property var sink: Pipewire.defaultAudioSink
    readonly property int volumePercent: (sink && sink.audio) ? Math.round(sink.audio.volume * 100) : 0
    readonly property bool muted: (sink && sink.audio) ? sink.audio.muted : false

    // ---- left island: the shell's anchor. Workspaces + focused window,
    // bundled -- see the file header for why this is one island and not two.
    // Summons no panel; it exists to be substantial, not to expand. ----
    // NOT Quickshell's own Hyprland.activeToplevel, and NOT each
    // HyprlandToplevel's own `activated` flag either -- both turned out to be
    // a real gap in this Quickshell version's Hyprland module: neither is
    // backed by Hyprland's initial state on connect (unlike `workspaces` and
    // `toplevels`, which populate immediately and correctly), only by live
    // "activewindow" events from that point on. Confirmed two different ways:
    // toplevelsCount was correctly 4 immediately after connecting while
    // activeToplevel stayed null throughout, and separately every toplevel's
    // own `activated` read false even while `hyprctl activewindow -j`
    // (queried completely independently of Quickshell) correctly reported
    // the real focused window. A session that never triggers a fresh
    // Hyprland focus event after this shell starts would otherwise show no
    // focused window here indefinitely.
    //
    // The reliable fix is the one already used elsewhere in this codebase for
    // anything Quickshell's own bindings don't cover (CPU/mem via /proc, disk
    // via `df`): a native subprocess, polled -- here `hyprctl activewindow
    // -j`, which is always correct because it asks Hyprland fresh every time
    // rather than trusting a change notification that might never come.
    property string activeAppId: ""
    property string activeTitle: ""

    Process {
        id: activeWindowProc
        command: ["hyprctl", "activewindow", "-j"]
        stdout: StdioCollector {
            onStreamFinished: {
                try {
                    const w = JSON.parse(this.text);
                    // Title before appId: onActiveAppIdChanged (below) reads
                    // root.activeTitle synchronously the moment appId is
                    // assigned, so setting title second meant every icon
                    // lookup ran one step behind, using whatever title had
                    // been set on the PREVIOUS window.
                    root.activeTitle = w.title || "";
                    root.activeAppId = w.class || "";
                } catch (e) {
                    // No focused window (e.g. an empty workspace) prints
                    // "{}" or an error string, not valid single-window JSON.
                    root.activeAppId = "";
                    root.activeTitle = "";
                }
            }
        }
    }
    Timer {
        interval: 1500; running: true; repeat: true; triggeredOnStart: true
        onTriggered: activeWindowProc.running = true
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

            Row {
                id: wsRow
                anchors.verticalCenter: parent.verticalCenter
                spacing: Theme.padXs

                Repeater {
                    model: root.workspaceList
                    delegate: Rectangle {
                        id: wsPill
                        required property var modelData
                        readonly property bool active: modelData.focused
                        width: active ? 22 : 8
                        height: 8
                        radius: Theme.roundingFull
                        anchors.verticalCenter: parent.verticalCenter
                        color: active ? Theme.accent : (wsArea.containsMouse ? Theme.layer2Hover : Theme.borderIdle)

                        Behavior on width { NumberAnimation { duration: Theme.durationFast; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveExpressiveFast } }
                        Behavior on color { ColorAnimation { duration: Theme.durationFast; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveStandard } }

                        MouseArea {
                            id: wsArea
                            anchors.fill: parent
                            anchors.margins: -4
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: wsPill.modelData.activate()
                        }
                    }
                }
            }

            // The divider that makes this read as two related things sharing
            // one capsule, not one thing -- present only when there is a
            // second thing to divide from (a focused window to show).
            Rectangle {
                visible: root.activeTitle.length > 0
                width: 1
                height: ShellSurface.chip
                anchors.verticalCenter: parent.verticalCenter
                color: Theme.borderIdle
            }

            Row {
                visible: root.activeTitle.length > 0
                anchors.verticalCenter: parent.verticalCenter
                spacing: Theme.padXs
                Text {
                    text: activityIsland.appGlyph
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSizeNormal
                    color: Theme.textActive
                    anchors.verticalCenter: parent.verticalCenter
                }
                Text {
                    text: root.activeTitle
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSizeSmaller
                    color: Theme.text
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
            font.weight: Font.DemiBold
            font.pixelSize: Theme.fontSizeNormal
        }
        Timer {
            interval: 1000; running: true; repeat: true; triggeredOnStart: true
            onTriggered: clockText.text = Qt.formatDateTime(new Date(), "HH:mm   MMM d")
        }
        MouseArea {
            anchors.fill: parent
            enabled: !clockIsland.expanded
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: root.calendarRequested()
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
        anchors.right: parent.right
        anchors.rightMargin: root.edgeMargin
        y: root.edgeMargin
        pinX: "right"
        pinY: "top"
        expanded: PanelManager.isOpen("quicksettings")
        collapsedWidth: statusRow.implicitWidth + ShellSurface.pad * 2
        collapsedHeight: root.islandHeight
        // Wider than before (was 640) and paired with a much shorter
        // contentHeight (see QuickSettings.qml): the reference panels this
        // is modeled on are wide, short dashboards, not tall narrow ones --
        // trading width for height gets the aspect ratio closer without
        // cutting real content.
        expandedWidth: ShellSurface.panelWidthWide
        // The status row IS Quick Settings' header now -- see clockIsland's
        // identical comment just above.
        expandedHeight: root.clampToScreen(collapsedHeight + ((panelItem && panelItem.contentHeight) ? panelItem.contentHeight : 380))
        panel: quickSettingsComponent
        onCloseRequested: PanelManager.close("quicksettings")

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

            // The shell's second material level. The reference bar carries its
            // readouts in small filled pills INSIDE the capsule rather than as
            // bare text sitting directly on it, and that nesting is most of
            // what makes it read as designed chrome instead of a label
            // floating on a slab. One capsule, one chip inside it, same
            // corner language at both levels (chipRadius is chip/2, exactly
            // as radius is unit/2 a level up).
            Rectangle {
                height: ShellSurface.chip
                width: volRow.implicitWidth + ShellSurface.pad
                radius: ShellSurface.chipRadius
                color: Theme.layer1
                anchors.verticalCenter: parent.verticalCenter

                Row {
                    id: volRow
                    anchors.centerIn: parent
                    spacing: Theme.padXs
                    Text {
                        text: root.muted ? "" : ""
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSizeSmaller
                        color: Theme.text
                        anchors.verticalCenter: parent.verticalCenter
                    }
                    Text {
                        text: root.volumePercent + "%"
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSizeSmaller
                        color: Theme.textActive
                        anchors.verticalCenter: parent.verticalCenter
                    }
                }
            }
        }
        MouseArea {
            anchors.fill: parent
            enabled: !statusIsland.expanded
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: root.quickSettingsRequested()
        }
    }


    Component {
        id: quickSettingsComponent
        QuickSettings { onCloseRequested: PanelManager.close("quicksettings") }
    }
}
