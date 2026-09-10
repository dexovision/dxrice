import QtQuick
import Quickshell
import Quickshell.Io

// Backlight control. hasBacklight starts false and flips true only once a
// real reading comes back, so a desktop with no backlight never shows a
// slider that does nothing.
//
// Watches the real sysfs brightness file (watchChanges: true) instead of
// only reading brightnessctl once at startup -- a one-shot read meant this
// never noticed a brightness change made outside Quickshell (a hardware
// key handled directly by brightnessctl's own keybind, another app), which
// is exactly the case an OSD needs to react to.
Item {
    id: root
    property bool hasBacklight: false
    property int percent: 0
    property string devicePath: ""
    property int max: 0

    Component.onCompleted: listProc.running = true

    // Discovers the backlight device name once (e.g. "amdgpu_bl2") rather
    // than hardcoding one -- varies by GPU/laptop.
    Process {
        id: listProc
        command: ["sh", "-c", "ls /sys/class/backlight 2>/dev/null | head -1"]
        stdout: StdioCollector {
            onStreamFinished: {
                const device = this.text.trim();
                if (device) root.devicePath = "/sys/class/backlight/" + device;
            }
        }
    }

    FileView {
        id: maxFile
        path: root.devicePath ? root.devicePath + "/max_brightness" : ""
        onLoaded: { root.max = parseInt(this.text().trim(), 10) || 0; root._recompute(); }
    }
    FileView {
        id: brightnessFile
        path: root.devicePath ? root.devicePath + "/brightness" : ""
        watchChanges: true
        onFileChanged: this.reload()
        onLoaded: root._recompute()
    }

    function _recompute() {
        const current = parseInt(brightnessFile.text().trim(), 10) || 0;
        if (root.max > 0) {
            root.hasBacklight = true;
            root.percent = Math.round(current / root.max * 100);
        }
    }

    function refresh() {
        if (root.devicePath) { maxFile.reload(); brightnessFile.reload(); }
    }

    function set(percent) {
        root.percent = percent;
        Quickshell.execDetached(["brightnessctl", "set", Math.max(1, Math.min(100, Math.round(percent))) + "%"]);
    }
}
