import QtQuick
import QtQuick.Effects

// Text button. variant: "primary" (accent-filled pill, for the one action
// that matters on a screen) or "secondary" (glass, everything else) --
// mirrors Material's filled-vs-tonal button distinction rather than
// giving every button the same weight.
Item {
    id: root
    property string text: ""
    property string variant: "secondary"
    // `enabled` is inherited from Item -- disabling it also correctly
    // stops the MouseArea below from receiving input, not just a name we
    // happen to reuse.
    signal clicked()

    implicitWidth: label.implicitWidth + Theme.padXl * 2
    implicitHeight: label.implicitHeight + Theme.padMd * 2
    opacity: root.enabled ? 1.0 : 0.5

    RectangularShadow {
        anchors.fill: surface
        radius: surface.radius
        color: Theme.accentGlow
        blur: Theme.shadowBlurSm
        spread: 1
        visible: root.variant === "primary"
        opacity: area.pressed ? 0.25 : 0.5
        Behavior on opacity { NumberAnimation { duration: Theme.durationDefault; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveStandard } }
    }

    Rectangle {
        id: surface
        anchors.fill: parent
        radius: root.variant === "primary" ? Theme.roundingFull : Theme.roundingSm
        scale: area.pressed ? 0.96 : 1.0

        gradient: root.variant === "primary" ? primaryGradient : secondaryGradient
        Gradient {
            id: primaryGradient
            GradientStop { position: 0.0; color: area.pressed ? Theme.accent : Theme.mix(Theme.accent, Qt.rgba(1, 1, 1, 1), 0.16) }
            GradientStop { position: 1.0; color: area.pressed ? Theme.mix(Theme.accent, Qt.rgba(0, 0, 0, 1), 0.12) : Theme.accent }
        }
        Gradient {
            id: secondaryGradient
            GradientStop { position: 0.0; color: area.pressed ? Theme.layer2Active : (area.containsMouse ? Theme.layer2Hover : Theme.layer1) }
            GradientStop { position: 1.0; color: area.pressed ? Theme.layer2 : (area.containsMouse ? Theme.layer2 : Theme.layer1) }
        }

        border.width: 1
        border.color: root.variant === "primary" ? Qt.rgba(1, 1, 1, 0.18) : Theme.borderIdle

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
}
