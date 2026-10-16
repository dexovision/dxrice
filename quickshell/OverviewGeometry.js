.pragma library

// The desktop overview's geometry, computed in the shell itself from
// `hyprctl -j clients` / `hyprctl -j monitors` -- a line-for-line mirror of
// scripts/dxrice_overview.py (the reference implementation and CLI; a test
// keeps the two equal on hundreds of random workspaces). It lives here so
// opening the overview never waits for a Python interpreter to start.
//
// overview(clients, monitors, monitorName, margin) ->
//   { monitor: {name, x, y, width, height},   // the usable area
//     reserved: [left, top, right, bottom], workspace, scale, fits, clipped,
//     windows: [{address, class, title, x, y, w, h, tx, ty, tw, th,
//                floating, fullscreen, pinned, z}] }   // bottom first
// Rects are relative to the usable area's top-left.

var OVERVIEW_MARGIN = 48;
var MIN_SCALE = 0.08;
var MAX_SCALE = 1.0;

function _round2(v) {
    return Math.round(v * 100) / 100;
}

function monitorRect(m) {
    var w = m.width, h = m.height;
    if ([1, 3, 5, 7].indexOf(m.transform || 0) >= 0) { var t = w; w = h; h = t; }
    var scale = Number(m.scale) || 1.0;
    if (scale > 0) { w = Math.round(w / scale); h = Math.round(h / scale); }
    var r = m.reserved || [0, 0, 0, 0];
    var left = parseInt(r[0]) || 0, top = parseInt(r[1]) || 0, right = parseInt(r[2]) || 0, bottom = parseInt(r[3]) || 0;
    if (!(left + right < w && top + bottom < h)) { left = top = right = bottom = 0; }
    return { rect: [m.x + left, m.y + top, m.x + w - right, m.y + h - bottom], reserved: [left, top, right, bottom] };
}

function pickMonitor(monitors, name) {
    if (!monitors || !monitors.length) return null;
    var i;
    if (name) for (i = 0; i < monitors.length; i++) if (monitors[i].name === name) return monitors[i];
    for (i = 0; i < monitors.length; i++) if (monitors[i].focused) return monitors[i];
    return monitors[0];
}

function members(clients, monitor) {
    var ws = (monitor.activeWorkspace || {}).id;
    var special = (monitor.specialWorkspace || {}).id || 0;
    var out = [];
    (clients || []).forEach(function (c) {
        if (c.mapped === false || c.hidden) return;
        var size = c.size || [0, 0];
        if (size[0] < 2 || size[1] < 2) return;
        var cws = (c.workspace || {}).id;
        var onMonitor = c.monitor === monitor.id;
        if (!(cws === ws || (special && cws === special) || (c.pinned && onMonitor))) return;
        out.push(c);
    });
    function layer(c) {
        if (c.fullscreen) return 2;
        return (c.floating || c.pinned) ? 1 : 0;
    }
    // stable sort (Python's is): least recently focused first within a layer
    out = out.map(function (c, i) { return { c: c, i: i }; });
    out.sort(function (a, b) {
        var la = layer(a.c), lb = layer(b.c);
        if (la !== lb) return la - lb;
        var fa = -(parseInt(a.c.focusHistoryID) || 0), fb = -(parseInt(b.c.focusHistoryID) || 0);
        if (fa !== fb) return fa - fb;
        return a.i - b.i;
    });
    return out.map(function (e) { return e.c; });
}

