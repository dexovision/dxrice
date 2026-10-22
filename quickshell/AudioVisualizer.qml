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
// Its band along the bottom is kept clear of the desktop's widgets: while it
// could show (it is on, cava works here, and a player exists -- not only
// while one plays, so pausing doesn't shuffle the widgets), it reports the
// band's height to WidgetStack and bottom-corner widgets sit above it.
//
// What it listens to (theme.json "visualizer_source", chosen in the bar's
// Sound section):
//   "auto"              PipeWire's own choice: what the default output plays
//   "monitor:<sink>"    one output device, through its monitor
//   "app:<name>"        one application's playback only (its stream, found by
//                       its application name each time cava starts)
// A microphone is never a source here: choosing what the visualizer shows
// must not start capturing the room. The choice takes effect at once: cava
// is restarted. Automatic runs on the shipped cava.conf itself; a chosen
// source on a copy of it with its [input] lines changed, written by the
// same small shell step that starts cava (it makes the directory first, so
// a fresh boot's missing $XDG_RUNTIME_DIR/dxrice can't leave cava without
// a config). A chosen app that isn't playing,
// or a source cava can't open, is said in `sourceState`, never replaced by
// another source.
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
    // 150 px on a 1080 px screen, in proportion elsewhere
    readonly property real barHeight: Math.round(Math.max(90, Math.min(180, (root.screen && root.screen.height ? root.screen.height : 1080) * 0.139)))
    MediaBackend { id: media; objectName: "visualizerMedia" }
    readonly property bool reserves: root.on && root.available && (root.chosen || media.available)
    Binding { target: WidgetStack; property: "visualizerBand"; value: root.reserves ? root.barHeight : 0 }
    Binding { target: WidgetStack; property: "visualizerState"; value: !root.on ? "off" : root.sourceState }
    // on automatic it follows the media player; a chosen source (a game has
    // no media player) runs while it is on, and fades while it is silent
    readonly property bool chosen: root.source !== "auto"
    readonly property bool active: root.on && root.available && (root.chosen || media.playing)
    property bool available: true          // false once cava turns out not to start
    property var values: []                // 0..1 per bar, from the last frame

    // ---- the source ----
    readonly property string source: String(Theme.data.visualizer_source || "auto")
    // "ok", "missing" (the chosen app isn't playing), "failed" (cava couldn't use it)
    property string sourceState: "ok"
    readonly property string runtimeConfig: (Quickshell.env("XDG_RUNTIME_DIR") || "/tmp") + "/dxrice/cava.conf"
    property FileView template: FileView { path: Quickshell.shellDir + "/cava.conf"; blockLoading: true }
    // the config cava was last started on (for the tests: what it read)
    property string lastConfig: ""
    // the cava [input] lines for a resolved source
    function configFor(method, src) {
        return root.template.text()
            .replace(/^method = pipewire$/m, "method = " + method)
            .replace(/^source = auto$/m, "source = " + src);
    }
    property bool _resolving: false
    Process {
        id: streams
        objectName: "visualizerStreams"
        command: ["pactl", "-f", "json", "list", "sink-inputs"]
        stdout: StdioCollector {
            onStreamFinished: {
                root._resolving = false;
                let list = [];
                try { list = JSON.parse(this.text); } catch (e) { list = []; }
                const want = root.source.slice(4);
                const hit = list.find((x) => { const p = x.properties || {}; return (p["application.name"] || p["node.name"]) === want && !x.corked; })
                    || list.find((x) => { const p = x.properties || {}; return (p["application.name"] || p["node.name"]) === want; });
                if (!hit) { root.sourceState = "missing"; return; }
                root._start("pipewire", String((hit.properties || {})["object.serial"] || hit.index));
            }
        }
    }
    function _start(method, src) {
        if (method === "pipewire" && src === "auto") {
            root.lastConfig = root.template.text();
            cava.command = ["cava", "-p", Quickshell.shellDir + "/cava.conf"];
        } else {
            const text = root.configFor(method, src);
            const dir = root.runtimeConfig.slice(0, root.runtimeConfig.lastIndexOf("/"));
            root.lastConfig = text;
            cava.command = ["sh", "-c", 'mkdir -p "$1" && printf %s "$2" > "$1/cava.conf" && exec cava -p "$1/cava.conf"', "cava", dir, text];
        }
        root.sourceState = "ok";
        root._frames = 0;
        Qt.callLater(() => { if (root.active) cava.running = true; });
    }
    // starts cava for the current source (resolving an app's stream first)
    function _launch() {
        if (root.source.indexOf("app:") === 0) {
            if (!root._resolving) { root._resolving = true; streams.running = true; }
        } else if (root.source.indexOf("monitor:") === 0) {
            root._start("pulse", root.source.slice(8) + ".monitor");
        } else {
            root._start("pipewire", "auto");
        }
    }
    // a new choice: cava restarts on it straight away
    onSourceChanged: {
        root.available = true;
        root.sourceState = "ok";
        retry.stop();
        if (cava.running) { root._switching = true; cava.running = false; }
        else root._sync();
    }
    property bool _switching: false
    // the chosen app isn't playing yet: look again every few seconds
    Timer {
        running: root.active && root.sourceState === "missing"
        interval: 3000; repeat: true
        onTriggered: root._launch()
    }
    // silence (nothing above the floor for a while) fades the bars out
    property bool quiet: false
    Timer { id: quietTimer; interval: 1500; onTriggered: root.quiet = true }
    onValuesChanged: {
        if (root.values.some((v) => v > 0.02)) { root.quiet = false; quietTimer.stop(); }
        else if (!root.quiet && !quietTimer.running) quietTimer.start();
    }

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
        onRunningChanged: if (!running) {
            if (root._switching) { root._switching = false; root.values = []; root._sync(); return; }
            if (!root.active) return;
            // never a frame: on automatic that means no cava/PipeWire here at
            // all; on a chosen source, that this source didn't work
            if (root._frames === 0) { if (root.source === "auto") root.available = false; else root.sourceState = "failed"; }
            else retry.start();
        }
    }
    Timer { id: retry; interval: 2000; onTriggered: root._sync() }
    function _sync() {
        if (root.active && !cava.running) root._launch();
        else if (!root.active && cava.running) cava.running = false;
    }
    onActiveChanged: { if (!root.active) { root.values = []; retry.stop(); } root._sync(); }
    Component.onCompleted: root._sync()

    property real shown: root.active && !(root.chosen && root.quiet) ? 1 : 0
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
