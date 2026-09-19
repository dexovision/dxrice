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
footprint, not some average guess). Stages 1 and 2 only ever dispatch move
commands; Stage 3 (see below) is the one exception -- and even there, only
an EXISTING window is ever resized, never the new one:

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

STAGE 3 -- resize, only as an actual last resort: evaluated only after
Stage 1 and Stage 2 have both already been scored and the better of the
two is still bad relative to the new window's own size (see
try_resize_room's RESIZE_TRIGGER_MULTIPLE) -- i.e. rearranging alone
couldn't produce a usable result. Shrinks exactly ONE existing window
(never the new one), along just the axis actually blocking the new
window, bounded by both a fraction of that window's own current size and
an absolute usable-size floor (MIN_USABLE_WIDTH/HEIGHT) that no resize
here may ever cross. Only applied when the resulting plan's total cost
(placement distance + a real cost per pixel removed) beats the best
rearrangement-only plan -- a resize that doesn't clearly help is never
used.

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
from dxrice_hypr_ipc import (hyprctl_json, move_window_exact_async, move_window_exact_lua,
                             batch_async, resize_window_exact_lua)
import dxrice_singleton
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

# Composition-quality terms, shared by Stage 1, Stage 2, and (via import)
# Algorithm B -- these exist because distance-to-target and bbox growth
# alone still pick "the nearest technically free rectangle," which is what
# produced the reported complaint: a new window wedging into a sliver of
# space above/below an existing one merely because that spot was a few
# pixels closer to center than a spot that would actually read as a clean
# addition to the layout. Every edge-derived candidate (see the xs/ys
# construction below) is already EITHER flush against some neighbor's edge
# (touching it, gap-width away) OR aligned with one (sharing an x or y
# coordinate without necessarily touching) OR neither -- these two terms
# score which of those three cases a candidate falls into:
#
#  - SLIVER_PENALTY_MAX: a candidate that's flush against a neighbor but
#    only barely overlaps that neighbor's edge reads as an awkward,
#    barely-touching wedge -- a clean composition either lines up with a
#    neighbor's full edge or doesn't try to touch it at all. Scored only
#    against the SINGLE best (highest-coverage) flush neighbor found, not
#    summed across every neighbor the candidate happens to be near, so a
#    candidate that's cleanly flush against one window and merely nearby
#    (not touching) another isn't double-penalized for the second one.
#  - ALIGN_BONUS: a candidate whose left/right/top/bottom edge lines up
#    with an existing window's corresponding edge reads as a deliberate
#    grid even when the two windows aren't directly touching -- rewarded
#    per axis it aligns on (capped at 2: one per axis), so it can only ever
#    tip a near-tie, never dominate a real distance difference.
#
# Both are pure functions of final geometry, evaluated the same way no
# matter what order candidates are considered in -- scoring stays
# deterministic and idempotent, same as every other term here.
SLIVER_PENALTY_MAX = 140.0
ALIGN_BONUS = 22.0
ALIGN_EPS = 1.5

# Cost per pixel of dead (unusable) space left between a candidate and a
# neighbour it lands near but not flush against -- see _dead_gap_penalty.
# Deliberately just above 1.0: at exactly 1.0 a candidate would be
# indifferent between closing a dead strip and moving the same number of
# pixels further from the viewport centre, and the whole point is that
# closing it should win that trade narrowly. Capped so this can only ever
# decide a near-tie between neighbouring candidates, never drag a window
# a long way across the canvas just to sit flush against something.
DEAD_GAP_WEIGHT = 1.2
DEAD_GAP_CAP = 120.0


def _axis_gap(a0, a1, b0, b1):
    """Positive = the real gap between two disjoint 1D intervals; 0 if they
    overlap (including just touching)."""
    if a1 <= b0:
        return b0 - a1
    if b1 <= a0:
        return a0 - b1
    return 0.0


