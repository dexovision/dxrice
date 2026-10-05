import QtQuick

// The one dismissal affordance every surface that can be closed uses --
// ShellIsland's own floating corner button (Calendar/QuickSettings/
// Taskbar) and Theme's header-row button used to be two independent
// implementations that only coincidentally looked similar: ShellIsland
// hand-drew a 22px Rectangle+Text, Theme reached for the generic
// IconButton at its 30px default -- a real, measurable 36% size
// difference, plus a different edge-offset convention, that nothing
// required, it simply never had a shared definition to converge on.
// This is that definition. Deliberately NOT built on IconButton: this
// button's hitbox/glyph ratio and hover treatment are tuned for sitting
// directly against a panel's own corner or header strip, a narrower job
// than IconButton's general-purpose (toggle, destructive-tint, variable
// size) one.
Rectangle {
    id: root
    signal clicked()

    width: 22
    height: 22
    radius: Theme.roundingFull
    color: area.containsMouse ? Theme.layer2Hover : Theme.layer1
    Behavior on color { ColorAnimation { duration: Theme.durationFast } }

    Text {
        anchors.centerIn: parent
        text: "✕"
        font.pixelSize: 10
        color: Theme.text
    }
    MouseArea {
        id: area
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: root.clicked()
    }
}
