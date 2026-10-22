import QtQuick

// "Back to the default": a quiet undo arrow beside a setting that has been
// moved off its default, and nothing at all while it is on it (a reset on
// every row would be clutter). Text-only like the value next to it; it
// lights up under the pointer. The hit area is larger than the glyph.
Item {
    id: root
    signal clicked()
    implicitWidth: 20
    implicitHeight: 20
    Accessible.role: Accessible.Button
    Accessible.name: "Reset to default"

    Text {
        anchors.centerIn: parent
        text: ""
        color: area.containsMouse ? Theme.textActive : Theme.text
        opacity: area.containsMouse ? 1 : Theme.opacitySecondary
        font.family: Theme.iconFamily
        font.pixelSize: Theme.fontSizeSmaller
        scale: Theme.pressScale(area.pressed, 0.88)
        Behavior on opacity { NumberAnimation { duration: Theme.durationFast; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveStandard } }
        Behavior on scale { NumberAnimation { duration: Theme.durationMove; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveExpressiveFast } }
    }
    MouseArea {
        id: area
        anchors.fill: parent
        anchors.margins: -4
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: root.clicked()
    }
}
