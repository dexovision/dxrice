pragma Singleton
import QtQuick
import Quickshell
import Quickshell.Io

// Screenshots and screen recordings (scripts/dxrice_capture.sh: grim, slurp,
// wf-recorder). A recording runs as long as its process does, so
// `recording` is the process itself, not a guess; `elapsed` counts seconds
// from its start for the bar's timer. Whoever asks for a capture closes its
// own panel first: the shot waits a moment so the panel is not in it.
QtObject {
    id: root
    readonly property string script: Quickshell.shellDir + "/../scripts/dxrice_capture.sh"
    // running = the script is up; `recording` only once wf-recorder has really
    // started (the script prints "started"), `picking` while a region is
    // still being chosen
    property bool _started: false
    readonly property bool recording: recorder.running && root._started
    readonly property bool picking: recorder.running && !root._started
    property int elapsed: 0
    property string _pendingShot: ""
    // the sound a recording takes: "none", "desktop" (what is playing) or
    // "mic"; picked before it starts (theme.json "record_audio" is the
    // default). `recordingAudio` is what the running one has.
    property string audio: ["desktop", "mic"].indexOf(String(Theme.data.record_audio)) >= 0 ? String(Theme.data.record_audio) : "none"
    property string recordingAudio: "none"

    property Process recorder: Process {
        onRunningChanged: { root._started = false; root.elapsed = 0; }
        stdout: SplitParser { onRead: (line) => { if (String(line).trim() === "started") { root.elapsed = 0; root._started = true; } } }
    }
    property Timer tick: Timer {
        interval: 1000; repeat: true
        running: root.recording
        onTriggered: root.elapsed += 1
    }
    property Timer shotDelay: Timer {
        interval: 280
        onTriggered: Quickshell.execDetached(["sh", root.script, "shot", root._pendingShot])
    }

    function shot(mode) {
        root._pendingShot = mode === "screen" ? "screen" : "region";
        root.shotDelay.restart();
    }
    // a recording waits the same moment, so its first frames aren't the
    // panel closing
    property Timer recordDelay: Timer {
        interval: 280
        onTriggered: root.recorder.running = true
    }
    function record(mode) {
        if (root.recorder.running || root.recordDelay.running) return;
        root.recordingAudio = root.audio;
        root.recorder.command = ["sh", root.script, "record", mode === "region" ? "region" : "screen", root.audio];
        root.recordDelay.restart();
    }
    function stop() { if (root.recorder.running) Quickshell.execDetached(["sh", root.script, "stop"]); }
    function clock(s) { return Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0"); }
}
