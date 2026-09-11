import QtQuick

// A quiet, full-width toggle row (Wi-Fi, Bluetooth, DND, Keep Awake) --
// deliberately NOT a big solid-accent tile. The accent's job is to mark
// "this one is on," not to become the dominant color of the panel, so an
// active row gets only a faint accent-tinted background wash, a tinted
// icon/label, and a small dot -- never a full-saturation fill. `active` is
// a plain external property this binds to; the caller owns the actual
// on/off state and reacts to `toggled(next)`.
Rectangle {
    id: root
    property string glyph: ""
    property string label: ""
    property bool active: false
    signal toggled(bool next)

    implicitWidth: parent ? parent.width : 200
    implicitHeight: 38
    radius: Theme.roundingSm
    color: area.containsMouse ? Theme.layer1 : "transparent"

    Behavior on color {
        ColorAnimation { duration: Theme.durationFast; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveStandard }
    }

    Row {
        anchors.left: parent.left
        anchors.leftMargin: Theme.padMd
        anchors.verticalCenter: parent.verticalCenter
        spacing: Theme.padSm
        Text {
            text: root.glyph
            width: 16
            horizontalAlignment: Text.AlignHCenter
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSizeNormal
            color: root.active ? Theme.accent : Theme.text
            opacity: root.active ? 1 : 0.75
        }
        Text {
            text: root.label
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSizeNormal
            font.weight: root.active ? Font.Medium : Font.Normal
            color: root.active ? Theme.textActive : Theme.text
            opacity: root.active ? 1 : 0.85
        }
    }

    Rectangle {
        visible: root.active
        anchors.right: parent.right
        anchors.rightMargin: Theme.padMd
        anchors.verticalCenter: parent.verticalCenter
        width: 6
        height: 6
        radius: 3
        color: Theme.accent
    }

    MouseArea {
        id: area
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: root.toggled(!root.active)
    }
}