function fit(rects, area, margin) {
    if (margin === undefined) margin = OVERVIEW_MARGIN;
    var ax0 = area[0], ay0 = area[1], ax1 = area[2], ay1 = area[3];
    if (!rects.length) return { scale: 1.0, dx: 0, dy: 0, fits: true, clipped: false };
    var bx0 = Infinity, by0 = Infinity, bx1 = -Infinity, by1 = -Infinity;
    rects.forEach(function (r) {
        bx0 = Math.min(bx0, r[0]); by0 = Math.min(by0, r[1]); bx1 = Math.max(bx1, r[2]); by1 = Math.max(by1, r[3]);
    });
    if (bx0 >= ax0 && by0 >= ay0 && bx1 <= ax1 && by1 <= ay1)
        return { scale: 1.0, dx: 0, dy: 0, fits: true, clipped: false };
    var availW = Math.max(1, (ax1 - ax0) - 2 * margin);
    var availH = Math.max(1, (ay1 - ay0) - 2 * margin);
    var want = Math.min(availW / Math.max(1, bx1 - bx0), availH / Math.max(1, by1 - by0));
    var scale = Math.min(MAX_SCALE, Math.max(MIN_SCALE, want));
    var cx = (ax0 + ax1) / 2, cy = (ay0 + ay1) / 2;
    return { scale: scale, dx: cx - scale * (bx0 + bx1) / 2, dy: cy - scale * (by0 + by1) / 2,
             fits: false, clipped: want < MIN_SCALE };
}

function overview(clients, monitors, monitorName, margin) {
    if (margin === undefined || margin === null) margin = OVERVIEW_MARGIN;
    var m = pickMonitor(monitors, monitorName);
    if (!m) return { monitor: null, reserved: [0, 0, 0, 0], workspace: null, scale: 1.0, fits: true, clipped: false, windows: [] };
    var mr = monitorRect(m), a = mr.rect;
    var wins = members(clients, m);
    var local = wins.map(function (c) {
        return [c.at[0] - a[0], c.at[1] - a[1], c.at[0] - a[0] + c.size[0], c.at[1] - a[1] + c.size[1]];
    });
    var f = fit(local, [0, 0, a[2] - a[0], a[3] - a[1]], margin);
    var out = wins.map(function (c, z) {
        var r = local[z];
        return {
            address: c.address || "", "class": c["class"] || "", title: c.title || "",
            x: r[0], y: r[1], w: r[2] - r[0], h: r[3] - r[1],
            tx: _round2(r[0] * f.scale + f.dx), ty: _round2(r[1] * f.scale + f.dy),
            tw: _round2((r[2] - r[0]) * f.scale), th: _round2((r[3] - r[1]) * f.scale),
            floating: !!c.floating, fullscreen: !!c.fullscreen, pinned: !!c.pinned, z: z
        };
    });
    return {
        monitor: { name: m.name || "", x: a[0], y: a[1], width: a[2] - a[0], height: a[3] - a[1] },
        reserved: mr.reserved, workspace: (m.activeWorkspace || {}).id,
        scale: f.scale, fits: f.fits, clipped: f.clipped, windows: out
    };
}

// Whether a window's real rect (usable-relative, as in overview()) shows on
// the monitor at all. A window entirely off screen is never given focus by a
// click: keystrokes would go to a window nobody can see.
function onScreen(w, layout) {
    var r = layout.reserved || [0, 0, 0, 0];
    var W = layout.monitor.width + r[0] + r[2], H = layout.monitor.height + r[1] + r[3];
    var x0 = w.x + r[0], y0 = w.y + r[1];
    return x0 < W && x0 + w.w > 0 && y0 < H && y0 + w.h > 0;
}

// How long Hyprland's window-move animation runs, in ms, from
// `hyprctl -j animations` ([[leaf...], [bezier...]] or a flat leaf list).
// The most specific overridden leaf wins: windowsMove, then windows, then
// global. A disabled leaf moves windows at once (0). Speed is in units of
// 100 ms. null when the reply can't be read.
function windowMoveMs(reply) {
    if (!reply || !reply.length) return null;
    const leaves = Array.isArray(reply[0]) ? reply[0] : reply;
    const byName = {};
    for (let i = 0; i < leaves.length; i++)
        if (leaves[i] && leaves[i].name) byName[leaves[i].name] = leaves[i];
    const order = ["windowsMove", "windows", "global"];
    for (let i = 0; i < order.length; i++) {
        const leaf = byName[order[i]];
        if (!leaf || (order[i] !== "global" && leaf.overridden === false)) continue;
        if (leaf.enabled === false) return 0;
        const speed = Number(leaf.speed);
        return isFinite(speed) && speed >= 0 ? Math.round(speed * 100) : null;
    }
    return null;
}
