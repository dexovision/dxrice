import QtQuick
import QtQuick.Effects
import "BranchGeometry.js" as BranchGeometry

// Taskbar Manager's "Add Shortcut" UI: a child surface that branches out of
// the taskbar panel, not a window of its own.
//
// It used to be a FloatingWindow -- a genuine second compositor toplevel,
// visible to SUPER+G and window placement although it was only ever a mode
// of the taskbar editor. This is an Item in Dock.qml's own PanelWindow (which
// already spans the screen height), a SIBLING of dockIsland rather than a
// child: ShellIsland's surface clips to its own growing bounds, which would
// clip anything meant to extend past the panel. TaskbarManager still owns
// all of the state and the one function that writes config-dock
// (`manager.addShortcut`); this file is presentation and geometry only.
//
// GEOMETRY: BranchGeometry.place() picks where the branch goes from the
// panel's LIVE rect, the Add control's position and the real screen size --
// beside the panel on whichever side has room, else above it, else as a
// sheet inside the panel's own body on a screen too small for either. It is
// always clamped on-screen, and follows the panel if the panel resizes while
// the branch is open.
//
// MOTION: one value (`reveal`) drives everything, the same pattern as
// ShellIsland's `morph`. The surface starts as a pill the height of the
// header line, right where the branch leaves the panel, stretches outward
// along the branching axis first, then unfolds on the other axis; content
// fades in only once the surface is mostly there. Closing runs the same
// curve backwards, so open/close/reopen at any point can never desync
// geometry from opacity -- there is nothing else to fall out of step.
//
// INPUT: Dock.qml's mask reads `inputActive` and this Item's layout rect
// (see the comment there): input exists exactly while open, never during
// or after a close.
Item {
    id: root
    objectName: "addShortcutBranch"
    required property Item manager
    required property Item anchorIsland
    required property real screenWidth
    required property real screenHeight
    required property real edgeMargin

    // Gated on the taskbar itself being open too, so closing the taskbar
    // (click-outside, IPC, SUPER+C's closeCurrent) closes this branch in
    // the same frame rather than leaving it up through the collapse.
    readonly property bool open: !!(manager && manager.addPanelOpen) && PanelManager.isOpen("taskbar")
    // Whether this branch may receive pointer input at all -- read by
    // Dock.qml's input mask. False the moment a close begins.
    readonly property bool inputActive: root.open

    // ---- geometry ----
    readonly property real gap: Theme.padMd
    readonly property real pad: Theme.padLg
    readonly property real rowH: 40
    // Everything in the content column except the app list itself (7
    // children -> 6 gaps).
    readonly property real fixedH: pad * 2 + headerRow.height + searchField.height + customCaption.height
        + nameField.height + cmdField.height + addRow.height + Theme.padMd * 6
    readonly property real wantH: fixedH + rowH * 6
    readonly property var anchorPoint: Qt.point(
        anchorIsland.x + (manager ? manager.addAnchorX : anchorIsland.width / 2),
        anchorIsland.y + (manager ? manager.headerCenterY : 24))
    readonly property var placement: BranchGeometry.place(
        { x: anchorIsland.x, y: anchorIsland.y, w: anchorIsland.width, h: anchorIsland.height },
        anchorPoint,
        { w: 340, h: wantH },
        { w: screenWidth, h: screenHeight },
        { margin: edgeMargin, gap: gap, minW: 280, minH: fixedH + rowH * 3,
          headerH: manager ? manager.headerHeight : 48, footerH: anchorIsland.collapsedHeight })
    readonly property string side: placement.side
    readonly property bool horizontal: side === "right" || side === "left"

    x: placement.x
    y: placement.y
    width: placement.w
    height: placement.h
    z: 10

    // The point where the branch meets its parent, in this Item's coords.
    readonly property real anchorLocalX: Math.max(0, Math.min(width, anchorPoint.x - x))
    readonly property real anchorLocalY: Math.max(0, Math.min(height, anchorPoint.y - y))

    // ---- motion ----
    property real reveal: root.open ? 1 : 0
    Behavior on reveal {
        NumberAnimation { duration: Theme.durationEnter; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveStandard }
    }
    function sub(p, from, to) { return Math.max(0, Math.min(1, (p - from) / (to - from))); }
    readonly property real pMain: sub(reveal, 0.0, 0.55)
    readonly property real pCross: sub(reveal, 0.25, 1.0)
    readonly property real stem: 36
    visible: reveal > 0.001

    // Clear the form once fully closed -- not on the close itself, so the
    // fields don't visibly empty while the surface is still folding away.
    onRevealChanged: if (reveal === 0 && !open) { searchInput.text = ""; nameInput.text = ""; cmdInput.text = ""; appFlick.contentY = 0; }
    onOpenChanged: if (open) searchInput.forceActiveFocus()

    // Start rect: a header-height pill where the branch leaves the parent.
    readonly property rect startRect: {
        const s = root.stem;
        switch (root.side) {
        case "right": return Qt.rect(0, root.anchorLocalY - s / 2, s, s);
        case "left": return Qt.rect(width - s, root.anchorLocalY - s / 2, s, s);
        case "above": return Qt.rect(root.anchorLocalX - s / 2, height - s, s, s);
        default: return Qt.rect(Math.min(width - s, Math.max(0, root.anchorLocalX - s / 2)), 0, s, s);
        }
    }
    readonly property real pX: horizontal ? pMain : pCross
    readonly property real pY: horizontal ? pCross : pMain

    // ---- the connector ----
    // A short neck of the same material spanning the gap between parent and
    // child at the header line (or above the Add control when stacked), so
    // the two read as one branching object rather than two panels that
    // happen to be near each other. It overlaps the parent's 1px edge so the
    // join has no visible seam.
    Rectangle {
        id: neck
        visible: root.side !== "sheet"
        readonly property real thickness: 18
        x: root.side === "right" ? -root.gap - 1 : (root.side === "left" ? root.width - 1 : root.anchorLocalX - thickness / 2)
        y: root.horizontal ? root.anchorLocalY - thickness / 2 : (root.side === "above" ? root.height - 1 : -root.gap - 1)
        width: root.horizontal ? (root.gap + 2) * root.sub(root.reveal, 0, 0.2) : thickness
        height: root.horizontal ? thickness : (root.gap + 2) * root.sub(root.reveal, 0, 0.2)
        color: Theme.panel
        opacity: root.sub(root.reveal, 0, 0.15)
    }

    RectangularShadow {
        anchors.fill: surface
        radius: surface.radius
        color: Theme.shadowColor
        // One step below the taskbar island's own elevation (2): this is a
        // branch of an open panel, not a standalone dialog.
        blur: Theme.elevationBlur(1)
        spread: Theme.elevationSpread(1)
        offset.y: Theme.elevationOffsetY(1)
        opacity: root.pCross
    }

    Rectangle {
        id: surface
        x: root.startRect.x + (0 - root.startRect.x) * root.pX
        y: root.startRect.y + (0 - root.startRect.y) * root.pY
        width: root.startRect.width + (root.width - root.startRect.width) * root.pX
        height: root.startRect.height + (root.height - root.startRect.height) * root.pY
        radius: Math.min(ShellSurface.radius, width / 2, height / 2)
        // Same material as the parent island (Level 1 tone + hairline), so
        // it reads as made of the same stuff; its lower rank comes from the
        // smaller elevation above and from being visibly attached by the
        // neck, not from a different colour.
        // As a sheet it sits ON the parent's own content, inside the same
        // layer surface -- compositor blur only ever applies to what is
        // behind the whole surface, never between items within it, so a
        // translucent sheet let the panel's controls show straight through.
        color: root.side === "sheet" ? Theme.withAlpha(Theme.mix(Theme.panelTone, Theme.layer1Tone, 0.25), 0.98) : Theme.panel
        border.width: Theme.borderWidth
        border.color: root.side === "sheet" ? Theme.border : Theme.borderIdle
        clip: true

        // Content is laid out at the FINAL size and held still while the
        // surface grows over it (a blind lifting, like ShellIsland), then
        // fades in for the last stretch of the reveal.
        Item {
            id: content
            x: -surface.x
            y: -surface.y
            width: root.width
            height: root.height
            opacity: root.sub(root.reveal, 0.6, 1.0)

            // Eats clicks on bare branch background so they never fall
            // through to Dock.qml's click-outside catcher underneath.
            MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons }

            Column {
                x: root.pad
                y: root.pad
                width: parent.width - root.pad * 2
                spacing: Theme.padMd

                Item {
                    id: headerRow
                    width: parent.width
                    height: 28
                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        text: "Add shortcut"
                        color: Theme.textActive
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSizeNormal
                        font.weight: Font.DemiBold
                    }
                    CloseButton {
                        id: closeBtn
                        objectName: "addShortcutBranchClose"
                        anchors.right: parent.right
                        anchors.verticalCenter: parent.verticalCenter
                        onClicked: root.manager.addPanelOpen = false
                    }
                }

                InputField {
                    id: searchField
                    glyph: ""
                    placeholder: "Search installed apps"
                    input: searchInput
                    TextInput {
                        id: searchInput
                        anchors.fill: parent
                        color: Theme.textActive
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSizeNormal
                        verticalAlignment: TextInput.AlignVCenter
                        clip: true
                        onTextChanged: if (root.manager) root.manager.query = text
                        Keys.onReturnPressed: {
                            const apps = root.manager ? root.manager.filteredApps : [];
                            if (apps.length > 0) root.pick(apps[0].name, apps[0].cmd);
                        }
                    }
                }

                Item {
                    id: listArea
                    width: parent.width
                    height: Math.max(root.rowH, root.height - root.fixedH)
                    readonly property var apps: root.manager ? root.manager.filteredApps : []

                    // Whole rows only: a viewport that ends mid-row reads as
                    // something cut off rather than a list that scrolls. The
                    // remainder stays as space below the list.
                    Flickable {
                        id: appFlick
                        width: parent.width
                        height: Math.max(1, Math.floor(parent.height / root.rowH)) * root.rowH
                        contentHeight: appList.height
                        clip: true
                        boundsBehavior: Flickable.StopAtBounds
                        Column {
                            id: appList
                            width: appFlick.width
                            Repeater {
                                model: listArea.apps
                                delegate: Rectangle {
                                    id: appRow
                                    required property var modelData
                                    width: appList.width
                                    height: root.rowH
                                    radius: Theme.roundingSm
                                    color: appArea.pressed ? Theme.layer2Active : (appArea.containsMouse ? Theme.layer2Hover : "transparent")
                                    Behavior on color { ColorAnimation { duration: Theme.durationFast } }
                                    Column {
                                        anchors.verticalCenter: parent.verticalCenter
                                        x: Theme.padSm
                                        width: parent.width - Theme.padSm * 2 - plus.width - Theme.padSm
                                        spacing: 1
                                        Text {
                                            width: parent.width
                                            text: appRow.modelData.name
                                            color: Theme.textActive
                                            font.family: Theme.fontFamily
                                            font.pixelSize: Theme.fontSizeNormal
                                            elide: Text.ElideRight
                                        }
                                        Text {
                                            width: parent.width
                                            text: appRow.modelData.cmd
                                            color: Theme.text
                                            opacity: Theme.opacityMuted
                                            font.family: Theme.fontFamily
                                            font.pixelSize: Theme.fontSizeSmall
                                            elide: Text.ElideRight
                                        }
                                    }
                                    Text {
                                        id: plus
                                        anchors.right: parent.right
                                        anchors.rightMargin: Theme.padSm
                                        anchors.verticalCenter: parent.verticalCenter
                                        text: "+"
                                        color: Theme.accent
                                        font.family: Theme.fontFamily
                                        font.pixelSize: Theme.fontSizeLarge
                                        opacity: appArea.containsMouse ? 1 : 0
                                        Behavior on opacity { NumberAnimation { duration: Theme.durationFast } }
                                    }
                                    MouseArea {
                                        id: appArea
                                        anchors.fill: parent
                                        hoverEnabled: true
                                        cursorShape: Qt.PointingHandCursor
                                        onClicked: root.pick(appRow.modelData.name, appRow.modelData.cmd)
                                    }
                                }
                            }
                        }
                    }
                    ScrollHint {
                        flickable: appFlick
                        height: appFlick.height
                        anchors.right: parent.right
                    }

                    // Empty / loading states: the list area keeps its size
                    // either way, so the branch never jumps as results come
                    // and go while typing.
                    Text {
                        anchors.centerIn: appFlick
                        width: parent.width - Theme.padLg * 2
                        horizontalAlignment: Text.AlignHCenter
                        wrapMode: Text.WordWrap
                        maximumLineCount: 2
                        elide: Text.ElideRight
                        visible: listArea.apps.length === 0
                        text: !root.manager || root.manager.appsLoading ? "Loading applications…"
                            : (searchInput.text.length > 0 ? "No apps match “" + searchInput.text + "”" : "No applications found")
                        color: Theme.text
                        opacity: Theme.opacityMuted
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSizeSmaller
                    }
                }

                Text {
                    id: customCaption
                    text: "Custom command"
                    color: Theme.text
                    opacity: Theme.opacityMuted
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSizeSmall
                    font.letterSpacing: 0.5
                }

                InputField {
                    id: nameField
                    placeholder: "Display name"
                    input: nameInput
                    TextInput {
                        id: nameInput
                        anchors.fill: parent
                        color: Theme.textActive
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSizeNormal
                        verticalAlignment: TextInput.AlignVCenter
                        clip: true
                        KeyNavigation.tab: cmdInput
                    }
                }
                InputField {
                    id: cmdField
                    placeholder: "Command to run"
                    input: cmdInput
                    TextInput {
                        id: cmdInput
                        anchors.fill: parent
                        color: Theme.textActive
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSizeNormal
                        verticalAlignment: TextInput.AlignVCenter
                        clip: true
                        Keys.onReturnPressed: root.addCustom()
                    }
                }

                Item {
                    id: addRow
                    width: parent.width
                    height: addButton.implicitHeight
                    GlassButton {
                        id: addButton
                        anchors.right: parent.right
                        text: "Add"
                        variant: "primary"
                        enabled: nameInput.text.trim().length > 0 && cmdInput.text.trim().length > 0
                        onClicked: root.addCustom()
                    }
                }
            }
        }
    }

    function pick(name, cmd) {
        root.manager.addShortcut(name, cmd);
        root.manager.addPanelOpen = false;
    }
    function addCustom() {
        const name = nameInput.text.trim(), cmd = cmdInput.text.trim();
        if (!name.length || !cmd.length) return;
        root.pick(name, cmd);
    }

    // A text field row: optional leading glyph, placeholder, focus ring.
    component InputField: Rectangle {
        id: field
        property string glyph: ""
        property string placeholder: ""
        property Item input: null
        default property alias inner: inputHolder.data
        width: parent ? parent.width : 0
        height: ShellSurface.rowHeight
        radius: Theme.roundingSm
        color: Theme.inputFill
        border.width: Theme.borderWidth
        border.color: field.input && field.input.activeFocus ? Theme.withAlpha(Theme.accent, 0.6) : Theme.borderIdle
        Behavior on border.color { ColorAnimation { duration: Theme.durationFast } }
        Text {
            id: glyphText
            visible: field.glyph.length > 0
            anchors.left: parent.left
            anchors.leftMargin: Theme.padMd
            anchors.verticalCenter: parent.verticalCenter
            text: field.glyph
            color: Theme.text
            opacity: Theme.opacityMuted
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSizeSmaller
        }
        Item {
            id: inputHolder
            anchors.fill: parent
            anchors.leftMargin: glyphText.visible ? Theme.padMd + glyphText.width + Theme.padSm : Theme.padMd
            anchors.rightMargin: Theme.padMd
        }
        Text {
            anchors.fill: inputHolder
            verticalAlignment: Text.AlignVCenter
            text: field.placeholder
            visible: !field.input || field.input.text.length === 0
            color: Theme.text
            opacity: Theme.opacityMuted
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSizeNormal
            elide: Text.ElideRight
        }
    }
}
