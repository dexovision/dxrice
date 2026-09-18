#!/usr/bin/env python3
"""Auto-places newly opened windows beside an existing one instead of
letting them spawn stacked on top of each other -- every window on this
rice is floating (hyprland.lua's "float-everything" rule), so without this,
every new app opens at Hyprland's own default floating position and
overlaps whatever's already there.

This only ever runs ONCE, at the moment a window opens -- it picks an
initial position, nothing more. It never re-positions a window after that,
so dragging one over another by hand (the normal Super+click drag this rice
already supports) always still works exactly as before; this script has no
opinion about anything past the first placement.

Algorithm, run against the new window's own REAL size (read back from
`hyprctl clients` once the window is actually mapped, never assumed or
fixed, and NEVER changed by this script -- a small dialog and a
maximized-by-default app get placed correctly relative to their own real
footprint, not some average guess, and this script only ever dispatches
move commands, never a resize):

STAGE 1 -- direct placement, move nothing else:
  1. No other floating window on this workspace yet -> leave it wherever
     Hyprland put it (nothing to avoid).
  2. Otherwise, this is an infinite canvas, not a bounded screen -- so
     candidates are generated from every existing window's edges (right/
     left/above/below, each exactly one gap-width away -- theme.json's own
     hypr_gaps_in, matching whatever gap size the user already chose for
     tiled windows) plus the plain center-of-the-current-view spot, with NO
     requirement to stay inside the visible monitor rectangle. Whichever
     valid candidate ends up closest to the middle of the current view
     wins, with a small secondary preference for a candidate that doesn't
     unnecessarily grow the existing layout's own footprint over one
     equally close to center that would -- if the winner is still outside
     the current viewport (reachable by panning, same as any other window
     on this canvas), that's fine. Fullscreen/maximized windows are always
     obstacles to avoid but are never counted as part of "the layout" for
     that secondary preference -- they're fixed furniture, not something
     new windows are being arranged near.
  3. If every one of those candidates conflicts with something (a tight
     cluster of windows), spirals outward from the view's center with no
     distance limit until it finds free space -- the canvas has no edge, so
     this always terminates.

STAGE 2 -- make room, only when it's actually worth it (see
try_make_room's docstring for the exact mechanics): also computes the best
position the new window could have if every ordinary window were free to
move out of the way (fixed obstacles still respected), relocates only the
ones actually blocking that spot (cascading if a relocation creates a new
conflict, bounded so it can't run away), and compares the TOTAL cost of
"stage 1's result, nothing else moves" against "stage 2's result, this
much existing-window movement" -- stage 2 is only used when it's a
genuine net win. There is no separate hardcoded "close enough to center"
cutoff deciding this on its own; the two plans are always actually
computed and compared.

Reads Hyprland's own event socket (.socket2.sock) directly -- the same
plain-text openwindow/activewindowv2 protocol `socat`/`hyprctl --instance`
users read by hand -- rather than polling, so this costs nothing while no
window is opening.
"""
import json
import math
import os
import socket
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dxrice_hypr_ipc import hyprctl_json, move_window_exact_async, move_window_exact_lua, batch_async
import dxrice_xdg

DEFAULT_GAP = 5


def live_gap():
    try:
        with open(os.path.join(dxrice_xdg.config_dir(), "theme.json")) as f:
            return int(json.load(f).get("hypr_gaps_in", DEFAULT_GAP))
    except Exception:
        return DEFAULT_GAP


def socket2_path():
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    sig = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
    if not runtime or not sig:
        return None
    return os.path.join(runtime, "hypr", sig, ".socket2.sock")


def get_monitor_bounds():
    try:
        monitors = hyprctl_json(["monitors"])
        if monitors:
            for m in monitors:
                if m.get("focused"):
                    return (m["x"], m["y"], m["x"] + m["width"], m["y"] + m["height"])
            m = monitors[0]
            return (m["x"], m["y"], m["x"] + m["width"], m["y"] + m["height"])
    except Exception:
        pass
    return (0, 0, 1920, 1080)


def find_window(clients, address):
    for w in clients:
        if w.get("address") == address:
            return w
    return None


def overlaps(a, b):
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    return not (ax1 <= bx0 or ax0 >= bx1 or ay1 <= by0 or ay0 >= by1)


def rect_for(x, y, w, h):
    return (x, y, x + w, y + h)


