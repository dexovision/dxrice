.pragma library

// Where a child surface that "branches" off something should go. Pure
// geometry -- no QML, no state -- so it can be exercised with any target
// rectangle and screen size (tests/qml/test_branch_geometry.py).
//
// Two policies share the same primitives (the room on each side of a
// target, where a surface beside / stacked off it starts, clamping):
//
//   place()   a branch off a whole PANEL -- the Taskbar's Add Shortcut.
//   attach()  a branch off one small CONTROL inside a panel -- the Theme
//             editor's colour picker growing out of the swatch clicked.
//
// Rects are {x, y, w, h}; points {x, y}; sizes {w, h}; all in the same
// (screen) coordinates.

function _rooms(t, bounds, g) {
    // Space between the target's edges (plus the gap) and the bounds.
    return {
        right: bounds.x + bounds.w - (t.x + t.w + g),
        left: t.x - g - bounds.x,
        below: bounds.y + bounds.h - (t.y + t.h + g),
        above: t.y - g - bounds.y,
    };
}

function _besideX(t, side, w, g) {
    return side === "right" ? t.x + t.w + g : t.x - g - w;
}

function _stackY(t, side, h, g) {
    return side === "below" ? t.y + t.h + g : t.y - g - h;
}

function _clamp(v, lo, hi) {
    return Math.max(lo, Math.min(v, hi));
}

// ---- place(): a branch off a panel (Add Shortcut) ---------------------------
//
//   parent  {x, y, w, h}  the parent panel's live on-screen rect
//   anchor  {x, y}        the control the branch grows out of (screen coords)
//   want    {w, h}        the branch's preferred size
//   screen  {w, h}
//   opts    {margin, gap, minW, minH, headerH, footerH}
//
// Preference order -- each the first that fits:
//   "right" / "left"  beside the parent, the same height as it and
//                     top/bottom-aligned with it (the side with
//                     the most room first, so a parent near one screen edge
//                     branches toward the open side);
//   "above" / "below" stacked off the parent edge with the most room,
//                     horizontally centred on the anchor;
//   "sheet"           nothing outside the parent fits (a small screen): an
//                     inset sheet INSIDE the parent's own body, hanging
//                     from its header -- still visibly part of the parent.
// Every result is clamped to the screen minus `margin` on all sides, and
// may shrink below `want` (never below minW/minH unless the screen itself
// is smaller) rather than run off-screen.
function place(parent, anchor, want, screen, opts) {
    const m = opts.margin, g = opts.gap;
    const minW = Math.min(opts.minW, screen.w - 2 * m);
    const minH = Math.min(opts.minH, screen.h - 2 * m);
    const maxH = Math.min(want.h, screen.h - 2 * m);

    function clampY(y, h) { return Math.max(m, Math.min(y, screen.h - m - h)); }
    function clampX(x, w) { return Math.max(m, Math.min(x, screen.w - m - w)); }

    const room = _rooms(parent, { x: m, y: m, w: screen.w - 2 * m, h: screen.h - 2 * m }, g);
    const sides = room.right >= room.left
        ? [["right", room.right], ["left", room.left]]
        : [["left", room.left], ["right", room.right]];
    for (const [side, r] of sides) {
        if (r < minW) continue;
        const w = Math.min(want.w, r);
        // Matching the parent's height (top AND bottom edges line up) is
        // what makes two surfaces read as one composition; the branch only
        // outgrows its parent when the parent is shorter than the branch's
        // usable minimum.
        const h = Math.min(maxH, Math.max(parent.h, minH));
        return { side: side, x: _besideX(parent, side, w, g), y: clampY(parent.y, h), w: w, h: h };
    }

    const stacks = room.above >= room.below
        ? [["above", room.above], ["below", room.below]]
        : [["below", room.below], ["above", room.above]];
    for (const [side, r] of stacks) {
        if (r < minH) continue;
        const h = Math.min(maxH, r);
        const w = Math.min(want.w, screen.w - 2 * m);
        return { side: side, x: clampX(anchor.x - w / 2, w), y: _stackY(parent, side, h, g), w: w, h: h };
    }

    // Sheet: inside the parent, below its header, inset like the parent's
    // own cards. Height is whatever the parent body offers.
    const inset = g;
    const w = Math.max(0, Math.min(want.w, parent.w - 2 * inset));
    const top = parent.y + opts.headerH;
    const h = Math.max(0, Math.min(maxH, parent.y + parent.h - (opts.footerH || 0) - inset - top));
    return { side: "sheet", x: clampX(Math.min(anchor.x + 24, parent.x + parent.w - inset) - w, w), y: clampY(top, h), w: w, h: h };
}

// ---- attach(): a branch off one control (the colour picker) ----------------
//
//   target  {x, y, w, h}  the control's live rect (the swatch)
//   want    {w, h}        the surface's preferred size
//   bounds  {x, y, w, h}  where the surface may go (the screen minus its
//                         margin -- and minus whatever the caller's panel
//                         hangs from, so it never rides over the bar)
//   opts    {gap, minW, minH, order?}
//
// The surface starts `gap` from the target's own edge and sits centred on
// it along that edge, so the control it grows out of is always right
// there -- never "beside the panel somewhere". Tries `order` (default
// right, left, below, above) and takes the first side with at least
// minW/minH of room. If none has, it squeezes onto the side with the most
// room rather than covering the target: `fallback: true` marks that.
// Every result lies inside `bounds`.
function attach(target, want, bounds, opts) {
    const g = opts.gap;
    const order = opts.order || ["right", "left", "below", "above"];
    const room = _rooms(target, bounds, g);
    const cx = target.x + target.w / 2, cy = target.y + target.h / 2;

    function make(side, w, h, fallback) {
        w = Math.max(0, Math.min(w, bounds.w));
        h = Math.max(0, Math.min(h, bounds.h));
        const horizontal = side === "right" || side === "left";
        const x = horizontal ? _besideX(target, side, w, g)
                             : _clamp(cx - w / 2, bounds.x, bounds.x + bounds.w - w);
        const y = horizontal ? _clamp(cy - h / 2, bounds.y, bounds.y + bounds.h - h)
                             : _stackY(target, side, h, g);
        return { side: side, x: x, y: y, w: w, h: h, fallback: fallback };
    }

    for (const side of order) {
        const horizontal = side === "right" || side === "left";
        if (horizontal && room[side] >= opts.minW) return make(side, Math.min(want.w, room[side]), want.h, false);
        if (!horizontal && room[side] >= opts.minH) return make(side, want.w, Math.min(want.h, room[side]), false);
    }
    // Nowhere fits: the roomiest side (relative to what each axis needs),
    // squeezed to its room -- still beside the target, still not over it.
    let best = order[0], bestScore = -Infinity;
    for (const side of order) {
        const horizontal = side === "right" || side === "left";
        const score = room[side] / (horizontal ? opts.minW : opts.minH);
        if (score > bestScore) { best = side; bestScore = score; }
    }
    const horizontal = best === "right" || best === "left";
    return horizontal ? make(best, Math.max(0, room[best]), want.h, true)
                      : make(best, want.w, Math.max(0, room[best]), true);
}
