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

    implicitHeight: 28
    width: parent ? parent.width : implicitWidth

    Row {
        anchors.fill: parent
        spacing: Theme.padSm

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
                height: 6
                radius: 3
                color: Qt.rgba(Theme.border.r, Theme.border.g, Theme.border.b, 0.25)

                Rectangle {
                    width: slider.visualPosition * parent.width
                    height: parent.height
                    radius: parent.radius
                    color: Theme.accentSoft
                }
            }

            handle: Rectangle {
                x: slider.leftPadding + slider.visualPosition * (slider.availableWidth - width)
                y: slider.topPadding + slider.availableHeight / 2 - height / 2
                width: 14
                height: 14
                radius: 7
                color: Theme.textActive
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
