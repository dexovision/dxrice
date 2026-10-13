import QtQuick

// A slider that IS the row, not a label next to a control: the whole bar
// is a single rounded slab, filled from the left up to the current value,
// with the label baked into the fill on the left and the live value on
// the right -- drag anywhere on the slab to change it. This exists so a
// numeric setting in the Theme Editor reads as one deliberate object
// (closer to a property editor in a real design tool) instead of
// "Title text" stacked above a separate generic form control.
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

    implicitHeight: 44
    width: parent ? parent.width : implicitWidth

    readonly property real fraction: root.to > root.from ? Math.max(0, Math.min(1, (root.value - root.from) / (root.to - root.from))) : 0
    readonly property string valueText: (root.decimals > 0 ? root.value.toFixed(root.decimals) : Math.round(root.value)) + root.unit
    readonly property bool dragging: area.pressed

    Rectangle {
        id: track
        anchors.fill: parent
        radius: Theme.roundingMd
        color: Theme.stateFill(Theme.layer1, area.containsMouse, false)
        clip: true
        Behavior on color { ColorAnimation { duration: Theme.durationFast; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveStandard } }

        // The fill is neutral -- a lighter step of the same surface -- and
        // the accent is only a thin line along its bottom: the value is the
        // small thing that's coloured, not the whole slab (a dozen of
        // these on the Theme editor's pages were a dozen tinted bars).
        Rectangle {
            id: fill
            width: Math.max(radius * 2, parent.width * root.fraction)
            height: parent.height
            radius: Theme.roundingMd
            color: Theme.mix(Theme.layer1, Theme.textActive, area.pressed ? 0.16 : (area.containsMouse ? 0.12 : 0.09))
            Behavior on color { ColorAnimation { duration: Theme.durationFast; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveStandard } }
            // Follows the pointer exactly while dragging; glides when the
            // value jumps (a click somewhere along the bar, Revert, a preset).
            Behavior on width {
                enabled: !root.dragging && !Theme.reduceMotion
                NumberAnimation { duration: Theme.durationDefault; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveEnter }
            }

            // The value line: 2px of accent along the fill's bottom edge,
            // inset clear of the rounded corners -- never under the label
            // (a vertical mark at the fill's end struck through the text
            // whenever the value was small).
            Rectangle {
                anchors.bottom: parent.bottom
                anchors.bottomMargin: 3
                x: Theme.roundingMd / 2
                width: Math.max(0, parent.width - Theme.roundingMd)
                height: area.pressed ? 3 : 2
                radius: height / 2
                color: Theme.accent
                opacity: root.fraction > 0.01 ? 1 : 0
            }
        }

        Text {
            anchors.left: parent.left
            anchors.leftMargin: Theme.padMd
            anchors.verticalCenter: parent.verticalCenter
            text: root.label
            color: Theme.textActive
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSizeSmaller
            font.weight: Font.Medium
            elide: Text.ElideRight
            width: parent.width - valueLabel.implicitWidth - Theme.padMd * 3
        }
        Text {
            id: valueLabel
            anchors.right: parent.right
            anchors.rightMargin: Theme.padMd
            anchors.verticalCenter: parent.verticalCenter
            text: root.valueText
            color: area.pressed ? Theme.textActive : Theme.text
            opacity: area.pressed ? 1 : Theme.opacityFaint
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSizeSmaller
            font.features: { "tnum": 1 }
        }
    }

    MouseArea {
        id: area
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        function setFromX(x) {
            const frac = Math.max(0, Math.min(1, x / width));
            const v = root.from + frac * (root.to - root.from);
            root.value = root.decimals > 0 ? v : Math.round(v);
            debounce.restart();
        }
        onPressed: (mouse) => setFromX(mouse.x)
        onPositionChanged: (mouse) => { if (pressed) setFromX(mouse.x); }
    }

    Timer { id: debounce; interval: root.debounceMs; onTriggered: root.changed(root.value) }
}
