import QtQuick

// Small round/square icon-only button (close buttons, "..." menus, trash,
// up/down arrows). `glyph` is a plain unicode/text symbol -- no icon-font
// bundling needed for the handful of symbols this rice actually uses.
Rectangle {
    id: root
    property string glyph: ""
    property bool destructive: false
    property real size: 30
    signal clicked()

    implicitWidth: size
    implicitHeight: size
    radius: Theme.entryRadius
    color: {
        if (area.containsMouse && root.destructive) return Theme.accentSoft;
        if (area.containsMouse) return Theme.active;
        return Theme.bgIdle;
    }
    border.width: 1
    border.color: (area.containsMouse && root.destructive) ? Theme.accent : Theme.borderIdle

    Behavior on color { ColorAnimation { duration: Theme.animMs } }

    Text {
        anchors.centerIn: parent
        text: root.glyph
        color: (area.containsMouse && root.destructive) ? Theme.textActive : Theme.text
        font.pixelSize: root.size * 0.5
    }

    MouseArea {
        id: area
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: root.clicked()
    }
}
