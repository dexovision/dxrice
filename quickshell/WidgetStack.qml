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
// Every widget is drawn at `scale`: designed for a 1080 px tall screen and
// sized in proportion to the real one (0.72x-1.3x), so the desktop keeps its
// composition on a laptop panel and on a 1440p monitor alike. Sizes reported
// here, and the places returned, are as drawn (scaled); the margins and
// gaps are not scaled, so the edges stay where the bar's are.
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
    // the widgets being dragged to new corners (ArrangeBar, IPC "widgets")
    property bool arranging: false
    readonly property real bottomClearance: Math.max(root.edgeClearance, root.visualizerBand > 0 ? root.visualizerBand + root.gap : 0)
    property real screenWidth: 1920
    property real screenHeight: 1080
    readonly property real scale: Math.max(0.72, Math.min(1.3, root.screenHeight / 1080))
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

    // how deep the facing corner's widgets reach over the span [x, x + w)
    function _reach(rects, x, w) {
        let r = 0;
        for (const q of rects) if (q.x < x + w && x < q.x + q.w) r = Math.max(r, q.y + q.h + root.gap);
        return r;
    }
    // Lays `names` out in columns from the corner, each against the facing
    // corner's widgets (`others`, as placed); returns its own as placed.
    // A widget that doesn't fit under the last one starts a new column, at
    // the first spot past its own columns where the facing corner leaves it
    // room -- right beside a narrow widget there, not past the widest.
    function _flow(names, others, out) {
        const placed = [];
        let col = { x: 0, w: 0, y: 0 };
        for (const n of names) {
            const e = root.entries[n];
            const fits = (x, y) => y + e.height <= root.room - root._reach(others, x, e.width);
            if (!fits(col.x, col.y)) {
                const from = col.y > 0 ? col.x + col.w + root.gap : col.x;
                const spots = [from].concat(others.map((q) => q.x + q.w + root.gap).filter((x) => x > from)).sort((a, b) => a - b);
                const x = spots.find((x) => fits(x, 0));
                col = { x: x === undefined ? from : x, w: 0, y: 0 };
            }
            out[n] = { dx: col.x, dy: col.y };
            placed.push({ x: col.x, y: col.y, w: e.width, h: e.height });
            col.y += e.height + root.gap;
            col.w = Math.max(col.w, e.width);
        }
        return placed;
    }
}
