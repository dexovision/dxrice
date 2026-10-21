import QtQuick
import Quickshell.Io

// cliphist-backed clipboard history. copyEntry() feeds the raw "<id>\t
// <preview>" line cliphist itself printed (never the decoded payload,
// which may be binary -- e.g. an image entry) to `cliphist decode`,
// which is what cliphist actually expects on stdin. The decoded output
// (text or binary) flows straight through a shell pipe into wl-copy, at
// the OS level, never round-tripped through QML/JS string marshaling.
//
// Also: search (`query` narrows `entries`), deleting one entry (`cliphist
// delete`, fed the same raw line) and clearing the whole history
// (`cliphist wipe`). What is kept, and for how long, is cliphist's own
// store (the wl-paste watchers in hyprland.lua); nothing is copied
// anywhere else. cliphist has no pinning, so none is offered.
Item {
    id: root
    property var all: []     // [{raw, preview}, ...], newest first
    property string query: ""
    readonly property var entries: root.query.length === 0 ? root.all
        : root.all.filter((e) => e.preview.toLowerCase().indexOf(root.query.toLowerCase()) >= 0)

    function refresh() {
        listProc.running = true;
    }

    Process {
        id: listProc
        command: ["cliphist", "list"]
        stdout: StdioCollector {
            onStreamFinished: {
                const lines = this.text.split("\n").filter((l) => l.length > 0).slice(0, 200);
                root.all = lines.map((line) => {
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

    Process {
        id: deleteProc
        command: ["cliphist", "delete"]
        stdinEnabled: true
        property string _pendingRaw: ""
        onRunningChanged: {
            if (running) { write(deleteProc._pendingRaw + "\n"); stdinEnabled = false; }
            else root.refresh();
        }
    }
    function remove(raw) {
        root.all = root.all.filter((e) => e.raw !== raw);     // gone at once; the store follows
        deleteProc._pendingRaw = raw;
        deleteProc.stdinEnabled = true;
        deleteProc.running = true;
    }
    Process {
        id: wipeProc
        command: ["cliphist", "wipe"]
        onRunningChanged: if (!running) root.refresh()
    }
    function wipe() { root.all = []; wipeProc.running = true; }

    function copyEntry(raw) {
        copyProc._pendingRaw = raw;
        copyProc.stdinEnabled = true;
        copyProc.running = true;
    }
}
