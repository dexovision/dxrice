import QtQuick

// A reading's recent history as a row of bars, newest on the right, each
// easing to its height. Only what was sampled is drawn: with fewer samples
// than slots, the left of the graph is simply empty (never padded with
// made-up values). Plain rectangles, so it draws under any renderer.
//
//   values   samples, oldest first
//   max      the value that fills the height (0 = the largest sample)
//   slots    how many bars fit across
Item {
    id: root
    property var values: []
    property real max: 100
    property int slots: 40
    property color color: Theme.accent
    property real gap: 2
    readonly property real ceiling: root.max > 0 ? root.max : Math.max(1, ...root.values)
    implicitHeight: 36

    Rectangle {      // the baseline
        anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom
        height: 1
        color: root.color
        opacity: 0.25
    }
    Repeater {
        model: root.slots
        delegate: Rectangle {
            required property int index
            // slot i shows the sample that is (slots-1-i) samples old
            readonly property int age: root.slots - 1 - index
            readonly property bool has: age < root.values.length
            readonly property real v: has ? root.values[root.values.length - 1 - age] : 0
            width: Math.max(1, (root.width - (root.slots - 1) * root.gap) / root.slots)
            x: index * (width + root.gap)
            height: has ? Math.max(2, root.height * Math.max(0, Math.min(1, v / root.ceiling))) : 0
            anchors.bottom: parent.bottom
            radius: Math.min(width / 2, 1.5)
            color: root.color
            opacity: has ? 0.35 + 0.65 * (index / Math.max(1, root.slots - 1)) : 0
            Behavior on height { NumberAnimation { duration: Theme.durationMove; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveStandard } }
        }
    }
}
