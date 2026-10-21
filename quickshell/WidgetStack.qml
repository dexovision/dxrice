pragma Singleton
import QtQuick

// Where each desktop widget sits: the desktop's layout, in one place.
//
// A widget chooses a corner (theme.json "widget_<name>_pos") and reports its
// corner, size and whether it is shown here; this places it after the ones
// before it in that corner, in the fixed order of `order` (not creation
// order, which QML doesn't promise), a `gap` apart -- downward from a top
// corner, upward from a bottom one -- and returns how far in from its
// corner it goes (placeOf).
//
// The space a side has is the screen's height between the bar
// (`topClearance`) and the bottom band (`bottomClearance`). When the next
// widget would run past it -- or, from a bottom corner, into the stack
// coming down from the top corner of the same side -- it starts a new
// column further in instead of overlapping (a short screen, or many
// widgets on one side).
//
// The bottom band is the audio visualizer's while it can show (it reports
// `visualizerBand`): bottom-corner widgets sit above it rather than on it.
// It is held while a player exists, not only while one plays, so pausing
// from the music card doesn't move the card out from under the pointer.
QtObject {
    id: root
    readonly property real gap: 16
    readonly property real sideMargin: 28
    readonly property real topClearance: 76      // the bar
    readonly property real edgeClearance: 28     // the screen's bottom edge
    property real visualizerBand: 0
    readonly property real bottomClearance: Math.max(root.edgeClearance, root.visualizerBand > 0 ? root.visualizerBand + root.gap : 0)
    property real screenWidth: 1920
    property real screenHeight: 1080
    readonly property real room: root.screenHeight - root.topClearance - root.bottomClearance

    readonly property var order: ["clock", "date", "reminders", "system", "cpu", "memory", "disk", "sensors", "battery", "weather", "music", "timer"]
    property var entries: ({})      // name -> { corner, width, height, shown, order }

    function report(name, corner, width, height, shown) {
        const old = root.entries[name];
        if (old && old.corner === corner && old.width === width && old.height === height && old.shown === shown) return;
        const e = Object.assign({}, root.entries);
        const at = root.order.indexOf(name);
        e[name] = { corner: corner, width: width, height: height, shown: shown, order: at >= 0 ? at : root.order.length };
        root.entries = e;
    }

    // name -> { dx, dy }: in from the corner's side edge, and down from the
    // bar (a top corner) or up from the bottom band (a bottom corner)
    readonly property var places: {
        const out = {};
        for (const side of ["left", "right"]) {
            const pick = (v) => Object.keys(root.entries)
                .filter((k) => root.entries[k].shown && root.entries[k].corner === v + "-" + side)
                .sort((a, b) => root.entries[a].order - root.entries[b].order || (a < b ? -1 : 1));
            const tops = root._flow(pick("top"), [], out);
            root._flow(pick("bottom"), tops, out);
        }
        return out;
    }
    function placeOf(name) { return root.places[name] || { dx: 0, dy: 0 }; }

    // the deepest the given columns reach over the span [x, x + w)
    function _reach(cols, x, w) {
        let r = 0;
        for (const c of cols) if (c.x < x + w && x < c.x + c.w && c.y > 0) r = Math.max(r, c.y);
        return r;
    }
    function _blocker(cols, x, w) {
        for (const c of cols) if (c.x < x + w && x < c.x + c.w && c.y > 0) return c;
        return null;
    }
    // lays `names` out in columns from the corner, avoiding `others` (the
    // facing corner's columns); returns its own columns
    function _flow(names, others, out) {
        const cols = [];
        let col = { x: 0, w: 0, y: 0 };
        cols.push(col);
        for (const n of names) {
            const e = root.entries[n];
            const fits = (c) => c.y + e.height <= root.room - root._reach(others, c.x, Math.max(c.w, e.width));
            if (!fits(col)) {
                if (col.y > 0) { col = { x: col.x + col.w + root.gap, w: 0, y: 0 }; cols.push(col); }
                // past whatever the facing corner leaves no room beside
                for (let guard = 0; guard < 8 && !fits(col); guard++) {
                    const b = root._blocker(others, col.x, e.width);
                    if (!b) break;
                    col.x = b.x + b.w + root.gap;
                }
            }
            out[n] = { dx: col.x, dy: col.y };
            col.y += e.height + root.gap;
            col.w = Math.max(col.w, e.width);
        }
        return cols;
    }
}