def _flush_coverage(cand, r, gap, tol=1.5):
    """None if `cand` and `r` aren't flush neighbors (separated by ~gap on
    exactly one axis while overlapping on the other) -- otherwise the
    fraction (0..1) of the shorter edge's length that's actually shared,
    i.e. how much of a "clean full-edge join" this adjacency is versus a
    thin corner-only sliver."""
    cx0, cy0, cx1, cy1 = cand
    rx0, ry0, rx1, ry1 = r
    xgap = _axis_gap(cx0, cx1, rx0, rx1)
    ygap = _axis_gap(cy0, cy1, ry0, ry1)
    if abs(xgap - gap) < tol and ygap == 0.0:
        overlap = min(cy1, ry1) - max(cy0, ry0)
        span = min(cy1 - cy0, ry1 - ry0)
        return overlap / span if span > 0 else 0.0
    if abs(ygap - gap) < tol and xgap == 0.0:
        overlap = min(cx1, rx1) - max(cx0, rx0)
        span = min(cx1 - cx0, rx1 - rx0)
        return overlap / span if span > 0 else 0.0
    return None


def _edge_alignment_count(cand, rects):
    cx0, cy0, cx1, cy1 = cand
    aligned_x = aligned_y = False
    for rx0, ry0, rx1, ry1 in rects:
        if not aligned_x and (abs(cx0 - rx0) < ALIGN_EPS or abs(cx1 - rx1) < ALIGN_EPS):
            aligned_x = True
        if not aligned_y and (abs(cy0 - ry0) < ALIGN_EPS or abs(cy1 - ry1) < ALIGN_EPS):
            aligned_y = True
        if aligned_x and aligned_y:
            break
    return int(aligned_x) + int(aligned_y)


def _dead_gap_penalty(cand, layout_rects, gap):
    """Penalises the strip of space left between `cand` and a neighbour it
    lands NEAR but not flush against.

    This closes a real hole the first two terms leave open: a candidate is
    rewarded for joining a neighbour cleanly (via coverage) and is neutral
    when it floats free in open space, but "sitting 50px off a neighbour's
    edge when the configured gap is 5" is neither -- and used to score as
    a completely free 0.0. Live QA caught exactly that: a new window landed
    5px from the window on one side and 55px from the one on the other,
    because scoring exact viewport-centering paid more than closing up a
    strip of space nothing can ever use. That leftover strip is precisely
    the "tiny awkward sliver of unusable space" that makes an arrangement
    read as accidental instead of composed.

    "Unusable" is measured, not guessed: a strip narrower than
    MIN_USABLE_WIDTH/HEIGHT could never hold another window, so it is dead
    by definition. Wider strips are left alone -- at that point the space
    reads as deliberate separation between two groups, not a misalignment.
    The penalty is capped so a candidate is never dragged across a large
    distance purely to close a gap."""
    worst = 0.0
    for r in layout_rects:
        xg = _axis_gap(cand[0], cand[2], r[0], r[2])
        yg = _axis_gap(cand[1], cand[3], r[1], r[3])
        # Only count neighbours actually FACING the candidate on one axis
        # (overlapping on the other) -- a diagonal neighbour isn't leaving
        # a dead strip between them, it's just elsewhere.
        if yg == 0.0 and gap < xg < MIN_USABLE_WIDTH:
            worst = max(worst, xg - gap)
        if xg == 0.0 and gap < yg < MIN_USABLE_HEIGHT:
            worst = max(worst, yg - gap)
    return min(worst, DEAD_GAP_CAP) * DEAD_GAP_WEIGHT