# Secondary tiebreak weight (see find_free_position's score()): distance
# to the viewport center is the primary signal, this only matters between
# candidates that are otherwise close in that primary distance -- it
# prefers whichever one doesn't unnecessarily stretch the existing
# layout's own footprint. Pixel-equivalent scale, same convention as
# dxrice_auto_arrange.py's own tiebreak weights, kept deliberately small
# relative to the primary (unweighted, coefficient 1) distance term so it
# can only ever break near-ties, never override a genuinely closer spot.
EXPANSION_WEIGHT = 0.3


def find_free_position(new_size, others, center, gap, viewport=None, layout_others=None):
    """others: [(x, y, w, h), ...] of every OTHER floating window on this
    workspace that the new window must not overlap -- both ordinary
    movable windows and fixed/fullscreen obstacles alike; ALL of them are
    a hard constraint here. This is an infinite canvas, not a bounded
    screen -- windows already routinely sit at absolute coordinates
    outside the current viewport (that's what panning the desktop actually
    is, see dxrice_infinite_desktop_core.py's pan_other_windows), so
    placement here has NO hard outer bound and no on-screen preference at
    all: `viewport` is accepted only so older callers
    (dxrice_align_windows.py, the previous SUPER+D collision-resolver,
    kept on disk as a revert point) keep working unmodified -- this
    function never reads it.

    layout_others: optional subset of `others` -- just the ordinary
    movable windows, excluding fixed/fullscreen ones -- used only for the
    "don't unnecessarily expand the existing layout" soft tiebreak (see
    score() below). Defaults to `others` itself when not given, so a
    caller that doesn't distinguish fixed obstacles (dxrice_align_windows.py)
    keeps its previous behavior. A fullscreen window is still always a
    hard obstacle via `others` either way; it's excluded here only so it
    doesn't count as part of "the layout" that a merely-nearby placement
    would be penalized for extending -- that bounding box is about the
    ordinary windows this feature actually arranges around, not a fixed
    obstacle it just has to avoid.

    Candidates are every crossing of "an X derived from some obstacle's
    left/right edge (or this window's own gap-width clearance past it)"
    with "a Y derived from some obstacle's top/bottom edge (or clearance
    past it)", plus the plain viewport-center point -- i.e. every place a
    new window could line up flush against an existing one on either axis,
    not just the four cardinal offsets immediately beside each obstacle.

    Candidates are scored by distance from the candidate's own center to
    `center` (the primary signal, no tiers of any kind: no on-screen-vs-
    off-screen preference, no axis preference -- a version of this that
    ranked on-screen candidates over off-screen ones, or vertical offsets
    over horizontal ones, was itself found to be a hardcoded directional
    bias and was removed; direction falls out purely of which spot is
    geometrically closest), plus a small secondary preference for
    candidates that don't unnecessarily grow the bounding box of the
    existing (non-fixed) layout beyond its current extent -- so among two
    candidates that are about equally close to center, the one that tucks
    in next to the existing windows wins over one that would start a
    disconnected island the same distance away.

    Returns (x, y), always -- if every generated candidate conflicts with
    something (a tight cluster of many windows), falls back to a spiral
    search centered on `center` with no distance limit, which always
    eventually finds free space since the canvas has no edge.
    """
    if layout_others is None:
        layout_others = others

    nw, nh = new_size
    cx, cy = center
    other_rects = [rect_for(ox, oy, ow, oh) for ox, oy, ow, oh in others]
    layout_rects = [rect_for(ox, oy, ow, oh) for ox, oy, ow, oh in layout_others]

    def free(x, y):
        candidate = rect_for(x, y, nw, nh)
        # Inflate the overlap check by `gap` on every side rather than just
        # testing literal overlap, so a valid candidate always ends up at
        # least one gap-width away from its neighbors, not flush against them.
        return not any(overlaps((candidate[0] - gap, candidate[1] - gap,
                                  candidate[2] + gap, candidate[3] + gap), r)
                        for r in other_rects)

    layout_bbox = None
    if layout_rects:
        layout_bbox = (min(r[0] for r in layout_rects), min(r[1] for r in layout_rects),
                        max(r[2] for r in layout_rects), max(r[3] for r in layout_rects))

    def score(x, y):
        px, py = x + nw / 2, y + nh / 2
        total = math.hypot(px - cx, py - cy)
        if layout_bbox is not None:
            bx0, by0, bx1, by1 = layout_bbox
            cand = (x, y, x + nw, y + nh)
            new_w = max(bx1, cand[2]) - min(bx0, cand[0])
            new_h = max(by1, cand[3]) - min(by0, cand[1])
            growth = (new_w - (bx1 - bx0)) + (new_h - (by1 - by0))
            total += EXPANSION_WEIGHT * growth
        return total

    xs = {cx - nw / 2}
    ys = {cy - nh / 2}
    for ox, oy, ow, oh in others:
        xs.update((ox, ox + ow + gap, ox - nw - gap))
        ys.update((oy, oy + oh + gap, oy - nh - gap))

    candidates = [(x, y) for x in xs for y in ys]
    valid = [(x, y) for x, y in candidates if free(x, y)]
    if valid:
        return min(valid, key=lambda p: score(*p))

    # Every edge-derived spot conflicts with something else -- spiral
    # outward from the viewport center until a free ring position turns up.
    # The canvas is unbounded, so this always terminates.
    step = max(nw, nh, 1) // 4 + gap
    ring = 1
    while True:
        radius = step * ring
        ring_candidates = [
            (cx - nw / 2 + radius, cy - nh / 2),
            (cx - nw / 2 - radius, cy - nh / 2),
            (cx - nw / 2, cy - nh / 2 + radius),
            (cx - nw / 2, cy - nh / 2 - radius),
            (cx - nw / 2 + radius, cy - nh / 2 + radius),
            (cx - nw / 2 - radius, cy - nh / 2 - radius),
            (cx - nw / 2 + radius, cy - nh / 2 - radius),
            (cx - nw / 2 - radius, cy - nh / 2 + radius),
        ]
        free_ring = [(x, y) for x, y in ring_candidates if free(x, y)]
        if free_ring:
            return min(free_ring, key=lambda p: score(*p))
        ring += 1
        if ring > 500:  # pathological guard, not a real-world limit
            return (cx - nw / 2, cy - nh / 2)


