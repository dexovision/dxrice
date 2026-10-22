pragma Singleton
import QtQuick
import Quickshell
import Quickshell.Io

// What mako (the running notification daemon) has: the notifications still
// on screen, which can be dismissed, and its history -- earlier ones, which
// mako keeps and has no way to clear, so they are listed, not removed.
// Summaries and app names only, never bodies.
//
// `unread` counts history entries newer than the last time the
// notifications section was looked at (markSeen); what was already in the
// history when the shell started doesn't count. mako itself announces
// nothing, but every notification passes over the session bus, so a watcher
// there (below) says when to read again -- two small makoctl calls each time.
QtObject {
    id: root
    property var onScreen: []          // [{id, app, summary}]
    property var history: []           // newest first
    property int seenId: -1
    property bool _first: true
    readonly property int unread: root.history.filter((n) => n.id > root.seenId).length + root.onScreen.length

    // `makoctl list -j` / `history -j` print a JSON array of objects; an
    // older mako printed a text listing ("Notification 12: summary" then
    // indented "App name: x"), read too
    function parse(text) {
        try {
            let d = JSON.parse(text);
            if (d && d.data) d = [].concat.apply([], d.data);
            if (Array.isArray(d)) {
                return d.map((n) => ({
                    id: Number((n.id && n.id.data !== undefined) ? n.id.data : n.id),
                    app: String((n.app_name && n.app_name.data !== undefined) ? n.app_name.data : (n.app_name || "")),
                    summary: String((n.summary && n.summary.data !== undefined) ? n.summary.data : (n.summary || "")).replace(/[⁨⁩]/g, ""),
                }));
            }
        } catch (e) {}
        const out = [];
        let cur = null;
        for (const line of String(text).split("\n")) {
            const m = /^Notification (\d+): (.*)$/.exec(line);
            if (m) { cur = { id: Number(m[1]), summary: m[2].replace(/[⁨⁩]/g, ""), app: "" }; out.push(cur); continue; }
            const a = /^\s+App name: (.*)$/.exec(line);
            if (a && cur) cur.app = a[1];
        }
        return out;
    }

    property Process historyProc: Process {
        command: ["makoctl", "history", "-j"]
        stdout: StdioCollector {
            onStreamFinished: {
                const list = root.parse(this.text).sort((a, b) => b.id - a.id);
                // mako numbers from 1 again when it restarts (its history
                // starts empty): what was cleared before means nothing then
                if (root.clearedId >= 0 && list.length && list[0].id < root._clearFloor) root._setCleared(-1, -1);
                root.history = list.filter((n) => n.id > root.clearedId).slice(0, 8);
                if (root._first) { root._first = false; root.markSeen(); }
            }
        }
    }
    property Process listProc: Process {
        command: ["makoctl", "list", "-j"]
        stdout: StdioCollector { onStreamFinished: root.onScreen = root.parse(this.text).sort((a, b) => b.id - a.id) }
    }
    function refresh() { historyProc.running = true; listProc.running = true; }
    // Told rather than asking: one dbus-monitor watches the session bus for
    // a notification arriving (Notify) or going (NotificationClosed,
    // CloseNotification) and the lists are read once, just after. stdbuf:
    // piped, dbus-monitor would hold its lines back until a buffer filled.
    // The poll stays as a slow safety net, and goes back to every 6 s if the
    // watcher can't run (no dbus-monitor, no session bus).
    readonly property bool watching: watch.running
    property Process watch: Process {
        command: ["stdbuf", "-oL", "dbus-monitor", "--session",
                  "type='method_call',interface='org.freedesktop.Notifications',member='Notify'",
                  "type='method_call',interface='org.freedesktop.Notifications',member='CloseNotification'",
                  "type='signal',interface='org.freedesktop.Notifications',member='NotificationClosed'"]
        running: true
        stdout: SplitParser { onRead: (line) => { if (/member=(Notify|CloseNotification|NotificationClosed)\b/.test(line)) root.soon.restart(); } }
        onRunningChanged: if (!running) rewatch.start()
    }
    property Timer rewatch: Timer { interval: 30000; onTriggered: root.watch.running = true }
    property Timer poll: Timer { interval: root.watching ? 60000 : 6000; repeat: true; running: true; triggeredOnStart: true; onTriggered: root.refresh() }
    property Timer soon: Timer { interval: 400; onTriggered: root.refresh() }

    function markSeen() {
        let max = root.seenId;
        for (const n of root.history) max = Math.max(max, n.id);
        for (const n of root.onScreen) max = Math.max(max, n.id);
        root.seenId = max;
    }
    function dismiss(id) { Quickshell.execDetached(["makoctl", "dismiss", "-n", String(id)]); root.soon.restart(); }
    function dismissAll() { Quickshell.execDetached(["makoctl", "dismiss", "--all"]); root.soon.restart(); }

    // ---- clearing ----
    // mako can't forget its history, so "Clear all" dismisses what is on
    // screen and the shell stops listing everything up to the newest one
    // (`clearedId`). Kept in $XDG_RUNTIME_DIR, which lives as long as the
    // session and mako do, so a shell restart doesn't bring them back.
    // `_clearFloor` is the newest id mako's history had then: a history
    // whose newest is older than that is a restarted mako's.
    property int clearedId: -1
    property int _clearFloor: -1
    readonly property string clearedPath: (Quickshell.env("XDG_RUNTIME_DIR") || "/tmp") + "/dxrice/notifications-cleared"
    property FileView clearedFile: FileView {
        path: root.clearedPath
        blockLoading: true
        printErrors: false
        onLoaded: root._readCleared()
    }
    Component.onCompleted: root._readCleared()
    function _readCleared() {
        const p = String(root.clearedFile.text()).trim().split(/\s+/).map(Number);
        if (p.length === 2 && p.every((v) => Number.isFinite(v))) { root.clearedId = p[0]; root._clearFloor = p[1]; }
    }
    function _setCleared(id, floor) {
        root.clearedId = id;
        root._clearFloor = floor;
        Quickshell.execDetached(["sh", "-c", 'mkdir -p "${1%/*}" && printf "%s %s" "$2" "$3" > "$1"', "sh", root.clearedPath, String(id), String(floor)]);
    }
    function clearAll() {
        let max = root.clearedId, floor = -1;
        for (const n of root.history) { max = Math.max(max, n.id); floor = Math.max(floor, n.id); }
        for (const n of root.onScreen) max = Math.max(max, n.id);
        if (max < 0) return;
        root._setCleared(max, floor >= 0 ? floor : max);
        root.history = [];
        root.markSeen();
        if (root.onScreen.length) root.dismissAll();
    }
}
