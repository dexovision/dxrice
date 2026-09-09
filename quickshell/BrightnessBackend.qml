import QtQuick
import Quickshell
import Quickshell.Io

// brightnessctl-backed backlight control. hasBacklight starts false and
// flips true only once a real reading comes back, so a desktop with no
// backlight never shows a slider that does nothing.
Item {
    id: root
    property bool hasBacklight: false
    property int percent: 0

    Component.onCompleted: refresh()

    function refresh() {
        getProc.running = true;
        maxProc.running = true;
    }

    property int current: 0
    property int max: 0

    function _recompute() {
        if (root.max > 0) {
            root.hasBacklight = true;
            root.percent = Math.round(root.current / root.max * 100);
        }
    }

    Process {
        id: getProc
        command: ["brightnessctl", "get"]
        stdout: StdioCollector {
            onStreamFinished: { root.current = parseInt(this.text.trim(), 10) || 0; root._recompute(); }
        }
    }
    Process {
        id: maxProc
        command: ["brightnessctl", "max"]
        stdout: StdioCollector {
            onStreamFinished: { root.max = parseInt(this.text.trim(), 10) || 0; root._recompute(); }
        }
    }

    function set(percent) {
        root.percent = percent;
        Quickshell.execDetached(["brightnessctl", "set", Math.max(1, Math.min(100, Math.round(percent))) + "%"]);
    }
}
