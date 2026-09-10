import QtQuick
import QtQuick.Effects

// Compact icon-badge-over-label toggle -- GNOME/mango-quick-settings style
// (Wi-Fi, Bluetooth, DND, Keep Awake). `active` is a plain external
// property this binds to; the caller owns the actual on/off state and
// reacts to `toggled(next)`, matching the rest of this rice's "backend
// owns state, widget just reflects and requests changes" pattern.
Item {
    id: root
    property string glyph: ""
    property string label: ""
    property bool active: false
    signal toggled(bool next)

    implicitWidth: 76
    implicitHeight: 78

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
        scale: area.pressed ? 0.96 : 1.0
        gradient: Gradient {
            GradientStop { position: 0.0; color: area.containsMouse ? Theme.layer2Hover : Theme.layer1Hover }
            GradientStop { position: 1.0; color: area.containsMouse ? Theme.layer2 : Theme.layer1 }
        }
        border.width: 1
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
        spacing: 6

        Rectangle {
            id: badge
            anchors.horizontalCenter: parent.horizontalCenter
            width: 30
            height: 30
            radius: Theme.roundingFull
            gradient: Gradient {
                GradientStop { position: 0.0; color: root.active ? Theme.mix(Theme.accent, Qt.rgba(1, 1, 1, 1), 0.2) : Theme.layer2 }
                GradientStop { position: 1.0; color: root.active ? Theme.accent : Theme.layer1 }
            }
            Behavior on opacity { NumberAnimation { duration: Theme.durationFast } }

            Text {
                anchors.centerIn: parent
                text: root.glyph
                font.family: Theme.fontFamily
                font.pixelSize: 15
                color: root.active ? Theme.textActive : Theme.text
            }
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
