import QtQuick

// A native-shell-control toggle tile (Wi-Fi, Bluetooth, DND, Keep Awake) --
// primary controls get real visual presence (a square tile, a centered
// icon, a label), not a thin list row, matching how an actual desktop
// control center presents its top-level toggles. The accent still only
// ever shows up as a quiet tint + a tinted icon when active -- never a
// solid/high-saturation fill -- so four of these sitting side by side
// read as "one is on" rather than "the panel turned cyan."
Rectangle {
    id: root
    property string glyph: ""
    property string label: ""
    property bool active: false
    signal toggled(bool next)

    implicitWidth: 74
    implicitHeight: 74
    radius: Theme.roundingLg
    color: {
        if (root.active) return Theme.mix(Theme.layer1, Theme.accent, area.containsMouse ? 0.22 : 0.14);
        return area.containsMouse ? Theme.layer1Hover : Theme.layer1;
    }
    scale: area.pressed ? 0.96 : 1.0

    Behavior on color {
        ColorAnimation { duration: Theme.durationFast; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveStandard }
    }
    Behavior on scale {
        NumberAnimation { duration: Theme.durationFast; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveExpressiveFast }
    }

    Column {
        anchors.centerIn: parent
        spacing: Theme.padXs
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: root.glyph
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSizeLarge
            color: root.active ? Theme.accent : Theme.text
            opacity: root.active ? 1 : 0.8
        }
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: root.label
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSizeSmall
            font.weight: root.active ? Font.Medium : Font.Normal
            color: root.active ? Theme.textActive : Theme.text
            opacity: root.active ? 1 : 0.85
            elide: Text.ElideRight
            width: 68
            horizontalAlignment: Text.AlignHCenter
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
