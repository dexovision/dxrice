import QtQuick

// The shell's one "working on it" indicator (scanning for networks,
// applying a theme, generating a palette): three dots that brighten in
// turn. Opacity only -- nothing moves, so it is also what reduce_motion
// gets -- and it only animates while it is actually visible.
Row {
    id: root
    property color color: Theme.text
    property real dotSize: Math.max(4, Math.round(Theme.fontSizeSmall * 0.45))
    spacing: Math.round(dotSize * 0.8)

    Repeater {
        model: 3
        delegate: Rectangle {
            id: dot
            required property int index
            width: root.dotSize; height: root.dotSize; radius: root.dotSize / 2
            color: root.color
            opacity: 0.25
            SequentialAnimation on opacity {
                running: root.visible
                loops: Animation.Infinite
                PauseAnimation { duration: dot.index * 160 }
                NumberAnimation { to: 0.95; duration: 280; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveStandard }
                NumberAnimation { to: 0.25; duration: 420; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveStandard }
                PauseAnimation { duration: (2 - dot.index) * 160 + 200 }
            }
        }
    }
}
