.pragma library

// Where a child surface that "branches" off a parent panel should go.
// Pure geometry -- no QML, no state -- so it can be exercised with any
// parent rectangle and screen size (tests/qml/test_branch_geometry.py),
// not just the one spot the dock happens to put its panel today.
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

    const roomRight = screen.w - m - (parent.x + parent.w + g);
    const roomLeft = parent.x - g - m;
    const sides = roomRight >= roomLeft
        ? [["right", roomRight], ["left", roomLeft]]
        : [["left", roomLeft], ["right", roomRight]];
    for (const [side, room] of sides) {
        if (room < minW) continue;
        const w = Math.min(want.w, room);
        // Matching the parent's height (top AND bottom edges line up) is
        // what makes two surfaces read as one composition; the branch only
        // outgrows its parent when the parent is shorter than the branch's
        // usable minimum.
        const h = Math.min(maxH, Math.max(parent.h, minH));
        const x = side === "right" ? parent.x + parent.w + g : parent.x - g - w;
        return { side: side, x: x, y: clampY(parent.y, h), w: w, h: h };
    }

    const roomAbove = parent.y - g - m;
    const roomBelow = screen.h - m - (parent.y + parent.h + g);
    const stacks = roomAbove >= roomBelow
        ? [["above", roomAbove], ["below", roomBelow]]
        : [["below", roomBelow], ["above", roomAbove]];
    for (const [side, room] of stacks) {
        if (room < minH) continue;
        const h = Math.min(maxH, room);
        const w = Math.min(want.w, screen.w - 2 * m);
        const y = side === "above" ? parent.y - g - h : parent.y + parent.h + g;
        return { side: side, x: clampX(anchor.x - w / 2, w), y: y, w: w, h: h };
    }

    // Sheet: inside the parent, below its header, inset like the parent's
    // own cards. Height is whatever the parent body offers.
    const inset = g;
    const w = Math.max(0, Math.min(want.w, parent.w - 2 * inset));
    const top = parent.y + opts.headerH;
    const h = Math.max(0, Math.min(maxH, parent.y + parent.h - (opts.footerH || 0) - inset - top));
    return { side: "sheet", x: clampX(Math.min(anchor.x + 24, parent.x + parent.w - inset) - w, w), y: clampY(top, h), w: w, h: h };
}
