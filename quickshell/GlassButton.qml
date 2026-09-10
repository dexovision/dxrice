import QtQuick

// Text button. variant: "primary" (accent-filled pill, for the one action
// that matters on a screen) or "secondary" (glass, everything else) --
// mirrors Material's filled-vs-tonal button distinction rather than
// giving every button the same weight.
Rectangle {
    id: root
    property string text: ""
    property string variant: "secondary"
    // `enabled` is inherited from Item -- disabling it also correctly
    // stops the MouseArea below from receiving input, not just a name we
    // happen to reuse.
    signal clicked()

    implicitWidth: label.implicitWidth + Theme.padXl * 2
    implicitHeight: label.implicitHeight + Theme.padMd * 2
    radius: root.variant === "primary" ? Theme.roundingFull : Theme.roundingSm
    opacity: root.enabled ? 1.0 : 0.5
    scale: area.pressed ? 0.96 : 1.0

    color: {
        if (root.variant === "primary") {
            return area.pressed ? Theme.accent : Theme.mix(Theme.accent, Qt.rgba(0, 0, 0, 1), 0.08);
        }
        if (area.pressed) return Theme.layer2Active;
        return area.containsMouse ? Theme.layer2Hover : Theme.layer1;
    }
    border.width: 1
    border.color: root.variant === "primary" ? Theme.accent : Theme.borderIdle

    Behavior on color {
        ColorAnimation { duration: Theme.durationFast; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveStandard }
    }
    Behavior on scale {
        NumberAnimation { duration: Theme.durationFast; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveExpressiveFast }
    }

    Text {
        id: label
        anchors.centerIn: parent
        text: root.text
        color: root.variant === "primary" ? Theme.textActive : Theme.text
        font.family: Theme.fontFamily
        font.pixelSize: 13
        font.weight: root.variant === "primary" ? Font.DemiBold : Font.Medium
    }

    MouseArea {
        id: area
        anchors.fill: parent
        hoverEnabled: true
        enabled: root.enabled
        cursorShape: Qt.PointingHandCursor
        onClicked: root.clicked()
    }
}
