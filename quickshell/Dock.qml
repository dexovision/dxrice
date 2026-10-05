import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland

// The shell's bottom edge -- one island, not a bar.
//
// Earlier this had a small "edit" tile inside the dock pill try to fuse into
// the taskbar editor on its own, growing upward from a 40x40 button into a
// 480-wide panel positioned above the dock. Numerically its origin rect
// matched the button; visually it was a small square ballooning into a much
// wider floating rectangle with an obvious overhang past the dock's own
// edges -- exactly the "not connected" look Quick Settings/Calendar had
// before those became ShellIslands too.
//
// The fix is the same one that fixed those: the surface that opens IS the
// surface that expands. Here that surface is the ENTIRE dock pill, not just
// the gear -- collapsed it is every shortcut icon plus the gear; expanded it
// is the Taskbar editor. It grows upward (pinY: "bottom") and symmetrically
// around its own centre (pinX: "center", matching how the dock is already
// centred on the screen), so widening past the collapsed dock's width reads
// as the same object spreading outward around its own middle, not a wider
// rectangle appearing off to one side.
PanelWindow {
    id: root

    signal taskbarRequested()

    // Same geometry system as the top bar (ShellSurface.qml): the dock slab
    // is one `unit` tall plus a gap above and below, and its icon tiles are
    // exactly `unit` -- so a dock icon and a bar capsule are the same size,
    // and both edges carry the same corner arc.
    readonly property real dockHeight: ShellSurface.dockUnit
    readonly property real edgeMargin: ShellSurface.gap

    // Same backstop as TopBar.qml's clampToScreen: this island sits
    // `edgeMargin` from the BOTTOM (its origin edge) and needs the same gap
    // free at the top, so nothing expanding from here may run off the top of
    // the screen regardless of what TaskbarManager.qml's own sizing computes.
    function clampToScreen(h) {
        return ShellSurface.clampToScreen(h, root.edgeMargin);
    }

    color: "transparent"
    anchors { bottom: true; left: true; right: true }
    implicitHeight: root.screen ? root.screen.height : 1080
    exclusionMode: ExclusionMode.Normal
    exclusiveZone: root.edgeMargin * 2 + root.dockHeight
    WlrLayershell.layer: WlrLayer.Top
    WlrLayershell.namespace: "dxrice-bar-dock"
    aboveWindows: true
    focusable: PanelManager.isOpen("taskbar")
    // Disabled while the Add-Shortcut branch is open: AddShortcutBranch.qml
    // owns its own Escape handler (closing just the branch, not the whole
    // taskbar), and two enabled Shortcut items racing for the same key
    // sequence is exactly the kind of ambiguity worth avoiding outright
    // rather than hoping Qt resolves it the way this file wants.
    Shortcut { sequence: "Escape"; enabled: root.focusable && !root.taskbarModalOpen; onActivated: PanelManager.close("taskbar") }

    // Whether TaskbarManager's own Add-Shortcut branch is open. Unlike the
    // FloatingWindow this used to be, the branch now lives inside THIS
    // window (see addBranch below) -- but the click-outside-to-dismiss
    // region below still has to suspend itself while it's open, for the
    // same reason as before: a click meant for the branch's search box or
    // text fields must never be caught by this window's own full-screen
    // dismiss region first.
    readonly property bool taskbarModalOpen: dockIsland.panelItem && dockIsland.panelItem.addPanelOpen

    // Same click-outside-to-dismiss pattern as TopBar.qml: the input region
    // only ever extends past dockIsland while Taskbar is actually open, and
    // collapses back to nothing the instant it closes.
    mask: Region {
        Region { item: dockIsland }
        Region { item: addBranch }
        Region {
            x: 0; y: 0
            width: (PanelManager.isOpen("taskbar") && !root.taskbarModalOpen) ? root.width : 0
            height: (PanelManager.isOpen("taskbar") && !root.taskbarModalOpen) ? root.height : 0
        }
    }

    MouseArea {
        id: dismissArea
        anchors.fill: parent
        enabled: PanelManager.isOpen("taskbar") && !root.taskbarModalOpen
        onClicked: PanelManager.close("taskbar")
    }

    Binding { target: ShellSurface; property: "bottomEdgeHeight"; value: root.exclusiveZone }

    readonly property string configPath: Xdg.configHome + "/waybar/config-dock"
    property var shortcuts: []

    FileView {
        id: configFile
        path: root.configPath
        watchChanges: true
        onFileChanged: this.reload()
        onLoaded: root.reloadShortcuts()
    }

    function reloadShortcuts() {
        try {
            const cfg = JSON.parse(configFile.text());
            const ids = cfg["modules-left"] || [];
            root.shortcuts = ids.map((id) => ({
                id,
                label: cfg[id] ? (cfg[id]["tooltip-format"] || cfg[id]["dxrice_label"] || id) : id,
                glyph: cfg[id] ? cfg[id]["format"] || "" : "",
                onClick: cfg[id] ? cfg[id]["on-click"] || "" : "",
            }));
        } catch (e) {
            console.warn("Dock: could not read", root.configPath, e);
        }
    }

    ShellIsland {
        id: dockIsland
        anchors.horizontalCenter: parent.horizontalCenter
        y: parent.height - root.edgeMargin - height
        pinX: "center"
        pinY: "bottom"
        expanded: PanelManager.isOpen("taskbar")
        collapsedWidth: dockRow.implicitWidth + ShellSurface.pad * 2
        collapsedHeight: root.dockHeight
        // Widened again (was 460, before that 420) specifically to let
        // TaskbarManager.qml put its Options and Shortcuts cards side by
        // side instead of stacked -- see that file's own comment on the Row
        // wrapping both cards. ShellSurface.panelWidthMedium lands in the
        // same size family as Quick Settings' panelWidthWide, so the two
        // dashboards read as siblings rather than one being noticeably
        // narrower than the other -- now a named relationship instead of
        // two bare numbers that happened to be close.
        expandedWidth: ShellSurface.panelWidthMedium
        // The dock's own shortcut row IS Taskbar's header now, staying put at
        // the BOTTOM (this island's origin edge) instead of fading away --
        // see ShellIsland.qml. Total height is that plus whatever the
        // editor's own body (options + shortcut list) needs.
        expandedHeight: root.clampToScreen(collapsedHeight + ((panelItem && panelItem.contentHeight) ? panelItem.contentHeight : 460))
        elevation: 2
        panel: taskbarComponent
        onCloseRequested: PanelManager.close("taskbar")

        Row {
            id: dockRow
            anchors.centerIn: parent
            spacing: Theme.padXs

            Repeater {
                model: root.shortcuts
                delegate: Rectangle {
                    id: shortcutTile
                    required property var modelData
                    // A single icon glyph is narrow enough that this just
                    // reduces to the same fixed square tile as before; a
                    // text-label shortcut (a full app name, e.g. "Visual
                    // Studio Code" rather than one glyph) grows the tile to
                    // fit its own rendered width instead of forcing it into
                    // that same fixed box, which is what was overlapping
                    // neighboring tiles -- this reacts to whatever the label
                    // actually is, so it holds for any name length or
                    // shortcut count without a hardcoded case for "text
                    // mode" specifically.
                    width: Math.max(ShellSurface.dockTile, tileLabel.implicitWidth + Theme.padMd * 2)
                    height: ShellSurface.dockTile
                    radius: ShellSurface.chipRadius
                    color: tileArea.containsMouse ? Theme.layer1Hover : "transparent"
                    scale: tileArea.pressed ? 0.9 : 1.0

                    Behavior on color { ColorAnimation { duration: Theme.durationFast } }
                    Behavior on scale { NumberAnimation { duration: Theme.durationFast; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveExpressiveFast } }

                    Text {
                        id: tileLabel
                        anchors.centerIn: parent
                        text: shortcutTile.modelData.glyph
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSizeLarge
                        color: Theme.textActive
                    }

                    MouseArea {
                        id: tileArea
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: {
                            // Must mirror TaskbarManager.unwrapShellCmd's
                            // un-escaping exactly -- this regex extracts
                            // the STILL '\''-escaped inner command (see
                            // TaskbarManager.wrapShellCmd for why it's
                            // escaped that way), and execDetached's argv
                            // form means sh -c here parses it as a fresh
                            // script, not as text nested inside another
                            // quote -- the escaping must be undone first or
                            // every shortcut containing a quote throws a
                            // shell syntax error instead of running.
                            const m = /^sh -c '(.*) >\/dev\/null 2>&1 &'$/.exec(shortcutTile.modelData.onClick);
                            const cmd = m ? m[1].replace(/'\\''/g, "'") : shortcutTile.modelData.onClick;
                            if (cmd) Quickshell.execDetached(["sh", "-c", cmd]);
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

            IconButton {
                // Nerd Font cog (U+F013) -- byte-verified after this exact
                // glyph silently came out as an empty string once already
                // this session (invisible in the tool transcript either
                // way, so the loss went unnoticed until a hexdump caught it).
                glyph: ""
                size: ShellSurface.dockTile
                anchors.verticalCenter: parent.verticalCenter
                onClicked: root.taskbarRequested()
            }
        }
    }

    Component {
        id: taskbarComponent
        TaskbarManager { onCloseRequested: PanelManager.close("taskbar") }
    }

    // The Add-Shortcut branch -- a sibling of dockIsland in THIS window,
    // not a child of it. dockIsland's own surface clips to its growing
    // bounds (ShellIsland.qml), so anything meant to visually extend past
    // the taskbar panel's own rectangle has to live outside that clip;
    // this window already spans the full screen height for exactly this
    // kind of thing (see this file's own `implicitHeight` comment), so no
    // second window is needed at all -- see AddShortcutBranch.qml's own
    // header comment for the full account of what this replaces.
    AddShortcutBranch {
        id: addBranch
        manager: dockIsland.panelItem
        anchorIsland: dockIsland
        screenWidth: root.width
        screenHeight: root.height
        edgeMargin: root.edgeMargin
    }
}
