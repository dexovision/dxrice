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
    readonly property string valueText: root.decimals > 0 ? root.value.toFixed(root.decimals) : Math.round(root.value) + root.unit

    Rectangle {
        id: track
        anchors.fill: parent
        radius: Theme.roundingMd
        color: Theme.layer1
        clip: true

        Rectangle {
            id: fill
            width: parent.width * root.fraction
            height: parent.height
            radius: Theme.roundingMd
            color: Theme.mix(Theme.layer1, Theme.accent, area.pressed ? 0.34 : 0.24)
            Behavior on color { ColorAnimation { duration: Theme.durationFast } }
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
            width: parent.width - 90
        }
        Text {
            anchors.right: parent.right
            anchors.rightMargin: Theme.padMd
            anchors.verticalCenter: parent.verticalCenter
            text: root.valueText
            color: Theme.text
            opacity: 0.8
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSizeSmaller
        }
    }

    MouseArea {
        id: area
        anchors.fill: parent
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