def find_least_disruptive_position(new_size, others, gap, current_pos, layout_others=None):
    """Relocates an EXISTING window that's blocking where the new window
    wants to go. Unlike find_free_position (which has no prior position to
    protect), here minimal movement from the window's own current spot is
    the PRIMARY signal, with the same bounding-box-growth tiebreak as a
    secondary preference -- there's no fixed target point at all, since a
    displaced window isn't trying to get anywhere in particular, only out
    of the way with the least disruption. Same candidate generation as
    find_free_position (every obstacle's edges crossed in both axes, plus
    the window's own current position as an explicit candidate), same
    guaranteed-terminating spiral fallback if every edge-derived spot
    conflicts with something.
    """
    if layout_others is None:
        layout_others = others

    nw, nh = new_size
    cx0, cy0 = current_pos
    other_rects = [rect_for(ox, oy, ow, oh) for ox, oy, ow, oh in others]
    layout_rects = [rect_for(ox, oy, ow, oh) for ox, oy, ow, oh in layout_others]

    def free(x, y):
        candidate = rect_for(x, y, nw, nh)
        return not any(overlaps((candidate[0] - gap, candidate[1] - gap,
                                  candidate[2] + gap, candidate[3] + gap), r)
                        for r in other_rects)

    layout_bbox = None
    if layout_rects:
        layout_bbox = (min(r[0] for r in layout_rects), min(r[1] for r in layout_rects),
                        max(r[2] for r in layout_rects), max(r[3] for r in layout_rects))

    def score(x, y):
        px, py = x + nw / 2, y + nh / 2
        total = math.hypot(px - cx0, py - cy0)
        if layout_bbox is not None:
            bx0, by0, bx1, by1 = layout_bbox
            cand = (x, y, x + nw, y + nh)
            new_w = max(bx1, cand[2]) - min(bx0, cand[0])
            new_h = max(by1, cand[3]) - min(by0, cand[1])
            growth = (new_w - (bx1 - bx0)) + (new_h - (by1 - by0))
            total += EXPANSION_WEIGHT * growth
        return total

    xs = {cx0 - nw / 2}
    ys = {cy0 - nh / 2}
    for ox, oy, ow, oh in others:
        xs.update((ox, ox + ow + gap, ox - nw - gap))
        ys.update((oy, oy + oh + gap, oy - nh - gap))

    candidates = [(x, y) for x in xs for y in ys]
    valid = [(x, y) for x, y in candidates if free(x, y)]
    if valid:
        return min(valid, key=lambda p: score(*p))

    step = max(nw, nh, 1) // 4 + gap
    ring = 1
    while True:
        radius = step * ring
        ring_candidates = [
            (cx0 - nw / 2 + radius, cy0 - nh / 2), (cx0 - nw / 2 - radius, cy0 - nh / 2),
            (cx0 - nw / 2, cy0 - nh / 2 + radius), (cx0 - nw / 2, cy0 - nh / 2 - radius),
            (cx0 - nw / 2 + radius, cy0 - nh / 2 + radius), (cx0 - nw / 2 - radius, cy0 - nh / 2 - radius),
            (cx0 - nw / 2 + radius, cy0 - nh / 2 - radius), (cx0 - nw / 2 - radius, cy0 - nh / 2 + radius),
        ]
        free_ring = [(x, y) for x, y in ring_candidates if free(x, y)]
        if free_ring:
            return min(free_ring, key=lambda p: score(*p))
        ring += 1
        if ring > 500:
            return (cx0 - nw / 2, cy0 - nh / 2)


