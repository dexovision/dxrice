#!/usr/bin/env python3
"""Automatic window placement: a newly opened window joins the cloud.

Every window on this rice floats (hyprland.lua's "float-everything" rule),
so without this every new app opens at Hyprland's default floating spot,
on top of whatever is already there.

WHAT TRIGGERS IT -- exactly one thing: Hyprland's `openwindow>>` event, a
window being mapped (see PlacementListener). Not focus changes (with
follow_mouse that is every time the pointer crosses a window), not title
changes (a browser retitling itself as links are hovered), not moves --
including this listener's own -- and not anything the pointer does. Each
window is handled once per mapping; repeated events for it are ignored.

WHAT IT PLACES -- application windows only. A tooltip, context menu or
link/tab hover card from an XWayland app arrives as an ordinary
`openwindow>>` too; dxrice_window_class.py asks the X server and filters
those out, along with splash screens, the shell's own dialogs and tiny
helper surfaces (measured before this: 300 of 300 simulated popups were
moved away from what they pointed at, and in 50 of them the windows around
the popup were moved or resized to make room for it). Fullscreen and tiled
windows are left alone until they become ordinary floating windows; pinned
windows are never moved.

WHERE IT GOES -- the same place SUPER+G would put it. A dialog of an app
that's already open (WM_TRANSIENT_FOR from the X server, or the PID/class
family signal -- see _find_family_anchor) goes beside the window it belongs
to. Anything else joins the existing composition through
dxrice_auto_arrange.join_composition: SUPER+G's own per-window step --
same edge-derived and organically staggered candidates, same composition
cost with the screen-shaped target, same compactness, detachment and
dead-gap terms -- with every existing window held exactly where it is. The
new window keeps its size (one exception: startup sizing, below), lands
exactly one gap from what it sits beside, overlaps nothing, and nothing
else moves or resizes. Re-balancing the whole desktop stays SUPER+G's job.

The previous placer here (now unused: find_free_position's Stage 1 and the
Stage 2 "make room" / Stage 3 "trim a neighbour" search below) aimed at a
round target and moved existing windows to make room on 594 of 969
simulated opens; on the same 200 opening sequences the cloud step moves
none, comes out screen-shaped (median 1.32:1 against 1.07:1) and is what
SUPER+G itself already counts as a good arrangement in 199 of 200 (185
before). See scripts/dxrice_autoplace_report.py.

It never re-positions a window after that first placement -- dragging one
anywhere by hand works exactly as before -- and if the window was moved by
someone else between being read and being placed (the user grabbed it, the
app positioned itself), it is left where it is.

STARTUP SIZING (comfortable_startup_size): a main window that maps in the
"too big for a dialog, too small to be deliberate" band is enlarged along
its own aspect ratio before it is placed. Never a dialog, never a window of
an app that's already open.

SWITCH: Settings > Experience > "Automatic window placement" (theme.json
"auto_place_windows", missing = on). Read on every window open, so it
applies to the next window without restarting anything; off means nothing
at all happens on open -- SUPER+G is separate and unaffected.

Reads Hyprland's own event socket (.socket2.sock) directly -- the same
plain-text protocol `socat` users read by hand -- rather than polling, so
this costs nothing while no window is opening.
"""
import json
import math
import os
import socket
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# batch_async and move_window_exact_async are module attributes the tests
# replace to record dispatches.
from dxrice_hypr_ipc import (hyprctl_json, move_window_exact_async, move_window_exact_lua,  # noqa: F401
                             batch_async, resize_window_exact_lua, dispatch_async)
import dxrice_singleton
import dxrice_xdg
import dxrice_window_class

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


def usable_bounds(m):
    """The part of one monitor (a `hyprctl monitors -j` entry) windows are
    meant to use, in layout coordinates: its logical size (scale and a
    90/270-degree transform applied) minus the space reserved by bars and
    docks (`reserved`: left, top, right, bottom). Placement and SUPER+G aim
    at this area's centre -- the raw monitor put "centre" under the bar's
    share of the screen and let windows sit beneath it."""
    w, h = m["width"], m["height"]
    if m.get("transform", 0) in (1, 3, 5, 7):
        w, h = h, w
    try:
        scale = float(m.get("scale") or 1.0)
    except (TypeError, ValueError):
        scale = 1.0
    if scale > 0:
        w, h = round(w / scale), round(h / scale)
    x0, y0 = m["x"], m["y"]
    res = m.get("reserved") or [0, 0, 0, 0]
    try:
        left, top, right, bottom = (int(v) for v in res)
    except (TypeError, ValueError):
        left = top = right = bottom = 0
    if left + right < w and top + bottom < h:
        return (x0 + left, y0 + top, x0 + w - right, y0 + h - bottom)
    return (x0, y0, x0 + w, y0 + h)


def get_monitor_bounds():
    """The focused monitor's usable area (usable_bounds)."""
    try:
        monitors = hyprctl_json(["monitors"])
        if monitors:
            for m in monitors:
                if m.get("focused"):
                    return usable_bounds(m)
            return usable_bounds(monitors[0])
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


def _px(v):
    """A computed position as the whole pixel Hyprland gets. FLOOR, not
    int(): int() truncates toward zero, which is not translation-invariant
    across 0 -- -393.5 goes UP to -393 while 0.5 goes DOWN to 0. Positions
    here are routinely fractional (centre-based and stepped candidates,
    Stage 2's relocations) and, on an infinite desktop, routinely negative,
    so two windows placed exactly `gap` apart but on opposite sides of the
    0 line came out 1px short. Measured: every gap violation across 3,816
    simulated placements (4 viewports, 6 scenario families) was exactly 4px
    where 5 was configured. floor(a + k) == floor(a) + k for any integer k,
    so coordinates that differ by a whole width-plus-gap keep exactly that
    difference. Identical to int() for every non-negative position."""
    return math.floor(v)


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

# How close to exactly `gap` two facing edges must sit to count as "flush
# neighbours" (see _flush_coverage). Numerically equal to ALIGN_EPS today,
# but a DIFFERENT question -- one is "are these two edges on the same
# line", the other is "is this pair separated by the configured gap" --
# so it gets its own name rather than sharing that constant by accident.
FLUSH_TOL = 1.5

# Cost per pixel of dead (unusable) space left between a candidate and a
# neighbour it lands near but not flush against -- see _dead_gap_penalty.
# Raised from an original 1.2 once ANGULAR_PENALTY_SCALE (2000) existed: a
# leftover dead-gap strip is an objective, unambiguous local flaw --
# "shared edges stay at the configured gap" is a hard-feeling requirement,
# not a soft aesthetic one to be traded against a more abstract radial
# preference. At the original weight a modest violation (a 50px strip
# where 5px was configured) cost only ~60 points -- nowhere near enough to
# outweigh a genuine, if modest, angular improvement, and raising DEAD_GAP_
# CAP alone did nothing because the cap was never what was binding; the
# per-pixel rate itself was just too cheap. Reproduced live: two windows
# with a new one between them landed 5px from one, 55px from the other,
# identically before and after a 120->900 cap change, because a 50px
# violation was only ever going to cost 50 * old_weight regardless of the
# cap. This weight is deliberately steep so even a modest violation costs
# more than a large angular improvement is realistically worth.
DEAD_GAP_WEIGHT = 8.0

# How much of the shorter perpendicular span two rectangles must actually
# share before they count as "facing" for dead-gap purposes at all -- see
# _dead_gap_penalty's own docstring for the live-traced root cause this
# closes. Before this existed, "facing" meant nothing more than `xgap==0.0`
# / `ygap==0.0` -- i.e. ANY positive perpendicular overlap, however
# trivial. A 338x194 window whose x-range merely overlapped a neighbour's
# by 39 of 447px (8.7%) was judged "facing" it, and the huge facing
# distance between two windows that happen to barely clip each other's
# projection scored a near-maximum phantom dead-gap penalty (near
# DEAD_GAP_CAP) -- enough to make a genuinely clean, flush candidate score
# roughly 10x WORSE than one that left a real, unblocked 44px gap
# elsewhere, because the "facing" test itself had no materiality
# threshold. Same convention as ADJACENCY_COVERAGE_THRESHOLD (0.3) in
# dxrice_auto_arrange.py -- "do these two rectangles genuinely face each
# other" is the same kind of question there (is this a real adjacency)
# and here (is this a real facing-gap), so it gets the same bar.
DEAD_GAP_FACING_COVERAGE_THRESHOLD = 0.3

# Still capped so a genuinely wide gap (already past MIN_USABLE_WIDTH/
# HEIGHT and therefore not "dead" at all -- see _dead_gap_penalty) can
# never be approached, and so this can only ever decide among candidates
# that are otherwise close, never drag a window a long way across the
# canvas just to sit flush against something.
DEAD_GAP_CAP = 900.0


def _axis_gap(a0, a1, b0, b1):
    """Positive = the real gap between two disjoint 1D intervals; 0 if they
    overlap (including just touching)."""
    if a1 <= b0:
        return b0 - a1
    if b1 <= a0:
        return a0 - b1
    return 0.0


def _flush_coverage(cand, r, gap, tol=FLUSH_TOL):
    """None if `cand` and `r` aren't flush neighbors (separated by ~gap on
    exactly one axis while overlapping on the other) -- otherwise the
    fraction (0..1) of the shorter edge's length that's actually shared,
    i.e. how much of a "clean full-edge join" this adjacency is versus a
    thin corner-only sliver."""
    cx0, cy0, cx1, cy1 = cand
    rx0, ry0, rx1, ry1 = r
    # _axis_gap inlined on both axes: this is the single hottest function
    # in the arrange pass (~150k calls at n=30, each paying two more
    # Python call frames). Identical logic, see _axis_gap's own docstring.
    if cx1 <= rx0:
        xgap = rx0 - cx1
    elif rx1 <= cx0:
        xgap = cx0 - rx1
    else:
        xgap = 0.0
    if cy1 <= ry0:
        ygap = ry0 - cy1
    elif ry1 <= cy0:
        ygap = cy0 - ry1
    else:
        ygap = 0.0
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
    # `-EPS < d < EPS` rather than `abs(d) < EPS`: identical test, but it
    # drops ~800k builtin calls per arrange pass at n=30. Same early break.
    neg_eps = -ALIGN_EPS
    for rx0, ry0, rx1, ry1 in rects:
        if not aligned_x:
            d0 = cx0 - rx0
            d1 = cx1 - rx1
            if (neg_eps < d0 < ALIGN_EPS) or (neg_eps < d1 < ALIGN_EPS):
                aligned_x = True
        if not aligned_y:
            d0 = cy0 - ry0
            d1 = cy1 - ry1
            if (neg_eps < d0 < ALIGN_EPS) or (neg_eps < d1 < ALIGN_EPS):
                aligned_y = True
        if aligned_x and aligned_y:
            break
    return int(aligned_x) + int(aligned_y)


