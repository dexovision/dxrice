import QtQuick

// Static progress bar for read-only stats (CPU/RAM/disk usage) -- no
// interaction, just a smoothly-animated fill.
Rectangle {
    id: root
    property real value: 0 // 0..1

    implicitHeight: 8
    radius: Theme.roundingFull
    color: Theme.borderFaint

    Rectangle {
        width: parent.width * Math.max(0, Math.min(1, root.value))
        height: parent.height
        radius: parent.radius
        color: Theme.accent
        Behavior on width {
            NumberAnimation { duration: Theme.durationDefault; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveExpressiveDefault }
        }
    }
}
