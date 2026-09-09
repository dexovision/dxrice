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
    implicitHeight: 56
    radius: Theme.entryRadius
    color: root.active ? Theme.accentSoft : (area.containsMouse ? Theme.active : Theme.bgIdle)
    border.width: 1
    border.color: root.active ? Theme.accent : Theme.borderIdle

    Behavior on color { ColorAnimation { duration: Theme.animMs } }
    Behavior on border.color { ColorAnimation { duration: Theme.animMs } }

    Column {
        anchors.centerIn: parent
        spacing: 2
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: root.glyph
            font.pixelSize: 18
            color: root.active ? Theme.textActive : Theme.text
        }
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: root.label
            font.family: Theme.fontFamily
            font.pixelSize: 11
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
