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
// variant "danger" is for the one irreversible action on a screen (forget a
// network, remove something): neutral at rest like every other secondary
// button, red only in its label and, under the pointer, a red-tinted fill
// -- the warning arrives as you reach for it. `busy` keeps the button's
// size, swaps the label for LoadingDots and stops it taking clicks, so
// "Applying..." can't be pressed twice or make the header jump.
Rectangle {
    id: root
    property string text: ""
    property string variant: "secondary"
    property bool badge: false
    property bool busy: false
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
    opacity: root.enabled ? 1.0 : 0.45
    Behavior on opacity { NumberAnimation { duration: Theme.durationFast; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveStandard } }
    scale: Theme.pressScale(area.pressed)

    color: {
        if (root.variant === "primary") {
            if (area.pressed) return Theme.mix(Theme.textActive, Theme.panelTone, 0.22);
            return area.containsMouse ? Theme.mix(Theme.textActive, Theme.panelTone, 0.1) : Theme.textActive;
        }
        if (root.variant === "danger" && (area.containsMouse || area.pressed))
            return Theme.mix(Theme.layer1, Theme.dangerTint, area.pressed ? 0.34 : 0.24);
        if (area.pressed) return Theme.layer2Active;
        return area.containsMouse ? Theme.layer2Hover : Theme.layer1;
    }

    Behavior on color {
        ColorAnimation { duration: Theme.durationFast; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveStandard }
    }
    Behavior on scale {
        NumberAnimation { duration: Theme.durationMove; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveExpressiveFast }
    }

    Text {
        id: label
        anchors.centerIn: parent
        text: root.text
        color: root.variant === "primary" ? Theme.panelTone
             : root.variant === "danger" ? Theme.mix(Theme.textActive, Theme.dangerTint, 0.55) : Theme.text
        opacity: root.busy ? 0 : 1
        Behavior on opacity { NumberAnimation { duration: Theme.durationFast; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveStandard } }
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fontSizeNormal
        font.weight: root.variant === "primary" ? Font.DemiBold : Font.Medium
    }

    LoadingDots {
        anchors.centerIn: parent
        visible: root.busy
        color: root.variant === "primary" ? Theme.panelTone : Theme.text
    }

    Rectangle {
        visible: root.badge && !root.busy
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
        enabled: root.enabled && !root.busy
        cursorShape: Qt.PointingHandCursor
        onClicked: root.clicked()
    }
}
