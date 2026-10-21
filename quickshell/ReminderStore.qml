pragma Singleton
import QtQuick
import Quickshell.Io

// Reminders you add yourself, kept on this machine in
// ~/.config/dxrice/reminders.json -- nothing is synced anywhere, and the
// panel and widget say so. One store for the calendar panel's agenda and
// the desktop reminders widget, so the two always show the same thing.
//
//   { "items": [ { "id": 3, "date": "2026-10-21", "text": "Dentist", "kind": "reminder" } ] }
//
// kind is one of `kinds` (a label and a glyph; nothing else depends on it).
QtObject {
    id: root
    readonly property string path: Xdg.configDir + "/reminders.json"
    readonly property var kinds: [
        { id: "reminder", label: "Reminder", glyph: "" },
        { id: "event", label: "Event", glyph: "" },
        { id: "birthday", label: "Birthday", glyph: "" },
        { id: "holiday", label: "Holiday", glyph: "" },
    ]
    property var items: []

    property FileView file: FileView {
        path: root.path
        watchChanges: true
        onFileChanged: this.reload()
        onLoaded: {
            try {
                const d = JSON.parse(this.text());
                root.items = Array.isArray(d.items) ? d.items.filter((i) => i && i.date && i.text) : [];
            } catch (e) {
                root.items = [];
            }
        }
        onLoadFailed: root.items = []
    }

    function key(date) {
        return date.getFullYear() + "-" + String(date.getMonth() + 1).padStart(2, "0") + "-" + String(date.getDate()).padStart(2, "0");
    }
    function on(date) { const k = root.key(date); return root.items.filter((i) => i.date === k); }
    function has(date) { const k = root.key(date); return root.items.some((i) => i.date === k); }
    // from `date` on, soonest first
    function upcoming(date, limit) {
        const k = root.key(date);
        return root.items.filter((i) => i.date >= k).sort((a, b) => a.date < b.date ? -1 : (a.date > b.date ? 1 : a.id - b.id)).slice(0, limit || 5);
    }
    function kindOf(id) { for (const k of root.kinds) if (k.id === id) return k; return root.kinds[0]; }

    function _save(list) {
        root.items = list;
        root.file.setText(JSON.stringify({ items: list }, null, 2) + "\n");
    }
    function add(date, text, kind) {
        const t = String(text || "").trim();
        if (!t) return false;
        let id = 1;
        for (const i of root.items) id = Math.max(id, (i.id || 0) + 1);
        root._save(root.items.concat([{ id: id, date: root.key(date), text: t, kind: root.kindOf(kind).id }]));
        return true;
    }
    function remove(id) { root._save(root.items.filter((i) => i.id !== id)); }
}
