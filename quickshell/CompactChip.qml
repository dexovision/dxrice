import QtQuick

// A small text action for dense list rows (Wi-Fi/Bluetooth device lists)
// where GlassButton's own padding (Theme.pad2xl per side, meant for a
// screen's one standalone primary/secondary action) reads as "a giant
// block" -- live-caught by actually expanding the Wi-Fi list in a ~160px
// card: a GlassButton "Connect" came out wider than the network name's
// own text, dominating a row it should just be one small part of. Same
// color/press language as GlassButton, deliberately tighter geometry.
Rectangle {
    id: root
    property string text: ""
    signal clicked()

    implicitWidth: label.implicitWidth + Theme.padMd * 2
    implicitHeight: label.implicitHeight + Theme.padXs * 2
    radius: Theme.roundingSm
    color: area.pressed ? Theme.layer2Active : (area.containsMouse ? Theme.layer2Hover : Theme.layer1)
    scale: area.pressed ? 0.96 : 1.0

    Behavior on color { ColorAnimation { duration: Theme.durationFast } }
    Behavior on scale {
        NumberAnimation { duration: Theme.durationFast; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveExpressiveFast }
    }

    Text {
        id: label
        anchors.centerIn: parent
        text: root.text
        color: Theme.text
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fontSizeSmall
        font.weight: Font.Medium
    }
    MouseArea {
        id: area
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: root.clicked()
    }
}
