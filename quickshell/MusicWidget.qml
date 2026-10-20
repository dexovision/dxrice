import QtQuick
import QtQuick.Effects

// What is playing, from whichever MPRIS player is active (MediaBackend):
// the cover, title, artist, play/pause/previous/next, and where in the track
// it is (drag or click the bar to seek, when the player lets you). Nothing
// shows while there is no player: the card isn't there at all.
DesktopWidget {
    id: root
    name: "music"
    defaultCorner: "bottom-left"
    defaultOn: true
    wanted: media.available
    contentWidth: 360
    contentHeight: 118

    MediaBackend { id: media; objectName: "musicMedia" }
    // MPRIS doesn't announce the position: ask once a second, only while playing and shown
    Timer {
        running: root.active && media.playing
        interval: 1000; repeat: true
        onTriggered: if (media.player) media.player.positionChanged()
    }

    // cover
    Item {
        id: cover
        width: 96; height: 96
        Rectangle {
            id: tile
            anchors.fill: parent; radius: 12
            color: Theme.mix(Theme.layer1, Theme.accent, 0.18)
            Text { anchors.centerIn: parent; text: ""; color: Theme.accent; opacity: 0.8; font.family: Theme.fontFamily; font.pixelSize: 30 }
        }
        Image {
            id: art
            objectName: "musicArt"
            anchors.fill: parent
            source: media.artUrl
            asynchronous: true; cache: true
            sourceSize: Qt.size(192, 192)
            fillMode: Image.PreserveAspectCrop
            opacity: status === Image.Ready ? 1 : 0
            Behavior on opacity { NumberAnimation { duration: Theme.durationDefault; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveStandard } }
            // rounded like the tile behind it
            layer.enabled: true
            layer.effect: MultiEffect { maskEnabled: true; maskSource: coverMask; maskThresholdMin: 0.5; maskSpreadAtMin: 1.0 }
        }
        Rectangle { id: coverMask; anchors.fill: parent; radius: 12; layer.enabled: true; visible: false }
        // a playing track's cover breathes very slightly; paused, it rests
        scale: media.playing ? 1 : 0.94
        Behavior on scale { NumberAnimation { duration: Theme.durationDefault; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveEmphasizedDecel } }
        opacity: media.playing ? 1 : 0.8
        Behavior on opacity { NumberAnimation { duration: Theme.durationDefault } }
    }

    Column {
        x: cover.width + 16
        width: parent.width - x
        spacing: 3
        Text {
            width: parent.width
            text: media.source.toUpperCase()
            color: Theme.accent; font.family: Theme.fontFamily; font.pixelSize: 10; font.weight: Font.DemiBold
            font.letterSpacing: 2; elide: Text.ElideRight
        }
        Text {
            objectName: "musicTitle"
            width: parent.width
            text: media.title
            color: Theme.textActive; font.family: Theme.fontFamily; font.pixelSize: 16; font.weight: Font.DemiBold
            elide: Text.ElideRight
        }
        Text {
            objectName: "musicArtist"
            width: parent.width
            text: media.artist
            visible: text.length > 0
            color: Theme.text; opacity: Theme.opacityMuted
            font.family: Theme.fontFamily; font.pixelSize: 13; elide: Text.ElideRight
        }
        Item { width: 1; height: 4 }
        Row {
            spacing: 14
            Repeater {
                model: [{ g: "", fn: "previous", big: false, name: "Prev" },
                        { g: "", fn: "playPause", big: true, name: "Play" },
                        { g: "", fn: "next", big: false, name: "Next" }]
                delegate: Rectangle {
                    id: btn
                    required property var modelData
                    objectName: "music" + btn.modelData.name
                    width: modelData.big ? 38 : 30; height: width; radius: width / 2
                    anchors.verticalCenter: parent.verticalCenter
                    color: modelData.big ? Theme.accent : (area.containsMouse ? Qt.rgba(1, 1, 1, 0.12) : "transparent")
                    scale: area.pressed ? 0.9 : (area.containsMouse ? 1.06 : 1)
                    Behavior on scale { NumberAnimation { duration: Theme.durationFast; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveStandard } }
                    Behavior on color { ColorAnimation { duration: Theme.durationFast } }
                    Text {
                        anchors.centerIn: parent
                        text: btn.modelData.big ? (media.playing ? "" : "") : btn.modelData.g
                        color: btn.modelData.big ? Theme.panel : Theme.textActive
                        font.family: Theme.fontFamily; font.pixelSize: btn.modelData.big ? 14 : 12
                    }
                    MouseArea {
                        id: area
                        anchors.fill: parent; hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: media[btn.modelData.fn]()
                    }
                }
            }
        }
    }

    // progress along the bottom edge of the content
    Item {
        id: progress
        objectName: "musicProgress"
        anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom
        height: 14
        readonly property real frac: media.length > 0 ? Math.max(0, Math.min(1, media.position / media.length)) : 0
        Rectangle {
            anchors.verticalCenter: parent.verticalCenter
            width: parent.width; height: 3; radius: 1.5
            color: Theme.borderIdle
            Rectangle {
                objectName: "musicProgressFill"
                height: parent.height; radius: 1.5
                width: parent.width * progress.frac
                color: Theme.accent
                Behavior on width { enabled: media.playing; NumberAnimation { duration: 950; easing.type: Easing.Linear } }
            }
        }
        MouseArea {
            anchors.fill: parent
            enabled: media.seekable
            cursorShape: media.seekable ? Qt.PointingHandCursor : Qt.ArrowCursor
            function seek(x) { media.seekTo(Math.max(0, Math.min(1, x / width)) * media.length); }
            onPressed: (m) => seek(m.x)
            onPositionChanged: (m) => { if (pressed) seek(m.x); }
        }
    }
}
