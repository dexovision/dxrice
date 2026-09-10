import QtQuick
import QtQuick.Effects

// Compact icon-over-label toggle -- GNOME-quick-settings style (Wi-Fi,
// Bluetooth, DND, Keep Awake). `active` is a plain external property this
// binds to; the caller owns the actual on/off state and reacts to
// `toggled(next)`, matching the rest of this rice's "backend owns state,
// widget just reflects and requests changes" pattern.
Item {
    id: root
    property string glyph: ""
    property string label: ""
    property bool active: false
    signal toggled(bool next)

    implicitWidth: 72
    implicitHeight: 60

    RectangularShadow {
        anchors.fill: surface
        radius: surface.radius
        color: Theme.accentGlow
        blur: Theme.shadowBlurSm
        spread: 1
        opacity: root.active ? 0.6 : 0
        Behavior on opacity { NumberAnimation { duration: Theme.durationDefault; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveStandard } }
    }

    Rectangle {
        id: surface
        anchors.fill: parent
        radius: Theme.roundingLg
        scale: area.pressed ? 0.97 : 1.0
        gradient: Gradient {
            GradientStop {
                position: 0.0
                color: root.active
                    ? Theme.mix(Theme.accentSoft, Qt.rgba(1, 1, 1, 1), area.containsMouse ? 0.06 : 0.14)
                    : (area.containsMouse ? Theme.layer2Hover : Theme.layer1Hover)
            }
            GradientStop {
                position: 1.0
                color: root.active
                    ? Theme.mix(Theme.accentSoft, Qt.rgba(0, 0, 0, 1), area.containsMouse ? 0.1 : 0)
                    : (area.containsMouse ? Theme.layer2 : Theme.layer1)
            }
        }
        border.width: root.active ? 0 : 1
        border.color: Theme.borderIdle

        Behavior on scale {
            NumberAnimation { duration: Theme.durationFast; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveExpressiveFast }
        }

        MouseArea {
            id: area
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: root.toggled(!root.active)
        }
    }

    Column {
        anchors.centerIn: surface
        spacing: 4
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: root.glyph
            font.family: Theme.fontFamily
            font.pixelSize: 19
            color: root.active ? Theme.textActive : Theme.text
        }
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: root.label
            font.family: Theme.fontFamily
            font.pixelSize: 11
            font.weight: Font.Medium
            color: root.active ? Theme.textActive : Theme.text
        }
    }
}
