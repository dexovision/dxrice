import QtQuick
import QtQuick.Effects
import Quickshell

FloatingWindow {
    id: root
    signal submitted(string password)
    property string ssid: ""
    title: "Connect to " + ssid
    color: "transparent"
    implicitWidth: 320
    implicitHeight: 160
    onVisibleChanged: if (!visible) root.destroy()

    Shortcut { sequence: "Escape"; onActivated: root.visible = false }

    RectangularShadow {
        anchors.fill: pwSurface
        radius: pwSurface.radius
        color: Theme.shadowColor
        blur: Theme.shadowBlurLg
        offset.y: 4
    }

    Rectangle {
        id: pwSurface
        anchors.fill: parent
        radius: Theme.roundingXl
        color: Theme.bg
        border.width: 1
        border.color: Theme.border

        Column {
            anchors.fill: parent
            anchors.margins: Theme.padLg
            spacing: Theme.padMd

            Text {
                text: "Password for " + root.ssid
                color: Theme.textActive
                font.family: Theme.fontFamily
                font.weight: Font.DemiBold
            }
            Rectangle {
                width: parent.width; height: 34; radius: Theme.entryRadius
                color: Qt.rgba(1, 1, 1, 0.06)
                border.width: 1; border.color: Theme.borderIdle
                TextInput {
                    id: pwInput
                    anchors.fill: parent; anchors.margins: 8
                    color: Theme.textActive
                    font.family: Theme.fontFamily
                    echoMode: TextInput.Password
                    verticalAlignment: TextInput.AlignVCenter
                    focus: true
                    onAccepted: { root.submitted(text); root.visible = false; }
                }
            }
            GlassButton {
                text: "Connect"
                variant: "primary"
                onClicked: { root.submitted(pwInput.text); root.visible = false; }
            }
        }
    }
}
