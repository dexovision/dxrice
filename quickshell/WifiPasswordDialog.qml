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

    ModalSurface {
        id: pwSurface
        anchors.fill: parent

        Column {
            anchors.fill: parent
            anchors.margins: Theme.padLg
            spacing: Theme.padMd

            Item {
                width: parent.width
                height: Math.max(pwTitle.implicitHeight, pwCloseBtn.height)
                Text {
                    id: pwTitle
                    anchors.verticalCenter: parent.verticalCenter
                    anchors.left: parent.left
                    anchors.right: pwCloseBtn.left
                    anchors.rightMargin: Theme.padSm
                    text: "Password for " + root.ssid
                    color: Theme.textActive
                    font.family: Theme.fontFamily
                    font.weight: Font.DemiBold
                    elide: Text.ElideRight
                }
                CloseButton {
                    id: pwCloseBtn
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    onClicked: root.visible = false
                }
            }
            Rectangle {
                width: parent.width; height: 34; radius: Theme.entryRadius
                color: Theme.inputFill
                border.width: Theme.borderWidth; border.color: Theme.borderIdle
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
