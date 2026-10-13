import QtQuick

// A labelled setting slider, in the same visual language as the shell's
// other sliders (SliderRow in Quick Settings): the name and the live value
// on one line, a slim track underneath with the accent only as the
// progress, and a knob you grab. It replaced a full-width filled slab with
// the label baked in, which stacked a third grey layer inside every card
// (panel > card > slab) and looked unlike every other slider in the shell.
//
// The value glides when it jumps (a click along the track, Revert, a
// preset) and tracks the pointer exactly while dragging. `changed` fires
// once the value settles (debounced), like SliderRow. No wheel handling on
// purpose: these live in a scrolling page, and a slider that eats the
// wheel turns "scroll down" into "change a setting".
Item {
    id: root
    property real from: 0
    property real to: 100
    property real value: 0
    property int decimals: 0
    property string label: ""
    property string unit: ""
    property real debounceMs: 80
    signal changed(real value)

    readonly property real fraction: root.to > root.from ? Math.max(0, Math.min(1, (root.value - root.from) / (root.to - root.from))) : 0
    readonly property string valueText: (root.decimals > 0 ? root.value.toFixed(root.decimals) : Math.round(root.value)) + root.unit
    readonly property bool dragging: area.pressed
    readonly property bool hovered: area.containsMouse

    implicitHeight: labelRow.height + Theme.padXs + trackArea.height
    width: parent ? parent.width : implicitWidth

    Item {
        id: labelRow
        width: parent.width
        height: nameLabel.implicitHeight
        Text {
            id: nameLabel
            anchors.left: parent.left
            width: parent.width - valueLabel.implicitWidth - Theme.padMd
            text: root.label
            color: Theme.textActive
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSizeNormal
            elide: Text.ElideRight
        }
        Text {
            id: valueLabel
            anchors.right: parent.right
            anchors.baseline: nameLabel.baseline
            text: root.valueText
            color: root.dragging ? Theme.textActive : Theme.text
            opacity: root.dragging ? 1 : Theme.opacitySecondary
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSizeSmaller
            font.features: { "tnum": 1 }
            Behavior on opacity { NumberAnimation { duration: Theme.durationFast; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveStandard } }
        }
    }

    // ---- the track: a grabbable band under the label row ----
    Item {
        id: trackArea
        y: labelRow.height + Theme.padXs
        width: parent.width
        height: 20
        readonly property real knobSize: 16

        Rectangle {
            id: track
            objectName: "fillSliderTrack"
            anchors.verticalCenter: parent.verticalCenter
            x: trackArea.knobSize / 2
            width: parent.width - trackArea.knobSize
            height: (root.hovered || root.dragging) && !Theme.reduceMotion ? 6 : 4
            radius: height / 2
            color: Theme.stateFill(Theme.borderFaint, root.hovered, false)
            Behavior on height { NumberAnimation { duration: Theme.durationMove; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveStandard } }
            Behavior on color { ColorAnimation { duration: Theme.durationFast; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveStandard } }

            // Progress: the one coloured part.
            Rectangle {
                id: fill
                objectName: "fillSliderProgress"
                height: parent.height
                radius: parent.radius
                width: parent.width * root.fraction
                color: Theme.accent
                Behavior on width {
                    enabled: !root.dragging && !Theme.reduceMotion
                    NumberAnimation { duration: Theme.durationDefault; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveEnter }
                }
            }
        }

        Rectangle {
            id: knob
            objectName: "fillSliderKnob"
            width: trackArea.knobSize; height: width; radius: width / 2
            anchors.verticalCenter: parent.verticalCenter
            x: track.x + fill.width - width / 2
            scale: Theme.reduceMotion ? 1 : (root.dragging ? 1.15 : (root.hovered ? 1.08 : 1))
            color: Theme.textActive
            border.width: root.dragging ? 4 : 0
            border.color: Theme.withAlpha(Theme.accent, 0.35)
            Behavior on scale { NumberAnimation { duration: Theme.durationMove; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveExpressiveFast } }
            Behavior on border.width { NumberAnimation { duration: Theme.durationMove; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveStandard } }
        }

        MouseArea {
            id: area
            anchors.fill: parent
            anchors.topMargin: -4
            anchors.bottomMargin: -4
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            preventStealing: true
            function setFromX(x) {
                const frac = Math.max(0, Math.min(1, (x - track.x) / track.width));
                const v = root.from + frac * (root.to - root.from);
                root.value = root.decimals > 0 ? Number(v.toFixed(root.decimals)) : Math.round(v);
                debounce.restart();
            }
            onPressed: (mouse) => setFromX(mouse.x)
            onPositionChanged: (mouse) => { if (pressed) setFromX(mouse.x); }
        }
    }

    Timer { id: debounce; interval: root.debounceMs; onTriggered: root.changed(root.value) }
}
