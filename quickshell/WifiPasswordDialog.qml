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
                width: parent.width; height: ShellSurface.rowHeight; radius: Theme.entryRadius
                color: Theme.inputFill
                border.width: Theme.borderWidth
                // Same focus treatment as the Add Shortcut fields.
                border.color: pwInput.activeFocus ? Theme.withAlpha(Theme.accent, 0.6) : Theme.borderIdle
                TextInput {
                    id: pwInput
                    anchors.fill: parent; anchors.leftMargin: Theme.padMd; anchors.rightMargin: Theme.padMd
                    color: Theme.textActive
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSizeNormal
                    echoMode: TextInput.Password
                    verticalAlignment: TextInput.AlignVCenter
                    clip: true
                    focus: true
                    onAccepted: if (text.length > 0) { root.submitted(text); root.visible = false; }
                }
                Text {
                    anchors.fill: pwInput
                    verticalAlignment: Text.AlignVCenter
                    visible: pwInput.text.length === 0
                    text: "Password"
                    color: Theme.text
                    opacity: Theme.opacityMuted
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSizeNormal
                }
            }
            Item {
                width: parent.width
                height: connectBtn.implicitHeight
                GlassButton {
                    id: connectBtn
                    anchors.right: parent.right
                    text: "Connect"
                    variant: "primary"
                    enabled: pwInput.text.length > 0
                    onClicked: { root.submitted(pwInput.text); root.visible = false; }
                }
            }
        }
    }
}