def composition_penalty(cand, layout_rects, gap):
    """Pixel-equivalent score contribution (added directly to a distance-
    based score, so 0 is neutral, positive is worse) capturing whether
    `cand` reads as a clean, intentional addition to `layout_rects` rather
    than merely a non-overlapping rectangle. See the weight comments above
    for what each term means; all are no-ops when there's no existing
    layout to compose with yet (an empty/absent `layout_rects`)."""
    if not layout_rects:
        return 0.0
    best_coverage = None
    for r in layout_rects:
        frac = _flush_coverage(cand, r, gap)
        if frac is not None:
            best_coverage = frac if best_coverage is None else max(best_coverage, frac)
    sliver = SLIVER_PENALTY_MAX * (1.0 - best_coverage) if best_coverage is not None else 0.0
    align = ALIGN_BONUS * _edge_alignment_count(cand, layout_rects)
    dead = _dead_gap_penalty(cand, layout_rects, gap)
    return sliver + dead - align


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
        cand = (x, y, x + nw, y + nh)
        if layout_bbox is not None:
            bx0, by0, bx1, by1 = layout_bbox
            new_w = max(bx1, cand[2]) - min(bx0, cand[0])
            new_h = max(by1, cand[3]) - min(by0, cand[1])
            growth = (new_w - (bx1 - bx0)) + (new_h - (by1 - by0))
            total += EXPANSION_WEIGHT * growth
        total += composition_penalty(cand, layout_rects, gap)
        return total

    # Candidates are derived from BOTH the hard obstacles and the
    # composition reference. Including layout_others here matters for
    # Stage 2 specifically: there, `others` is only the fixed/fullscreen
    # windows (often none at all), because every ordinary window is free to
    # move out of the way -- so without this the only candidate that ever
    # existed was the bare viewport-centre point, and Stage 2's target was
    # decided by nothing but "dead centre," ignoring the layout entirely.
    # These edges aren't constraints (free() below still only tests
    # `others`), they're the positions worth CONSIDERING -- lining up with
    # a window that happens to stay put is exactly what makes the result
    # read as composed rather than dropped in the middle.
    xs = {cx - nw / 2}
    ys = {cy - nh / 2}
    for ox, oy, ow, oh in list(others) + list(layout_others):
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
        cand = (x, y, x + nw, y + nh)
        if layout_bbox is not None:
            bx0, by0, bx1, by1 = layout_bbox
            new_w = max(bx1, cand[2]) - min(bx0, cand[0])
            new_h = max(by1, cand[3]) - min(by0, cand[1])
            growth = (new_w - (bx1 - bx0)) + (new_h - (by1 - by0))
            total += EXPANSION_WEIGHT * growth
        total += composition_penalty(cand, layout_rects, gap)
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

# A flat per-pixel movement cost treats shoving a 1200x800 application
# aside exactly like nudging a 250x150 dialog the same distance -- live
# testing surfaced exactly this: a tiny dialog opening beside a large,
# already-centered window relocated that large window 480px just to land
# the dialog dead-center, because 480px of "movement" was cheap in raw
# pixels regardless of whose 480px it was. A human doesn't experience
# those as equally disruptive -- displacing the big, prominent thing
# reads as the layout being torn up; nudging the small one reads as
# tidying. This scales the per-pixel cost of moving a given window by
# how much LARGER its own area is than the new window's -- a window at or
# below the new window's own size still costs the base rate (moving
# something small or similarly-sized to make room stays cheap, e.g. a
# tiny window sliding aside for a large new application), while a window
# substantially bigger than the new one costs progressively more per
# pixel, so Stage 2 only relocates something significantly more prominent
# than the new window when the centering win is real, not just numerically
# ahead. Square-rooted rather than linear in the area ratio so a modestly
# bigger window isn't punished as harshly as a dramatically bigger one.
def prominence_weight(addr, eligible_by_addr, new_area):
    aw, ah = eligible_by_addr[addr]["size"]
    area = aw * ah
    if new_area <= 0 or area <= new_area:
        return 1.0
    return math.sqrt(area / new_area)


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
    # `fixed_obstacles` are the only HARD constraints here -- every ordinary
    # window is free to move, which is the whole point of this stage. But
    # the ordinary windows are still passed as the COMPOSITION reference
    # (layout_others), because "which of the equally-central spots actually
    # lines up with the furniture that's already there" is a real question
    # even when that furniture could move. Without this, Stage 2 scored
    # nothing but raw distance to centre and reliably produced arbitrary,
    # non-gap-width offsets (live QA: 5px from the window on one side, 55px
    # from the one on the other) -- technically central, visibly unplanned.
    eligible_rects = [(w["at"][0], w["at"][1], w["size"][0], w["size"][1]) for w in eligible]
    target_pos = find_free_position(new_size, fixed_obstacles, center, gap,
                                     layout_others=eligible_rects)
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


