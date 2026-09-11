import QtQuick
import QtQuick.Effects
import Quickshell
import Quickshell.Wayland
import Quickshell.Services.Pipewire

// A real on-screen-display for volume/mic/brightness -- until now these
// keybinds (XF86AudioRaiseVolume etc., see hyprland.lua) changed real
// system state with zero visual feedback at all. Reactive, not
// command-triggered: watches the same live Pipewire/backlight state Quick
// Settings already reads, so it fires correctly no matter how the value
// changed (a keybind, Quick Settings' own slider, another app) rather than
// depending on every call site remembering to also poke an OSD.
//
// Always loaded (see shell.qml), not a lazy panel -- it has to be watching
// before the first keypress, and costs nothing while hidden since showing
// is just an opacity/scale animation, not construction.
PanelWindow {
    id: root
    color: "transparent"
    anchors { top: true }
    margins { top: 76 }
    exclusionMode: ExclusionMode.Ignore
    aboveWindows: true
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.namespace: "dxrice-osd"
    focusable: false

    implicitWidth: 280
    implicitHeight: 92

    PwObjectTracker { objects: [Pipewire.defaultAudioSink, Pipewire.defaultAudioSource] }
    readonly property var sink: Pipewire.defaultAudioSink
    readonly property var source: Pipewire.defaultAudioSource
    BrightnessBackend { id: brightnessBackend }

    property bool ready: false
    property string glyph: ""
    property real value: 0
    property string label: ""

    function trigger(g, v, l) {
        root.glyph = g;
        root.value = v;
        root.label = l;
        hideTimer.restart();
        surface.opacity = 1;
        surface.scale = 1;
    }

    Timer {
        id: hideTimer
        interval: 1600
        onTriggered: { surface.opacity = 0; surface.scale = 0.92; }
    }

    // Guard against firing on the very first read of each value at daemon
    // startup (nothing actually changed, there's just no "previous value"
    // yet) -- only start reacting once every source has reported once.
    property bool sinkSeen: false
    property bool sourceSeen: false
    property bool brightnessSeen: false

    Connections {
        target: root.sink ? root.sink.audio : null
        function onVolumeChanged() {
            if (!root.sinkSeen) { root.sinkSeen = true; return; }
            root.trigger(root.sink.audio.muted ? "" : "", root.sink.audio.volume, Math.round(root.sink.audio.volume * 100) + "%");
        }
        function onMutedChanged() {
            if (!root.sinkSeen) { root.sinkSeen = true; return; }
            root.trigger(root.sink.audio.muted ? "" : "", root.sink.audio.volume, root.sink.audio.muted ? "Muted" : Math.round(root.sink.audio.volume * 100) + "%");
        }
    }
    Connections {
        target: root.source ? root.source.audio : null
        function onVolumeChanged() {
            if (!root.sourceSeen) { root.sourceSeen = true; return; }
            root.trigger(root.source.audio.muted ? "" : "", root.source.audio.volume, Math.round(root.source.audio.volume * 100) + "%");
        }
        function onMutedChanged() {
            if (!root.sourceSeen) { root.sourceSeen = true; return; }
            root.trigger(root.source.audio.muted ? "" : "", root.source.audio.volume, root.source.audio.muted ? "Mic muted" : Math.round(root.source.audio.volume * 100) + "%");
        }
    }
    Connections {
        target: brightnessBackend
        function onPercentChanged() {
            if (!root.brightnessSeen) { root.brightnessSeen = true; return; }
            root.trigger("☀", brightnessBackend.percent / 100, brightnessBackend.percent + "%");
        }
    }

    Item {
        id: surface
        anchors.fill: parent
        opacity: 0
        scale: 0.92
        transformOrigin: Item.Top

        Behavior on opacity { NumberAnimation { duration: Theme.durationFast; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveStandard } }
        Behavior on scale { NumberAnimation { duration: Theme.durationDefault; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveEmphasizedDecel } }

        RectangularShadow {
            anchors.fill: card
            radius: card.radius
            color: Theme.shadowColor
            blur: Theme.elevationBlur(2)
            spread: Theme.elevationSpread(2)
            offset.y: Theme.elevationOffsetY(2)
        }

        Rectangle {
            id: card
            anchors.fill: parent
            radius: Theme.roundingXl
            color: Theme.bg

            Column {
                anchors.centerIn: parent
                width: parent.width - Theme.pad2xl * 2
                spacing: Theme.padSm

                Row {
                    width: parent.width
                    spacing: Theme.padMd
                    Text {
                        text: root.glyph
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSizeLarge
                        color: Theme.textActive
                        anchors.verticalCenter: parent.verticalCenter
                    }
                    Text {
                        text: root.label
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSizeNormal
                        color: Theme.text
                        anchors.verticalCenter: parent.verticalCenter
                    }
                }

                Rectangle {
                    width: parent.width
                    height: 6
                    radius: Theme.roundingFull
                    color: Theme.layer2

                    Rectangle {
                        width: parent.width * Math.max(0, Math.min(1, root.value))
                        height: parent.height
                        radius: parent.radius
                        color: Theme.accent

                        Behavior on width {
                            NumberAnimation { duration: Theme.durationFast; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveStandard }
                        }
                    }
                }
            }
        }
    }
}