# How much a pixel of TOTAL movement imposed on existing windows "costs"
# relative to a pixel of improvement in the NEW window's own distance from
# the viewport center. Stage 2 (move existing windows to make room) is
# chosen over Stage 1 (direct placement, nothing else moves) ONLY when it
# wins this comparison outright -- there is no separate hardcoded "close
# enough to center" distance that gates the decision on its own; both
# plans are always actually computed, and whichever has the lower total
# cost wins. A pixel of existing-window disruption is weighted at half a
# pixel of new-window centering benefit: existing windows are already
# wherever their owner (or a previous placement) put them, so nudging one
# costs more than the same pixel would for the brand-new window (which has
# no established position to protect) -- but not so much more that a real,
# substantial centering win gets rejected over a modest rearrangement.
# Reasoned starting value, not measured -- retune if the live result
# rearranges too eagerly or too reluctantly.
MAKE_ROOM_MOVEMENT_WEIGHT = 0.5


def _rect_center(rect):
    x0, y0, x1, y1 = rect
    return ((x0 + x1) / 2, (y0 + y1) / 2)


def try_make_room(new_size, eligible, fixed_obstacles, center, gap):
    """Stage 2. `eligible`/`fixed_obstacles`: [(x, y, w, h), ...] plus an
    "address" key on each `eligible` entry (fixed obstacles never move, so
    they don't need one).

    1. Finds the best position the new window could have if every ordinary
       window were free to move out of the way -- i.e. find_free_position
       run against ONLY the fixed obstacles. This is the true upper bound
       on how close the new window could get to the viewport center; it's
       unreachable if an ordinary window is still sitting there, which is
       exactly what the rest of this function tries to fix.
    2. Finds which ELIGIBLE windows actually overlap that reserved
       rectangle (gap-inflated) -- only these are ever touched. Everything
       else on the workspace stays exactly where it is.
    3. Relocates them one at a time, largest-area first (ties broken by
       address -- deterministic, never based on a moving computation like
       distance-to-a-centroid, so the same input always produces the same
       plan) via find_least_disruptive_position, which treats the new
       window's reserved rectangle, every fixed obstacle, and every OTHER
       eligible window's current effective position (already-relocated
       ones at their new spot, untouched ones at their original spot) as
       obstacles to avoid -- so a relocated window can never be pushed
       back into space that's already reserved or already occupied.
    4. If relocating one window creates a NEW conflict with a window not
       yet queued, that window joins the queue too (this is the only way
       "cascading" happens here, and it's bounded: the queue can never
       need more rounds than there are eligible windows, since each round
       either finishes a real conflict or discovers a new one that must
       itself eventually be finished the same way -- if that bound is
       somehow exceeded anyway, this returns None and the caller falls
       back to Stage 1 rather than trying to force a resolution).

    Returns (target_pos, {address: new_pos, ...}) -- the second dict holds
    ONLY the windows that actually needed to move, empty if the ideal spot
    was already clear. Returns None if the cascade doesn't resolve within
    that bound, or if a final overlap sanity check somehow still fails
    (defensive -- shouldn't happen given the construction above).
    """
    target_pos = find_free_position(new_size, fixed_obstacles, center, gap)
    nw, nh = new_size
    target_rect = rect_for(target_pos[0], target_pos[1], nw, nh)

    by_addr = {w["address"]: w for w in eligible}
    state = {w["address"]: rect_for(w["at"][0], w["at"][1], w["size"][0], w["size"][1])
             for w in eligible}
    original_center = {addr: _rect_center(rect) for addr, rect in state.items()}
    fixed_rects = [rect_for(*r) for r in fixed_obstacles]

    def gap_inflated(rect):
        return (rect[0] - gap, rect[1] - gap, rect[2] + gap, rect[3] + gap)

    def conflicts_with(rect, exclude=()):
        inflated = gap_inflated(rect)
        return [addr for addr, r in state.items() if addr not in exclude and overlaps(inflated, r)]

    initial_conflicts = conflicts_with(target_rect)
    if not initial_conflicts:
        return target_pos, {}

    def sort_key(addr):
        w = by_addr[addr]
        return (-(w["size"][0] * w["size"][1]), addr)

    queue = sorted(initial_conflicts, key=sort_key)
    queued_or_moved = set(queue)
    moved = {}
    max_rounds = len(eligible) + 1
    rounds = 0

    while queue:
        rounds += 1
        if rounds > max_rounds:
            return None
        addr = queue.pop(0)
        w = by_addr[addr]
        size = tuple(w["size"])
        other_rects_xyxy = [r for a, r in state.items() if a != addr] + [target_rect]
        other_xywh = [(r[0], r[1], r[2] - r[0], r[3] - r[1]) for r in other_rects_xyxy] + fixed_obstacles

        new_pos = find_least_disruptive_position(size, other_xywh, gap, original_center[addr])
        new_rect = rect_for(new_pos[0], new_pos[1], size[0], size[1])
        state[addr] = new_rect
        moved[addr] = new_pos

        for other_addr in conflicts_with(new_rect, exclude={addr}):
            if other_addr not in queued_or_moved:
                queue.append(other_addr)
                queued_or_moved.add(other_addr)

    # Final sanity check: everything the new window's reservation or an
    # ACTUALLY-MOVED window ends up next to must still respect the gap.
    # This deliberately does NOT audit pairs of two untouched, pre-existing
    # eligible windows against each other -- Stage 2 didn't create
    # whatever relationship they already had (a real desktop could have
    # two windows sitting closer together than this rice would place them
    # itself, e.g. from a manual drag), and it isn't Stage 2's job to
    # police or reject an otherwise-valid plan over something it never
    # touched and wasn't asked to fix.
    untouched = [r for addr, r in state.items() if addr not in moved]
    touched = [target_rect] + [state[addr] for addr in moved]
    all_rects = touched + untouched + fixed_rects
    for i, rect_i in enumerate(touched):
        for j, rect_j in enumerate(all_rects):
            if rect_i is rect_j:
                continue
            if overlaps(gap_inflated(rect_i), rect_j):
                return None  # defensive -- shouldn't happen given the construction above

    return target_pos, moved


