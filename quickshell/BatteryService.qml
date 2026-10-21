pragma Singleton
import QtQuick
import Quickshell.Io

// The machine's own battery (not a mouse's or a headset's: those report
// scope "Device"), for the bar and the Power panel. Found once; then two
// small sysfs reads every 20 s -- cheap enough to keep running, so the bar
// doesn't need the full performance sampler. No battery: `available` is
// false and nothing about one is shown.
QtObject {
    id: root
    property string path: ""
    readonly property bool available: root.path.length > 0 && root.percent >= 0
    property int percent: -1
    property string status: ""            // "Charging", "Discharging", "Full", "Not charging"
    readonly property bool charging: root.status === "Charging"
    readonly property bool plugged: root.status === "Charging" || root.status === "Full" || root.status === "Not charging"

    property Process detect: Process {
        command: ["sh", "-c", "for b in /sys/class/power_supply/*; do [ \"$(cat $b/type 2>/dev/null)\" = Battery ] "
                              + "&& [ \"$(cat $b/scope 2>/dev/null)\" != Device ] && [ -f $b/capacity ] && { echo $b; break; }; done; true"]
        running: true
        stdout: StdioCollector { onStreamFinished: { root.path = this.text.trim(); root.read(); } }
    }
    property FileView capFile: FileView { path: root.path ? root.path + "/capacity" : "" }
    property FileView statusFile: FileView { path: root.path ? root.path + "/status" : "" }
    function read() {
        if (!root.path) return;
        capFile.reload(); statusFile.reload();
        const c = parseInt(capFile.text().trim());
        root.percent = isNaN(c) ? -1 : Math.max(0, Math.min(100, c));
        root.status = statusFile.text().trim();
    }
    property Timer tick: Timer { interval: 20000; repeat: true; running: root.path.length > 0; onTriggered: root.read() }
}