# ---- Stage 3: resize an existing window, only when rearrangement alone
# still produces a genuinely bad result ----
#
# Priority order, per the actual product requirement: always preserve the
# new window's own mapped size; prefer moving existing windows (Stage 2)
# over resizing anything; only resize when doing so produces a materially
# better composition than the best rearrangement-only plan, never merely
# "shrink things until they fit." This stage is deliberately the last
# resort -- it's only even evaluated when Stage 1 and Stage 2 have both
# already been scored and the better of the two is still bad.
#
# MIN_USABLE_WIDTH/HEIGHT is an absolute floor that no resize -- here or
# anywhere else that ever touches an existing window's size -- may cross.
# Chosen as "still comfortably usable," not "the smallest a toolkit
# happens to allow": a terminal or dialog shrunk to exactly this size still
# has a readable title bar and enough body to be worth keeping open.
MIN_USABLE_WIDTH = 240
MIN_USABLE_HEIGHT = 160

# How much of an existing window's OWN dimension Stage 3 may remove in a
# single placement, as a fraction of what it currently has -- capped well
# short of "shrink it into uselessness" even before MIN_USABLE_* applies,
# so a window already close to the floor doesn't lose most of what's left.
MAX_SHRINK_FRACTION = 0.25

# Pixel-equivalent cost of permanently shrinking an existing window by one
# pixel of either dimension -- higher than MAKE_ROOM_MOVEMENT_WEIGHT's
# per-pixel move cost, since changing a window's size is a more lasting
# change to something the user (or the app itself) already sized
# deliberately than a reversible reposition is. Reasoned starting value,
# not measured, same convention as this file's other weights.
RESIZE_COST_PER_PIXEL = 1.2

# Stage 3 is only even considered when the better of Stage 1's and Stage
# 2's cost is still this many times the new window's own diagonal -- i.e.
# only for outcomes that are genuinely bad, never as a routine alternative
# to rearranging. A normal placement or ordinary make-room never approaches
# this multiple in practice.
RESIZE_TRIGGER_MULTIPLE = 1.5


def clamp_to_usable_size(w, h):
    """Raises (w, h) up to MIN_USABLE_WIDTH/HEIGHT if either falls below
    it, scaling the OTHER dimension up by the same factor so a size that
    genuinely needs the floor applied doesn't come out distorted. A no-op
    for anything already at or above both minimums -- this is a last-line
    safety clamp, not a placement decision; nothing in Stage 1/2/3 needs to
    call it under normal operation since Stage 3 already respects these
    same floors directly, but any future caller that hands this module a
    literal size to work with can run it through here first for free."""
    if w >= MIN_USABLE_WIDTH and h >= MIN_USABLE_HEIGHT:
        return (w, h)
    scale = max(MIN_USABLE_WIDTH / w if w > 0 else 1.0,
                MIN_USABLE_HEIGHT / h if h > 0 else 1.0)
    return (max(MIN_USABLE_WIDTH, round(w * scale)), max(MIN_USABLE_HEIGHT, round(h * scale)))