_DEBUG = os.environ.get("DXRICE_DEBUG") == "1"


def place_new_window(address, workspace_id, gap):
    # The window may not be immediately queryable the instant openwindow
    # fires -- give Hyprland a couple of ticks to finish mapping it.
    clients = None
    new_win = None
    for _ in range(5):
        clients = hyprctl_json(["clients"])
        if clients:
            new_win = find_window(clients, address)
            if new_win:
                break
        time.sleep(0.03)
    if _DEBUG:
        print(f"DEBUG address={address} found={new_win is not None} floating={new_win.get('floating') if new_win else None}", file=sys.stderr, flush=True)
    if not new_win or not new_win.get("floating"):
        return

    # Hyprland's own real fullscreen state (0 = normal, 2 = fullscreen,
    # confirmed live) -- a fullscreened/maximized window has no sensible
    # "beside" position and must be left exactly where Hyprland put it.
    # Previously this was guessed from size (>=90% of monitor area), which
    # false-positived on any large-but-intentionally-sized normal window
    # and false-negatived on a fullscreen window on a small/scaled output.
    if new_win.get("fullscreen", 0) != 0:
        if _DEBUG:
            print(f"DEBUG address={address} skipped: fullscreen={new_win.get('fullscreen')}", file=sys.stderr, flush=True)
        return

    new_w, new_h = new_win["size"][0], new_win["size"][1]
    mx0, my0, mx1, my1 = get_monitor_bounds()

    same_ws = [w for w in clients
               if w.get("floating") and w.get("workspace", {}).get("id") == workspace_id
               and w.get("address") != address]
    if _DEBUG:
        print(f"DEBUG same_ws count={len(same_ws)} workspace_id={workspace_id}", file=sys.stderr, flush=True)
    if not same_ws:
        return  # first window on this workspace -- nothing to avoid

    # The middle of the current viewport in absolute canvas coordinates --
    # not a bound, just the point new placements try to land closest to.
    center = ((mx0 + mx1) / 2, (my0 + my1) / 2)
    others = [(w["at"][0], w["at"][1], w["size"][0], w["size"][1]) for w in same_ws]
    # Fullscreen/maximized windows are still hard obstacles (via `others`
    # above) but aren't part of "the layout" for the expansion tiebreak --
    # they're fixed furniture to route around, not something the new
    # window is meaningfully being arranged near.
    layout_others = [(w["at"][0], w["at"][1], w["size"][0], w["size"][1])
                      for w in same_ws if not w.get("fullscreen")]

    # Stage 1: best position without moving anything else.
    pos1 = find_free_position((new_w, new_h), others, center, gap,
                               viewport=(mx0, my0, mx1, my1), layout_others=layout_others)
    d1 = math.hypot(pos1[0] + new_w / 2 - center[0], pos1[1] + new_h / 2 - center[1])

    # Stage 2: best position if every ordinary window could move out of
    # the way, and what that would actually cost to carry out. Always
    # computed so the decision is a real comparison, never a hardcoded
    # "close enough" cutoff -- see MAKE_ROOM_MOVEMENT_WEIGHT's comment.
    eligible = [w for w in same_ws if not w.get("fullscreen")]
    fixed_only = [(w["at"][0], w["at"][1], w["size"][0], w["size"][1])
                  for w in same_ws if w.get("fullscreen")]

    use_stage2 = False
    stage2 = try_make_room((new_w, new_h), eligible, fixed_only, center, gap) if eligible else None
    if stage2 is not None:
        pos2, moved = stage2
        d2 = math.hypot(pos2[0] + new_w / 2 - center[0], pos2[1] + new_h / 2 - center[1])
        orig_at = {w["address"]: w["at"] for w in eligible}
        total_movement = sum(
            math.hypot(nx - orig_at[addr][0], ny - orig_at[addr][1])
            for addr, (nx, ny) in moved.items()
        )
        cost1, cost2_total = d1, d2 + MAKE_ROOM_MOVEMENT_WEIGHT * total_movement
        if _DEBUG:
            print(f"DEBUG stage1 d1={d1:.1f} | stage2 d2={d2:.1f} moved={len(moved)} "
                  f"total_movement={total_movement:.1f} cost1={cost1:.1f} cost2={cost2_total:.1f}",
                  file=sys.stderr, flush=True)
        if cost2_total < cost1:
            use_stage2 = True

    if use_stage2:
        exprs = [move_window_exact_lua(int(pos2[0]), int(pos2[1]), address)]
        for addr, (mx, my) in moved.items():
            exprs.append(move_window_exact_lua(int(mx), int(my), addr))
        if _DEBUG:
            print(f"DEBUG using STAGE 2: pos={pos2} + {len(moved)} window(s) relocated", file=sys.stderr, flush=True)
        batch_async(exprs)
    else:
        if _DEBUG:
            print(f"DEBUG using STAGE 1: pos={pos1} new_size=({new_w},{new_h}) center={center}", file=sys.stderr, flush=True)
        move_window_exact_async(int(pos1[0]), int(pos1[1]), address)


