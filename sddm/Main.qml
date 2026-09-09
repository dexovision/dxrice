// DXrice SDDM greeter theme.
//
// Plain QtQuick + QtQuick.Controls.Basic + QtQuick.Layouts only -- no KDE
// Plasma frameworks, no legacy SddmComponents module -- so this works on
// any Qt6-only install (this rice targets QtVersion=6 in metadata.desktop
// since a Qt5-only greeter binary isn't guaranteed to exist).
//
// Colors/radius/font/animation timing all come from theme.conf (rendered
// from the user's live theme.json by dxrice_sync_sddm_theme.py), read here
// via the `config` object SDDM exposes -- so this screen matches whatever
// look the rest of the desktop currently has, not a value hardcoded here.
// The background is a pre-blurred copy of the wallpaper (blurred once at
// sync time, not live-shaded), so this has zero GPU shader dependency.
import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

Item {
    id: root
    width: 1920
    height: 1080

    readonly property color bgColor: config.stringValue("BackgroundColor") || "#12141a"
    readonly property color cardColor: config.stringValue("CardColor") || "#12141a"
    readonly property real cardOpacity: config.realValue("CardOpacity") || 0.85
    readonly property color borderColor: config.stringValue("BorderColor") || "#ffffff"
    readonly property real borderOpacity: config.realValue("BorderOpacity") || 0.25
    readonly property color accentColor: config.stringValue("AccentColor") || "#e67878"
    readonly property color textColor: config.stringValue("TextColor") || "#e6e6e6"
    readonly property color textActiveColor: config.stringValue("TextActiveColor") || "#ffffff"
    readonly property real cornerRadius: config.realValue("Radius") || 12
    readonly property string fontFamily: config.stringValue("FontFamily") || "sans-serif"
    readonly property int animMs: config.intValue("AnimMs") || 150

    // ---- background: pre-blurred wallpaper, dark scrim for legibility ----

    Image {
        id: bg
        anchors.fill: parent
        fillMode: Image.PreserveAspectCrop
        asynchronous: true
        source: {
            var p = config.stringValue("Background")
            return p ? "file://" + p : ""
        }
        onStatusChanged: {
            if (status === Image.Error) {
                source = ""
            }
        }
    }

    Rectangle {
        anchors.fill: parent
        visible: bg.status !== Image.Ready
        color: root.bgColor
    }

    Rectangle {
        anchors.fill: parent
        color: "black"
        opacity: 0.28
    }

    // ---- clock ----

    Column {
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: card.top
        anchors.bottomMargin: 36
        spacing: 2
        opacity: 0
        Behavior on opacity { NumberAnimation { duration: root.animMs * 3; easing.type: Easing.OutCubic } }
        Component.onCompleted: opacity = 1

        Text {
            id: clockText
            anchors.horizontalCenter: parent.horizontalCenter
            color: root.textActiveColor
            font.family: root.fontFamily
            font.pixelSize: 56
            font.weight: Font.Light
        }
        Text {
            id: dateText
            anchors.horizontalCenter: parent.horizontalCenter
            color: root.textColor
            font.family: root.fontFamily
            font.pixelSize: 16
            opacity: 0.85
        }
    }

    Timer {
        interval: 1000
        running: true
        repeat: true
        triggeredOnStart: true
        onTriggered: {
            var now = new Date()
            clockText.text = Qt.formatTime(now, "h:mm AP")
            dateText.text = Qt.formatDate(now, "dddd, MMMM d")
        }
    }

    // ---- login card ----

    Rectangle {
        id: card
        anchors.centerIn: parent
        width: 360
        implicitHeight: cardLayout.implicitHeight + 48
        height: implicitHeight
        radius: root.cornerRadius
        color: Qt.rgba(root.cardColor.r, root.cardColor.g, root.cardColor.b, root.cardOpacity)
        border.width: 1
        border.color: Qt.rgba(root.borderColor.r, root.borderColor.g, root.borderColor.b, root.borderOpacity)

        opacity: 0
        scale: 0.96
        Behavior on opacity { NumberAnimation { duration: root.animMs * 4; easing.type: Easing.OutCubic } }
        Behavior on scale { NumberAnimation { duration: root.animMs * 4; easing.type: Easing.OutCubic } }
        Component.onCompleted: { opacity = 1; scale = 1 }

        ColumnLayout {
            id: cardLayout
            anchors.centerIn: parent
            width: parent.width - 48
            spacing: 14

            Text {
                Layout.alignment: Qt.AlignHCenter
                text: "Welcome back"
                color: root.textActiveColor
                font.family: root.fontFamily
                font.pixelSize: 20
                font.weight: Font.DemiBold
            }

            Text {
                Layout.alignment: Qt.AlignHCenter
                text: sddm.hostName
                color: root.textColor
                opacity: 0.7
                font.family: root.fontFamily
                font.pixelSize: 12
            }

            ComboBox {
                id: userBox
                Layout.fillWidth: true
                model: userModel
                textRole: "name"
                currentIndex: userModel.lastIndex >= 0 ? userModel.lastIndex : 0

                background: Rectangle {
                    radius: Math.max(0, root.cornerRadius - 2)
                    color: Qt.rgba(1, 1, 1, 0.06)
                    border.width: 1
                    border.color: Qt.rgba(root.borderColor.r, root.borderColor.g, root.borderColor.b, root.borderOpacity)
                }
                contentItem: Text {
                    text: userBox.displayText
                    color: root.textActiveColor
                    font.family: root.fontFamily
                    verticalAlignment: Text.AlignVCenter
                    leftPadding: 12
                }
                popup.background: Rectangle {
                    radius: Math.max(0, root.cornerRadius - 2)
                    color: root.bgColor
                    border.width: 1
                    border.color: Qt.rgba(root.borderColor.r, root.borderColor.g, root.borderColor.b, root.borderOpacity)
                }
                delegate: ItemDelegate {
                    width: userBox.width
                    contentItem: Text {
                        text: model.name
                        color: root.textActiveColor
                        font.family: root.fontFamily
                        verticalAlignment: Text.AlignVCenter
                    }
                    highlighted: userBox.highlightedIndex === index
                }
            }

            TextField {
                id: passwordField
                Layout.fillWidth: true
                placeholderText: "Password"
                echoMode: TextInput.Password
                color: root.textActiveColor
                font.family: root.fontFamily
                selectByMouse: true
                focus: true

                background: Rectangle {
                    radius: Math.max(0, root.cornerRadius - 2)
                    color: Qt.rgba(1, 1, 1, 0.06)
                    border.width: 1
                    border.color: passwordField.activeFocus
                        ? root.accentColor
                        : Qt.rgba(root.borderColor.r, root.borderColor.g, root.borderColor.b, root.borderOpacity)
                    Behavior on border.color { ColorAnimation { duration: root.animMs } }
                }
                leftPadding: 12
                rightPadding: 12
                topPadding: 10
                bottomPadding: 10

                onAccepted: root.startLogin()

                Timer {
                    interval: 200
                    running: true
                    onTriggered: passwordField.forceActiveFocus()
                }
            }

            Text {
                id: messageText
                Layout.fillWidth: true
                Layout.alignment: Qt.AlignHCenter
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.WordWrap
                text: ""
                color: root.accentColor
                font.family: root.fontFamily
                font.pixelSize: 12
                visible: text.length > 0
            }

            Button {
                id: loginButton
                Layout.fillWidth: true
                text: "Log In"

                background: Rectangle {
                    radius: Math.max(0, root.cornerRadius - 2)
                    color: Qt.rgba(root.accentColor.r, root.accentColor.g, root.accentColor.b,
                                   loginButton.pressed ? 1.0 : 0.9)
                    Behavior on color { ColorAnimation { duration: root.animMs } }
                }
                contentItem: Text {
                    text: loginButton.text
                    color: root.textActiveColor
                    font.family: root.fontFamily
                    font.weight: Font.DemiBold
                    horizontalAlignment: Text.AlignHCenter
                }
                topPadding: 10
                bottomPadding: 10

                onClicked: root.startLogin()
            }

            RowLayout {
                Layout.fillWidth: true
                Layout.topMargin: 4
                visible: sessionModel.count > 1

                Text {
                    text: "Session"
                    color: root.textColor
                    opacity: 0.7
                    font.family: root.fontFamily
                    font.pixelSize: 11
                }

                ComboBox {
                    id: sessionBox
                    Layout.fillWidth: true
                    model: sessionModel
                    textRole: "name"
                    currentIndex: sessionModel.lastIndex >= 0 ? sessionModel.lastIndex : 0
                    background: Rectangle { color: "transparent" }
                    contentItem: Text {
                        text: sessionBox.displayText
                        color: root.textColor
                        font.family: root.fontFamily
                        font.pixelSize: 11
                        horizontalAlignment: Text.AlignRight
                        verticalAlignment: Text.AlignVCenter
                    }
                    popup.background: Rectangle {
                        radius: Math.max(0, root.cornerRadius - 2)
                        color: root.bgColor
                        border.width: 1
                        border.color: Qt.rgba(root.borderColor.r, root.borderColor.g, root.borderColor.b, root.borderOpacity)
                    }
                    delegate: ItemDelegate {
                        width: sessionBox.width
                        contentItem: Text {
                            text: model.name
                            color: root.textActiveColor
                            font.family: root.fontFamily
                            verticalAlignment: Text.AlignVCenter
                        }
                        highlighted: sessionBox.highlightedIndex === index
                    }
                }
            }
        }
    }

    // ---- power row ----

    Row {
        anchors.bottom: parent.bottom
        anchors.right: parent.right
        anchors.margins: 24
        spacing: 12

        PowerGlyph { glyph: "⏻"; tooltip: "Shut down"; visible: sddm.canPowerOff; onActivated: sddm.powerOff() }
        PowerGlyph { glyph: "⟳"; tooltip: "Restart"; visible: sddm.canReboot; onActivated: sddm.reboot() }
        PowerGlyph { glyph: "⏾"; tooltip: "Suspend"; visible: sddm.canSuspend; onActivated: sddm.suspend() }
    }

    function startLogin() {
        messageText.text = ""
        passwordField.enabled = false
        loginButton.enabled = false
        sddm.login(userBox.currentText, passwordField.text, sessionBox.visible ? sessionBox.currentIndex : sessionModel.lastIndex)
    }

    Connections {
        target: sddm
        function onLoginFailed() {
            messageText.text = "Incorrect password"
            passwordField.text = ""
            passwordField.enabled = true
            loginButton.enabled = true
            passwordField.forceActiveFocus()
        }
        function onInformationMessage(message) {
            messageText.text = message
        }
    }

    component PowerGlyph: Rectangle {
        id: glyphRoot
        property string glyph: ""
        property string tooltip: ""
        signal activated()

        width: 40
        height: 40
        radius: width / 2
        color: Qt.rgba(1, 1, 1, glyphArea.containsMouse ? 0.14 : 0.06)
        Behavior on color { ColorAnimation { duration: root.animMs } }

        Text {
            anchors.centerIn: parent
            text: glyphRoot.glyph
            color: root.textActiveColor
            font.pixelSize: 18
        }

        MouseArea {
            id: glyphArea
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: glyphRoot.activated()
        }
    }
}
