import QtQuick

// Taskbar Manager's "Add Shortcut" UI, as a branch off the taskbar panel
// itself rather than a separate Hyprland window. It used to be a real
// FloatingWindow -- a genuine second compositor-managed toplevel, visible
// to SUPER+G and every other window-placement mechanism even though it
// was conceptually just a mode of the taskbar editor. This is an Item
// instead: a sibling of dockIsland in Dock.qml's own PanelWindow (which
// already spans the full screen height -- see that file's own
// `implicitHeight` comment), positioned relative to dockIsland's current
// bounds and animated to read as growing out of it.
//
// Deliberately NOT a child of dockIsland/TaskbarManager's own Item tree:
// ShellIsland's `surface` has `clip: true` (so the panel's own growing
// bounds clip ITS content cleanly), which would silently clip this
// branch to nothing the moment it tried to render outside the taskbar
// panel's own rectangle -- the entire point of a surface that visually
// extends past its parent. Living as a sibling in the same window
// sidesteps that clip without needing a second window at all.
//
// `manager`: TaskbarManager's own root Item (`dockIsland.panelItem`) --
// this component owns presentation and positioning only; the actual
// installed-app list, search filtering and "add a shortcut" action all
// still live on TaskbarManager, exactly as before. This just reads/
// writes `manager`'s properties and calls `manager.addShortcut(...)`
// instead of owning any of that state itself.
Item {
    id: root
    required property Item manager
    required property Item anchorIsland
    required property real screenWidth
    required property real screenHeight
    required property real edgeMargin

    readonly property bool open: !!(manager && manager.addPanelOpen)
    readonly property real branchWidth: 320
    readonly property real branchHeight: Math.min(460, root.screenHeight - root.edgeMargin * 2)
    readonly property real gap: Theme.padLg

    // Prefer branching to the right of the taskbar panel (matches the
    // dock sitting centered -- usually near-symmetric space either way,
    // and right-then-left is a reasonable, consistent default); fall
    // back to the left when the panel is close enough to the right edge
    // that the branch wouldn't fit, and clamp vertically so it never
    // runs off the top of the screen regardless of where dockIsland's
    // own top edge currently is.
    readonly property bool fitsRight: anchorIsland.x + anchorIsland.width + gap + branchWidth <= root.screenWidth - edgeMargin
    x: fitsRight ? (anchorIsland.x + anchorIsland.width + gap) : (anchorIsland.x - gap - branchWidth)
    y: Math.max(edgeMargin, Math.min(anchorIsland.y, root.screenHeight - edgeMargin - branchHeight))
    width: branchWidth
    height: branchHeight
    z: 10

    // Grows from the edge touching the parent island -- the opening
    // animation this file's own header comment promises, not just a
    // plain fade. transformOrigin follows whichever side it actually
    // branched to, so it always reads as "coming from the taskbar," not
    // "appearing from a fixed corner" when fitsRight flips.
    transformOrigin: fitsRight ? Item.Left : Item.Right
    visible: opacity > 0.01
    opacity: root.open ? 1 : 0
    scale: root.open ? 1 : 0.85
    Behavior on opacity { NumberAnimation { duration: Theme.durationDefault; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveStandard } }
    Behavior on scale { NumberAnimation { duration: Theme.durationEnter; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveEmphasizedDecel } }

    onOpenChanged: if (!open) { searchInput.text = ""; nameInput.text = ""; cmdInput.text = ""; }

    ModalSurface {
        id: surface
        anchors.fill: parent
        // One elevation step below the modal register (3): this is a
        // branch OFF an already-open panel, not a standalone dialog
        // demanding its own full prominence -- the parent island stays
        // the visually dominant surface, matching the "child has
        // slightly lower visual hierarchy" requirement this component
        // was built against.
        elevation: 2

        Column {
            anchors.fill: parent
            anchors.margins: Theme.padLg
            spacing: Theme.padMd

            Item {
                width: parent.width
                height: Math.max(titleText.implicitHeight, closeBtn.height)
                Text {
                    id: titleText
                    anchors.verticalCenter: parent.verticalCenter
                    text: "Add Shortcut"
                    color: Theme.textActive
                    font.family: Theme.fontFamily
                    font.weight: Font.DemiBold
                }
                CloseButton {
                    id: closeBtn
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    onClicked: root.manager.addPanelOpen = false
                }
            }

            Rectangle {
                width: parent.width; height: ShellSurface.rowHeight; radius: Theme.entryRadius
                color: Theme.inputFill
                border.width: Theme.borderWidth; border.color: Theme.borderIdle
                TextInput {
                    id: searchInput
                    anchors.fill: parent; anchors.margins: 8
                    color: Theme.textActive
                    font.family: Theme.fontFamily
                    verticalAlignment: TextInput.AlignVCenter
                    onTextChanged: root.manager.query = text
                }
                Text { text: "Search installed apps..."; color: Theme.text; opacity: searchInput.text.length ? 0 : 0.5; anchors.left: parent.left; anchors.leftMargin: 8; anchors.verticalCenter: parent.verticalCenter }
            }

            Flickable {
                width: parent.width
                height: 220
                contentHeight: appList.implicitHeight
                clip: true
                Column {
                    id: appList
                    width: parent.width
                    Repeater {
                        model: root.manager ? root.manager.filteredApps : []
                        delegate: Rectangle {
                            width: appList.width
                            height: 36
                            radius: Theme.entryRadius
                            color: appArea.containsMouse ? Theme.active : "transparent"
                            Behavior on color { ColorAnimation { duration: Theme.animMs } }
                            Column {
                                anchors.verticalCenter: parent.verticalCenter
                                anchors.left: parent.left
                                anchors.leftMargin: 8
                                width: parent.width - 16
                                Text { text: modelData.name; color: Theme.textActive; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeNormal; elide: Text.ElideRight; width: parent.width }
                                Text { text: modelData.cmd; color: Theme.text; opacity: 0.6; font.pixelSize: Theme.fontSizeSmall; elide: Text.ElideRight; width: parent.width }
                            }
                            MouseArea {
                                id: appArea
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: {
                                    root.manager.addShortcut(modelData.name, modelData.cmd);
                                    root.manager.addPanelOpen = false;
                                }
                            }
                        }
                    }
                }
            }

            Text { text: "Or add a custom shortcut"; color: Theme.text; opacity: 0.7; font.pixelSize: Theme.fontSizeSmaller; font.family: Theme.fontFamily }

            Rectangle {
                width: parent.width; height: ShellSurface.rowHeight; radius: Theme.entryRadius
                color: Theme.inputFill
                border.width: Theme.borderWidth; border.color: Theme.borderIdle
                TextInput {
                    id: nameInput
                    anchors.fill: parent; anchors.margins: 8
                    color: Theme.textActive
                    font.family: Theme.fontFamily
                    verticalAlignment: TextInput.AlignVCenter
                }
                Text { text: "Display name"; color: Theme.text; opacity: nameInput.text.length ? 0 : 0.5; anchors.left: parent.left; anchors.leftMargin: 8; anchors.verticalCenter: parent.verticalCenter }
            }
            Rectangle {
                width: parent.width; height: ShellSurface.rowHeight; radius: Theme.entryRadius
                color: Theme.inputFill
                border.width: Theme.borderWidth; border.color: Theme.borderIdle
                TextInput {
                    id: cmdInput
                    anchors.fill: parent; anchors.margins: 8
                    color: Theme.textActive
                    font.family: Theme.fontFamily
                    verticalAlignment: TextInput.AlignVCenter
                }
                Text { text: "Command to run"; color: Theme.text; opacity: cmdInput.text.length ? 0 : 0.5; anchors.left: parent.left; anchors.leftMargin: 8; anchors.verticalCenter: parent.verticalCenter }
            }

            GlassButton {
                text: "Add"
                variant: "primary"
                onClicked: {
                    if (nameInput.text.length && cmdInput.text.length) {
                        root.manager.addShortcut(nameInput.text, cmdInput.text);
                        nameInput.text = ""; cmdInput.text = "";
                        root.manager.addPanelOpen = false;
                    }
                }
            }
        }
    }

    Shortcut { sequence: "Escape"; enabled: root.open; onActivated: root.manager.addPanelOpen = false }
}
