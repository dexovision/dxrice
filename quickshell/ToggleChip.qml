import QtQuick

// Compact icon+label toggle (Wi-Fi, Bluetooth, DND, Keep Awake). Flat fill,
// no border, no glow -- end-4/caelestia-style panels stay monochrome and
// quiet at rest, and use color only for the one thing that's actually on.
// `active` is a plain external property this binds to; the caller owns the
// actual on/off state and reacts to `toggled(next)`, matching the rest of
// this rice's "backend owns state, widget just reflects and requests
// changes" pattern.
Rectangle {
    id: root
    property string glyph: ""
    property string label: ""
    property bool active: false
    signal toggled(bool next)

    implicitWidth: 76
    implicitHeight: 72
    radius: Theme.roundingLg
    scale: area.pressed ? 0.97 : 1.0
    color: {
        if (root.active) return area.containsMouse ? Theme.mix(Theme.accent, Qt.rgba(0, 0, 0, 1), 0.08) : Theme.accent;
        return area.containsMouse ? Theme.layer2Hover : Theme.layer1;
    }

    Behavior on color {
        ColorAnimation { duration: Theme.durationFast; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveStandard }
    }
    Behavior on scale {
        NumberAnimation { duration: Theme.durationFast; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveExpressiveFast }
    }

    Column {
        anchors.centerIn: parent
        spacing: 6
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: root.glyph
            font.family: Theme.fontFamily
            font.pixelSize: 17
            color: root.active ? Theme.textActive : Theme.text
        }
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: root.label
            font.family: Theme.fontFamily
            font.pixelSize: 11
            font.weight: Font.Medium
            color: root.active ? Theme.textActive : Theme.text
        }
    }

    MouseArea {
        id: area
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: root.toggled(!root.active)
    }
}