def try_resize_room(new_size, eligible, fixed_obstacles, center, gap, best_cost):
    """DECISION (investigated, not assumed): this stage is a deliberate,
    intentionally-rare safety fallback -- kept, not redesigned or removed.
    Across every synthetic test in dxrice_test_placement.py plus 10
    deliberately adversarial real-layout scenarios on a live compositor
    (a large centered window + a tiny dialog, a tiny centered window + a
    large application, a narrow gap between two windows, an L of windows,
    windows surrounding the viewport center, a dense 6-window cluster,
    scattered far-apart windows, a huge window overlapping the viewport,
    a fullscreen obstacle, and windows with extreme/mismatched aspect
    ratios), Stage 1 and Stage 2 resolved every single one on their own --
    this function never fired naturally once. That's evidence the infinite
    canvas rarely if ever runs out of room to rearrange into, not that this
    code is dead: an infinite canvas means Stage 2's spiral fallback always
    eventually finds free space, so RESIZE_TRIGGER_MULTIPLE's bar (rearrange
    alone still bad) is genuinely hard to clear outside a pathological,
    extremely dense/gridlocked cluster. Kept specifically for that case
    rather than removed, since it costs nothing when it doesn't fire (only
    evaluated once Stage 1/2 are both already scored as bad) and is fully
    bounded/tested when it does. Verified separately, by forcing the trigger
    threshold directly, that the mechanism itself (variant selection, the
    MIN_USABLE/MAX_SHRINK bounds, the explicit anchor correction below) is
    correct -- see dxrice_test_placement.py's TestResizeMinimums.

    Only called once Stage 1 and Stage 2 have already both been scored
    and the better of the two (`best_cost`) is still bad relative to the
    new window's own size -- see RESIZE_TRIGGER_MULTIPLE. Tries shrinking
    exactly ONE existing eligible window (never the new one, never more
    than one per placement) just enough that the new window can land at a
    clean, Stage-1-quality spot -- and only returns a plan when doing so
    beats `best_cost` even after adding the resize's own cost, so a resize
    that doesn't clearly help is never applied. Every candidate size is
    bounded by both MAX_SHRINK_FRACTION of that window's own current size
    and the absolute MIN_USABLE_* floor, whichever is stricter.

    Tries FOUR shrink variants per window -- width from the right, width
    from the left, height from the bottom, height from the top -- rather
    than assuming which edge should recede: Hyprland's own window.resize
    dispatch resizes a floating window around its CENTER (confirmed live:
    resizing in place moves the top-left too), so this function always
    computes its own explicit target top-left for whichever edge it
    intends to keep fixed, and the caller dispatches an explicit move
    alongside the resize to land exactly there -- it never relies on
    Hyprland's own resize anchor to happen to match what was scored here.

    Returns (target_pos, address_to_resize, (new_x, new_y), (new_w, new_h))
    or None. new_x/new_y is the resized window's own corrected top-left,
    which the caller must move it to (not just resize it) for the geometry
    that was actually scored to be what actually happens.
    """
    nw, nh = new_size
    new_diag = math.hypot(nw, nh)
    if best_cost < RESIZE_TRIGGER_MULTIPLE * new_diag:
        return None  # rearrangement alone is already good enough -- don't touch sizes

    fixed_rects = [rect_for(*r) for r in fixed_obstacles]
    best_plan = None

    for w in eligible:
        ow, oh = w["size"]
        ox, oy = w["at"]
        other_eligible_rects = [rect_for(o["at"][0], o["at"][1], o["size"][0], o["size"][1])
                                 for o in eligible if o["address"] != w["address"]]
        fixed_and_others = other_eligible_rects + fixed_rects

        variants = []  # (shrunk_x, shrunk_y, shrunk_w, shrunk_h, shrink_amount)
        w_floor = max(MIN_USABLE_WIDTH, ow * (1 - MAX_SHRINK_FRACTION))
        if w_floor < ow - 1:
            amount = ow - w_floor
            variants.append((ox, oy, w_floor, oh, amount))                 # keep left edge fixed, shrink from the right
            variants.append((ox + amount, oy, w_floor, oh, amount))        # keep right edge fixed, shrink from the left
        h_floor = max(MIN_USABLE_HEIGHT, oh * (1 - MAX_SHRINK_FRACTION))
        if h_floor < oh - 1:
            amount = oh - h_floor
            variants.append((ox, oy, ow, h_floor, amount))                 # keep top edge fixed, shrink from the bottom
            variants.append((ox, oy + amount, ow, h_floor, amount))        # keep bottom edge fixed, shrink from the top

        for sx, sy, sw, sh, shrink_amount in variants:
            obstacles_xywh = [(r[0], r[1], r[2] - r[0], r[3] - r[1]) for r in fixed_and_others]
            obstacles_xywh.append((sx, sy, sw, sh))
            pos = find_free_position(new_size, obstacles_xywh, center, gap, layout_others=obstacles_xywh)

            d = math.hypot(pos[0] + nw / 2 - center[0], pos[1] + nh / 2 - center[1])
            cost = d + RESIZE_COST_PER_PIXEL * shrink_amount
            if cost < best_cost and (best_plan is None or cost < best_plan[0]):
                best_plan = (cost, pos, w["address"], (int(sx), int(sy)), (int(sw), int(sh)))

    if best_plan is None:
        return None
    _, pos, addr, new_xy, size = best_plan
    return pos, addr, new_xy, size


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
        eligible_by_addr = {w["address"]: w for w in eligible}
        new_area = new_w * new_h
        total_movement = sum(
            math.hypot(nx - orig_at[addr][0], ny - orig_at[addr][1])
            * prominence_weight(addr, eligible_by_addr, new_area)
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
        best_cost = cost2_total
    else:
        best_cost = d1

    # Stage 3: only reached when neither rearranging nor a direct spot got
    # close to the viewport center -- see RESIZE_TRIGGER_MULTIPLE. Never
    # touches the new window's own size, never touches more than one
    # existing window, and never crosses MIN_USABLE_WIDTH/HEIGHT.
    stage3 = try_resize_room((new_w, new_h), eligible, fixed_only, center, gap, best_cost) if eligible else None

    if stage3 is not None:
        pos3, resize_addr, resize_xy, resize_size = stage3
        if _DEBUG:
            print(f"DEBUG using STAGE 3: pos={pos3} resizing {resize_addr} to {resize_size} "
                  f"@ {resize_xy}", file=sys.stderr, flush=True)
        # Order matters: resize first (Hyprland's own floating-window resize
        # is center-anchored, confirmed live), THEN move it to the exact
        # top-left this was actually scored against -- never rely on
        # Hyprland's own anchor to land where try_resize_room computed.
        batch_async([
            resize_window_exact_lua(resize_size[0], resize_size[1], resize_addr),
            move_window_exact_lua(int(resize_xy[0]), int(resize_xy[1]), resize_addr),
            move_window_exact_lua(int(pos3[0]), int(pos3[1]), address),
        ])
    elif use_stage2:
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

    # Found live, via a 40-cycle soak test that opened/closed windows in
    # rapid bursts: every dispatch above is fire-and-forget (want_reply=
    # False) so this function returns the instant the move/resize command
    # is SENT, not once Hyprland has actually applied it. If a second
    # openwindow event arrives and this function runs again before that
    # happens, its `hyprctl clients` read of "where everything else
    # currently is" can catch the first window still at its PRE-move
    # position -- both placements get computed against a real position
    # that's about to change out from under them, and the actual result on
    # screen can overlap even though each individual decision was correct
    # against the (stale) state it saw. Reproduced exactly once in the
    # burst-spawn soak scenario, never in normal one-app-at-a-time use.
    # A brief settle delay here, before this function returns and the
    # listener reads its next buffered event, gives Hyprland's own IPC time
    # to actually finish applying what was just dispatched -- imperceptible
    # for a human opening one window at a time, and closes the race for
    # everything short of multiple windows mapping within single-digit
    # milliseconds of each other. Not a formal guarantee (that would need
    # waiting for confirmation the move actually landed, adding real
    # latency to the common case for a rare edge case) -- a bounded,
    # proportionate mitigation for a bounded, rare race.
    time.sleep(0.03)


def main():
    path = socket2_path()
    if not path:
        print("HYPRLAND_INSTANCE_SIGNATURE/XDG_RUNTIME_DIR not set -- not running under Hyprland?", file=sys.stderr)
        sys.exit(1)

    _lock = dxrice_singleton.claim_single_instance("auto-place-window")
    if _lock is None:
        print("another dxrice_auto_place_window.py already holds the listener lock -- exiting.",
              file=sys.stderr, flush=True)
        sys.exit(0)
    print(f"dxrice_auto_place_window: listening on {path} (pid {os.getpid()})",
          file=sys.stderr, flush=True)

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
                                except Exception as e:
                                    # One window failing to place must never take
                                    # the listener down, but silently swallowing it
                                    # is how this went unnoticed before -- say so.
                                    print(f"placement failed for {addr} on ws {ws_id}: "
                                          f"{type(e).__name__}: {e}", file=sys.stderr, flush=True)
        except (ConnectionRefusedError, FileNotFoundError, OSError) as e:
            print(f"socket2 unavailable ({type(e).__name__}: {e}) -- retrying in 1s",
                  file=sys.stderr, flush=True)
            time.sleep(1)


if __name__ == "__main__":
    main()
