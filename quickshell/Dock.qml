import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import Quickshell.Hyprland

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
    // the launcher tile ("wofi --show drun" as shipped) opens the shell's own launcher
    signal launcherRequested()

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
    // The ONE Escape handler for everything this window hosts. Qt delivers
    // a key sequence claimed by two enabled Shortcuts in the same window
    // as `activatedAmbiguously` to one of them and never as `activated`
    // (verified directly: two enabled Escape Shortcuts -> only the
    // ambiguous signal ever fires), so the three handlers this window used
    // to carry (this one, TaskbarManager's always-enabled one, and the
    // Add-Shortcut branch's) meant Escape closed nothing at all whenever
    // two of them were enabled at once -- i.e. any time Taskbar was open.
    // Escape peels one layer: the branch if it is open, else the panel.
    Shortcut {
        objectName: "dockEscape"
        sequence: "Escape"
        enabled: root.focusable
        onActivated: {
            if (root.taskbarModalOpen) dockIsland.panelItem.addPanelOpen = false;
            else PanelManager.close("taskbar");
        }
    }

    // Whether TaskbarManager's Add-Shortcut branch is open (see addBranch
    // below) -- Escape and click-outside close it before the panel.
    readonly property bool taskbarModalOpen: addBranch.open

    // Same click-outside-to-dismiss pattern as TopBar.qml: the input region
    // only ever extends past dockIsland while Taskbar is actually open, and
    // collapses back to nothing the instant it closes.
    mask: Region {
        Region { item: dockIsland }
        // Explicit geometry gated on the branch actually being open -- NOT
        // `Region { item: addBranch }`. An item region is that item's
        // mapped rectangle regardless of visible/opacity (see Quickshell's
        // PendingRegion::build), and the branch Item keeps its full size
        // while closed, so the item form left a permanent, invisible
        // ~270x390 input-blocking rectangle beside the dock -- clicks on
        // any application underneath it (lower half of the screen, to the
        // right of the dock) were swallowed even with every panel closed.
        // It was also stale while OPEN: an item region is only rebuilt on
        // x/y/width/height changes, never on a scale animation, so the
        // mask stayed frozen at the branch's half-animated size and its
        // own close button sat outside its own input region. These
        // explicit bounds track the branch's layout rect (the shape it
        // settles into) and collapse to nothing the instant it starts to
        // close, so input can never outlive what is on screen.
        Region {
            x: addBranch.x
            y: addBranch.y
            width: addBranch.inputActive ? addBranch.width : 0
            height: addBranch.inputActive ? addBranch.height : 0
        }
        // Click-outside-to-dismiss, only while Taskbar is open. It stays on
        // while the branch is open too: the branch is an Item in THIS
        // window now (it used to be a separate FloatingWindow this region
        // had to stand aside for), stacked above dismissArea with its own
        // click-eating background, so a click inside it never reaches the
        // catcher -- and a click outside it peels one layer, exactly like
        // Escape.
        Region {
            x: 0; y: 0
            width: PanelManager.isOpen("taskbar") ? root.width : 0
            height: PanelManager.isOpen("taskbar") ? root.height : 0
        }
    }

    MouseArea {
        id: dismissArea
        anchors.fill: parent
        enabled: PanelManager.isOpen("taskbar")
        onClicked: {
            if (root.taskbarModalOpen) dockIsland.panelItem.addPanelOpen = false;
            else PanelManager.close("taskbar");
        }
    }

    Binding { target: ShellSurface; property: "bottomEdgeHeight"; value: root.exclusiveZone }

    // the saved shortcuts (Shortcuts: one list for the dock and the bar)
    readonly property string configPath: Shortcuts.configPath
    readonly property var shortcuts: Shortcuts.list

    ShellIsland {
        id: dockIsland
        objectName: "dockIsland"
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
        closeCenterY: panelItem ? panelItem.headerCenterY : 24
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
                    objectName: "dockTile:" + modelData.label
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
                    scale: Theme.pressScale(tileArea.pressed, 0.9)

                    Behavior on color { ColorAnimation { duration: Theme.durationFast; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveStandard } }
                    Behavior on scale { NumberAnimation { duration: Theme.durationMove; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveExpressiveFast } }

                    // is its app open, and is it the focused one (Hyprland's own window list)
                    readonly property string appKey: root.appKeyOf(shortcutTile.modelData.onClick)
                    readonly property bool running: root.isRunning(shortcutTile.appKey)
                    readonly property bool focusedApp: shortcutTile.running && root.matches(root.focusedClass, shortcutTile.appKey)
                    // the glyph lifts a little under the pointer and hops when launched;
                    // only this icon moves, so sweeping across the dock stays calm
                    property real hop: 0
                    SequentialAnimation {
                        id: hopAnim
                        NumberAnimation { target: shortcutTile; property: "hop"; to: -9; duration: Theme.reduceMotion ? 0 : 110; easing.type: Easing.OutQuad }
                        NumberAnimation { target: shortcutTile; property: "hop"; to: 0; duration: Theme.durationSpring; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveSpringFast }
                    }

                    Text {
                        id: tileLabel
                        objectName: "dockGlyph"
                        anchors.centerIn: parent
                        anchors.verticalCenterOffset: (tileArea.containsMouse ? -3 : 0) + shortcutTile.hop
                        Behavior on anchors.verticalCenterOffset {
                            enabled: !hopAnim.running
                            NumberAnimation { duration: Theme.durationSpringFast; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveSpringFast }
                        }
                        text: shortcutTile.modelData.glyph
                        font.family: Theme.iconFamily
                        font.pixelSize: Theme.fontSizeLarge
                        color: Theme.textActive
                    }
                    // running: a small mark under the icon; focused: a wider accent one
                    Rectangle {
                        objectName: "dockRunning"
                        anchors.horizontalCenter: parent.horizontalCenter
                        anchors.bottom: parent.bottom
                        anchors.bottomMargin: 2
                        height: 3; radius: 1.5
                        width: shortcutTile.focusedApp ? 14 : 4
                        color: shortcutTile.focusedApp ? Theme.accent : Theme.textActive
                        opacity: shortcutTile.running ? (shortcutTile.focusedApp ? 1 : 0.55) : 0
                        Behavior on width { NumberAnimation { duration: Theme.durationSpringFast; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveSpringFast } }
                        Behavior on opacity { NumberAnimation { duration: Theme.durationFast } }
                        Behavior on color { ColorAnimation { duration: Theme.durationFast } }
                    }

                    MouseArea {
                        id: tileArea
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onContainsMouseChanged: {
                            if (containsMouse) root.hoverTile = shortcutTile;
                            else if (root.hoverTile === shortcutTile) root.hoverTile = null;
                        }
                        onPressed: dockTip.dismissed = true
                        onClicked: {
                            // Shortcuts.launch un-escapes the saved command (see there)
                            const what = Shortcuts.launch(shortcutTile.modelData.onClick, "dock");
                            if (what === "launcher") root.launcherRequested();
                            else if (what === "launched") hopAnim.restart();
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
                objectName: "taskbarToggle"
                size: ShellSurface.dockTile
                anchors.verticalCenter: parent.verticalCenter
                onClicked: root.taskbarRequested()
            }
        }
    }

    // ---- which shortcuts' apps are open ----
    // A shortcut's app: the program its command runs, by name ("/usr/bin/
    // discord --x" -> "discord"). An open window matches when its class or
    // app id is that name, or ends in it after a dot ("org.gnome.Nautilus"
    // for "nautilus"), or starts with it and a dash ("brave-browser").
    function appKeyOf(onClick) { return Shortcuts.appKeyOf(onClick); }
    function matches(cls, key) { return Shortcuts.matches(cls, key); }
    function classOf(t) { return Shortcuts.classOf(t); }
    function isRunning(key) { return Shortcuts.isRunning(key); }
    // set by shell.qml from TopBar, which knows the focused window from the
    // start; Hyprland.activeToplevel only as a fallback (null until the
    // first focus change after the shell starts)
    property string focusedAppId: ""
    readonly property string focusedClass: root.focusedAppId || root.classOf(Hyprland.activeToplevel)

    // ---- the hovered icon's name, above the dock ----
    // Icon-only tiles say nothing about what they launch until clicked.
    // Shown after the pointer rests a moment (not on a fly-past), then
    // follows the pointer from icon to icon at once. Not part of `mask`,
    // so it can never take a click meant for whatever is under it; hidden
    // while the Taskbar editor is open and once a tile is pressed.
    property Item hoverTile: null
    onHoverTileChanged: {
        if (!root.hoverTile) { tipDelay.stop(); dockTip.dismissed = false; dockTip.shown = false; return; }
        if (dockTip.shown) dockTip.text = root.hoverTile.modelData.label;
        else tipDelay.restart();
    }
    Timer {
        id: tipDelay
        interval: 450
        onTriggered: if (root.hoverTile) { dockTip.text = root.hoverTile.modelData.label; dockTip.shown = true; }
    }
    Rectangle {
        id: dockTip
        objectName: "dockTooltip"
        property bool shown: false
        property bool dismissed: false
        property string text: ""
        readonly property bool active: shown && !dismissed && root.hoverTile !== null && !dockIsland.expanded
        readonly property point anchorPt: root.hoverTile
            ? root.hoverTile.mapToItem(root.contentItem, root.hoverTile.width / 2, 0) : Qt.point(0, 0)
        width: tipLabel.implicitWidth + Theme.padMd * 2
        height: tipLabel.implicitHeight + Theme.padSm * 2
        radius: height / 2
        x: Math.max(root.edgeMargin, Math.min(root.width - width - root.edgeMargin, anchorPt.x - width / 2))
        y: dockIsland.y - height - Theme.padSm + (active ? 0 : Theme.contentShift / 2)
        color: Theme.withAlpha(Theme.panelTone, 0.96)
        border.width: Theme.borderWidth
        border.color: Theme.border
        opacity: active ? 1 : 0
        visible: opacity > 0.01
        Behavior on opacity { NumberAnimation { duration: Theme.durationFast; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveStandard } }
        Behavior on y { NumberAnimation { duration: Theme.durationMove; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveEnter } }
        Behavior on x {
            enabled: dockTip.opacity > 0.5
            NumberAnimation { duration: Theme.durationMove; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveStandard }
        }
        Text {
            id: tipLabel
            anchors.centerIn: parent
            text: dockTip.text
            color: Theme.textActive
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSizeSmaller
            font.weight: Font.Medium
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