def _gap_is_blocked(cand, r, all_rects, axis):
    """Is there a THIRD rectangle genuinely occupying the facing strip
    between `cand` and `r` along `axis`? The only question that should
    ever exempt a facing gap from the dead-gap penalty -- see
    _dead_gap_penalty's own docstring for the live evidence that a fixed
    "big enough to assume deliberate" size threshold cannot answer this
    correctly, because it is not a question about size at all."""
    cx0, cy0, cx1, cy1 = cand
    rx0, ry0, rx1, ry1 = r
    if axis == "x":
        if cx1 <= rx0:
            gx0, gx1 = cx1, rx0
        elif rx1 <= cx0:
            gx0, gx1 = rx1, cx0
        else:
            return True  # not actually facing on this axis
        oy0, oy1 = max(cy0, ry0), min(cy1, ry1)
        for ox0, oy0_, ox1, oy1_ in all_rects:
            if (ox0, oy0_, ox1, oy1_) == r:
                continue
            if ox1 > gx0 + 0.6 and ox0 < gx1 - 0.6 and oy1_ > oy0 + 0.6 and oy0_ < oy1 - 0.6:
                return True
        return False
    else:
        if cy1 <= ry0:
            gy0, gy1 = cy1, ry0
        elif ry1 <= cy0:
            gy0, gy1 = ry1, cy0
        else:
            return True
        ox0, ox1 = max(cx0, rx0), min(cx1, rx1)
        for ox0_, oy0, ox1_, oy1 in all_rects:
            if (ox0_, oy0, ox1_, oy1) == r:
                continue
            if oy1 > gy0 + 0.6 and oy0 < gy1 - 0.6 and ox1_ > ox0 + 0.6 and ox0_ < ox1 - 0.6:
                return True
        return False


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
    strip of space nothing can ever use.

    STRUCTURAL FIX (this was previously a fixed size threshold --
    MIN_USABLE_WIDTH/HEIGHT, "wide enough to assume deliberate separation"
    -- and that was proven wrong, not just imprecise): a real 7-window
    layout (browser/terminal/Discord/settings-dialog/utility-dialog/large-
    app proportions), scrambled and run through the real production
    SUPER+G path, left THREE separate facing pairs with 372-657px gaps
    between them -- all comfortably above any threshold that could ever
    be raised to "fix" the small 180px case without also exempting gaps
    this large. Each pair was demonstrably part of ONE connected
    composition (reachable via other windows' exact-5px links), so these
    were not legitimate separate clusters -- they were genuine holes.
    Root cause, confirmed by instrumenting the real incremental build: a
    window can choose to sit flush against ITS best neighbour (by the
    composition/compactness/movement terms) while ending up facing a
    DIFFERENT, already-placed window with nothing between them -- and
    nothing ever asked whether that specific facing relationship left a
    hole, because the only question this function asked was "is the gap
    narrower than a plausible window," never "is anything actually here."
    A gap between two windows that both belong to one connected
    composition is wrong at ANY size when nothing fills it.
    "Genuinely occupied" is now checked for directly (_gap_is_blocked),
    not inferred from gap width -- the one question that actually
    distinguishes a filled gap from an empty one. Below MIN_USABLE_WIDTH/
    HEIGHT (the resize floor, reused here only as "too small for any real
    window to occupy regardless") the blocking check is skipped entirely
    as a fast path, since nothing could block a gap that size anyway;
    verified this adds no observable cost for the common small-gap case
    this function was originally written for, and a measured, accepted
    cost (1.1x-2.2x at n=5-30, see the dxrice_test_placement.py benchmark)
    for genuinely large gaps, which is exactly when the real check is
    needed. The penalty is still capped so a candidate is never dragged
    across a large distance purely to close one gap."""
    worst = 0.0
    cx0, cy0, cx1, cy1 = cand
    for r in layout_rects:
        rx0, ry0, rx1, ry1 = r
        # _axis_gap inlined on both axes -- same reason as in
        # _flush_coverage: this loop runs once per obstacle per candidate.
        if cx1 <= rx0:
            xg = rx0 - cx1
        elif rx1 <= cx0:
            xg = cx0 - rx1
        else:
            xg = 0.0
        if cy1 <= ry0:
            yg = ry0 - cy1
        elif ry1 <= cy0:
            yg = cy0 - ry1
        else:
            yg = 0.0
        # Only count neighbours actually FACING the candidate on one axis
        # (overlapping on the other) -- a diagonal neighbour isn't leaving
        # a dead strip between them, it's just elsewhere. "Facing" itself
        # requires a MATERIAL share of the shorter perpendicular span, not
        # merely a nonzero overlap (see DEAD_GAP_FACING_COVERAGE_THRESHOLD)
        # -- a sliver-thin overlap between two rectangles that barely clip
        # each other's projection is not a real facing relationship.
        if yg == 0.0 and xg > gap:
            overlap = min(cy1, ry1) - max(cy0, ry0)
            span = min(cy1 - cy0, ry1 - ry0)
            frac = overlap / span if span > 0 else 0.0
            if frac >= DEAD_GAP_FACING_COVERAGE_THRESHOLD:
                d = xg - gap
                if d > worst and not (xg >= MIN_USABLE_WIDTH and _gap_is_blocked(cand, r, layout_rects, "x")):
                    worst = d
        if xg == 0.0 and yg > gap:
            overlap = min(cx1, rx1) - max(cx0, rx0)
            span = min(cx1 - cx0, rx1 - rx0)
            frac = overlap / span if span > 0 else 0.0
            if frac >= DEAD_GAP_FACING_COVERAGE_THRESHOLD:
                d = yg - gap
                if d > worst and not (yg >= MIN_USABLE_HEIGHT and _gap_is_blocked(cand, r, layout_rects, "y")):
                    worst = d
    return min(worst, DEAD_GAP_CAP) * DEAD_GAP_WEIGHT


# How far two near-flush neighbours' OUTER (perpendicular) edges may differ
# before it reads as a silhouette notch rather than ordinary imprecision --
# set just above ALIGN_EPS/FLUSH_TOL's own precision tolerance, not an
# independently-invented "how big is too big" number: anything this small
# is rounding noise, not a visible step in the outline.
NOTCH_MIN_DEPTH = 8.0

# Cost per pixel of unblocked silhouette-notch depth -- see _notch_penalty's
# own docstring for the live-measured evidence this closes. Deliberately
# lighter than DEAD_GAP_WEIGHT: a notch is a softer defect than a true dead
# gap (the two neighbours involved ARE genuinely flush -- the problem is
# one axis removed, on their OTHER edges, and is very often only partially
# avoidable at all when window heights/widths genuinely differ), but it
# must still be steep enough to move the optimizer's choice toward a
# shallower alternative when one exists at comparable cost.
NOTCH_WEIGHT = 6.0
NOTCH_CAP = 900.0


def _region_is_occupied(region, all_rects, exclude):
    """Does any rect OTHER than the two in `exclude` genuinely fill this
    axis-aligned region? Same "is anything actually here" question as
    _gap_is_blocked, applied to a perpendicular notch strip instead of a
    facing-gap strip."""
    rx0, ry0, rx1, ry1 = region
    for ox0, oy0, ox1, oy1 in all_rects:
        if (ox0, oy0, ox1, oy1) == exclude[0] or (ox0, oy0, ox1, oy1) == exclude[1]:
            continue
        if ox1 > rx0 + 0.6 and ox0 < rx1 - 0.6 and oy1 > ry0 + 0.6 and oy0 < ry1 - 0.6:
            return True
    return False


def _notch_penalty(cand, layout_rects, gap):
    """Penalises a SILHOUETTE NOTCH: live-traced, DISTINCT root cause from
    the dead-gap/sliver family above. Two neighbours can be PERFECTLY flush
    on their facing axis (zero dead-gap penalty, zero sliver penalty -- the
    facing edge genuinely touches cleanly) while their OTHER, perpendicular
    edges land a material distance apart, leaving an exposed step in the
    composition's outer silhouette. The facing-axis checks structurally
    cannot see this: they only ever look at the axis two rectangles are
    disjoint on, never the axis they overlap on.

    Found via a dedicated offline diagnostic (not the existing dead-gap
    sweep, which measures something else entirely) after a direct user
    report with a visual reference: "a window almost reaches another
    window/cluster but leaves a skinny strip of unused space... along the
    sides/outer edges." A randomized sweep (420 layouts, n=3..12, six
    window-shape archetypes) found an unblocked silhouette notch in 72.6%
    of them -- the dominant visual defect in this file, far more common
    than genuine dead gaps, and entirely unscored before this. Live
    example: two 1700x1100 windows stacked in a column, perfectly flush
    top-to-bottom, but their LEFT edges differing by 394px because a third
    window of a different size was placed between them earlier in the
    build -- composition_penalty scored this pair at a clean 0.0 (nothing
    wrong by the existing terms) despite the resulting 1700px-long, 394px-
    deep unblocked gutter running the full height of the shorter column.

    Deliberately scored on DEPTH alone (not depth x length, unlike this
    module's own diagnostic classification, which uses both to decide
    whether a notch is worth reporting at all) -- a cost that scaled with
    length would reward making windows SHORTER/NARROWER purely to shrink
    a notch's extent, which is exactly the "shrink things just because you
    can" behavior ruled out elsewhere in this file. Only penalised when
    nothing already fills the resulting strip (_region_is_occupied) -- a
    third window genuinely occupying that space means it was never a
    notch, matching _gap_is_blocked's identical principle for dead gaps.

    Not expected to reach zero on every composition: when neighbouring
    windows genuinely differ in height/width, SOME silhouette irregularity
    is geometrically unavoidable without resizing one of them to match,
    which is not always the right trade. What this term adds is the
    thing that was completely missing -- a reason for the optimizer to
    prefer the shallower of two otherwise-comparable alternatives, and for
    a resize that genuinely closes a notch to be correctly credited as an
    improvement (via composition_penalty's existing use in _final_cost and
    every per-step candidate score)."""
    worst = 0.0
    cx0, cy0, cx1, cy1 = cand
    for r in layout_rects:
        rx0, ry0, rx1, ry1 = r
        if cx1 <= rx0:
            xg = rx0 - cx1
        elif rx1 <= cx0:
            xg = cx0 - rx1
        else:
            xg = 0.0
        if cy1 <= ry0:
            yg = ry0 - cy1
        elif ry1 <= cy0:
            yg = cy0 - ry1
        else:
            yg = 0.0

        # Vertically-flush neighbours (stacked, overlapping on x) -- their
        # LEFT and RIGHT edges are the perpendicular pair to check.
        if xg == 0.0 and abs(yg - gap) < FLUSH_TOL:
            overlap = min(cx1, rx1) - max(cx0, rx0)
            span = min(cx1 - cx0, rx1 - rx0)
            frac = overlap / span if span > 0 else 0.0
            if frac >= DEAD_GAP_FACING_COVERAGE_THRESHOLD:
                top, bot = (cand, r) if cy1 <= ry0 else (r, cand)
                tx0, ty0, tx1, ty1 = top
                bx0, by0, bx1, by1 = bot
                # LEFT side: whichever of top/bot sticks out further left
                # leaves a notch beside the OTHER one, over the OTHER
                # one's own y-range (the one that sticks out doesn't
                # extend into that y-range at all, so nothing of its own
                # could ever fill the strip).
                if tx0 < bx0:
                    depth, region = bx0 - tx0, (tx0, by0, bx0, by1)
                else:
                    depth, region = tx0 - bx0, (bx0, ty0, tx0, ty1)
                if depth >= NOTCH_MIN_DEPTH and depth > worst \
                        and not _region_is_occupied(region, layout_rects, (cand, r)):
                    worst = depth
                # RIGHT side: symmetric.
                if tx1 > bx1:
                    depth, region = tx1 - bx1, (bx1, by0, tx1, by1)
                else:
                    depth, region = bx1 - tx1, (tx1, ty0, bx1, ty1)
                if depth >= NOTCH_MIN_DEPTH and depth > worst \
                        and not _region_is_occupied(region, layout_rects, (cand, r)):
                    worst = depth

        # Horizontally-flush neighbours (side by side, overlapping on y) --
        # their TOP and BOTTOM edges are the perpendicular pair to check.
        if yg == 0.0 and abs(xg - gap) < FLUSH_TOL:
            overlap = min(cy1, ry1) - max(cy0, ry0)
            span = min(cy1 - cy0, ry1 - ry0)
            frac = overlap / span if span > 0 else 0.0
            if frac >= DEAD_GAP_FACING_COVERAGE_THRESHOLD:
                left, right = (cand, r) if cx1 <= rx0 else (r, cand)
                lx0, ly0, lx1, ly1 = left
                rx0_, ry0_, rx1_, ry1_ = right
                # TOP side: symmetric to LEFT above, rotated 90 degrees.
                if ly0 < ry0_:
                    depth, region = ry0_ - ly0, (rx0_, ly0, rx1_, ry0_)
                else:
                    depth, region = ly0 - ry0_, (lx0, ry0_, lx1, ly0)
                if depth >= NOTCH_MIN_DEPTH and depth > worst \
                        and not _region_is_occupied(region, layout_rects, (cand, r)):
                    worst = depth
                # BOTTOM side: symmetric.
                if ly1 > ry1_:
                    depth, region = ly1 - ry1_, (rx0_, ry1_, rx1_, ly1)
                else:
                    depth, region = ry1_ - ly1, (lx0, ly1, lx1, ry1_)
                if depth >= NOTCH_MIN_DEPTH and depth > worst \
                        and not _region_is_occupied(region, layout_rects, (cand, r)):
                    worst = depth
    return min(worst, NOTCH_CAP) * NOTCH_WEIGHT


# ============================================================================
# GLOBAL composition model: mass-weighted center-of-mass + angular spread
# ============================================================================
#
# Diagnosis this section fixes: every score() in this file was a per-
# candidate distance to viewport_center plus purely LOCAL terms ("does this
# candidate touch its one neighbor cleanly"). Nothing anywhere asked what
# the WHOLE composition looks like. A vertical stack of 4 windows satisfies
# every local term perfectly (each is 100%-flush against its neighbor) and
# minimizes bbox growth, because a stack IS the minimum bounding rectangle
# for that footprint -- individual-distance-to-center + local edge-quality +
# bbox-growth is, together, a 2D bin-packing objective. No single term was
# "wrong"; the objective itself was rectangle packing with nicer edges.
#
# These two functions replace "how close is THIS window to center" with
# "how well-distributed is the WHOLE mass-weighted composition around
# center" -- reused by Stage 1, Stage 2, and (via import) Algorithm B, so
# one definition of "organic" governs every placement decision here.

# Bounds a window's contribution to the composition so neither a huge
# window nor a tiny one can swamp/vanish from the balance calculation --
# sqrt(area ratio), same shape as prominence_weight's own movement-cost
# scaling below, for the same reason: a 4x larger window should matter
# more than a same-sized one, but not 4x more (that would make the angular
# math effectively ignore every smaller window whenever one large one is
# present, defeating the point of measuring the WHOLE composition).
MASS_MIN = 0.35
MASS_MAX = 2.5


def window_mass(w, h, reference_area):
    if reference_area <= 0:
        return 1.0
    return min(MASS_MAX, max(MASS_MIN, math.sqrt((w * h) / reference_area)))


def _effective_count(weights):
    """Kish's effective sample size: sum(w)^2 / sum(w^2). Equals the literal
    count when every weight is equal; drops toward 1 as one weight comes to
    dominate the rest. Used by composition_cost to scale the concentration
    penalty by how many windows are actually contributing meaningful mass,
    not by raw window count -- "distribution is based on physical
    composition, not window count": 3 tiny dialogs clustered next to one
    huge window shouldn't be weighed the same as 4 similarly-sized windows
    when deciding whether the layout is spread out enough."""
    total = sum(weights)
    sq = sum(w * w for w in weights)
    return (total * total) / sq if sq > 0 else 0.0


# Pixel-equivalent scale for the shape-anisotropy penalty (see
# composition_cost). Raised from an earlier 2000 (tuned for a now-replaced
# LINEAR-in-R formulation) after the same value produced a fragile-to-wrong
# result once anisotropy became quadratic and confidence steepened: with a
# 3-window vertical pair-plus-one, extending the pair straight down (a real
# stack, aniso=0.648) came out numerically ahead of breaking to the side
# (aniso=0.473) because the stack's center of mass happened to land exactly
# on the viewport center while the side option cost ~289px of decentering
# -- at the old scale that 289px comfortably outweighed even the FULL-
# confidence quadratic difference between the two anisotropies. Raised
# until the side option wins that comparison with a real margin (checked
# directly, not just "no test fails") while dxrice_test_placement.py's full
# suite -- including the sliver/alignment/gap-preservation cases this
# constant must not override -- still passes.
ANGULAR_PENALTY_SCALE = 3500.0

# Pixel-equivalent weight for how far the mass-weighted CENTER of the whole
# composition sits from the viewport center. This is "balanced_cluster
# around viewport_center," not "every_window -> viewport_center": it
# replaces the old per-candidate hypot(px-cx, py-cy) term, and degenerates
# to exactly that old term when there's only one window in the composition
# (its own center IS the mass center) -- so single/first-window placement
# is unchanged; behavior only diverges once there's an actual cluster to
# balance.
CENTER_OF_MASS_WEIGHT = 1.0


def _axial_concentration(weighted_angles):
    """LEGACY / A-vs-B comparison tooling only -- no longer used by
    composition_cost (see its own docstring for why). Kept only so a
    diagnostic can report the old point-only metric alongside the new
    covariance-based one for an honest before/after comparison.

    weighted_angles: [(angle_radians, weight), ...]. Returns (R, n_eff): R
    in [0, 1] is the mass-weighted mean resultant length of DOUBLED angles
    (the axial/directional-statistics trick where "above" and "below" both
    read as "on the vertical axis" instead of cancelling); n_eff is the
    Kish effective count of the weights.
    """
    if not weighted_angles:
        return 0.0, 0.0
    weights = [w for _, w in weighted_angles]
    total = sum(weights)
    if total <= 0:
        return 0.0, 0.0
    rx = sum(w * math.cos(2 * a) for a, w in weighted_angles) / total
    ry = sum(w * math.sin(2 * a) for a, w in weighted_angles) / total
    return math.hypot(rx, ry), _effective_count(weights)


def mass_center(weighted_rects):
    """weighted_rects: [(cx, cy, w, h, mass), ...]. Returns (com_x, com_y),
    or None if there's no mass at all (empty list)."""
    # One pass instead of three. The accumulation order is the same one
    # sum() uses (left to right from 0), so this is bit-identical to the
    # three-sum version it replaces -- it just stops walking the list
    # twice more. This is on the hottest path in the whole arrange pass.
    total_w = 0.0
    sx = sy = 0.0
    for cx, cy, _w, _h, m in weighted_rects:
        total_w += m
        sx += cx * m
        sy += cy * m
    if total_w <= 0:
        return None
    return (sx / total_w, sy / total_w)


def covariance_matrix(weighted_rects, ref_point):
    """Mass-weighted second moment of the whole set of RECTANGLES (not
    just their center points) about `ref_point`. This is the actual fix
    for "a window is not a point" (see the module's COMPOSITION MODEL
    section): each window contributes both how far its center sits from
    ref_point (dx, dy) AND its own intrinsic footprint via the standard
    parallel-axis theorem -- a rectangle w x h has second moment w^2/12
    about its own center on the x axis (h^2/12 on y), so a 1400x900
    window registers as genuinely spread across a large area even before
    its distance from anything else is considered, while a 300x200 dialog
    barely registers beyond its own center point. Returns (Cxx, Cyy, Cxy),
    the entries of the symmetric 2x2 mass-weighted covariance matrix,
    normalized by total mass so its scale doesn't depend on how many
    windows are in the set."""
    rx, ry = ref_point
    # `total` accumulates in the same pass as the moments rather than in a
    # separate sum() over the same list -- identical arithmetic, one walk.
    total = 0.0
    Cxx = Cyy = Cxy = 0.0
    for cx, cy, w, h, m in weighted_rects:
        total += m
        dx, dy = cx - rx, cy - ry
        Cxx += m * (dx * dx + (w * w) / 12.0)
        Cyy += m * (dy * dy + (h * h) / 12.0)
        Cxy += m * (dx * dy)
    if total <= 0:
        return 0.0, 0.0, 0.0
    return Cxx / total, Cyy / total, Cxy / total


def principal_axes(Cxx, Cyy, Cxy):
    """Closed-form eigen-decomposition of the symmetric 2x2 matrix
    [[Cxx, Cxy], [Cxy, Cyy]] -- no numpy dependency needed for a 2x2.
    Returns (lambda1, lambda2, angle): lambda1 >= lambda2 >= 0 are the
    variances along the major and minor axes of the mass distribution,
    and angle (radians) is the direction of the major axis -- the actual
    orientation of whatever elongation is present, available for a future
    "don't extend THIS specific axis further" search bias if ever needed,
    though anisotropy() alone (see below) already captures the magnitude
    of the effect regardless of orientation, which is what composition_cost
    uses today."""
    trace = Cxx + Cyy
    diff = Cxx - Cyy
    disc = math.hypot(diff, 2 * Cxy)
    lambda1 = max(0.0, (trace + disc) / 2.0)
    lambda2 = max(0.0, (trace - disc) / 2.0)
    angle = 0.5 * math.atan2(2 * Cxy, diff) if disc > 1e-9 else 0.0
    return lambda1, lambda2, angle


def anisotropy(lambda1, lambda2):
    """0 = the mass is spread evenly in every direction (a round, balanced
    cluster); 1 = every bit of mass lies along a single line, whatever
    orientation that line has (a stack or row). This is the direct 2D-
    shape replacement for the old points-only axial statistic: it comes
    from the real mass-weighted covariance of the whole set of RECTANGLES
    (see covariance_matrix), so a composition made of a few large windows
    that genuinely fill a 2D area reads as balanced even if their bare
    center points happen to line up, and a composition of small, point-
    like windows strung along one line reads as elongated exactly when it
    visually is."""
    total = lambda1 + lambda2
    return (lambda1 - lambda2) / total if total > 1e-9 else 0.0


def composition_cost(weighted_rects, viewport_center, aspect=1.0):
    """The GLOBAL (whole-cluster) composition term -- see the module
    comment above for why this exists. `weighted_rects`: [(cx, cy, w, h,
    mass), ...] for EVERY window in the composition, including whatever
    candidate is being scored (the caller assembles this list fresh per
    candidate, since the candidate's own point changes each time). Never
    includes fixed/fullscreen obstacles -- those are furniture the
    composition routes around, not mass it's trying to balance, same
    convention `layout_others` already uses for the local terms.

    Two components, both pixel-equivalent and summed directly:

      - center-of-mass distance: how far the mass-weighted average
        position of the WHOLE group sits from viewport_center. With one
        window this is exactly that window's own distance to center (the
        old per-window term, preserved as a special case); with several,
        it's the aggregate's distance, so no single window is rewarded
        merely for personally sitting close to center.
      - shape anisotropy (see anisotropy()): is the group's own mass
        distribution round/balanced, or concentrated along one line --
        computed from the group's actual second moment about its OWN mass
        center, not viewport_center. This deliberately separates two
        different questions that the earlier point-angle-from-viewport
        formulation conflated: "is the group in the right place"
        (center-of-mass distance, above) and "is the group's own SHAPE
        good" (a property of the group alone, independent of where it
        happens to sit relative to the viewport -- moment of inertia is
        conventionally measured about an object's own centroid for
        exactly this reason).

    Replaces the earlier doubled-angle circular-statistics approach
    (_axial_concentration, kept only for old-vs-new comparison tooling):
    that measured concentration of window CENTER POINTS around the
    viewport, which is a reasonable approximation for point-like windows
    but has no notion that a real window occupies a 2D area -- a large
    window's own footprint didn't otherwise register at all in a
    points-only view, and "is this near the exact center" had to be
    special-cased via `angle_eps` to avoid atan2 noise for anything
    sitting close to that single reference point. Measuring the real
    second moment removes that special case entirely: a window sitting
    exactly at the group's own mass center contributes zero from its own
    offset but still contributes its own w^2/12, h^2/12 extent, no
    separate exclusion or confidence-count patch needed -- the class of
    bug that special case existed to fix (see the previous docstring
    revision's account of the L-shaped centered-window confidence
    loophole) can't recur because there's no separate "angle-bearing
    subset" of points anymore; every window, wherever it sits, is one
    uniform contribution to one matrix.
    """
    center_of_mass_cost, angular_cost = composition_cost_components(weighted_rects, viewport_center, aspect)
    return CENTER_OF_MASS_WEIGHT * center_of_mass_cost + angular_cost


def composition_cost_components(weighted_rects, viewport_center, aspect=1.0):
    """Same two ingredients composition_cost sums together, returned
    SEPARATELY as (center_of_mass_cost, angular_cost) -- angular_cost
    already includes its own ANGULAR_PENALTY_SCALE multiplication (i.e. it
    is on the SAME absolute scale composition_cost itself uses, not a bare
    0..1 anisotropy value), so a caller that wants to weight the two
    ingredients differently can do so without re-deriving the formula.

    Why this exists: place_new_window's Stage 1 vs Stage 2 decision (and
    Stage 3's comparison against it) dampens composition_cost's
    contribution to a SECONDARY role via STAGE_DECISION_COMPOSITION_WEIGHT
    -- necessary because the RAW center-of-mass term is vulnerable to a
    real bug (see that weight's own comment: a small window already
    sitting near center can pull the mass-weighted AVERAGE position close
    to center even while a large, dominant new window sits far off,
    making eviction look unnecessary when it wasn't). But a live benchmark
    (this change's own report, "Case A": two huge windows already stacked,
    a new medium window arrives) found that dampening the WHOLE
    composition_cost -- shape included -- let a candidate that measurably
    WORSENED the group's shape (extending the existing stack) win anyway,
    because moving a huge window 460px to slot the new one into the same
    line also happened to pull the new window's own distance-to-center
    down a lot, and that saving wasn't fairly weighed against the shape it
    cost. The center-of-mass term's averaging bug and the shape term's
    "extends a stack" signal are different phenomena with different
    failure modes -- damping BOTH by the same factor was the actual
    representational error, not a constant needing further tuning. This
    split lets a caller keep center-of-mass secondary (where the bug
    lives) while keeping shape at its own already-validated, undamped
    scale (where it doesn't)."""
    if not weighted_rects:
        return 0.0, 0.0
    vx, vy = viewport_center
    com = mass_center(weighted_rects)
    if com is None:
        return 0.0, 0.0
    center_of_mass_cost = math.hypot(com[0] - vx, com[1] - vy)

    # `aspect` (width/height) is the shape the composition should read as
    # balanced at: 1.0 (the default, every caller but SUPER+G) is round. The
    # vertical spread is measured in units stretched by it, so a cluster
    # with exactly that aspect has zero anisotropy -- SUPER+G passes the
    # screen's own shape, so a whole-desktop arrangement fills a 16:9 view
    # instead of being pulled toward a circle (or a tall column) inside it.
    if aspect != 1.0:
        weighted_rects = [(cx, cy * aspect, w, h * aspect, m) for cx, cy, w, h, m in weighted_rects]
        com = (com[0], com[1] * aspect)
    Cxx, Cyy, Cxy = covariance_matrix(weighted_rects, com)
    lambda1, lambda2, _angle = principal_axes(Cxx, Cyy, Cxy)
    aniso = anisotropy(lambda1, lambda2)

    # Confidence scaling: any 2 windows are always exactly collinear
    # through their OWN shared mass center (2 points define a line by
    # construction), so n_eff==2 must never be penalized -- but a genuine
    # THIRD contributor is where "stacking" becomes a real, avoidable
    # property rather than an unavoidable fact about any 2 rectangles, and
    # that is exactly the regime real desktop use lives in most of the
    # time (3-6 windows). A live diagnostic (sequential-open test, see this
    # change's own report) found the earlier, gentler ramp
    # ((n_eff-2)/(n_eff-1), giving only 0.5 confidence at n_eff==3) let a
    # THIRD window extend an already-vertical pair into a straight 3-stack,
    # because that specific candidate's center-of-mass distance happened
    # to be exactly 0 (extending a pair that's symmetric about the
    # viewport keeps the average dead-center) while a genuinely
    # better-shaped candidate to the side was ~289px off-center -- at half
    # confidence, the centering saving outweighed the elongation
    # difference. This matters at n_eff==3 specifically, so the ramp needs
    # to mature fast there, not gradually: 1 - 1/(n_eff-1)^2 stays exactly
    # 0 at n_eff==2 (same non-negotiable floor) but reaches 0.75 already at
    # n_eff==3 instead of 0.5.
    n_eff = _effective_count([m for _, _, _, _, m in weighted_rects])
    confidence = max(0.0, 1.0 - 1.0 / (n_eff - 1.0) ** 2) if n_eff > 1 else 0.0
    # Squared, not linear: the SAME diagnostic showed that even at full
    # confidence, a linear aniso term let a moderately-more-elongated
    # candidate (0.648) beat a moderately-less-elongated one (0.473) by
    # only a fragile margin once weighed against a real centering
    # difference -- a near-tie for what should be a clear call. Squaring
    # makes the penalty escalate faster as elongation actually gets worse
    # (the gap between 0.47^2=0.22 and 0.65^2=0.42 is proportionally much
    # larger than between 0.47 and 0.65 themselves), which is also the more
    # literal reading of the user's own "a strong elongated chain gets a
    # penalty" framing -- escalating, not flat-rate.
    angular_cost = ANGULAR_PENALTY_SCALE * (aniso ** 2) * confidence

    return center_of_mass_cost, angular_cost


def composition_penalty(cand, layout_rects, gap):
    """Pixel-equivalent score contribution (added directly to a distance-
    based score, so 0 is neutral, positive is worse) capturing whether
    `cand` reads as a clean, intentional addition to `layout_rects` rather
    than merely a non-overlapping rectangle. See the weight comments above
    for what each term means; all are no-ops when there's no existing
    layout to compose with yet (an empty/absent `layout_rects`)."""
    if not layout_rects:
        return 0.0
    # All three terms fused into ONE pass over layout_rects.
    #
    # This is the single hottest loop in a SUPER+G pass -- it runs once per
    # obstacle per candidate position -- and the three helpers it replaces
    # walked the same list three times while _flush_coverage and
    # _dead_gap_penalty each independently recomputed the SAME two axis
    # gaps for the same pair of rectangles. Fused, the gaps are computed
    # once and all three terms are derived from them.
    #
    # The arithmetic is identical, not merely equivalent-looking, and
    # _flush_coverage / _edge_alignment_count / _dead_gap_penalty remain
    # the canonical definitions (still used by the adjacency coherence
    # check and by their own tests). test_composition_penalty_fused_pass_
    # matches_the_individual_helpers pins the two against each other on
    # randomised geometry so this copy can never silently drift from them.
    #
    # The one deliberate difference: the alignment scan no longer breaks
    # early once both axes are satisfied, because the other two terms need
    # the rest of the list anyway. Same result, strictly less loop
    # overhead than three separate traversals.
    cx0, cy0, cx1, cy1 = cand
    neg_eps = -ALIGN_EPS
    best_coverage = None
    worst_dead = 0.0
    aligned_x = aligned_y = False
    for rx0, ry0, rx1, ry1 in layout_rects:
        if cx1 <= rx0:
            xgap = rx0 - cx1
        elif rx1 <= cx0:
            xgap = cx0 - rx1
        else:
            xgap = 0.0
        if cy1 <= ry0:
            ygap = ry0 - cy1
        elif ry1 <= cy0:
            ygap = cy0 - ry1
        else:
            ygap = 0.0

        # --- flush coverage (see _flush_coverage) ---
        frac = None
        if -FLUSH_TOL < (xgap - gap) < FLUSH_TOL and ygap == 0.0:
            overlap = min(cy1, ry1) - max(cy0, ry0)
            span = min(cy1 - cy0, ry1 - ry0)
            frac = overlap / span if span > 0 else 0.0
        elif -FLUSH_TOL < (ygap - gap) < FLUSH_TOL and xgap == 0.0:
            overlap = min(cx1, rx1) - max(cx0, rx0)
            span = min(cx1 - cx0, rx1 - rx0)
            frac = overlap / span if span > 0 else 0.0
        if frac is not None:
            best_coverage = frac if best_coverage is None else max(best_coverage, frac)

        # --- dead gap (see _dead_gap_penalty's own docstring for the live
        # evidence this is a "is anything actually here" question, not a
        # "is the gap narrower than some size" one) -- "facing" requires a
        # MATERIAL share of the shorter perpendicular span, not merely a
        # nonzero overlap (see DEAD_GAP_FACING_COVERAGE_THRESHOLD) ---
        if ygap == 0.0 and xgap > gap:
            overlap = min(cy1, ry1) - max(cy0, ry0)
            span = min(cy1 - cy0, ry1 - ry0)
            frac = overlap / span if span > 0 else 0.0
            if frac >= DEAD_GAP_FACING_COVERAGE_THRESHOLD:
                d = xgap - gap
                if d > worst_dead and not (xgap >= MIN_USABLE_WIDTH
                                            and _gap_is_blocked(cand, (rx0, ry0, rx1, ry1), layout_rects, "x")):
                    worst_dead = d
        if xgap == 0.0 and ygap > gap:
            overlap = min(cx1, rx1) - max(cx0, rx0)
            span = min(cx1 - cx0, rx1 - rx0)
            frac = overlap / span if span > 0 else 0.0
            if frac >= DEAD_GAP_FACING_COVERAGE_THRESHOLD:
                d = ygap - gap
                if d > worst_dead and not (ygap >= MIN_USABLE_HEIGHT
                                            and _gap_is_blocked(cand, (rx0, ry0, rx1, ry1), layout_rects, "y")):
                    worst_dead = d

        # --- edge alignment (see _edge_alignment_count) ---
        if not aligned_x:
            d0 = cx0 - rx0
            d1 = cx1 - rx1
            if (neg_eps < d0 < ALIGN_EPS) or (neg_eps < d1 < ALIGN_EPS):
                aligned_x = True
        if not aligned_y:
            d0 = cy0 - ry0
            d1 = cy1 - ry1
            if (neg_eps < d0 < ALIGN_EPS) or (neg_eps < d1 < ALIGN_EPS):
                aligned_y = True

    sliver = SLIVER_PENALTY_MAX * (1.0 - best_coverage) if best_coverage is not None else 0.0
    align = ALIGN_BONUS * (int(aligned_x) + int(aligned_y))
    dead = min(worst_dead, DEAD_GAP_CAP) * DEAD_GAP_WEIGHT
    return sliver + dead - align


# Caps how many obstacles ever contribute their own edges as candidate
# ANCHORS in find_free_position / find_least_disruptive_position /
# _candidate_targets -- profiled at n=25 eligible windows: these three
# functions each build their candidate set as every x-value crossed with
# every y-value derived from EVERY obstacle's edges, an O(n) x n) = O(n^2)
# candidate count, each then scored in O(n) time -- an O(n^3) cost PER
# CALL that dominated Stage 2's own wall-clock time (0.58s of it for a
# single try_make_room call at n=25, almost entirely inside
# _candidate_targets's own candidate generation+scoring, not the cascade
# resolution loop this file's other performance fix already bounded).
# Rather than changing WHICH positions win (any change there risks
# altering already-verified behavior), this only prunes WHICH OBSTACLES
# get to propose candidate x/y values in the first place, to the
# CANDIDATE_ANCHOR_CAP nearest (by center distance) to the point the
# search actually cares about being near -- `free()` and every scoring
# term still check the FULL, unpruned obstacle/layout set, so correctness
# (never overlapping something far away, being weighed correctly in the
# global composition) is completely unaffected; only how many CANDIDATE
# POSITIONS get proposed changes, and only when there are meaningfully
# more obstacles than this cap. An obstacle far from the point of
# interest is exceedingly unlikely to ever produce the winning candidate
# anyway (its edges are nowhere near where the search is actually
# looking), so this is pruning by relevance, not by an arbitrary count --
# per this session's own explicit "only consider windows that can
# actually conflict" guidance. No-op for every realistic desktop window
# count (this file's own test suite never exceeds this many eligible
# windows in one call), verified by re-running the full suite unchanged.
CANDIDATE_ANCHOR_CAP = 12


def _nearest_for_candidates(obstacles, anchor, cap=CANDIDATE_ANCHOR_CAP):
    """obstacles: [(x, y, w, h), ...]. Returns the `cap` closest (by center
    distance to `anchor`) unchanged if there are already `cap` or fewer --
    see CANDIDATE_ANCHOR_CAP's own comment for why this only prunes which
    obstacles propose candidate x/y VALUES, never which obstacles are
    checked for validity or counted in the composition."""
    obstacles = list(obstacles)
    if len(obstacles) <= cap:
        return obstacles
    ax, ay = anchor
    def dist2(o):
        ox, oy, ow, oh = o
        return (ox + ow / 2 - ax) ** 2 + (oy + oh / 2 - ay) ** 2
    return sorted(obstacles, key=dist2)[:cap]


def find_free_position(new_size, others, center, gap, viewport=None, layout_others=None,
                        reference_area=None):
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
    movable windows, excluding fixed/fullscreen ones -- used for the local
    "don't unnecessarily expand the existing layout" tiebreak AND as the
    GLOBAL composition reference (see score() below and composition_cost's
    own docstring). Defaults to `others` itself when not given, so a
    caller that doesn't distinguish fixed obstacles (dxrice_align_windows.py)
    keeps its previous behavior. A fullscreen window is still always a
    hard obstacle via `others` either way; it's excluded here only so it
    doesn't count as mass/layout the new window is meaningfully being
    composed with -- it's fixed furniture to route around.

    reference_area: the "typical window size" used to normalize mass for
    the global composition term -- defaults to this window's own area
    (matching prominence_weight's existing convention) so a caller placing
    a single new window doesn't need to think about it; a caller arranging
    a whole group (Algorithm B) passes a shared value so every window in
    that pass is weighed against the same yardstick.

    Candidates are every crossing of "an X derived from some obstacle's
    left/right edge (or this window's own gap-width clearance past it)"
    with "a Y derived from some obstacle's top/bottom edge (or clearance
    past it)", plus the plain viewport-center point -- i.e. every place a
    new window could line up flush against an existing one on either axis,
    not just the four cardinal offsets immediately beside each obstacle.
    This set already includes diagonal/corner-relative positions (an x
    from one obstacle crossed with a y from another, or the same one)
    without needing a separate "generate diagonals" step.

    Candidates are scored by the GLOBAL composition cost of the whole
    layout with this candidate added (see composition_cost) -- how far the
    mass-weighted center of everything sits from `center`, plus how
    concentrated the whole set of windows is along a single angular axis
    through it -- NOT by this one candidate's own distance to `center`
    (that per-window pull was itself the source of a real bug: it made
    every window in a sequence prefer whichever spot was individually
    closest to center, which reliably piled new windows onto whatever
    axis already had the shortest remaining path there). A small local
    tiebreak for candidates that don't unnecessarily grow the existing
    layout's own footprint, plus the existing sliver/dead-gap/alignment
    terms, round out the score -- both are intentionally secondary to the
    composition term, per the explicit requirement that compactness not
    dominate the visual result.

    Returns (x, y), always -- if every generated candidate conflicts with
    something (a tight cluster of many windows), falls back to a spiral
    search centered on `center` with no distance limit, which always
    eventually finds free space since the canvas has no edge.
    """
    if layout_others is None:
        layout_others = others

    nw, nh = new_size
    cx, cy = center
    if reference_area is None:
        reference_area = nw * nh
    other_rects = [rect_for(ox, oy, ow, oh) for ox, oy, ow, oh in others]
    layout_rects = [rect_for(ox, oy, ow, oh) for ox, oy, ow, oh in layout_others]

    # Precomputed once: every OTHER window's contribution to the global
    # composition (center + mass) -- fixed for the whole candidate search,
    # since only the candidate itself varies between calls to score().
    other_points = [(ox + ow / 2, oy + oh / 2, ow, oh, window_mass(ow, oh, reference_area))
                     for ox, oy, ow, oh in layout_others]
    cand_mass = window_mass(nw, nh, reference_area)

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
        cand = (x, y, x + nw, y + nh)
        total = composition_cost(other_points + [(px, py, nw, nh, cand_mass)], center)
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
    for ox, oy, ow, oh in _nearest_for_candidates(list(others) + list(layout_others), center):
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


def find_least_disruptive_position(new_size, others, gap, current_pos, layout_others=None,
                                    viewport_center=None, reference_area=None):
    """Relocates an EXISTING window that's blocking where the new window
    wants to go. Unlike find_free_position (which has no prior position to
    protect), here minimal movement from the window's own current spot is
    the PRIMARY signal -- there's no fixed target point at all, since a
    displaced window isn't trying to get anywhere in particular, only out
    of the way with the least disruption. Same candidate generation as
    find_free_position (every obstacle's edges crossed in both axes, plus
    the window's own current position as an explicit candidate), same
    guaranteed-terminating spiral fallback if every edge-derived spot
    conflicts with something.

    The GLOBAL composition cost (see composition_cost) is added as a
    secondary term when `viewport_center` is given -- among positions that
    are roughly equally cheap to reach, prefer whichever one leaves the
    overall composition better balanced, rather than treating "get this
    window out of the way" as having no opinion at all about the result.
    Movement-to-own-position has no artificial cap and typically differs
    by tens to hundreds of pixels between genuinely different candidates,
    so it dominates the decision in the normal case; the composition term
    only breaks near-ties, matching the "movement should be minimized"
    requirement while still steering toward a better shape when the choice
    is otherwise open. Omitted entirely (falls back to the old
    movement-only behavior) if the caller has no meaningful viewport
    center to offer -- callers that already had this contract keep working
    unmodified.
    """
    if layout_others is None:
        layout_others = others

    nw, nh = new_size
    cx0, cy0 = current_pos
    if reference_area is None:
        reference_area = nw * nh
    other_rects = [rect_for(ox, oy, ow, oh) for ox, oy, ow, oh in others]
    layout_rects = [rect_for(ox, oy, ow, oh) for ox, oy, ow, oh in layout_others]
    other_points = [(ox + ow / 2, oy + oh / 2, ow, oh, window_mass(ow, oh, reference_area))
                     for ox, oy, ow, oh in layout_others]
    cand_mass = window_mass(nw, nh, reference_area)

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
        if viewport_center is not None:
            total += composition_cost(other_points + [(px, py, nw, nh, cand_mass)], viewport_center)
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
    for ox, oy, ow, oh in _nearest_for_candidates(others, current_pos):
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

# Secondary influence of the GLOBAL composition cost on the Stage 1 vs
# Stage 2 decision itself (see the comment where this is used, in
# place_new_window) -- deliberately small relative to d1/d2's own
# coefficient of 1.0, so the new window's own centeredness stays the
# dominant consideration (restoring the property that worked before the
# composition audit) while a genuine, large composition difference between
# the two plans (the kind that matters for 3+ window stack-breaking, where
# this term was never actually the deciding factor to begin with -- that
# happens inside find_free_position's own candidate search) can still tip
# a close call.
STAGE_DECISION_COMPOSITION_WEIGHT = 0.3

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


def _candidate_targets(new_size, fixed_obstacles, layout_others, center, gap, top_k=6):
    """Generates and ranks candidate positions for the new window, treating
    every ORDINARY window in `layout_others` as potentially movable (i.e.
    NOT a hard constraint -- only `fixed_obstacles` block a candidate here).
    Returns up to `top_k` candidates by the same composition-aware scoring
    find_free_position uses, best first.

    This exists because evaluating only the SINGLE best "ideal spot for the
    new window, ignoring what it would take to evict whoever's there" was a
    real, live-confirmed bug (see try_make_room's own docstring): with no
    fixed obstacles, that ideal spot is essentially always the bare
    viewport-center candidate, so Stage 2 kept trying to evict whatever
    already occupied dead-center and shove it further along the SAME axis,
    every single time a new window arrived -- 4 similarly-sized windows
    opened one after another produced a 3-window column plus one window
    stranded off to the side, not the 2x2-ish spread the same 4 rectangles
    could easily have formed. The fix isn't a bigger penalty on that one
    spot; it's evaluating SEVERAL candidate spots and letting the actual
    cost of each one's eviction plan decide, which is what try_make_room
    does with this function's output.
    """
    nw, nh = new_size
    cx, cy = center
    reference_area = nw * nh
    fixed_rects = [rect_for(*r) for r in fixed_obstacles]
    layout_rects = [rect_for(*r) for r in layout_others]
    other_points = [(ox + ow / 2, oy + oh / 2, ow, oh, window_mass(ow, oh, reference_area))
                     for ox, oy, ow, oh in layout_others]
    cand_mass = window_mass(nw, nh, reference_area)

    def free(x, y):
        candidate = rect_for(x, y, nw, nh)
        inflated = (candidate[0] - gap, candidate[1] - gap, candidate[2] + gap, candidate[3] + gap)
        return not any(overlaps(inflated, r) for r in fixed_rects)

    layout_bbox = None
    if layout_rects:
        layout_bbox = (min(r[0] for r in layout_rects), min(r[1] for r in layout_rects),
                        max(r[2] for r in layout_rects), max(r[3] for r in layout_rects))

    def score(x, y):
        px, py = x + nw / 2, y + nh / 2
        cand = (x, y, x + nw, y + nh)
        total = composition_cost(other_points + [(px, py, nw, nh, cand_mass)], center)
        if layout_bbox is not None:
            bx0, by0, bx1, by1 = layout_bbox
            new_w = max(bx1, cand[2]) - min(bx0, cand[0])
            new_h = max(by1, cand[3]) - min(by0, cand[1])
            growth = (new_w - (bx1 - bx0)) + (new_h - (by1 - by0))
            total += EXPANSION_WEIGHT * growth
        total += composition_penalty(cand, layout_rects, gap)
        return total

    xs = {cx - nw / 2}
    ys = {cy - nh / 2}
    for ox, oy, ow, oh in _nearest_for_candidates(list(fixed_obstacles) + list(layout_others), center):
        xs.update((ox, ox + ow + gap, ox - nw - gap))
        ys.update((oy, oy + oh + gap, oy - nh - gap))
    candidates = [(x, y) for x in xs for y in ys]
    valid = [(x, y) for x, y in candidates if free(x, y)]
    if not valid:
        # Every edge-derived spot conflicts with a FIXED obstacle -- fall
        # back to find_free_position's own guaranteed-terminating spiral.
        return [find_free_position(new_size, fixed_obstacles, center, gap,
                                    layout_others=layout_others, reference_area=reference_area)]
    valid.sort(key=lambda p: score(*p))
    return valid[:top_k]


def _resolve_conflicts(target_rect, eligible, fixed_obstacles, gap, center, reference_area):
    """Given a FIXED target_rect for the new window, relocates whichever
    ELIGIBLE windows actually overlap it (gap-inflated) -- only these are
    ever touched, largest-area first (ties by address -- deterministic),
    cascading if a relocation creates a new conflict, bounded so it can
    never need more rounds than there are eligible windows. Same mechanics
    try_make_room always used for a single target; factored out so multiple
    candidate targets (see _candidate_targets) can each be resolved and
    compared. Returns {address: new_pos, ...} (empty if nothing needed to
    move), or None if the cascade doesn't resolve within its bound or a
    final overlap sanity check fails."""
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
        return {}

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
        other_xywh = [(r[0], r[1], r[2] - r[0], r[3] - r[1]) for r in other_rects_xyxy] + list(fixed_obstacles)

        new_pos = find_least_disruptive_position(size, other_xywh, gap, original_center[addr],
                                                  viewport_center=center, reference_area=reference_area)
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
    # eligible windows against each other -- this pass didn't create
    # whatever relationship they already had (a real desktop could have
    # two windows sitting closer together than this rice would place them
    # itself, e.g. from a manual drag), and it isn't this pass's job to
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

    return moved


def try_make_room(new_size, eligible, fixed_obstacles, center, gap, top_k=6):
    """Stage 2. `eligible`/`fixed_obstacles`: [(x, y, w, h), ...] plus an
    "address" key on each `eligible` entry (fixed obstacles never move, so
    they don't need one).

    A genuine JOINT search, not a two-step "find the one ideal spot, then
    evict whoever's there" pipeline: generates several candidate target
    positions for the new window (_candidate_targets, up to `top_k`, best
    composition-scored first, treating every ordinary window as movable),
    resolves the actual eviction/relocation plan for EACH one
    (_resolve_conflicts), scores each resulting FULL layout (new window +
    every eligible window at its final position, whether moved or not) by
    the same whole-composition cost plus prominence-weighted total
    movement, and returns whichever candidate's plan wins.

    This directly fixes a live-confirmed bug in the single-candidate
    version: with no fixed obstacles, the one "ideal spot" a lone
    find_free_position call would compute is essentially always the bare
    viewport-center point, so every new window's Stage 2 plan was "evict
    whatever already sits at dead-center," regardless of whether a
    DIFFERENT nearby spot would have required evicting nothing at all, or
    would have produced a far more balanced resulting shape. Four
    similarly-sized windows opened one after another, under the old
    single-candidate version, produced a 3-window vertical column plus one
    window stranded to the side -- confirmed via
    dxrice_test_placement.py's TestJointStage2Search and the live
    before/after comparison in this change's own report. Evaluating
    multiple targets and scoring the WHOLE resulting layout is what lets
    the search discover "place the new window beside the existing pair
    instead, displacing nothing" when that is, in fact, the better plan.

    Returns (target_pos, {address: new_pos, ...}) -- the second dict holds
    ONLY the windows that actually needed to move, empty if the winning
    target was already clear. Returns None if no candidate target resolves
    to a valid plan at all (the caller falls back to Stage 1).
    """
    if not eligible:
        return None
    nw, nh = new_size
    # One reference area for the WHOLE Stage 2 decision, derived from the
    # actual new window being placed (not whichever eligible window happens
    # to be getting relocated in a given cascade round) -- every mass
    # comparison in this pass needs the same yardstick, or "how prominent
    # is window X" would mean something different depending on which call
    # computed it.
    reference_area = nw * nh
    eligible_rects = [(w["at"][0], w["at"][1], w["size"][0], w["size"][1]) for w in eligible]

    targets = _candidate_targets(new_size, fixed_obstacles, eligible_rects, center, gap, top_k=top_k)

    best = None  # (score, target_pos, moved)
    for target_pos in targets:
        target_rect = rect_for(target_pos[0], target_pos[1], nw, nh)
        moved = _resolve_conflicts(target_rect, eligible, fixed_obstacles, gap, center, reference_area)
        if moved is None:
            continue

        eligible_by_addr = {w["address"]: w for w in eligible}
        orig_at = {w["address"]: w["at"] for w in eligible}
        cand_mass = window_mass(nw, nh, reference_area)
        whole_points = [(target_pos[0] + nw / 2, target_pos[1] + nh / 2, nw, nh, cand_mass)]
        for w in eligible:
            addr = w["address"]
            ow, oh = w["size"]
            mx, my = moved[addr] if addr in moved else w["at"]
            whole_points.append((mx + ow / 2, my + oh / 2, ow, oh, window_mass(ow, oh, reference_area)))
        comp = composition_cost(whole_points, center)
        total_movement = sum(
            math.hypot(nx - orig_at[a][0], ny - orig_at[a][1]) * prominence_weight(a, eligible_by_addr, reference_area)
            for a, (nx, ny) in moved.items()
        )
        score = comp + MAKE_ROOM_MOVEMENT_WEIGHT * total_movement
        if best is None or score < best[0]:
            best = (score, target_pos, moved)

    if best is None:
        return None
    _, target_pos, moved = best
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

# (Formerly RESIZE_TRIGGER_MULTIPLE: a fixed "only consider resize when the
# new window's own positional cost is this many times its diagonal" gate.
# Removed after a live sizing audit (dxrice_test_placement.py's
# TestResizeCompositionAware, and this change's own report) showed it was
# measuring the wrong thing -- the new window's own distance to center has
# no reliable relationship to whether the WHOLE composition is actually
# bad. Two windows already sitting far apart from each other (each only
# moderately close to center individually) produced a genuinely poor
# composition (high anisotropy) that this gate never even let Stage 3
# look at, while other cases with an equally "fine-looking" positional
# cost turned out to have real, measurable composition improvements
# available from a modest resize. try_resize_room now always evaluates its
# candidates (cheap -- bounded by eligible-window count) and scores them
# against the actual composition_cost of the whole resulting layout, the
# same objective Stage 1 vs Stage 2 already decides by -- so "only resize
# when it materially helps" is enforced by an honest comparison, not a
# threshold guess.)

# A resize is only taken when it beats `best_cost` by at least this
# FRACTION, not merely scores numerically lower. Added after a live
# benchmark (sequential A-F window opens, no SUPER+G involved at all)
# found the SAME existing window resized on two SEPARATE, unrelated
# new-window arrivals -- 550px wide down to 412, then down to 309, a 44%
# total cut with neither single event's own MAX_SHRINK_FRACTION cap
# looking like a runaway in isolation. Stage 3 has no memory of a window
# having already given up space for a DIFFERENT earlier arrival (each
# openwindow event is an independent decision -- see this file's own
# architecture), so a hard eligibility floor keyed on the incoming
# window's own size was tried first and rejected: it either did nothing
# (the floor's reference, new_area, varies per event and isn't a stable
# quantity to gate on) or broke a genuinely legitimate resize (a modest,
# one-time trim of an existing MEDIUM window to help a larger new one
# arrive, which needs the EXISTING window to be considered even though
# it's smaller than the incoming one). What actually distinguishes the
# two cases, measured directly: the first resize (of a not-yet-touched
# window) beat its baseline by ~8%; the second (of the SAME window,
# already smaller from the first) beat its baseline by only ~4% --
# diminishing returns from trimming something already trimmed, whether or
# not this script can remember that fact directly. A moderate required
# margin (comfortably below the genuinely-beneficial ~8-15% margins seen
# in real cases, comfortably above the ~4% seen when compounding on an
# already-shrunk window) captures this without any cross-event memory at
# all -- verified against both the repeated-resize regression and the
# original genuine-improvement case (dxrice_test_placement.py's
# TestResizeCompositionAware).
STAGE3_RESIZE_MARGIN_FRACTION = 0.05

# Bounded search, not brute force: profiled at n=20 eligible windows,
# try_resize_room's own find_free_position call (already O(n^2)-ish per
# call, since it scores every edge-crossing candidate against every other
# obstacle) was being repeated once per eligible window x up to 4 edge
# variants -- an UNBOUNDED outer factor stacked on an already-expensive
# per-call cost, measured at 3.3s wall-clock for a single new-window
# placement with 20 existing windows already open (vs. 5ms at 2). Per this
# session's own explicit performance requirement ("more computation OK for
# N<=8, bounded pruning for larger N"), only the CANDIDATE_CAP largest-by-
# area eligible windows are ever tried as a resize target when there are
# more than that many -- largest-first is the same convention
# dxrice_auto_arrange.py's own top-level sort already uses, and is a
# reasonable proxy here too: a window already smaller than most of the
# group was never a plausible "the big one in the way" candidate, and the
# margin/d3-gate checks already in this function would reject shrinking it
# for a real improvement anyway -- this never changes which resize
# actually gets chosen at realistic window counts, it only skips wasted
# work when there are many more candidates than could plausibly matter.
STAGE3_RESIZE_CANDIDATE_CAP = 8


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


def try_resize_room(new_size, eligible, fixed_obstacles, center, gap, best_cost, best_direct_distance,
                    resize_locked=frozenset()):
    """DECISION (investigated, not assumed): a live sizing audit (6
    deterministic mixed-size scenarios, see this change's own report and
    dxrice_test_placement.py's TestResizeCompositionAware) found the
    PREVIOUS version of this stage -- gated behind a fixed "new window's
    own positional cost is this many times its diagonal" trigger, and
    scored only by that same new-window-only distance -- never fired at
    all across any of the 6 scenarios, even ones where a modest resize
    measurably improved the actual composition_cost of the whole layout
    (2 large windows + 1 small one open sequentially: the trigger's
    positional check looked "fine" every time, while the real objective
    the rest of this file optimizes for was left clearly worse than it
    needed to be). This version fixes that by using the SAME "always
    compute honestly, compare, pick the winner" pattern Stage 1 vs Stage 2
    already uses (see place_new_window) instead of a threshold guess:
    every candidate resize is scored by the actual composition_cost of the
    WHOLE resulting layout (new window + every eligible window, one of
    them shrunk) plus the resize's own cost, and only returned when that
    total genuinely beats `best_cost` -- which the caller now derives from
    the SAME cost1/cost2_total values (including their own composition
    term) used to choose between Stage 1 and Stage 2, not a bare
    positional distance. The same audit also found forcing a resize can
    make things WORSE (2 large windows side by side: shrinking either
    one's height doesn't address the actual left-right spread causing the
    bad composition) -- this is exactly why the comparison has to be
    against the real objective, not assumed to help just because Stage 1/2
    already looked mediocre.

    Why an EXISTING window and never the new one: the new window's size is
    what the application itself just asked for (or what a window rule
    deliberately set for it), and nobody has seen it yet -- shrinking it
    before its first frame means the user never gets to see the size the
    app actually wanted, and "make the new window small enough to fit the
    hole that's left" is precisely the behaviour this whole stage exists
    to avoid. An existing window, by contrast, is already on screen at a
    size the user has seen and can judge, a modest trim of it is visible
    and undoable, and it is the window actually in the way. Preferring the
    incumbent to absorb the compromise also keeps the rule predictable:
    opening an app never silently changes that app, only ever its
    neighbour, and only when nothing short of that worked.

    Tries shrinking exactly ONE existing eligible window (never the new
    one, never more than one per placement) -- every OTHER eligible window
    stays at its current position/size for this pass (Stage 2 already
    covers general multi-window rearrangement; this stage's job is
    narrowly "would trimming ONE window materially help"). Every candidate
    size is bounded by both MAX_SHRINK_FRACTION of that window's own
    current size and the absolute MIN_USABLE_* floor, whichever is
    stricter. Resize cost is prominence-weighted (see prominence_weight):
    a window at or below the new window's own size costs the base rate to
    shrink, a substantially bigger/more important window costs
    progressively more per pixel, so this stage doesn't casually carve a
    chunk off whatever the biggest, most prominent app on the desktop
    happens to be just because it was geometrically in the way.

    Tries FOUR shrink variants per window -- width from the right, width
    from the left, height from the bottom, height from the top -- rather
    than assuming which edge should recede: Hyprland's own window.resize
    dispatch resizes a floating window around its CENTER (confirmed live:
    resizing in place moves the top-left too), so this function always
    computes its own explicit target top-left for whichever edge it
    intends to keep fixed, and the caller dispatches an explicit move
    alongside the resize to land exactly there -- it never relies on
    Hyprland's own resize anchor to happen to match what was scored here.

    `best_direct_distance`: the new window's own distance-to-center under
    whichever of Stage 1/Stage 2 actually won (d1 if Stage 1, d2 if Stage
    2) -- a candidate here must ALSO get the new window MEANINGFULLY
    closer to center than that, not just improve the total cost. Added
    after a live benchmark ("Case F": three same-sized windows in a row,
    a fourth same-sized window arrives) found the composition-cost
    comparison alone let a resize through that shrank an EXISTING window
    (H1) by 25% while leaving the new window at the EXACT SAME position
    it already had without any resize at all (d3 == d1 to the pixel) --
    the entire ~6% "improvement" came from reshaping the existing trio's
    own second moment, not from helping the window Stage 3 exists to
    help. None of H1/H2/H3 was oversized relative to anything either (all
    four windows were the same size) -- Stage 3's whole justification is
    "rearranging alone couldn't get the new window a usable spot," and a
    plan that doesn't move the new window's own spot at all has, by
    definition, not satisfied that justification, regardless of how the
    abstract score reads.

    resize_locked: addresses DXrice already resized and the user hasn't
    resized since (see dxrice_resize_memory.py) -- never offered as the
    window to trim. STAGE3_RESIZE_MARGIN_FRACTION slows repeated trims of
    the same window across separate arrivals but cannot prevent them, and
    it cannot see a trim SUPER+G made at all.

    Returns (target_pos, address_to_resize, (new_x, new_y), (new_w, new_h))
    or None. new_x/new_y is the resized window's own corrected top-left,
    which the caller must move it to (not just resize it) for the geometry
    that was actually scored to be what actually happens.
    """
    nw, nh = new_size
    new_area = nw * nh
    fixed_rects = [rect_for(*r) for r in fixed_obstacles]
    best_plan = None
    # See best_direct_distance's own docstring paragraph: a resize
    # candidate must get the new window meaningfully closer to center than
    # rearrangement alone already does, not just improve the aggregate
    # score. "Meaningfully" mirrors the same margin philosophy used
    # elsewhere in this file (SUPER_G_RESIZE_MARGIN_FRACTION,
    # STAGE3_RESIZE_MARGIN_FRACTION) rather than requiring a bare, fragile
    # inequality.
    direct_distance_threshold = best_direct_distance * (1.0 - STAGE3_RESIZE_MARGIN_FRACTION)
    # See STAGE3_RESIZE_MARGIN_FRACTION's own comment: a resize must beat
    # best_cost by a real margin, not just numerically, so that trimming
    # the SAME window again on a later, unrelated new-window arrival
    # (which this function has no memory of) needs a genuine improvement
    # to repeat, not just any improvement at all.
    resize_threshold = best_cost * (1.0 - STAGE3_RESIZE_MARGIN_FRACTION)

    # Bounded search, not brute force -- see STAGE3_RESIZE_CANDIDATE_CAP's
    # own comment.
    resize_candidates = eligible
    if len(eligible) > STAGE3_RESIZE_CANDIDATE_CAP:
        resize_candidates = sorted(eligible, key=lambda w: -(w["size"][0] * w["size"][1]))[:STAGE3_RESIZE_CANDIDATE_CAP]

    for w in resize_candidates:
        if w["address"] in resize_locked:
            continue
        ow, oh = w["size"]
        ox, oy = w["at"]
        other_eligible = [o for o in eligible if o["address"] != w["address"]]
        other_eligible_rects = [rect_for(o["at"][0], o["at"][1], o["size"][0], o["size"][1])
                                 for o in other_eligible]
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

        # Same "how much more prominent is this window than the one being
        # placed" scaling prominence_weight already uses for Stage 2's
        # movement cost -- see the docstring above.
        resize_prominence = prominence_weight(w["address"], {w["address"]: w}, new_area)

        for sx, sy, sw, sh, shrink_amount in variants:
            obstacles_xywh = [(r[0], r[1], r[2] - r[0], r[3] - r[1]) for r in fixed_and_others]
            obstacles_xywh.append((sx, sy, sw, sh))
            pos = find_free_position(new_size, obstacles_xywh, center, gap, layout_others=obstacles_xywh)

            # Same shape as cost1/cost2_total in place_new_window (see
            # composition_cost_components' own docstring for why the two
            # ingredients are weighted DIFFERENTLY, not the combined
            # composition_cost dampened by one shared factor): the new
            # window's own distance to center as the PRIMARY signal,
            # center-of-mass as a damped secondary term (STAGE_DECISION_
            # COMPOSITION_WEIGHT), shape/anisotropy at its own full,
            # undamped scale. An earlier version of this fix scored
            # candidates by raw composition_cost with no distance term at
            # all, which let a resize win against `best_cost` purely from a
            # scale mismatch, not a real improvement -- caught by comparing
            # actual resulting com_err/anisotropy before and after: a
            # candidate that "won" by ~230 points numerically produced a
            # change of 0.0004 in anisotropy and 0.003px in com_err. Using
            # the identical formula Stage 1/2 already use makes the
            # comparison actually fair.
            d3 = math.hypot(pos[0] + nw / 2 - center[0], pos[1] + nh / 2 - center[1])
            cand_mass = window_mass(nw, nh, new_area)
            whole_points = [(pos[0] + nw / 2, pos[1] + nh / 2, nw, nh, cand_mass),
                            (sx + sw / 2, sy + sh / 2, sw, sh, window_mass(sw, sh, new_area))]
            for o in other_eligible:
                oox, ooy = o["at"]
                oow, ooh = o["size"]
                whole_points.append((oox + oow / 2, ooy + ooh / 2, oow, ooh, window_mass(oow, ooh, new_area)))
            com_cost3, shape_cost3 = composition_cost_components(whole_points, center)
            cost = (d3 + STAGE_DECISION_COMPOSITION_WEIGHT * com_cost3 + shape_cost3
                    + RESIZE_COST_PER_PIXEL * shrink_amount * resize_prominence)
            if (cost < resize_threshold and d3 < direct_distance_threshold
                    and (best_plan is None or cost < best_plan[0])):
                best_plan = (cost, pos, w["address"], (_px(sx), _px(sy)), (int(sw), int(sh)))

    if best_plan is None:
        return None
    _, pos, addr, new_xy, size = best_plan
    return pos, addr, new_xy, size


_DEBUG = os.environ.get("DXRICE_DEBUG") == "1"


# ---- startup sizing: is a newly-mapped window suspiciously undersized? ----
#
# Some applications map at a size nobody would choose -- a main window that
# comes up at 500x350 on a 1920x1080 display is not a considered decision,
# it is a toolkit default nobody overrode. Others map small because small
# is CORRECT: a confirmation dialog, a colour picker, a utility palette.
# Guessing wrong in either direction is worse than doing nothing, so this
# deliberately only acts in the band where the evidence is one-sided, and
# leaves everything else exactly as the application asked for it.
#
# All thresholds are fractions of the actual viewport, never pixel
# constants: "too small to be a main window" means something different on a
# 4K panel than on a 1366x768 laptop, and a hardcoded 600 would be wrong on
# both.
#
# Below DIALOG_AREA_FRACTION of the viewport a window is dialog-sized and
# is never touched. An application's MAIN window is essentially never 2% of
# the screen, while dialogs very often are, so in that range "leave it
# alone" is right far more often than any enlargement would be.
STARTUP_DIALOG_AREA_FRACTION = 0.05
# Between that and this, a window is too big to be a dialog but too small
# to be a deliberate main-window size -- the only band where enlarging is
# defensible.
STARTUP_UNDERSIZED_AREA_FRACTION = 0.12
# What "comfortable" means, as a fraction of viewport area. Aspect ratio is
# always preserved -- the application chose its shape even if it did not
# meaningfully choose its size.
STARTUP_COMFORTABLE_AREA_FRACTION = 0.18
# No single dimension may exceed this fraction of the viewport as a result
# of startup sizing, so an extreme aspect ratio can't produce something
# absurdly wide or tall.
STARTUP_MAX_DIMENSION_FRACTION = 0.6


# Calibrated against real, live-observed geometry, not borrowed from
# dxrice_auto_arrange.py's unrelated SIZE_CLASS_RATIO (2.25 -- that
# constant answers "do these two windows belong to the same size class in
# a COMPOSITION", a different question, and using it here was tried
# first and PROVED wrong: the real VirtualBox "Settings" dialog (840x489)
# against its own "Manager" window (960x756) is only a 1.77x area ratio,
# comfortably under 2.25 -- the exact real case this feature exists for
# would have been missed by its own threshold.
#
# The two real numbers that matter are on opposite sides of this line:
# VirtualBox's Settings dialog vs its Manager is 1.77x (must be ABOVE the
# threshold, so it anchors); Brave's own two independent windows, opened
# from the same PID, are 1.33x (must stay BELOW it, so a second real
# browser window is never forced to anchor beside the first). 1.5 sits
# with real margin on both sides -- about 12% above the sibling-window
# ratio, about 15% below the real dialog ratio -- rather than squeezed
# against either.
FAMILY_ANCHOR_SIZE_RATIO = 1.5


def _known_pid(pid):
    return isinstance(pid, int) and pid > 0


def _find_family_anchor(new_win, siblings):
    """Is this new window a DIALOG/UTILITY of an app that's already open,
    rather than an independent window earning its own place in the
    composition -- and if so, which existing window is it a dialog OF?

    General signals only, no application names: sharing a PID covers an
    app like VirtualBox, which spawns its Settings/disk-picker/notice
    windows from the SAME process under a DIFFERENT window class ("Virtual
    Box Manager" vs "VirtualBox") -- class alone would miss that family
    relationship entirely -- and the common case of a toolkit dialog with
    its parent's app-id, which is in-process too. Class only decides when
    a PID is unknown: with both PIDs known, a same-class window from
    another process is another instance of the app, not a dialog.
    
    Requiring the candidate to be meaningfully SMALLER (FAMILY_ANCHOR_
    SIZE_RATIO) than the window it would anchor to is what keeps this from
    firing on a second, equally-large, genuinely independent window of the
    same app -- Brave's own separate browser windows all share one PID,
    and forcing them to stack next to each other would be exactly wrong.
    A dialog reads as smaller than the window that spawned it; a sibling
    window does not.

    Among multiple qualifying candidates, the one most recently focused
    (Hyprland's own focusHistoryID, 0 = currently focused) wins -- that's
    the window the user was actually looking at when this one popped up,
    which is a better signal than "the biggest one" when an app has
    several same-family windows open already. Falls back to the largest
    when focus history is unavailable or tied.

    Returns the anchor window dict, or None if this doesn't look like a
    dialog of anything already open (the normal composition placement
    handles it in that case, unchanged)."""
    new_w, new_h = new_win.get("size", (0, 0))
    if new_w <= 0 or new_h <= 0:
        return None
    new_area = new_w * new_h
    new_pid = new_win.get("pid")
    new_class = (new_win.get("class") or new_win.get("initialClass") or "").lower()

    candidates = []
    for sib in siblings:
        if sib.get("fullscreen"):
            continue  # fixed furniture, not a family relationship
        sib_pid = sib.get("pid")
        if _known_pid(new_pid) and _known_pid(sib_pid):
            # A dialog lives in its parent's process. Same class in a
            # DIFFERENT process is another instance of the app -- a second,
            # smaller terminal is a window of its own, not the first one's
            # dialog (measured on the nested compositor: kitty windows of
            # different sizes anchored to each other and walked the whole
            # composition off one side of the screen). Cross-process dialogs
            # of XWayland apps are still found, by WM_TRANSIENT_FOR.
            same_family = sib_pid == new_pid
        else:
            same_family = bool(new_class) and (sib.get("class") or sib.get("initialClass") or "").lower() == new_class
        if not same_family:
            continue
        sw, sh = sib.get("size", (0, 0))
        if sw <= 0 or sh <= 0:
            continue
        if (sw * sh) < new_area * FAMILY_ANCHOR_SIZE_RATIO:
            continue  # not meaningfully bigger -- a sibling, not a parent
        candidates.append(sib)

    if not candidates:
        return None
    return min(candidates, key=lambda w: (w.get("focusHistoryID", 10**9), -(w["size"][0] * w["size"][1])))


def _place_beside_anchor(anchor, new_w, new_h, obstacle_rects, gap, center):
    """The best free position flush against one of `anchor`'s four edges,
    centered on that edge -- or None if all four are blocked by something
    else already on the workspace.

    Deliberately does not clamp to the monitor or fall back to a
    composition-aware search of its own: if the anchor itself currently
    sits off-screen (a real, observed state on this infinite canvas -- see
    the session note on desktop-wide drift), the dialog belongs right
    beside it wherever that is, not wherever the viewport happens to be
    looking. A press of SUPER+G brings the anchor and its now genuinely-
    adjacent dialog back into view TOGETHER, as one connected shape,
    which composition-aware placement could not guarantee if it ignored
    the family relationship and reasoned about the dialog independently.
    """
    ax0, ay0, ax1, ay1 = rect_for(anchor["at"][0], anchor["at"][1], anchor["size"][0], anchor["size"][1])
    acx, acy = (ax0 + ax1) / 2, (ay0 + ay1) / 2

    candidates = [
        (ax1 + gap, acy - new_h / 2),              # right of anchor, vertically centered
        (ax0 - new_w - gap, acy - new_h / 2),      # left of anchor
        (acx - new_w / 2, ay1 + gap),              # below anchor, horizontally centered
        (acx - new_w / 2, ay0 - new_h - gap),      # above anchor
    ]

    def free(x, y):
        cand = (x, y, x + new_w, y + new_h)
        inflated = (cand[0] - gap, cand[1] - gap, cand[2] + gap, cand[3] + gap)
        return not any(overlaps(inflated, r) for r in obstacle_rects)

    valid = [(x, y) for x, y in candidates if free(x, y)]
    if not valid:
        return None
    return min(valid, key=lambda p: math.hypot(p[0] + new_w / 2 - center[0], p[1] + new_h / 2 - center[1]))


def comfortable_startup_size(win, siblings, viewport_w, viewport_h):
    """The size a newly-mapped window should actually be placed at.

    Returns the window's own current size unchanged in every case except
    the narrow one this exists for: a window with no same-class window
    already open, sized into the "too big for a dialog, too small to be
    deliberate" band, which gets scaled up along its own aspect ratio to a
    comfortable area.

    `siblings`: the other windows already on this workspace. A window whose
    class is ALREADY on screen is treated as a secondary window of a
    running application -- a dialog, a preferences panel, a file chooser --
    and is never resized. That single signal does most of the work here and
    needs no per-application knowledge: toolkits give a dialog the same
    app-id as the application that spawned it, so "something of this class
    is already running" is a strong, general, and cheap indicator that this
    window is subordinate to it rather than a main window in its own right.
    """
    w, h = win.get("size", (0, 0))[0], win.get("size", (0, 0))[1]
    if w <= 0 or h <= 0:
        return w, h
    viewport_area = max(1.0, float(viewport_w) * float(viewport_h))
    area_fraction = (w * h) / viewport_area

    if area_fraction >= STARTUP_UNDERSIZED_AREA_FRACTION:
        return w, h                      # already a reasonable size
    if area_fraction < STARTUP_DIALOG_AREA_FRACTION:
        return w, h                      # dialog-sized: small is the point

    own_class = (win.get("class") or win.get("initialClass") or "").lower()
    if own_class:
        for other in siblings:
            other_class = (other.get("class") or other.get("initialClass") or "").lower()
            if other_class == own_class:
                return w, h              # secondary window of a running app

    scale = math.sqrt((STARTUP_COMFORTABLE_AREA_FRACTION * viewport_area) / (w * h))
    if scale <= 1.0:
        return w, h
    max_w = viewport_w * STARTUP_MAX_DIMENSION_FRACTION
    max_h = viewport_h * STARTUP_MAX_DIMENSION_FRACTION
    scale = min(scale, max_w / w if w > 0 else scale, max_h / h if h > 0 else scale)
    if scale <= 1.0:
        return w, h
    return int(round(w * scale)), int(round(h * scale))


def _settle_moves(expected, timeout=2.0, poll=0.01):
    """Block until every address in `expected` reports the position (and,
    if given, size) that was just dispatched, or `timeout` elapses.

    Every move/resize dispatch in this file is fire-and-forget
    (want_reply=False) -- the call returns the instant the command is SENT,
    not once Hyprland has actually applied it. If the next buffered
    openwindow event's place_new_window() call reads `hyprctl clients`
    before that happens, it sees the just-moved window(s) still at their
    PRE-move position/size, computes its own placement against a reality
    that's about to change out from under it, and the two results can
    genuinely overlap on screen even though each decision was individually
    correct against the (stale) state it saw. This was reproduced live: a
    22-window rapid burst under real system load produced 30 confirmed
    pixel-overlapping pairs, all traced to exactly this race -- a prior
    flat `time.sleep(0.03)` here was a guess at how long Hyprland needs and
    wasn't always enough once the compositor was under load from the burst
    itself.

    The first version of this function capped `timeout` at 0.25s, reasoning
    that a quarter second was generous for a single window move. Live
    testing under the SAME 22-window burst proved that guess wrong too: a
    Stage-3 resize dispatch on an existing window genuinely took longer
    than 250ms to land while the compositor was busy mapping 22 simultaneous
    terminal processes, the timeout fired, place_new_window returned with
    the position still unconfirmed, and the very next buffered event read
    that stale position -- reopening the exact same race, just rarer
    (30 overlaps dropped to 17, not to 0). Zero overlap is the actual
    requirement, not "fewer overlaps," so the timeout is a generous ceiling
    meant only to prevent a genuinely stuck/closed window from hanging the
    listener forever -- not a guess at "how long a move should take." It
    costs nothing in the overwhelmingly common case (opening one window at
    a time confirms within a poll or two, well under 20ms) and is only ever
    spent when the compositor is demonstrably still catching up, which is
    exactly when waiting the extra time is correct. Confirmed live: the
    same burst produced zero true overlaps once this was raised to 2s.
    """
    remaining = dict(expected)
    deadline = time.time() + timeout
    while remaining and time.time() < deadline:
        clients = hyprctl_json(["clients"])
        if clients:
            by_addr = {w["address"]: w for w in clients}
            for addr in list(remaining):
                w = by_addr.get(addr)
                if not w:
                    continue
                want = remaining[addr]
                at_ok = "at" not in want or tuple(w.get("at", ())) == want["at"]
                size_ok = "size" not in want or tuple(w.get("size", ())) == want["size"]
                if at_ok and size_ok:
                    del remaining[addr]
        if remaining:
            time.sleep(poll)
    if remaining and _DEBUG:
        print(f"DEBUG _settle_moves timed out waiting for: {remaining}", file=sys.stderr, flush=True)


def place_new_window(address, workspace_id, gap):
    # The window may not be immediately queryable the instant openwindow
    # fires -- give Hyprland a couple of ticks to finish mapping it.
    #
    # This used to be a fixed "try 5 times, 30ms apart" budget (150ms
    # total). Live testing under a 22-window rapid burst (the same test
    # that found the _settle_moves race, see its docstring) proved that
    # budget insufficient too: under real IPC load from that many
    # simultaneous window maps, `hyprctl clients` itself took longer than
    # 150ms to return this address at all, `new_win` stayed None, and
    # place_new_window returned WITHOUT EVER PLACING the window -- it was
    # left wherever Hyprland's own default floating-spawn position put it.
    # Several such skipped windows landing at the same compositor default
    # is exactly what produced the tight mutual-overlap cluster seen live
    # (BURST18/19/20/21, and a couple of legitimately-placed neighbors
    # whose own dispatches likely suffered the same slow-IPC delay).
    # Same fix as _settle_moves and for the same reason: a deadline is a
    # correctness bound, not a guessed duration, so make it generous. Costs
    # nothing in the common case (one window opening finds itself in the
    # very first or second poll) and is only ever spent when the
    # compositor is demonstrably still catching up -- exactly when it's
    # worth waiting rather than silently giving up on placing the window.
    clients = None
    new_win = None
    deadline = time.time() + 2.0
    while time.time() < deadline:
        clients = hyprctl_json(["clients"])
        if clients:
            new_win = find_window(clients, address)
            if new_win:
                break
        time.sleep(0.03)

    # Existing but not yet SETTLED is a different problem from not existing
    # yet, and it has a real, measured consequence. Some toolkits map at one
    # size and immediately resize to another (zenity maps 320x246 and settles
    # to 300x226). Placing against the transient size puts the window at the
    # correct gap for a size it is about to stop being -- and because
    # Hyprland resizes a floating window around its CENTRE (confirmed live,
    # see try_resize_room), the app's own shrink then walks the window half
    # the difference away from the neighbour it was just placed against.
    # Reproduced exactly and deterministically: a 20px self-shrink left a
    # 15px gap where 5px was configured, identically on every trial.
    # So: wait for two consecutive reads to agree on the size before
    # committing to a placement. Costs one short interval in the common case
    # (a window whose size is already stable agrees immediately), is capped
    # so a pathologically animated window can't stall the listener, and
    # stays comfortably inside the window's own map-to-visible latency --
    # measured at ~93ms here, against which this is invisible.
    if new_win:
        stable_since = tuple(new_win.get("size", ()))
        for _ in range(6):
            time.sleep(0.012)
            clients = hyprctl_json(["clients"]) or clients
            probe = find_window(clients, address)
            if not probe:
                break
            size_now = tuple(probe.get("size", ()))
            new_win = probe
            if size_now == stable_since:
                break
            stable_since = size_now
    if _DEBUG:
        print(f"DEBUG t={time.time():.3f} address={address} found={new_win is not None} floating={new_win.get('floating') if new_win else None} poll_elapsed={time.time()-(deadline-2.0):.3f}", file=sys.stderr, flush=True)
    # (poll_elapsed above is relative to this function's 2.0s existence-poll deadline)
    if not new_win:
        return "gone"
    # Before anything else: is this an application window at all? A
    # tooltip, a context menu or a browser's link/tab hover card opened by
    # an XWayland app arrives here exactly like a real window (see
    # dxrice_window_class.py for the evidence) -- it must be left where the
    # app put it, and it must never count as part of anyone's layout.
    kinds, x11 = classify_clients(clients)
    mx0, my0, mx1, my1 = get_monitor_bounds()
    # An XWayland window the X server couldn't be asked about: big ones are
    # still placed; a small one may well be a popup, and moving a popup
    # away from what it points at is the bug this exists for. The same rule
    # SUPER+G applies (dxrice_window_class.settle_unknown).
    dxrice_window_class.settle_unknown(kinds, clients, (mx1 - mx0) * (my1 - my0))
    kind = kinds.get(address, dxrice_window_class.NORMAL)
    if not dxrice_window_class.is_arrangeable(kind) or new_win.get("pinned"):
        if _DEBUG:
            print(f"DEBUG address={address} ignored: kind={kind} pinned={new_win.get('pinned')}",
                  file=sys.stderr, flush=True)
        return "ignored"

    if not new_win.get("floating"):
        # Tiled right now. It may become floating later (see main()'s
        # changefloatingmode handling) -- say so rather than silently
        # dropping it forever.
        return "not-floating"

    # Hyprland's own real fullscreen state (0 = normal, 2 = fullscreen,
    # confirmed live) -- a fullscreened/maximized window has no sensible
    # "beside" position and must be left exactly where Hyprland put it.
    # Previously this was guessed from size (>=90% of monitor area), which
    # false-positived on any large-but-intentionally-sized normal window
    # and false-negatived on a fullscreen window on a small/scaled output.
    if new_win.get("fullscreen", 0) != 0:
        if _DEBUG:
            print(f"DEBUG address={address} skipped: fullscreen={new_win.get('fullscreen')}", file=sys.stderr, flush=True)
        return "fullscreen"

    eligible, fixed = dxrice_window_class.partition(clients, workspace_id, kinds, exclude=address)
    same_ws = eligible + fixed
    if _DEBUG:
        print(f"DEBUG eligible={len(eligible)} fixed={len(fixed)} workspace_id={workspace_id}",
              file=sys.stderr, flush=True)

    # Startup sizing happens BEFORE any placement maths, and the placement
    # then runs against whatever size the window actually ended up at --
    # never against the size it was asked to become. Same reasoning as the
    # settle loop above: a position computed for a size the window does not
    # have is a gap or an overlap on screen, and the client is entitled to
    # refuse (size increments, a minimum size). So dispatch, wait for the
    # size to stop moving, re-read, and carry on with the truth.
    # The X server's word on a dialog's parent, read now: it is keyed by
    # the geometry the X server reported, i.e. before anything below moves
    # or resizes the window.
    parent_geom = dxrice_window_class.x11_parent_geometry(new_win, x11, _scales_for_matching())
    # A window the X server says is a dialog is small on purpose.
    if kind == dxrice_window_class.DIALOG:
        want_w, want_h = new_win["size"][0], new_win["size"][1]
    else:
        want_w, want_h = comfortable_startup_size(new_win, same_ws, mx1 - mx0, my1 - my0)
    if (want_w, want_h) != (new_win["size"][0], new_win["size"][1]):
        if _DEBUG:
            print(f"DEBUG address={address} startup-resize {new_win['size']} -> {(want_w, want_h)}",
                  file=sys.stderr, flush=True)
        dispatch_async(resize_window_exact_lua(want_w, want_h, address))
        stable_since = None
        for _ in range(8):
            time.sleep(0.015)
            clients = hyprctl_json(["clients"]) or clients
            probe = find_window(clients, address)
            if not probe:
                return "gone"
            new_win = probe
            size_now = tuple(probe.get("size", ()))
            if size_now == stable_since:
                break
            stable_since = size_now
        eligible, fixed = dxrice_window_class.partition(clients, workspace_id, kinds, exclude=address)
        same_ws = eligible + fixed

    new_w, new_h = new_win["size"][0], new_win["size"][1]
    seen_at = tuple(new_win["at"])

    obstacles = [(w["at"][0], w["at"][1], w["size"][0], w["size"][1]) for w in same_ws]
    center = ((mx0 + mx1) / 2, (my0 + my1) / 2)

    # A dialog/utility of an app that's already open (VirtualBox's
    # Settings, a disk-image picker, a details popup) goes right beside
    # the window it belongs to, not into the general composition -- see
    # _find_family_anchor's own docstring for why PID/class family
    # membership plus a size gap is what identifies this, with no
    # application names involved. For an XWayland dialog the X server can
    # name the parent outright (WM_TRANSIENT_FOR), which beats any guess.
    target = None
    family_anchor = None
    if parent_geom:
        scales = _scales_for_matching()
        family_anchor = next((w for w in same_ws if dxrice_window_class.same_window(
            parent_geom, (w["at"][0], w["at"][1], w["size"][0], w["size"][1]), scales)), None)
    if family_anchor is None:
        family_anchor = _find_family_anchor(new_win, same_ws)
    if family_anchor is not None:
        # beside its parent at the composition spacing, like any neighbour
        # in the composition (see dxrice_spiral.pair_spacing)
        import dxrice_spiral
        spacing = dxrice_spiral.pair_spacing(new_w * new_h, family_anchor["size"][0] * family_anchor["size"][1],
                                             dxrice_spiral.read_spacing())
        target = _place_beside_anchor(family_anchor, new_w, new_h,
                                      [rect_for(*o) for o in obstacles], spacing, center)
        if _DEBUG and target is not None:
            print(f"DEBUG address={address} placed beside family anchor "
                  f"{family_anchor.get('address')} ({family_anchor.get('title','')[:30]!r}) at {target}",
                  file=sys.stderr, flush=True)
        # All four sides of the anchor blocked: join the composition below
        # rather than leave it wherever the compositor mapped it.

    if target is None:
        # Join the cloud: SUPER+G's own per-window step, every existing
        # window held where it is (see dxrice_auto_arrange.join_composition).
        # Composed with what's in view; everything is an obstacle.
        import dxrice_auto_arrange
        # the composition it joins: visible application windows, not dialogs
        # attached to a parent (those stay obstacles)
        attached = dxrice_window_class.attached_children(clients, kinds, x11, _scales_for_matching()) if x11 else {}
        # The composition it joins: every application window of the
        # workspace (not dialogs attached to a parent -- those stay
        # obstacles), in creation order, which is how the spiral reads its
        # arm (dxrice_spiral.next_rect: the first is the anchor, the last
        # the tip) -- including the outer windows that have grown past the
        # screen edge, or the next window would lose track of the arm.
        # Only when none of it is on screen (the user panned away) does a
        # new window start a new anchor at the centre instead of being
        # pulled off screen to join it.
        members = [(e["at"][0], e["at"][1], e["size"][0], e["size"][1])
                   for e in sorted(eligible, key=_creation_key) if e["address"] not in attached]
        on_screen = any(x < mx1 and x + w > mx0 and y < my1 and y + h > my0 for x, y, w, h in members)
        visible = members if on_screen else []
        target = dxrice_auto_arrange.join_composition((new_w, new_h), visible, obstacles,
                                                     (mx0, my0, mx1, my1), gap)
        if _DEBUG:
            print(f"DEBUG address={address} joins the composition at {target} "
                  f"(composed with {len(visible)} visible of {len(eligible)}, {len(fixed)} fixed)",
                  file=sys.stderr, flush=True)

    # Last look before moving it: if the window is gone, or something
    # other than the compositor's initial mapping moved it in the meantime
    # (the user already grabbed it, or the app positioned itself), the
    # user's or app's choice stands.
    latest = find_window(hyprctl_json(["clients"]) or [], address)
    if not latest:
        return "gone"
    if tuple(latest["at"]) != seen_at:
        if _DEBUG:
            print(f"DEBUG address={address} moved by someone else ({seen_at} -> {latest['at']}) -- left alone",
                  file=sys.stderr, flush=True)
        return "user-moved"

    tx, ty = _px(target[0]), _px(target[1])
    if (tx, ty) == tuple(latest["at"]):
        return "placed"  # already exactly there (a first window mapped centred)
    dispatch_async(move_window_exact_lua(tx, ty, address))
    _settle_moves({address: {"at": (tx, ty)}})
    return "placed"


def _creation_key(client):
    """Creation order of a client: Hyprland's stableId (assigned once, in
    order, when a window is created), else its place in the client list
    (which Hyprland keeps in creation order) -- sorted() is stable."""
    sid = client.get("stableId")
    try:
        return int(str(sid), 16) if sid is not None else 0
    except ValueError:
        return 0


def _scales_for_matching():
    """Monitor scale factors (see dxrice_window_class.same_window); empty
    when Hyprland can't be asked, which leaves exact matching only."""
    try:
        return dxrice_window_class.monitor_scales(hyprctl_json(["monitors"]))
    except Exception:
        return []


def _classify_with_scales(clients):
    scales = _scales_for_matching() if any(c.get("xwayland") for c in clients) else []
    return dxrice_window_class.classify_all(clients, scales=scales)


# The classification seam: tests replace this to say what the X server
# would answer, without an X server.
classify_clients = _classify_with_scales


# theme.json key for Settings > Experience > "Automatic window placement".
# Missing means on: new windows have always been auto-placed, so an existing
# theme.json that predates the switch keeps doing exactly that.
AUTO_PLACE_KEY = "auto_place_windows"


class ThemeSettings:
    """The two theme.json values this listener needs -- the window gap and
    the on/off switch -- re-read only when the file actually changes (one
    stat() per event otherwise), so turning the switch off in Settings
    takes effect on the very next window without restarting anything.

    A file that is missing, mid-write or unparsable keeps the last values
    that were read (the defaults, before any): a half-written theme.json
    must neither switch placement off nor reset the gap."""

    def __init__(self, path=None):
        self.path = path or os.path.join(dxrice_xdg.config_dir(), "theme.json")
        self._stamp = None
        self.gap = DEFAULT_GAP
        self.enabled = True

    def refresh(self):
        try:
            st = os.stat(self.path)
        except OSError:
            return self
        stamp = (st.st_mtime_ns, st.st_size, st.st_ino)
        if stamp == self._stamp:
            return self
        try:
            with open(self.path) as f:
                data = json.load(f)
            gap = int(data.get("hypr_gaps_in", DEFAULT_GAP))
        except (OSError, ValueError, TypeError, AttributeError):
            return self  # not recorded: retried on the next event
        self._stamp = stamp
        self.gap = gap
        self.enabled = data.get(AUTO_PLACE_KEY, True) is not False
        return self


class PlacementListener:
    """What happens for each line of Hyprland's event socket.

    Placement is driven by exactly one thing: `openwindow>>`, i.e. a window
    being mapped. Focus changes (`activewindow>>` -- with follow_mouse that
    is every time the pointer crosses a window), title changes (a browser
    retitling itself as a link is hovered), `movewindow>>`, workspace
    switches and everything else are ignored outright, so neither the
    pointer nor this listener's own moves can ever start a placement. What
    `openwindow>>` itself can carry that isn't an application window (an
    XWayland tooltip/menu/hover card) is filtered by place_new_window.

    Each window is handled at most once per mapping: a repeated
    `openwindow>>` for an address already handled is ignored until that
    window's `closewindow>>`. The one exception is a window mapped
    fullscreen or tiled, which can't be placed yet: it is remembered and
    retried when a fullscreen/floating state change is reported, and placed
    at most once when it becomes an ordinary floating window."""

    def __init__(self, settings=None, place=None):
        self.settings = settings or ThemeSettings()
        self._place = place or place_new_window
        self.handled = set()
        self.deferred = {}  # {address: workspace_id}

    def _attempt(self, addr, ws_id, what="placement"):
        try:
            return self._place(addr, ws_id, self.settings.gap)
        except Exception as e:
            # One window failing to place must never take the listener
            # down, but silently swallowing it is how this went unnoticed
            # before -- say so.
            print(f"{what} failed for {addr} on ws {ws_id}: {type(e).__name__}: {e}",
                  file=sys.stderr, flush=True)
            return None

    def handle_line(self, line):
        """Returns what was done, for logging and tests."""
        if line.startswith("openwindow>>"):
            parts = line[len("openwindow>>"):].split(",", 3)
            if len(parts) < 2:
                return None
            addr = "0x" + parts[0]
            try:
                ws_id = int(parts[1])
            except ValueError:
                return None
            if addr in self.handled or addr in self.deferred:
                return "duplicate"
            if not self.settings.refresh().enabled:
                self.handled.add(addr)  # opened while off: not placed later either
                return "disabled"
            status = self._attempt(addr, ws_id)
            if status in ("fullscreen", "not-floating"):
                self.deferred[addr] = ws_id
            else:
                self.handled.add(addr)
            return status
        if line.startswith("closewindow>>"):
            addr = "0x" + line[len("closewindow>>"):].strip()
            self.handled.discard(addr)
            self.deferred.pop(addr, None)
            return "closed"
        if line.startswith("fullscreen>>") or line.startswith("changefloatingmode>>"):
            # An application that MAPS fullscreen or tiled and only later
            # becomes an ordinary floating window used to be lost: it was
            # judged once, at the one moment it was guaranteed to be
            # ineligible. That is exactly why a game launcher like Sober --
            # which comes up fullscreen and is later dropped to a floating
            # window -- never got placed. fullscreen>> carries no address,
            # so the deferred set is re-checked rather than the payload
            # trusted. This cannot feed back on itself: placement only moves
            # windows, it never changes fullscreen or floating state.
            if not self.deferred:
                return None
            if not self.settings.refresh().enabled:
                self.handled.update(self.deferred)
                self.deferred.clear()
                return "disabled"
            for addr, ws_id in list(self.deferred.items()):
                status = self._attempt(addr, ws_id, what="deferred placement")
                if status is not None and status not in ("fullscreen", "not-floating"):
                    self.deferred.pop(addr, None)
                    self.handled.add(addr)
            return "rechecked"
        return None


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

    settings = ThemeSettings()
    while True:
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                s.connect(path)
                # Fresh state on every (re)connect, not just once at process
                # start: socket2 only ever drops when Hyprland itself
                # restarts/crashes, at which point every window address this
                # process knew about is gone along with it. A partial line
                # held over from the dead connection would corrupt the first
                # real event's parse, and stale deferred entries would each
                # spend place_new_window's full 2s existence poll concluding
                # "gone" right when the restarted desktop needs this working.
                listener = PlacementListener(settings)
                buf = ""
                while True:
                    chunk = s.recv(4096)
                    if not chunk:
                        break
                    buf += chunk.decode(errors="replace")
                    while "\n" in buf:
                        line, buf = buf.split("\n", 1)
                        if _DEBUG and line:
                            print(f"DEBUG t={time.time():.3f} line={line!r}", file=sys.stderr, flush=True)
                        listener.handle_line(line)
        except (ConnectionRefusedError, FileNotFoundError, OSError) as e:
            print(f"socket2 unavailable ({type(e).__name__}: {e}) -- retrying in 1s",
                  file=sys.stderr, flush=True)
            time.sleep(1)


if __name__ == "__main__":
    main()
