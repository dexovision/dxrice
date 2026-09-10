import QtQuick

// Small round icon-only button (close buttons, "..." menus, trash,
// up/down arrows, power-row actions). `glyph` is a plain unicode/text
// symbol -- no icon-font bundling needed for the handful of symbols this
// rice actually uses. Fully round (roundingFull) rather than a rounded
// square -- reads as a distinct "chip" you tap, not a leftover corner of a
// bigger shape.
//
// `tint`, when set, colors the badge at rest (not just on hover) -- a row
// of otherwise-identical gray circles (lock/logout/reboot/power off) reads
// as flat and same-y; a quiet color note per action reads as designed.
// `destructive` is kept as a shorthand for `tint: Theme.dangerTint`.
Rectangle {
    id: root
    property string glyph: ""
    property bool destructive: false
    property var tint: null
    property real size: 30
    signal clicked()

    readonly property var effectiveTint: tint !== null ? tint : (destructive ? Theme.dangerTint : null)

    implicitWidth: size
    implicitHeight: size
    radius: Theme.roundingFull
    scale: area.pressed ? 0.92 : 1.0
    color: {
        if (root.effectiveTint !== null) return Theme.tintBg(root.effectiveTint, area.containsMouse || area.pressed);
        if (area.pressed) return Theme.layer2Active;
        if (area.containsMouse) return Theme.layer2Hover;
        return Theme.layer1;
    }
    border.width: 1
    border.color: root.effectiveTint !== null ? Theme.tintBorder(root.effectiveTint, area.containsMouse) : Theme.borderIdle

    Behavior on color {
        ColorAnimation { duration: Theme.durationFast; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveStandard }
    }
    Behavior on scale {
        NumberAnimation { duration: Theme.durationFast; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveExpressiveFast }
    }

    Text {
        anchors.centerIn: parent
        text: root.glyph
        color: root.effectiveTint !== null ? Theme.mix(Theme.textActive, root.effectiveTint, 0.35) : Theme.text
        font.family: Theme.fontFamily
        font.pixelSize: root.size * 0.45
    }

    MouseArea {
        id: area
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: root.clicked()
    }
}
