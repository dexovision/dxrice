import QtQuick

// Test stub reproducing Quickshell's PendingRegion semantics (quickshell
// src/core/region.cpp + window/proxywindow.cpp) closely enough to model
// INPUT GEOMETRY the way the compositor sees it:
//  - an `item:` region is that item's rect mapped to the window scene,
//    INCLUDING any scale/transform, and ignores visible/opacity entirely;
//  - the window's mask is rebuilt (every item re-mapped live) only when
//    some region in the tree emits `changed` -- its own x/y/width/height/
//    item/children, or a tracked item's x/y/width/height. A scale or
//    opacity animation alone emits none of those, so the compositor keeps
//    whatever geometry the last rebuild captured. `_snapshot` caches the
//    rebuilt rects at the ROOT region the same way, so tests observe the
//    same (possibly stale) input region Hyprland would.
//  - child regions are unioned (the default Combine intersection).
QtObject {
    id: root
    default property list<QtObject> regions
    property Item item: null
    property real x: 0
    property real y: 0
    property real width: 0
    property real height: 0
    property int shape: 0
    property int intersection: 0

    signal changed()
    onXChanged: root.changed()
    onYChanged: root.changed()
    onWidthChanged: root.changed()
    onHeightChanged: root.changed()
    onRegionsChanged: {
        for (let i = 0; i < root.regions.length; i++) {
            const r = root.regions[i];
            if (r && r.changed && !r._hooked) { r._hooked = true; r.changed.connect(root.changed); }
        }
        root.changed();
    }
    property bool _hooked: false
    property Item _connected: null
    onItemChanged: {
        if (root._connected) {
            root._connected.xChanged.disconnect(root.changed);
            root._connected.yChanged.disconnect(root.changed);
            root._connected.widthChanged.disconnect(root.changed);
            root._connected.heightChanged.disconnect(root.changed);
        }
        root._connected = root.item;
        if (root.item) {
            root.item.xChanged.connect(root.changed);
            root.item.yChanged.connect(root.changed);
            root.item.widthChanged.connect(root.changed);
            root.item.heightChanged.connect(root.changed);
        }
        root.changed();
    }

    function _window(it) {
        let p = it;
        while (p && !p.isShellSurface) p = p.parent;
        return p;
    }
    function _liveRects() {
        let out = [];
        if (root.item) {
            const win = root._window(root.item);
            const p0 = root.item.mapToItem(win, 0, 0);
            const p1 = root.item.mapToItem(win, root.item.width, root.item.height);
            const r = { x: Math.floor(p0.x), y: Math.floor(p0.y), w: Math.ceil(p1.x - p0.x), h: Math.ceil(p1.y - p0.y) };
            if (r.w > 0 && r.h > 0) out.push(r);
        } else if (root.width > 0 && root.height > 0) {
            out.push({ x: root.x, y: root.y, w: root.width, h: root.height });
        }
        for (let i = 0; i < root.regions.length; i++) {
            const c = root.regions[i];
            if (c && c._liveRects) out = out.concat(c._liveRects());
        }
        return out;
    }

    // Root-only: the mask as last rebuilt. Rebuilt on the next event-loop
    // turn after a change, like the window's own deferred mask update.
    property var _snapshot: []
    property bool _pending: false
    onChanged: if (!root._pending) { root._pending = true; Qt.callLater(root._rebuild); }
    function _rebuild() { root._pending = false; root._snapshot = root._liveRects(); }
    Component.onCompleted: Qt.callLater(root._rebuild)

    function rects() { return root._snapshot; }
    function contains(px, py) {
        for (const r of root._snapshot) if (px >= r.x && px < r.x + r.w && py >= r.y && py < r.y + r.h) return true;
        return false;
    }
}
