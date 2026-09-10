import QtQuick
import QtQuick.Controls.Basic

// A value slider with a live percentage label. The visual label/handle
// update on every drag tick, but `changed(value)` only fires ~80ms after
// motion pauses -- same debounce rationale as the old GTK apps: a fast
// drag must not spawn a subprocess (wpctl/brightnessctl/...) per pixel.
Item {
    id: root
    property real from: 0
    property real to: 100
    property real value: 0
    property int decimals: 0
    property real debounceMs: 80
    signal changed(real value)

    implicitHeight: 32
    width: parent ? parent.width : implicitWidth

    Row {
        anchors.fill: parent
        spacing: Theme.padMd

        Slider {
            id: slider
            width: parent.width - valueLabel.implicitWidth - parent.spacing
            anchors.verticalCenter: parent.verticalCenter
            from: root.from
            to: root.to
            value: root.value

            background: Rectangle {
                x: slider.leftPadding
                y: slider.topPadding + slider.availableHeight / 2 - height / 2
                width: slider.availableWidth
                height: 8
                radius: Theme.roundingFull
                color: Qt.rgba(Theme.border.r, Theme.border.g, Theme.border.b, 0.22)

                Rectangle {
                    width: slider.visualPosition * parent.width
                    height: parent.height
                    radius: parent.radius
                    color: Theme.accent
                }
            }

            handle: Rectangle {
                x: slider.leftPadding + slider.visualPosition * (slider.availableWidth - width)
                y: slider.topPadding + slider.availableHeight / 2 - height / 2
                width: slider.pressed ? 20 : 16
                height: width
                radius: Theme.roundingFull
                color: Theme.textActive
                border.width: slider.pressed ? 4 : 0
                border.color: Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.3)

                Behavior on width {
                    NumberAnimation { duration: Theme.durationFast; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveExpressiveFast }
                }
                Behavior on border.width {
                    NumberAnimation { duration: Theme.durationFast; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveExpressiveFast }
                }
            }

            onMoved: {
                root.value = slider.value;
                debounce.restart();
            }
        }

        Text {
            id: valueLabel
            anchors.verticalCenter: parent.verticalCenter
            text: root.decimals > 0 ? root.value.toFixed(root.decimals) : Math.round(root.value) + "%"
            color: Theme.text
            font.family: Theme.fontFamily
            font.pixelSize: 12
            width: 42
            horizontalAlignment: Text.AlignRight
        }
    }

    Timer {
        id: debounce
        interval: root.debounceMs
        onTriggered: root.changed(root.value)
    }

    onValueChanged: if (!slider.pressed) slider.value = value
}