def main():
    path = socket2_path()
    if not path:
        print("HYPRLAND_INSTANCE_SIGNATURE/XDG_RUNTIME_DIR not set -- not running under Hyprland?", file=sys.stderr)
        sys.exit(1)

    buf = ""
    while True:
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                s.connect(path)
                gap = live_gap()
                last_gap_check = time.time()
                while True:
                    chunk = s.recv(4096)
                    if not chunk:
                        break
                    buf += chunk.decode(errors="replace")
                    while "\n" in buf:
                        line, buf = buf.split("\n", 1)
                        if _DEBUG and line:
                            print(f"DEBUG line={line!r}", file=sys.stderr, flush=True)
                        if line.startswith("openwindow>>"):
                            parts = line[len("openwindow>>"):].split(",", 3)
                            if len(parts) >= 2:
                                addr = "0x" + parts[0]
                                try:
                                    ws_id = int(parts[1])
                                except ValueError:
                                    continue
                                if time.time() - last_gap_check > 5:
                                    gap = live_gap()
                                    last_gap_check = time.time()
                                try:
                                    place_new_window(addr, ws_id, gap)
                                except Exception:
                                    pass
        except (ConnectionRefusedError, FileNotFoundError, OSError):
            time.sleep(1)


if __name__ == "__main__":
    main()
