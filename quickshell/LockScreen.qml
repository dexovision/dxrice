import QtQuick
import QtQuick.Effects
import Quickshell
import Quickshell.Wayland
import Quickshell.Services.Pam

// DXrice lock screen -- a real Wayland session lock (ext-session-lock-v1),
// not a regular window: once `locked` is true, a conformant compositor
// guarantees nothing behind it is visible or reachable until this code
// itself sets `locked` back to false, matching hyprlock's own security
// model exactly (same PAM stack: /etc/pam.d/hyprlock).
//
// IMPORTANT: per Quickshell's own docs, if this component (or the whole
// Quickshell process) dies while locked, the compositor leaves the screen
// SECURELY locked rather than exposing the session -- that's the point of
// the protocol, not a bug, but it means there is no "just kill the
// process to get back in" escape hatch the way there is for a normal
// window. If this ever refuses to unlock with a correct password, switch
// to a different TTY (Ctrl+Alt+F3 or similar), log in there, and restart
// the graphical session (or `loginctl terminate-session`) -- the same
// recovery path that applies to any Wayland session lock, hyprlock
// included, if its client crashes mid-lock.
WlSessionLock {
    id: lock

    surface: Component {
        WlSessionLockSurface {
            id: surfaceRoot
            color: "black"

            readonly property bool isPrimary: screen === Quickshell.screens[0]

            Image {
                id: bg
                anchors.fill: parent
                fillMode: Image.PreserveAspectCrop
                asynchronous: true
                source: Theme.wallpaper ? "file://" + Theme.wallpaper : ""
                visible: status === Image.Ready
            }
            Rectangle { anchors.fill: parent; color: "black"; opacity: 0.4 }

            PamContext {
                id: pam
                objectName: "lockPam"
                config: "hyprlock"
                property string pendingPassword: ""

                onPamMessage: {
                    if (responseRequired) pam.respond(pam.pendingPassword);
                }
                onCompleted: (result) => {
                    if (result === PamResult.Success) {
                        lock.locked = false;
                    } else {
                        passwordField.text = "";
                        passwordField.enabled = true;
                        messageText.text = "Incorrect password";
                        // Under reduce_motion the message alone says it.
                        if (!Theme.reduceMotion) shakeAnim.start();
                    }
                }
                onError: (err) => {
                    passwordField.enabled = true;
                    messageText.text = "Auth error: " + PamError.toString(err);
                }
            }

            function tryUnlock() {
                if (pam.active || passwordField.text.length === 0) return;
                messageText.text = "";
                passwordField.enabled = false;
                pam.pendingPassword = passwordField.text;
                pam.start();
            }

            // Arrival: the clock and the card settle into place as the lock
            // comes up (fade only under reduce_motion).
            property real arrive: 0
            Behavior on arrive {
                NumberAnimation { duration: Theme.durationEnter * 1.6; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveEnter }
            }

            Column {
                id: clockColumn
                anchors.horizontalCenter: parent.horizontalCenter
                y: parent.height * 0.24 + (1 - surfaceRoot.arrive) * Theme.contentShift * 3
                opacity: surfaceRoot.arrive
                spacing: 4
                visible: surfaceRoot.isPrimary

                Text {
                    id: clockText
                    anchors.horizontalCenter: parent.horizontalCenter
                    color: Theme.textActive
                    font.family: Theme.fontFamily
                    // The lock screen's clock dominates the screen: a
                    // step above Quick Settings' hero clock, in the light
                    // weight a proportional face carries well at this size.
                    font.pixelSize: Math.round(Theme.fontSizeHero * 1.4)
                    font.weight: Font.Light
                    font.features: { "tnum": 1 }
                }
                Text {
                    id: dateText
                    anchors.horizontalCenter: parent.horizontalCenter
                    color: Theme.textActive
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSizeLarge
                    opacity: Theme.opacityFaint
                }
            }

            Timer {
                interval: 1000
                running: true
                repeat: true
                triggeredOnStart: true
                onTriggered: {
                    const now = new Date();
                    // 24-hour, like the bar and Quick Settings.
                    clockText.text = Qt.formatTime(now, "HH:mm");
                    dateText.text = Qt.formatDate(now, "dddd, MMMM d");
                }
            }

            // ---- scattered information zones -- the same real data used
            // in Quick Settings (no fabricated widgets: this shell has no
            // weather source, so it isn't pretending to have one), placed
            // in the corners around the clock instead of one single card
            // holding everything. Purely additive to the surface: nothing
            // here touches PamContext or tryUnlock(). ----
            SystemInfoBackend { id: systemInfo }
            WorldClockBackend { id: worldClock }
            MediaBackend { id: mediaBackend }

            Column {
                visible: surfaceRoot.isPrimary
                anchors.left: parent.left
                anchors.top: parent.top
                anchors.margins: Theme.pad3xl
                spacing: Theme.padXs
                Text {
                    text: "This device"
                    color: Theme.text
                    opacity: 0.55
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSizeSmall
                }
                Text {
                    text: systemInfo.osName + " · " + systemInfo.kernel
                    color: Theme.textActive
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSizeSmaller
                }
                Text {
                    text: systemInfo.hostname + " · up " + systemInfo.uptime
                    color: Theme.text
                    opacity: 0.7
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSizeSmaller
                }
            }

            Column {
                visible: surfaceRoot.isPrimary
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.margins: Theme.pad3xl
                spacing: Theme.padXs
                Text {
                    text: "World clock"
                    color: Theme.text
                    opacity: 0.55
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSizeSmall
                    anchors.right: parent.right
                }
                Repeater {
                    model: worldClock.cities
                    delegate: Row {
                        anchors.right: parent.right
                        spacing: Theme.padSm
                        Text { text: modelData.label; color: Theme.text; opacity: 0.85; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSmaller }
                        Text { text: modelData.time; color: Theme.textActive; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSmaller }
                    }
                }
            }

            Row {
                visible: surfaceRoot.isPrimary && mediaBackend.available
                anchors.left: parent.left
                anchors.bottom: parent.bottom
                anchors.margins: Theme.pad3xl
                spacing: Theme.padMd

                IconButton { anchors.verticalCenter: parent.verticalCenter; glyph: ""; size: 30; onClicked: mediaBackend.previous() }
                IconButton { anchors.verticalCenter: parent.verticalCenter; glyph: mediaBackend.playing ? "" : ""; size: 34; onClicked: mediaBackend.playPause() }
                IconButton { anchors.verticalCenter: parent.verticalCenter; glyph: ""; size: 30; onClicked: mediaBackend.next() }

                Column {
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 2
                    Text {
                        text: mediaBackend.title
                        color: Theme.textActive
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSizeNormal
                        elide: Text.ElideRight
                        width: 240
                    }
                    Text {
                        visible: mediaBackend.artist.length > 0
                        text: mediaBackend.artist
                        color: Theme.text
                        opacity: 0.65
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSizeSmaller
                        elide: Text.ElideRight
                        width: 240
                    }
                }
            }

            Item {
                id: card
                visible: surfaceRoot.isPrimary
                anchors.horizontalCenter: parent.horizontalCenter
                y: parent.height * 0.24 + clockColumn.implicitHeight + Theme.pad3xl * 1.5 + (1 - surfaceRoot.arrive) * Theme.contentShift * 4
                opacity: surfaceRoot.arrive
                width: 340
                height: cardColumn.implicitHeight + Theme.pad2xl * 2
                x: shakeAnim.running ? shakeAnim.offset : 0

                SequentialAnimation {
                    id: shakeAnim
                    objectName: "lockShake"
                    property real offset: 0
                    loops: 1
                    NumberAnimation { target: shakeAnim; property: "offset"; from: 0; to: -10; duration: 50 }
                    NumberAnimation { target: shakeAnim; property: "offset"; from: -10; to: 10; duration: 50 }
                    NumberAnimation { target: shakeAnim; property: "offset"; from: 10; to: -6; duration: 50 }
                    NumberAnimation { target: shakeAnim; property: "offset"; from: -6; to: 0; duration: 50 }
                }

                ModalSurface {
                    id: cardSurface
                    anchors.fill: parent

                    Column {
                        id: cardColumn
                        x: Theme.pad2xl
                        y: Theme.pad2xl
                        width: parent.width - Theme.pad2xl * 2
                        spacing: Theme.padMd

                        // Who is being unlocked: an initial in a quiet disc,
                        // the name under it -- centred, so the card reads as
                        // one object rather than a form with a heading.
                        Rectangle {
                            anchors.horizontalCenter: parent.horizontalCenter
                            width: 52; height: 52; radius: width / 2
                            color: Theme.layer2
                            border.width: Theme.borderWidth
                            border.color: Theme.cardBorder
                            Text {
                                anchors.centerIn: parent
                                text: (Quickshell.env("USER") || "?").charAt(0).toUpperCase()
                                color: Theme.textActive
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSizeLarge
                                font.weight: Font.DemiBold
                            }
                        }
                        Text {
                            text: "Welcome back, " + Quickshell.env("USER")
                            color: Theme.textActive
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSizeLarger
                            font.weight: Font.DemiBold
                            width: parent.width
                            horizontalAlignment: Text.AlignHCenter
                            elide: Text.ElideRight
                        }

                        Rectangle {
                            id: field
                            readonly property bool checking: pam.active
                            readonly property bool failed: messageText.text.length > 0 && !checking
                            width: parent.width
                            height: 40
                            radius: height / 2
                            color: Theme.inputFill
                            border.width: Theme.borderWidth
                            border.color: field.failed ? Theme.withAlpha(Theme.dangerTint, 0.7)
                                : passwordField.activeFocus ? Theme.accent : Theme.borderIdle
                            Behavior on border.color {
                                ColorAnimation { duration: Theme.durationFast; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveStandard }
                            }

                            TextInput {
                                id: passwordField
                                anchors.left: parent.left
                                anchors.right: submit.left
                                anchors.leftMargin: Theme.padLg
                                anchors.rightMargin: Theme.padSm
                                anchors.verticalCenter: parent.verticalCenter
                                color: Theme.textActive
                                opacity: field.checking ? 0.5 : 1
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSizeNormal
                                echoMode: TextInput.Password
                                passwordCharacter: "\u2022"
                                verticalAlignment: TextInput.AlignVCenter
                                clip: true
                                focus: surfaceRoot.isPrimary
                                onAccepted: surfaceRoot.tryUnlock()
                                onTextChanged: if (text.length > 0 && !field.checking) messageText.text = ""
                            }
                            Text {
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSizeNormal
                                text: "Password"
                                color: Theme.text
                                opacity: passwordField.text.length ? 0 : Theme.opacityMuted
                                anchors.left: parent.left
                                anchors.leftMargin: Theme.padLg
                                anchors.verticalCenter: parent.verticalCenter
                            }
                            // Submit: an arrow while there's something to
                            // send, the shell's LoadingDots while PAM checks.
                            Rectangle {
                                id: submit
                                objectName: "lockSubmit"
                                anchors.right: parent.right
                                anchors.rightMargin: 4
                                anchors.verticalCenter: parent.verticalCenter
                                width: parent.height - 8; height: width; radius: width / 2
                                readonly property bool ready: passwordField.text.length > 0 && !field.checking
                                color: submit.ready ? Theme.stateFill(Theme.textActive, false, submitArea.pressed)
                                                    : Theme.stateFill(Theme.layer1, submitArea.containsMouse, false)
                                scale: Theme.pressScale(submitArea.pressed, 0.92)
                                Behavior on color { ColorAnimation { duration: Theme.durationFast; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveStandard } }
                                Behavior on scale { NumberAnimation { duration: Theme.durationMove; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveExpressiveFast } }
                                Text {
                                    anchors.centerIn: parent
                                    visible: !field.checking
                                    text: "\u2192"
                                    color: submit.ready ? Theme.panelTone : Theme.text
                                    opacity: submit.ready ? 1 : Theme.opacityMuted
                                    font.family: Theme.fontFamily
                                    font.pixelSize: Theme.fontSizeLarger
                                    font.weight: Font.DemiBold
                                }
                                LoadingDots {
                                    anchors.centerIn: parent
                                    visible: field.checking
                                    dotSize: 4
                                    color: Theme.text
                                }
                                MouseArea {
                                    id: submitArea
                                    anchors.fill: parent
                                    hoverEnabled: true
                                    cursorShape: submit.ready ? Qt.PointingHandCursor : Qt.ArrowCursor
                                    onClicked: surfaceRoot.tryUnlock()
                                }
                            }
                        }

                        Text {
                            id: messageText
                            text: ""
                            color: Theme.mix(Theme.textActive, Theme.dangerTint, 0.6)
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSizeSmaller
                            visible: text.length > 0
                            width: parent.width
                            horizontalAlignment: Text.AlignHCenter
                            wrapMode: Text.WordWrap
                        }
                        Text {
                            visible: messageText.text.length === 0
                            text: field.checking ? "Checking\u2026" : "Enter to unlock"
                            color: Theme.text
                            opacity: Theme.opacityMuted
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSizeSmall
                            width: parent.width
                            horizontalAlignment: Text.AlignHCenter
                        }
                    }
                }
            }

            Component.onCompleted: {
                surfaceRoot.arrive = 1;
                if (surfaceRoot.isPrimary) passwordField.forceActiveFocus();
            }
        }
    }
}
