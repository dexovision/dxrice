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
        // A reading, not a gesture: move straight to the new value. The
        // expressive curve overshot (control point y = 1.21), so every
        // 1.5s Performance sample bounced past the new value and back.
        Behavior on width {
            NumberAnimation { duration: Theme.durationDefault; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveStandard }
        }
    }
}
