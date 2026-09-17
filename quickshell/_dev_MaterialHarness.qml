import QtQuick
import QtQuick.Effects
import Quickshell

// Throwaway material-QA rig -- NOT part of the shell, never wired into
// shell.qml. Renders the shell's actual Level-1/Level-2 tokens (Theme.panel,
// Theme.layer1, ShellSurface.radius/cardRadius) over three backdrops built
// entirely out of QML gradients/fills -- a near-black swatch (stands in for
// a dark terminal/browser), a saturated green swatch (stands in for the
// colorful wallpaper that kept tinting the panel olive), and a light swatch
// -- all inside ONE floating window. This exists so material contrast can be
// checked with a single self-contained screenshot, with zero dependency on
// the real wallpaper, workspace, or any live application.
//
// Run with: qs -p _dev_MaterialHarness.qml
//
// Renders straight to a PNG via Item.grabToImage() and quits -- no grim, no
// screen coordinates, no dependency on where the compositor actually put the
// window. A screen-capture tool grabs whatever pixels are at a location;
// this grabs the QML item's own render output directly from Qt, so it is
// structurally impossible for it to contain anything other than this file's
// own content, regardless of what else is on screen or how floating windows
// happen to stack.
FloatingWindow {
    id: win
    implicitWidth: 1020
    implicitHeight: 420
    title: "Material Harness"
    color: "black"

    Component.onCompleted: grabTimer.start()
    Timer {
        id: grabTimer
        interval: 300
        onTriggered: {
            content.grabToImage((result) => {
                result.saveToFile("/tmp/material_harness_render.png");
                Qt.quit();
            });
        }
    }

    Row {
        id: content
        anchors.fill: parent
        spacing: 0

        Repeater {
            model: [
                { name: "Dark backdrop", bg: "#0a0a0a", grad: false },
                { name: "Colorful wallpaper", bg: "#2f6b34", grad: true },
                { name: "Light backdrop", bg: "#e8e6df", grad: false },
            ]
            delegate: Rectangle {
                required property var modelData
                width: win.implicitWidth / 3
                height: win.implicitHeight
                color: modelData.bg
                clip: true

                // A rough stand-in for a blurred, saturated wallpaper: a
                // gradient plus a bright patch, so "does the panel pick up
                // green/olive tint" has something worth testing against.
                Rectangle {
                    visible: parent.modelData.grad
                    anchors.fill: parent
                    gradient: Gradient {
                        GradientStop { position: 0.0; color: "#3a9142" }
                        GradientStop { position: 0.5; color: "#1f5c2a" }
                        GradientStop { position: 1.0; color: "#0f3a18" }
                    }
                }
                Rectangle {
                    visible: parent.modelData.grad
                    x: parent.width * 0.15; y: parent.height * 0.1
                    width: parent.width * 0.5; height: parent.height * 0.35
                    radius: 40
                    color: "#8fd97a"
                    opacity: 0.55
                }

                Text {
                    anchors.top: parent.top
                    anchors.horizontalCenter: parent.horizontalCenter
                    anchors.topMargin: 10
                    text: parent.modelData.name
                    color: "white"
                    font.pixelSize: 12
                    font.family: "sans-serif"
                }

                // ---- Level 1: the shell surface itself ----
                Rectangle {
                    id: level1
                    anchors.centerIn: parent
                    width: parent.width - 60
                    height: parent.height - 90
                    radius: ShellSurface.radius
                    color: Theme.panel
                    border.width: 1
                    border.color: Theme.borderIdle

                    Text {
                        anchors.top: parent.top
                        anchors.horizontalCenter: parent.horizontalCenter
                        anchors.topMargin: 10
                        text: "Level 1 (panel)"
                        color: Theme.text
                        opacity: 0.6
                        font.pixelSize: 10
                        font.family: "sans-serif"
                    }

                    // ---- Level 2: a card sitting on the surface ----
                    Rectangle {
                        anchors.centerIn: parent
                        width: parent.width - 40
                        height: parent.height * 0.55
                        radius: ShellSurface.cardRadius
                        color: Theme.layer1

                        Text {
                            anchors.centerIn: parent
                            text: "Level 2 (card)"
                            color: Theme.text
                            opacity: 0.75
                            font.pixelSize: 11
                            font.family: "sans-serif"
                        }
                    }
                }
            }
        }
    }
}
