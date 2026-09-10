import QtQuick

// Compact icon-over-label toggle -- GNOME-quick-settings style (Wi-Fi,
// Bluetooth, DND, Keep Awake). `active` is a plain external property this
// binds to; the caller owns the actual on/off state and reacts to
// `toggled(next)`, matching the rest of this rice's "backend owns state,
// widget just reflects and requests changes" pattern.
Rectangle {
    id: root
    property string glyph: ""
    property string label: ""
    property bool active: false
    signal toggled(bool next)

    implicitWidth: 72
    implicitHeight: 60
    radius: Theme.roundingLg
    scale: area.pressed ? 0.97 : 1.0
    color: {
        if (root.active) return area.containsMouse ? Theme.mix(Theme.accentSoft, Qt.rgba(0, 0, 0, 1), 0.06) : Theme.accentSoft;
        if (area.containsMouse) return Theme.layer2Hover;
        return Theme.layer1;
    }
    border.width: root.active ? 0 : 1
    border.color: Theme.borderIdle

    Behavior on color {
        ColorAnimation { duration: Theme.durationFast; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveStandard }
    }
    Behavior on scale {
        NumberAnimation { duration: Theme.durationFast; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveExpressiveFast }
    }

    Column {
        anchors.centerIn: parent
        spacing: 4
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: root.glyph
            font.pixelSize: 19
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
