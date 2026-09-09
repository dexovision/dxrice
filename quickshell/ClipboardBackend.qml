import QtQuick
import Quickshell.Io

// cliphist-backed clipboard history. copyEntry() feeds the raw "<id>\t
// <preview>" line cliphist itself printed (never the decoded payload,
// which may be binary -- e.g. an image entry) to `cliphist decode`,
// which is what cliphist actually expects on stdin. The decoded output
// (text or binary) flows straight through a shell pipe into wl-copy, at
// the OS level, never round-tripped through QML/JS string marshaling.
Item {
    id: root
    property var entries: [] // [{raw, preview}, ...]

    function refresh() {
        listProc.running = true;
    }

    Process {
        id: listProc
        command: ["cliphist", "list"]
        stdout: StdioCollector {
            onStreamFinished: {
                const lines = this.text.split("\n").filter((l) => l.length > 0).slice(0, 8);
                root.entries = lines.map((line) => {
                    const tab = line.indexOf("\t");
                    return tab >= 0 ? { raw: line, preview: line.slice(tab + 1) } : null;
                }).filter((e) => e !== null);
            }
        }
    }

    Process {
        id: copyProc
        command: ["sh", "-c", "cliphist decode | wl-copy"]
        stdinEnabled: true
        onRunningChanged: {
            if (running) {
                write(copyProc._pendingRaw + "\n");
                stdinEnabled = false; // closes stdin -> EOF -> cliphist decode can finish
            }
        }
        property string _pendingRaw: ""
    }

    function copyEntry(raw) {
        copyProc._pendingRaw = raw;
        copyProc.stdinEnabled = true;
        copyProc.running = true;
    }
}
