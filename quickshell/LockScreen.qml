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
                        shakeAnim.start();
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

            Column {
                anchors.horizontalCenter: parent.horizontalCenter
                y: parent.height * 0.28
                spacing: 4
                visible: surfaceRoot.isPrimary

                Text {
                    id: clockText
                    anchors.horizontalCenter: parent.horizontalCenter
                    color: Theme.textActive
                    font.family: Theme.fontFamily
                    // The one deliberately huge display size in this whole
                    // shell -- a lock screen clock is meant to dominate,
                    // same as every reference rice's own lock screen.
                    font.pixelSize: 72
                    font.weight: Font.Light
                }
                Text {
                    id: dateText
                    anchors.horizontalCenter: parent.horizontalCenter
                    color: Theme.text
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSizeLarger
                    opacity: 0.85
                }
            }

            Timer {
                interval: 1000
                running: true
                repeat: true
                triggeredOnStart: true
                onTriggered: {
                    const now = new Date();
                    clockText.text = Qt.formatTime(now, "h:mm AP");
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
                y: parent.height * 0.28 + 160
                width: 320
                height: cardColumn.implicitHeight + Theme.pad2xl * 2
                x: shakeAnim.running ? shakeAnim.offset : 0

                SequentialAnimation {
                    id: shakeAnim
                    property real offset: 0
                    loops: 1
                    NumberAnimation { target: shakeAnim; property: "offset"; from: 0; to: -10; duration: 50 }
                    NumberAnimation { target: shakeAnim; property: "offset"; from: -10; to: 10; duration: 50 }
                    NumberAnimation { target: shakeAnim; property: "offset"; from: 10; to: -6; duration: 50 }
                    NumberAnimation { target: shakeAnim; property: "offset"; from: -6; to: 0; duration: 50 }
                }

                RectangularShadow {
                    anchors.fill: cardSurface
                    radius: cardSurface.radius
                    color: Theme.shadowColor
                    blur: Theme.elevationBlur(3)
                    spread: Theme.elevationSpread(3)
                    offset.y: Theme.elevationOffsetY(3)
                }

                Rectangle {
                    id: cardSurface
                    anchors.fill: parent
                    radius: Theme.roundingXl
                    color: Theme.bg
                    border.width: 1
                    border.color: Theme.border

                    Column {
                        id: cardColumn
                        x: Theme.pad2xl
                        y: Theme.pad2xl
                        width: parent.width - Theme.pad2xl * 2
                        spacing: Theme.padMd

                        Text {
                            text: "Welcome back, " + Quickshell.env("USER")
                            color: Theme.textActive
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSizeLarger
                            font.weight: Font.DemiBold
                            width: parent.width
                            elide: Text.ElideRight
                        }

                        Rectangle {
                            width: parent.width
                            height: 38
                            radius: Theme.roundingSm
                            color: Theme.inputFill
                            border.width: Theme.borderWidth
                            border.color: passwordField.activeFocus
                                ? Theme.accent
                                : Theme.borderIdle
                            Behavior on border.color {
                                ColorAnimation { duration: Theme.durationFast; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveStandard }
                            }

                            TextInput {
                                id: passwordField
                                anchors.fill: parent
                                anchors.margins: 10
                                color: Theme.textActive
                                font.family: Theme.fontFamily
                                echoMode: TextInput.Password
                                verticalAlignment: TextInput.AlignVCenter
                                focus: surfaceRoot.isPrimary
                                onAccepted: surfaceRoot.tryUnlock()
                            }
                            Text {
                                text: "Password"
                                color: Theme.text
                                opacity: passwordField.text.length ? 0 : 0.5
                                anchors.left: parent.left
                                anchors.leftMargin: 10
                                anchors.verticalCenter: parent.verticalCenter
                            }
                        }

                        Text {
                            id: messageText
                            text: ""
                            color: Theme.accent
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSizeSmaller
                            visible: text.length > 0
                            width: parent.width
                            wrapMode: Text.WordWrap
                        }
                    }
                }
            }

            Component.onCompleted: {
                if (surfaceRoot.isPrimary) passwordField.forceActiveFocus();
            }
        }
    }
}
