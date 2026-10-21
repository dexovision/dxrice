import QtQuick
import QtQuick.Effects

// What is playing, from whichever MPRIS player is active (MediaBackend), led
// by its artwork: the card's ground is the cover itself, blurred and dimmed,
// with the sharp cover on it, then the source, title and artist, the time,
// and play/pause/previous/next. The bar seeks (click or drag) when the
// player allows it. A new track slides its text in. Nothing shows while
// there is no player: the card isn't there at all.
DesktopWidget {
    id: root
    name: "music"
    defaultCorner: "bottom-left"
    defaultOn: true
    wanted: media.available
    surface: "none"
    pad: 0
    contentWidth: 420
    contentHeight: 148

    MediaBackend { id: media; objectName: "musicMedia" }
    // MPRIS doesn't announce the position: ask once a second, only while playing and shown
    Timer {
        running: root.active && media.playing
        interval: 1000; repeat: true
        onTriggered: if (media.player) media.player.positionChanged()
    }
    readonly property bool hasArt: art.status === Image.Ready

    // ---- the ground: the cover, blurred, under a scrim (or a flat tint) ----
    Item {
        id: ground
        anchors.fill: parent
        layer.enabled: root.effects
        layer.effect: MultiEffect { maskEnabled: true; maskSource: groundMask; maskThresholdMin: 0.5; maskSpreadAtMin: 1.0 }
        // rounded themselves too, for when there is no mask (software rendering)
        Rectangle { anchors.fill: parent; radius: 18; color: Theme.mix(Theme.panel, Theme.accent, 0.22) }
        Image {
            anchors.fill: parent
            source: root.effects ? media.artUrl : ""
            visible: root.hasArt && root.effects  // unblurred it would only be noise behind the text
            asynchronous: true; cache: true
            sourceSize: Qt.size(96, 96)          // it is blurred: a small decode is plenty
            fillMode: Image.PreserveAspectCrop
            layer.enabled: root.effects
            layer.effect: MultiEffect { blurEnabled: true; blur: 1.0; blurMax: 48; saturation: 0.2 }
        }
        Rectangle { anchors.fill: parent; radius: 18; color: Qt.rgba(0, 0, 0, root.hasArt && root.effects ? 0.5 : 0.25) }
        Rectangle {
            anchors.fill: parent
            color: "transparent"; radius: 18
            border.width: 1; border.color: Qt.rgba(1, 1, 1, 0.08)
        }
    }
    Rectangle { id: groundMask; anchors.fill: parent; radius: 18; layer.enabled: true; visible: false }

    // ---- the cover ----
    Item {
        id: cover
        x: 16; y: 16
        width: 116; height: 116
        Rectangle {
            anchors.fill: parent; radius: 10
            color: Theme.mix(Theme.layer1, Theme.accent, 0.3)
            Text { anchors.centerIn: parent; text: String.fromCodePoint(0xf075a); color: Theme.textActive; opacity: 0.7; font.family: Theme.iconFamily; font.pixelSize: 40 }
        }
        Image {
            id: art
            objectName: "musicArt"
            anchors.fill: parent
            source: media.artUrl
            asynchronous: true; cache: true
            sourceSize: Qt.size(232, 232)
            fillMode: Image.PreserveAspectCrop
            opacity: status === Image.Ready ? 1 : 0
            Behavior on opacity { NumberAnimation { duration: Theme.durationDefault; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveStandard } }
            layer.enabled: root.effects
            layer.effect: MultiEffect { maskEnabled: true; maskSource: coverMask; maskThresholdMin: 0.5; maskSpreadAtMin: 1.0 }
        }
        Rectangle { id: coverMask; anchors.fill: parent; radius: 10; layer.enabled: true; visible: false }
        // playing, the cover sits full size; paused, it settles back a little
        scale: media.playing ? 1 : 0.93
        Behavior on scale { NumberAnimation { duration: Theme.durationDefault; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveExpressiveDefault } }
    }

    // ---- the words: a new track slides in ----
    Column {
        id: words
        x: cover.x + cover.width + 18
        y: 18
        width: parent.width - x - 18
        spacing: 2
        property real slide: 0
        transform: Translate { x: words.slide }
        Text {
            width: parent.width
            text: media.source.toUpperCase()
            color: root.hasArt ? "white" : Theme.accent; opacity: 0.75
            font.family: Theme.fontFamily; font.pixelSize: 10; font.weight: Font.Bold
            font.letterSpacing: 2.5; elide: Text.ElideRight
        }
        Text {
            objectName: "musicTitle"
            width: parent.width
            text: media.title
            color: "white"
            font.family: Theme.fontFamily; font.pixelSize: 19; font.weight: Font.Bold
            wrapMode: Text.Wrap; maximumLineCount: 2; elide: Text.ElideRight
            lineHeight: 0.95
        }
        Text {
            objectName: "musicArtist"
            width: parent.width
            text: media.artist
            visible: text.length > 0
            color: "white"; opacity: 0.72
            font.family: Theme.fontFamily; font.pixelSize: 13; elide: Text.ElideRight
        }
    }
    property string _track: media.title + "\u0001" + media.artist
    on_TrackChanged: if (root.active) trackIn.restart()
    ParallelAnimation {
        id: trackIn
        NumberAnimation { target: words; property: "slide"; from: 14; to: 0; duration: Theme.durationDefault; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveEmphasizedDecel }
        NumberAnimation { target: words; property: "opacity"; from: 0; to: 1; duration: Theme.durationDefault; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveStandard }
    }

    // ---- time, controls, and the bar ----
    Item {
        id: lower
        x: words.x
        width: words.width
        y: parent.height - 18 - height
        height: 44
        Row {
            anchors.left: parent.left
            anchors.top: parent.top
            spacing: 4
            Text {
                objectName: "musicTime"
                text: media.formatTime(media.position)
                color: "white"
                font.family: Theme.fontMono; font.pixelSize: 11
            }
            Text {
                text: media.length > 0 ? "/ " + media.formatTime(media.length) : ""
                color: "white"; opacity: 0.55
                font.family: Theme.fontMono; font.pixelSize: 11
            }
        }
        Row {
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.topMargin: -8
            spacing: 6
            Repeater {
                model: [{ g: "󰒮", fn: "previous", big: false, name: "Prev" },
                        { g: "", fn: "playPause", big: true, name: "Play" },
                        { g: "󰒭", fn: "next", big: false, name: "Next" }]
                delegate: Rectangle {
                    id: btn
                    required property var modelData
                    objectName: "music" + btn.modelData.name
                    width: modelData.big ? 34 : 28; height: width; radius: width / 2
                    anchors.verticalCenter: parent.verticalCenter
                    color: modelData.big ? Theme.accent : (area.containsMouse ? Qt.rgba(1, 1, 1, 0.16) : "transparent")
                    scale: area.pressed ? 0.88 : (area.containsMouse ? 1.08 : 1)
                    Behavior on scale { NumberAnimation { duration: Theme.durationFast; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveExpressiveFast } }
                    Behavior on color { ColorAnimation { duration: Theme.durationFast } }
                    Text {
                        anchors.centerIn: parent
                        text: btn.modelData.big ? (media.playing ? "󰏤" : "󰐊") : btn.modelData.g
                        color: btn.modelData.big ? Theme.panel : "white"
                        font.family: Theme.iconFamily; font.pixelSize: btn.modelData.big ? 17 : 16
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
        Item {
            id: progress
            objectName: "musicProgress"
            anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom
            height: 14
            readonly property real frac: media.length > 0 ? Math.max(0, Math.min(1, media.position / media.length)) : 0
            Rectangle {
                anchors.verticalCenter: parent.verticalCenter
                width: parent.width; height: progressArea.containsMouse ? 5 : 3; radius: height / 2
                color: Qt.rgba(1, 1, 1, 0.18)
                Behavior on height { NumberAnimation { duration: Theme.durationFast; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveStandard } }
                Rectangle {
                    objectName: "musicProgressFill"
                    height: parent.height; radius: parent.radius
                    width: parent.width * progress.frac
                    color: root.hasArt ? "white" : Theme.accent
                    // one short step per second, not a bar that is always animating
                    Behavior on width { enabled: !progressArea.pressed; NumberAnimation { duration: 240; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveStandard } }
                }
            }
            MouseArea {
                id: progressArea
                anchors.fill: parent
                hoverEnabled: true
                enabled: media.seekable
                cursorShape: media.seekable ? Qt.PointingHandCursor : Qt.ArrowCursor
                function seek(x) { media.seekTo(Math.max(0, Math.min(1, x / width)) * media.length); }
                onPressed: (m) => seek(m.x)
                onPositionChanged: (m) => { if (pressed) seek(m.x); }
            }
        }
    }
}
