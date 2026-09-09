import QtQuick

// Plain on/off switch (Taskbar's "Show icons", etc.) -- external state,
// same pattern as ToggleChip.
Rectangle {
    id: root
    property bool checked: false
    signal toggled(bool next)

    implicitWidth: 44
    implicitHeight: 24
    radius: height / 2
    color: root.checked ? Theme.accentSoft : Qt.rgba(Theme.border.r, Theme.border.g, Theme.border.b, 0.25)

    Behavior on color { ColorAnimation { duration: Theme.animMs } }

    Rectangle {
        width: parent.height - 4
        height: parent.height - 4
        radius: height / 2
        color: Theme.textActive
        y: 2
        x: root.checked ? parent.width - width - 2 : 2
        Behavior on x { NumberAnimation { duration: Theme.animMs; easing.type: Easing.OutCubic } }
    }

    MouseArea {
        anchors.fill: parent
        cursorShape: Qt.PointingHandCursor
        onClicked: root.toggled(!root.checked)
    }
}
