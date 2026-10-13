import QtQuick
import QtQuick.Effects
import Quickshell

FloatingWindow {
    id: root
    signal submitted(string password)
    property string ssid: ""
    title: "Connect to " + ssid
    color: "transparent"
    implicitWidth: 380
    implicitHeight: content.implicitHeight + Theme.pad2xl * 2
    onVisibleChanged: if (!visible) root.destroy()

    Shortcut { sequence: "Escape"; onActivated: root.visible = false }

    function submit() {
        if (pwInput.text.length === 0) return;
        root.submitted(pwInput.text);
        root.visible = false;
    }

    ModalSurface {
        id: pwSurface
        objectName: "wifiDialogSurface"
        anchors.fill: parent

        Column {
            id: content
            x: Theme.pad2xl
            y: Theme.pad2xl
            width: parent.width - Theme.pad2xl * 2
            spacing: Theme.padLg

            // What this is and what it wants, in one glance: the network,
            // then the ask.
            Item {
                width: parent.width
                height: Math.max(headerText.implicitHeight, netIcon.height)
                Rectangle {
                    id: netIcon
                    width: 36; height: 36; radius: width / 2
                    color: Theme.layer2
                    anchors.verticalCenter: parent.verticalCenter
                    Text {
                        anchors.centerIn: parent
                        text: "\u{f05a9}"
                        color: Theme.textActive
                        font.family: Theme.iconFamily
                        font.pixelSize: Theme.fontSizeLarger
                    }
                }
                Column {
                    id: headerText
                    anchors.left: netIcon.right
                    anchors.leftMargin: Theme.padMd
                    anchors.right: pwCloseBtn.left
                    anchors.rightMargin: Theme.padSm
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 2
                    Text {
                        id: pwTitle
                        width: parent.width
                        text: root.ssid
                        color: Theme.textActive
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSizeLarger
                        font.weight: Font.DemiBold
                        elide: Text.ElideRight
                    }
                    Text {
                        width: parent.width
                        text: "This network needs a password"
                        color: Theme.text
                        opacity: Theme.opacitySecondary
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSizeSmaller
                        elide: Text.ElideRight
                    }
                }
                CloseButton {
                    id: pwCloseBtn
                    anchors.right: parent.right
                    anchors.top: parent.top
                    onClicked: root.visible = false
                }
            }

            InputField {
                id: pwField
                glyph: ""
                placeholder: "Password"
                input: pwInput
                TextInput {
                    id: pwInput
                    objectName: "wifiPasswordInput"
                    anchors.left: parent.left
                    anchors.right: revealBtn.left
                    anchors.rightMargin: Theme.padSm
                    anchors.verticalCenter: parent.verticalCenter
                    color: Theme.textActive
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSizeNormal
                    echoMode: revealBtn.revealed ? TextInput.Normal : TextInput.Password
                    passwordCharacter: "•"
                    verticalAlignment: TextInput.AlignVCenter
                    clip: true
                    focus: true
                    onAccepted: root.submit()
                }
                // Show/hide: a typo in a long Wi-Fi key is otherwise only
                // discovered by failing to connect.
                Text {
                    id: revealBtn
                    objectName: "wifiPasswordReveal"
                    property bool revealed: false
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    text: revealed ? "" : ""
                    color: Theme.text
                    opacity: revealArea.containsMouse ? 1 : Theme.opacitySecondary
                    font.family: Theme.iconFamily
                    font.pixelSize: Theme.fontSizeNormal
                    Behavior on opacity { NumberAnimation { duration: Theme.durationFast; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveStandard } }
                    MouseArea {
                        id: revealArea
                        anchors.fill: parent
                        anchors.margins: -6
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: revealBtn.revealed = !revealBtn.revealed
                    }
                }
            }

            Row {
                anchors.right: parent.right
                spacing: Theme.padSm
                GlassButton {
                    text: "Cancel"
                    onClicked: root.visible = false
                }
                GlassButton {
                    id: connectBtn
                    objectName: "wifiConnect"
                    text: "Connect"
                    variant: "primary"
                    enabled: pwInput.text.length > 0
                    onClicked: root.submit()
                }
            }
        }
    }
}
