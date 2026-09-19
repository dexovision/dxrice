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
    // Hover feedback, matching ToggleChip's idiom (lift the track toward
    // the accent when on, toward the hover layer when off) -- this was the
    // one interactive primitive in the shell with a MouseArea and a
    // pointing-hand cursor but no visual response to the pointer at all,
    // which reads as a dead control next to every other toggle.
    color: root.checked
        ? Theme.mix(Theme.accent, Theme.textActive, area.containsMouse ? 0.18 : 0.0)
        : (area.containsMouse ? Theme.layer1Hover : Theme.borderFaint)

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
        id: area
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: root.toggled(!root.checked)
    }
}
