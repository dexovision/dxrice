import QtQuick

// Plain on/off switch (Taskbar's "Show icons", etc.) -- external state,
// same pattern as ToggleChip.
Rectangle {
    id: root
    property bool checked: false
    signal toggled(bool next)

    implicitWidth: 46
    implicitHeight: 26
    radius: Theme.roundingFull
    color: root.checked ? Theme.accent : Qt.rgba(Theme.border.r, Theme.border.g, Theme.border.b, 0.25)

    Behavior on color {
        ColorAnimation { duration: Theme.durationFast; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveStandard }
    }

    Rectangle {
        width: parent.height - 4
        height: parent.height - 4
        radius: Theme.roundingFull
        color: Theme.textActive
        y: 2
        x: root.checked ? parent.width - width - 2 : 2
        Behavior on x {
            NumberAnimation { duration: Theme.durationDefault; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveExpressiveDefault }
        }
    }

    MouseArea {
        anchors.fill: parent
        cursorShape: Qt.PointingHandCursor
        onClicked: root.toggled(!root.checked)
    }
}
