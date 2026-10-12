import QtQuick

// One Expandable (Quick Settings' accordion) with a few rows, on its own.
Item {
    id: root
    width: 480
    height: 400
    readonly property Item exp: expItem
    Rectangle { anchors.fill: parent; color: "#202228" }
    Expandable {
        id: expItem
        x: 20; y: 20; width: 440
        title: "Output"
        trailingText: "Speakers"
        Repeater {
            model: ["Speakers", "Headphones", "HDMI", "Bluetooth"]
            delegate: Text { required property string modelData; text: modelData; color: "white"; height: 32 }
        }
    }
}
