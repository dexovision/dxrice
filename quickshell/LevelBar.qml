import QtQuick

// Static progress bar for read-only stats (CPU/RAM/disk usage) -- no
// interaction, just a smoothly-animated fill.
Rectangle {
    id: root
    property real value: 0 // 0..1

    implicitHeight: 6
    radius: height / 2
    color: Qt.rgba(Theme.border.r, Theme.border.g, Theme.border.b, 0.25)

    Rectangle {
        width: parent.width * Math.max(0, Math.min(1, root.value))
        height: parent.height
        radius: parent.radius
        color: Theme.accentSoft
        Behavior on width { NumberAnimation { duration: Theme.animMs; easing.type: Easing.OutCubic } }
    }
}
