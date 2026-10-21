pragma Singleton
import QtQuick

// Where each desktop widget sits within its corner. Widgets choose a corner
// (theme.json "widget_<name>_pos"); two in the same corner used to land on
// top of each other. Each shown widget reports its corner and height here,
// and is placed after the ones before it in that corner, in the fixed order
// of `order` (not creation order, which QML doesn't promise), a gap apart --
// downward from a top corner, upward from a bottom one.
QtObject {
    id: root
    readonly property real gap: 16
    readonly property var order: ["clock", "reminders", "system", "cpu", "memory", "disk", "battery", "weather", "music", "timer"]
    property var entries: ({})      // name -> { corner, height, shown, order }

    function report(name, corner, height, shown) {
        const old = root.entries[name];
        if (old && old.corner === corner && old.height === height && old.shown === shown) return;
        const e = Object.assign({}, root.entries);
        const at = root.order.indexOf(name);
        e[name] = { corner: corner, height: height, shown: shown, order: at >= 0 ? at : root.order.length };
        root.entries = e;
    }
    function offsetOf(name) {
        const me = root.entries[name];
        if (!me) return 0;
        let off = 0;
        for (const k in root.entries) {
            const o = root.entries[k];
            if (k !== name && o.shown && o.corner === me.corner && o.order < me.order) off += o.height + root.gap;
        }
        return off;
    }
}
