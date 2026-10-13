import QtQuick

// Text button. variant: "primary" (the one action that matters on a
// screen) or "secondary" (glass, everything else) -- filled-vs-tonal, so
// buttons don't all carry the same weight. Flat fill, no border, no
// gradient. The primary fill is high-contrast NEUTRAL (the text colour,
// with the panel tone as its label), not the accent: the shell's accent is
// reserved for small marks -- a selection, an indicator dot, a progress
// fill -- never the fill of a whole control, so a green or blue wallpaper
// accent can't turn every dialog's main button into a coloured slab.
// `badge` adds a small accent dot (e.g. "there is something to apply").
Rectangle {
    id: root
    property string text: ""
    property string variant: "secondary"
    property bool badge: false
    // `enabled` is inherited from Item -- disabling it also correctly
    // stops the MouseArea below from receiving input, not just a name we
    // happen to reuse.
    signal clicked()

    implicitWidth: label.implicitWidth + Theme.pad2xl * 2
    implicitHeight: label.implicitHeight + Theme.padMd * 2
    // One shape for every button, the shell's pill: a primary pill next to
    // a rounded-rect secondary (Apply / Revert) read as two different kinds
    // of control.
    radius: height / 2
    opacity: root.enabled ? 1.0 : 0.5
    scale: area.pressed ? 0.96 : 1.0

    color: {
        if (root.variant === "primary") {
            if (area.pressed) return Theme.mix(Theme.textActive, Theme.panelTone, 0.22);
            return area.containsMouse ? Theme.mix(Theme.textActive, Theme.panelTone, 0.1) : Theme.textActive;
        }
        if (area.pressed) return Theme.layer2Active;
        return area.containsMouse ? Theme.layer2Hover : Theme.layer1;
    }

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
        color: root.variant === "primary" ? Theme.panelTone : Theme.text
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fontSizeNormal
        font.weight: root.variant === "primary" ? Font.DemiBold : Font.Medium
    }

    Rectangle {
        visible: root.badge
        width: 6; height: 6; radius: 3
        color: Theme.accent
        anchors.right: parent.right
        anchors.rightMargin: Theme.padMd
        anchors.verticalCenter: parent.verticalCenter
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
