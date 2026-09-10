import QtQuick

// Small round icon-only button (close buttons, "..." menus, trash,
// up/down arrows). `glyph` is a plain unicode/text symbol -- no icon-font
// bundling needed for the handful of symbols this rice actually uses.
// Fully round (roundingFull) rather than a rounded square -- reads as a
// distinct "chip" you tap, not a leftover corner of a bigger shape.
Rectangle {
    id: root
    property string glyph: ""
    property bool destructive: false
    property real size: 30
    signal clicked()

    implicitWidth: size
    implicitHeight: size
    radius: Theme.roundingFull
    scale: area.pressed ? 0.92 : 1.0
    color: {
        if (area.pressed) return root.destructive ? Theme.accent : Theme.layer2Active;
        if (area.containsMouse) return root.destructive ? Theme.mix(Theme.layer1, Theme.accent, 0.35) : Theme.layer2Hover;
        return Theme.layer1;
    }
    border.width: 1
    border.color: (area.containsMouse && root.destructive) ? Theme.accent : Theme.borderIdle

    Behavior on color {
        ColorAnimation { duration: Theme.durationFast; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveStandard }
    }
    Behavior on scale {
        NumberAnimation { duration: Theme.durationFast; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveExpressiveFast }
    }

    Text {
        anchors.centerIn: parent
        text: root.glyph
        color: (area.containsMouse && root.destructive) ? Theme.textActive : Theme.text
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
