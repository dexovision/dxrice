import QtQuick
import Quickshell

// A stopwatch and a countdown, one at a time. The stopwatch counts up
// from start (pause and resume keep its time, Lap marks a split -- the last
// three show, newest first -- reset clears it all); a
// countdown runs from one of a few presets and, when it reaches zero, says
// so with a real desktop notification. Time is measured against the clock,
// not by counting ticks, so it stays right if the shell is busy.
DesktopWidget {
    id: root
    name: "timer"
    defaultCorner: "bottom-right"
    defaultOn: false
    surface: "glass"
    contentWidth: 232
    contentHeight: col.implicitHeight

    property string mode: "stopwatch"          // or "countdown"
    property bool running: false
    property real elapsedMs: 0                   // stopwatch: time counted so far
    property real startedAt: 0                   // when the running stretch began
    property real targetMs: 5 * 60 * 1000        // countdown length
    property real now: Date.now()
    readonly property real totalElapsed: root.elapsedMs + (root.running ? root.now - root.startedAt : 0)
    readonly property real shownMs: root.mode === "countdown" ? Math.max(0, root.targetMs - root.totalElapsed) : root.totalElapsed

    function start() { if (root.running) return; root.startedAt = Date.now(); root.now = root.startedAt; root.running = true; }
    function pause() { if (!root.running) return; root.elapsedMs += Date.now() - root.startedAt; root.running = false; }
    function reset() { root.running = false; root.elapsedMs = 0; root.laps = []; }
    // splits: the total at each Lap, newest first
    property var laps: []
    function lap() { if (root.mode === "stopwatch" && root.running) { root.now = Date.now(); root.laps = [root.totalElapsed].concat(root.laps); } }
    function countdown(minutes) { root.reset(); root.mode = "countdown"; root.targetMs = minutes * 60000; root.start(); }
    function stopwatch() { root.reset(); root.mode = "stopwatch"; }
    function format(ms) {
        const t = Math.floor(ms / 1000);
        const h = Math.floor(t / 3600), m = Math.floor(t % 3600 / 60), sec = t % 60;
        const tenths = root.mode === "stopwatch" && h === 0 ? "." + Math.floor(ms % 1000 / 100) : "";
        return (h > 0 ? h + ":" + String(m).padStart(2, "0") : String(m)) + ":" + String(sec).padStart(2, "0") + tenths;
    }
    Timer {
        running: root.running && root.active
        interval: root.mode === "stopwatch" ? 100 : 250
        repeat: true
        onTriggered: {
            root.now = Date.now();
            if (root.mode === "countdown" && root.shownMs <= 0) {
                root.running = false;
                root.elapsedMs = root.targetMs;
                Quickshell.execDetached(["notify-send", "-a", "DXrice", "Timer", "Your " + Math.round(root.targetMs / 60000) + "-minute timer is done."]);
            }
        }
    }

    Column {
        id: col
        width: parent.width
        spacing: 10
        Row {
            spacing: 6
            Repeater {
                model: [{ id: "stopwatch", label: "Stopwatch" }, { id: "countdown", label: "Timer" }]
                delegate: Text {
                    required property var modelData
                    text: modelData.label.toUpperCase()
                    color: root.mode === modelData.id ? Theme.accent : Theme.text
                    opacity: root.mode === modelData.id ? 1 : 0.55
                    font.family: Theme.fontFamily; font.pixelSize: 10; font.weight: Font.Bold; font.letterSpacing: 1.5
                    rightPadding: 8
                    MouseArea {
                        anchors.fill: parent; cursorShape: Qt.PointingHandCursor
                        onClicked: modelData.id === "stopwatch" ? root.stopwatch() : root.countdown(5)
                    }
                }
            }
        }
        Text {
            objectName: "timerDisplay"
            text: root.format(root.shownMs)
            color: Theme.textActive
            font.family: Theme.fontMono; font.pixelSize: 40; font.weight: Font.Light
        }
        Row {
            spacing: Theme.padSm
            visible: root.mode === "countdown"
            Repeater {
                model: [1, 5, 10, 25]
                delegate: GlassButton {
                    required property int modelData
                    objectName: "timerPreset:" + modelData
                    text: modelData + "m"; variant: "secondary"
                    onClicked: root.countdown(modelData)
                }
            }
        }
        Row {
            spacing: Theme.padSm
            GlassButton {
                objectName: "timerStartPause"
                text: root.running ? "Pause" : (root.totalElapsed > 0 && root.shownMs > 0 ? "Resume" : "Start")
                variant: "primary"
                onClicked: root.running ? root.pause() : root.start()
            }
            GlassButton { objectName: "timerLap"; visible: root.mode === "stopwatch" && root.running; text: "Lap"; variant: "secondary"; onClicked: root.lap() }
            GlassButton { objectName: "timerReset"; visible: !(root.mode === "stopwatch" && root.running); text: "Reset"; variant: "secondary"; onClicked: root.reset() }
        }
        Column {
            visible: root.laps.length > 0
            width: parent.width
            spacing: 2
            Repeater {
                model: root.laps.slice(0, 3)
                delegate: Item {
                    required property real modelData
                    required property int index
                    objectName: "timerLapRow:" + index
                    width: col.width; height: 18
                    Text {
                        text: "Lap " + (root.laps.length - index)
                        color: Theme.text; opacity: Theme.opacityMuted
                        font.family: Theme.fontFamily; font.pixelSize: 11
                    }
                    Text {
                        anchors.right: parent.right
                        // the split, and its length since the lap before
                        text: root.format(modelData - (index + 1 < root.laps.length ? root.laps[index + 1] : 0)) + "   " + root.format(modelData)
                        color: index === 0 ? Theme.textActive : Theme.text
                        font.family: Theme.fontMono; font.pixelSize: 11
                    }
                }
            }
        }
    }
}
