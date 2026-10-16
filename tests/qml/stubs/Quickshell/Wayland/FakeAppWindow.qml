import QtQuick

// A stand-in application window: title bar, a few "content" lines, drawn at
// the window's real logical size and scaled to fit -- what a live capture of
// a real window looks like when the overview shrinks it.
Item {
    id: root
    property color fill: "#2b3140"
    property string title: ""
    property real logicalWidth: width
    clip: true
    Item {
        width: root.logicalWidth
        height: root.height * (root.logicalWidth / Math.max(1, root.width))
        scale: root.width / Math.max(1, root.logicalWidth)
        transformOrigin: Item.TopLeft
        Rectangle { anchors.fill: parent; color: root.fill; border.color: Qt.lighter(root.fill, 1.5); border.width: 2 }
        Rectangle { width: parent.width; height: 34; color: Qt.darker(root.fill, 1.35) }
        Text { x: 14; y: 8; color: "#e8eaf0"; font.pixelSize: 16; text: root.title; width: parent.width - 28; elide: Text.ElideRight }
        Column {
            x: 18; y: 52; spacing: 12
            Repeater {
                model: Math.max(0, Math.floor((parent.parent.height - 70) / 22))
                Rectangle { required property int index; height: 8; radius: 4; width: (0.35 + ((index * 37) % 50) / 100) * (root.logicalWidth - 40); color: Qt.lighter(root.fill, 1.6); opacity: 0.55 }
            }
        }
    }
}
