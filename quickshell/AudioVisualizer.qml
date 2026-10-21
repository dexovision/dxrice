import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland

// A real audio spectrum along the bottom of the desktop, under every window:
// cava (one process, reading PipeWire's monitor of what is playing) prints
// one frame of bar heights per line, and each bar eases to its value.
//
// It runs only while it can be seen and there is something to show: the
// setting is on (theme.json "widget_visualizer", default on) and a media
// player is playing. Otherwise cava isn't running at all. Without cava
// installed it simply never appears -- nothing here invents bars.
//
// Styles ("visualizer_style"):
//   "bars"    (default) rounded bars rising from the bottom edge, the accent
//             at the base fading toward the top
//   "blocks"  the same values as block characters, a terminal's spectrum
PanelWindow {
    id: root
    objectName: "visualizer"

    readonly property bool on: Theme.widgetOn("visualizer", true)
    readonly property string style: Theme.data.visualizer_style === "blocks" ? "blocks" : "bars"
    readonly property int bars: 48
    readonly property real barHeight: 150
    MediaBackend { id: media; objectName: "visualizerMedia" }
    readonly property bool active: root.on && media.playing && root.available
    property bool available: true          // false once cava turns out not to start
    property var values: []                // 0..1 per bar, from the last frame

    // cava's frame: "v;v;v;...;" with 0..1000 per bar
    function feed(line) {
        const parts = String(line).split(";");
        const out = [];
        for (let i = 0; i < parts.length && out.length < root.bars; i++) {
            if (parts[i].length === 0) continue;
            const v = Number(parts[i]);
            if (isNaN(v)) return;              // not a frame: ignore the line
            out.push(Math.max(0, Math.min(1, v / 1000)));
        }
        if (out.length > 0) root.values = out;
    }

    // started and stopped with `active`. A cava that exits on its own after
    // drawing (PipeWire restarting, say) is started again 2 s later; one that
    // never produced a frame (not installed, no PipeWire) means there is no
    // visualizer on this machine, and it stays hidden.
    property int _frames: 0
    Process {
        id: cava
        objectName: "visualizerCava"
        command: ["cava", "-p", Quickshell.shellDir + "/cava.conf"]
        running: false
        stdout: SplitParser { onRead: (data) => { root._frames += 1; root.feed(data); } }
        onRunningChanged: if (!running && root.active) {
            if (root._frames === 0) root.available = false;
            else retry.start();
        }
    }
    Timer { id: retry; interval: 2000; onTriggered: root._sync() }
    function _sync() {
        if (root.active && !cava.running) cava.running = true;
        else if (!root.active && cava.running) cava.running = false;
    }
    onActiveChanged: { if (!root.active) { root.values = []; retry.stop(); } root._sync(); }
    Component.onCompleted: root._sync()

    property real shown: root.active ? 1 : 0
    Behavior on shown { NumberAnimation { duration: Theme.durationDefault; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveStandard } }
    visible: root.shown > 0
    color: "transparent"
    exclusionMode: ExclusionMode.Ignore
    aboveWindows: false
    WlrLayershell.layer: WlrLayer.Bottom
    WlrLayershell.namespace: "dxrice-visualizer"
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.None
    // a strip along the bottom edge, only as tall as the bars: it redraws 30
    // times a second while music plays, so it must not be a whole-screen surface
    anchors { left: true; right: true; bottom: true }
    implicitHeight: root.barHeight
    mask: Region {}                        // only to look at: never takes input

    Item {
        id: stage
        anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom
        height: root.barHeight
        opacity: root.shown
        // it sinks in and out of the bottom edge
        transform: Translate { y: (1 - root.shown) * 40 }

        Row {
            id: barRow
            objectName: "visualizerBars"
            visible: root.style === "bars"
            anchors.bottom: parent.bottom
            anchors.horizontalCenter: parent.horizontalCenter
            readonly property real gap: 6
            width: parent.width - 48
            spacing: gap
            Repeater {
                model: root.bars
                delegate: Rectangle {
                    required property int index
                    readonly property real v: index < root.values.length ? root.values[index] : 0
                    width: (barRow.width - (root.bars - 1) * barRow.gap) / root.bars
                    height: Math.max(3, v * (root.barHeight - 8))
                    anchors.bottom: parent.bottom
                    radius: width / 2
                    gradient: Gradient {
                        GradientStop { position: 0; color: Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.0) }
                        GradientStop { position: 1; color: Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.45) }
                    }
                    Behavior on height { NumberAnimation { duration: 90; easing.type: Easing.OutQuad } }
                }
            }
        }

        Text {
            objectName: "visualizerBlocks"
            visible: root.style === "blocks"
            anchors.bottom: parent.bottom
            anchors.bottomMargin: 6
            anchors.horizontalCenter: parent.horizontalCenter
            readonly property string ramp: " ▁▂▃▄▅▆▇█"
            text: root.values.map((v) => ramp.charAt(Math.round(v * 8))).join(" ")
            color: Theme.accentText
            opacity: 0.75
            font.family: Theme.fontMono
            font.pixelSize: 28
        }
    }
}
