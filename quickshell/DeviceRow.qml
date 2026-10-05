import QtQuick

// One network or device in a Quick Settings list (Wi-Fi networks, paired
// Bluetooth devices) as ONE interactive row with a fixed height:
//
//   [glyph]  Name ........................  [forget] [Action]
//            secondary detail
//
// The name is the one thing sized to be read; the detail line (signal,
// security, battery, "Connected") is quieter beneath it; the action is a
// CompactChip, never a full-size button. "Forget" is destructive, so it is
// a separate icon that only appears while the row is hovered -- but its
// slot is reserved at all times, so the name never reflows (or slides under
// a control) as the pointer moves across the list, and an invisible button
// is never clickable.
//
// Wi-Fi and Bluetooth each feed this their own detail text, glyph and
// action; nothing here knows which kind of thing it is showing.
Rectangle {
    id: root
    property string glyph: ""
    property string title: ""
    property string detail: ""
    property bool connected: false
    // Action chip label; empty for no chip (e.g. an already-connected
    // Wi-Fi network, whose state is shown by the trailing check instead).
    property string actionText: ""
    property bool canForget: false
    // Trailing check mark for a connected row that has no action chip.
    readonly property bool showCheck: root.connected && root.actionText.length === 0
    signal actionClicked()
    signal forgetClicked()

    width: parent ? parent.width : 0
    height: 44
    radius: Theme.roundingSm
    color: hover.hovered ? Theme.layer2Hover : (root.connected ? Theme.mix(Theme.layer1, Theme.accent, 0.08) : "transparent")
    Behavior on color { ColorAnimation { duration: Theme.durationFast } }

    HoverHandler { id: hover }

    Text {
        id: glyphText
        x: Theme.padSm
        width: 20
        anchors.verticalCenter: parent.verticalCenter
        horizontalAlignment: Text.AlignHCenter
        text: root.glyph
        color: root.connected ? Theme.accent : Theme.text
        opacity: root.connected ? 1 : Theme.opacitySecondary
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fontSizeLarger
    }

    Column {
        anchors.verticalCenter: parent.verticalCenter
        anchors.left: glyphText.right
        anchors.leftMargin: Theme.padSm
        anchors.right: controls.left
        anchors.rightMargin: Theme.padSm
        spacing: 1
        Text {
            width: parent.width
            text: root.title
            color: Theme.textActive
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSizeNormal
            font.weight: root.connected ? Font.DemiBold : Font.Normal
            elide: Text.ElideRight
        }
        Text {
            width: parent.width
            visible: root.detail.length > 0
            text: root.detail
            color: root.connected ? Theme.accent : Theme.text
            opacity: root.connected ? 0.9 : Theme.opacityMuted
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSizeSmall
            elide: Text.ElideRight
        }
    }

    Row {
        id: controls
        anchors.right: parent.right
        anchors.rightMargin: Theme.padSm
        anchors.verticalCenter: parent.verticalCenter
        spacing: Theme.padXs

        Item {
            width: root.canForget ? 26 : 0
            height: 26
            anchors.verticalCenter: parent.verticalCenter
            IconButton {
                anchors.centerIn: parent
                visible: root.canForget && hover.hovered
                glyph: ""
                size: 26
                destructive: true
                onClicked: root.forgetClicked()
            }
        }
        CompactChip {
            visible: root.actionText.length > 0
            anchors.verticalCenter: parent.verticalCenter
            text: root.actionText
            onClicked: root.actionClicked()
        }
        Text {
            visible: root.showCheck
            anchors.verticalCenter: parent.verticalCenter
            width: 20
            horizontalAlignment: Text.AlignHCenter
            text: ""
            color: Theme.accent
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSizeSmaller
        }
    }
}
