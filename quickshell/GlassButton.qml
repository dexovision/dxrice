import QtQuick

// Text button. variant: "primary" (accent-filled) or "secondary" (glass).
Rectangle {
    id: root
    property string text: ""
    property string variant: "secondary"
    // `enabled` is inherited from Item -- disabling it also correctly
    // stops the MouseArea below from receiving input, not just a name we
    // happen to reuse.
    signal clicked()

    implicitWidth: label.implicitWidth + Theme.padLg * 2
    implicitHeight: label.implicitHeight + Theme.padSm * 2
    radius: Theme.entryRadius
    opacity: root.enabled ? 1.0 : 0.5

    color: {
        if (root.variant === "primary") {
            return Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, area.pressed ? 1.0 : 0.9);
        }
        return area.containsMouse ? Theme.active : Theme.bgIdle;
    }
    border.width: 1
    border.color: root.variant === "primary" ? Theme.accent : Theme.borderIdle

    Behavior on color { ColorAnimation { duration: Theme.animMs } }

    Text {
        id: label
        anchors.centerIn: parent
        text: root.text
        color: root.variant === "primary" ? Theme.textActive : Theme.text
        font.family: Theme.fontFamily
        font.weight: root.variant === "primary" ? Font.DemiBold : Font.Normal
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
