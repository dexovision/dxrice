import QtQuick

// A native-shell-control toggle tile (Wi-Fi, Bluetooth, DND, Keep Awake) --
// primary controls get real visual presence (a square tile, a centered
// icon, a label), not a thin list row, matching how an actual desktop
// control center presents its top-level toggles. The accent still only
// ever shows up as a quiet tint + a tinted icon when active -- never a
// solid/high-saturation fill -- so four of these sitting side by side
// read as "one is on" rather than "the panel turned cyan."
Rectangle {
    id: root
    property string glyph: ""
    property string label: ""
    property bool active: false
    // asked for but not yet confirmed by the system (see QuickSettings)
    property bool pending: false
    // false: nothing to switch on this machine -- dimmed, takes no clicks
    property bool available: true
    signal toggled(bool next)
    opacity: root.available ? 1 : 0.45
    Behavior on opacity { NumberAnimation { duration: Theme.durationFast } }

    implicitWidth: 74
    implicitHeight: 74
    radius: Theme.roundingLg
    color: {
        if (root.active) return Theme.mix(Theme.layer1, Theme.accent, area.containsMouse ? 0.22 : 0.14);
        return area.containsMouse ? Theme.layer1Hover : Theme.layer1;
    }
    scale: Theme.pressScale(area.pressed && root.available)

    Behavior on color {
        ColorAnimation { duration: Theme.durationFast; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveStandard }
    }
    Behavior on scale {
        NumberAnimation { duration: Theme.durationMove; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveExpressiveFast }
    }

    Column {
        anchors.centerIn: parent
        spacing: Theme.padXs
        Text {
            id: glyphText
            anchors.horizontalCenter: parent.horizontalCenter
            text: root.glyph
            font.family: Theme.iconFamily
            font.pixelSize: Theme.fontSizeLarge
            color: root.active ? Theme.accentText : Theme.text
            opacity: root.active ? 1 : 0.8
            // pending: the icon breathes until the system confirms
            SequentialAnimation on opacity {
                running: root.pending
                loops: Animation.Infinite
                NumberAnimation { to: 0.35; duration: 420; easing.type: Easing.InOutSine }
                NumberAnimation { to: 1; duration: 420; easing.type: Easing.InOutSine }
                onRunningChanged: if (!running) glyphText.opacity = Qt.binding(() => root.active ? 1 : 0.8)
            }
        }
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: root.label
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSizeSmall
            font.weight: root.active ? Font.Medium : Font.Normal
            color: root.active ? Theme.textActive : Theme.text
            opacity: root.active ? 1 : 0.85
            // Wrapping, not eliding: at a fixed 68px this tile's label was
            // truncating "Do Not Disturb" to "Do Not Di..." regardless of
            // how much room the surrounding card had, since the constraint
            // is this tile's own fixed width, not its neighbors -- verified
            // by reading the tile in isolation, not just in the full
            // Connectivity row. Two short lines inside a 74px-tall square
            // fits comfortably; elide is kept as a last-resort safety net
            // for a future label too long even wrapped.
            wrapMode: Text.WordWrap
            maximumLineCount: 2
            elide: Text.ElideRight
            // A fixed two-line box: wrapping is tried at full size first,
            // and only a single word too wide for the tile ("Bluetooth" at
            // a larger shell text size, which elided to "Bluetoo...")
            // shrinks -- never below 85%. The fixed height also keeps every
            // tile's icon on the same line whether its label takes one line
            // or two (a two-line label used to push its icon up).
            fontSizeMode: Text.Fit
            minimumPixelSize: Math.round(Theme.fontSizeSmall * 0.85)
            height: Math.ceil(Theme.fontSizeSmall * 2.7)
            verticalAlignment: Text.AlignTop
            width: 68
            horizontalAlignment: Text.AlignHCenter
        }
    }

    MouseArea {
        id: area
        anchors.fill: parent
        hoverEnabled: root.available
        enabled: root.available
        cursorShape: root.available ? Qt.PointingHandCursor : Qt.ArrowCursor
        onClicked: root.toggled(!root.active)
    }
}
