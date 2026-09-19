#!/usr/bin/env python3
"""Auto-places newly opened windows beside an existing one instead of
letting them spawn stacked on top of each other -- every window on this
rice is floating (hyprland.lua's "float-everything" rule), so without this,
every new app opens at Hyprland's own default floating position and
overlaps whatever's already there.

COMPOSITION MODEL: every candidate position is scored primarily by
composition_cost -- a GLOBAL measure of whether the whole set of windows
(existing plus the one being placed) reads as a balanced cluster around the
viewport center, not by how close any single window's own center is to
that point. The distinction matters: individual-distance-to-center is what
originally made new windows pile onto whichever axis already had the
shortest remaining path there (a vertical/horizontal stack minimizes that
distance just as well as it minimizes bounding-box growth, since both are
really the same rectangle-packing objective wearing different names).
composition_cost instead measures the mass-weighted center of the whole
group (so no single window is rewarded merely for personally sitting near
center) and how concentrated that mass is along one angular axis through
it (so a straight run of windows costs more as a THIRD, FOURTH, etc. one
joins it, however that line happens to be oriented -- never by comparing
against a hardcoded compass direction). See composition_cost's own
docstring for the full mechanics. Local terms (composition_penalty's
sliver/dead-gap/alignment checks, and EXPANSION_WEIGHT's bbox-growth
tiebreak) remain and stay genuinely secondary -- they decide between
candidates the global term is otherwise indifferent between, they don't
override it.

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


# Pixel-equivalent scale for the angular-concentration penalty. Empirically
# tuned, not just reasoned: an initial value comparable to SLIVER_PENALTY_MAX
# (a few hundred) was measured (via dxrice_test_placement.py's
# TestRadialComposition* cases, both directly instrumented and via the live
# desktop) to be reliably beaten by MOVEMENT_WEIGHT/COMPACTNESS_WEIGHT's
# realistic swings whenever breaking a stack requires a genuinely large
# geometric jump -- the composition term correctly PREFERRED the
# better-distributed candidate in every case checked, just not by enough
# margin to survive the real movement cost of reaching it. Raised until it
# reliably won that trade in the adversarial stacking tests without
# overriding a genuinely necessary edge join (verified by the same test
# suite still passing the sliver/alignment/gap-preservation cases).
ANGULAR_PENALTY_SCALE = 2000.0

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
    """weighted_angles: [(angle_radians, weight), ...] for every window
    with a meaningfully-defined direction from the viewport center (a
    window sitting essentially AT the center has no stable angle and is
    excluded by the caller -- its mass still counts via the center-of-mass
    term instead).

    Returns (R, n_eff). R in [0, 1] is the mass-weighted mean resultant
    length of DOUBLED angles -- the standard directional-statistics trick
    for axial (line-like) data, where a window directly above center and
    one directly below center both represent "on the vertical axis" rather
    than being seen as opposite/cancelling directions. R near 1 means the
    mass is concentrated on a single line through the center (a vertical
    or horizontal stack, or any other straight run, in ANY orientation);
    R near 0 means the mass is spread across multiple distinct directions
    -- a plus/cross or X-shaped cluster scores R=0, a straight stack scores
    R=1, regardless of which absolute compass direction that line happens
    to run in. Nothing here ever tests whether an angle equals 0/90/180/
    270 -- only whether the whole set of angles clusters onto ANY one line
    -- which is the "no hardcoded preferred angles" requirement.

    n_eff is the Kish effective count of the angle-bearing weights: with
    exactly 2 windows, ANY two points are trivially "on a line" (R is
    always 1 for n=2 regardless of the actual angle between them), which
    would wrongly flag a perfectly normal side-by-side pair as a bad stack.
    composition_cost scales the penalty by a confidence term derived from
    n_eff so it contributes ~0 at n=2 and grows only as a THIRD, FOURTH,
    etc. window joins the same line -- that's when "stacking" becomes an
    actual, avoidable pattern rather than an unavoidable property of any
    two points.
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


def mass_center(weighted_points):
    """weighted_points: [(cx, cy, mass), ...]. Returns (com_x, com_y), or
    None if there's no mass at all (empty list)."""
    total_w = sum(w for _, _, w in weighted_points)
    if total_w <= 0:
        return None
    com_x = sum(cx * w for cx, cy, w in weighted_points) / total_w
    com_y = sum(cy * w for cx, cy, w in weighted_points) / total_w
    return (com_x, com_y)


def composition_cost(weighted_points, viewport_center, angle_eps=6.0):
    """The GLOBAL (whole-cluster) composition term -- see the module
    comment above for why this exists. `weighted_points`: [(cx, cy, mass),
    ...] for EVERY window in the composition, including whatever candidate
    is being scored (the caller assembles this list fresh per candidate,
    since the candidate's own point changes each time). Never includes
    fixed/fullscreen obstacles -- those are furniture the composition
    routes around, not mass it's trying to balance, same convention
    `layout_others` already uses for the local terms.

    Two components, both pixel-equivalent and summed directly:

      - center-of-mass distance: how far the mass-weighted average
        position sits from viewport_center. With one window this is
        exactly that window's own distance to center (the old per-window
        term, preserved as a special case); with several, it's the
        aggregate's distance, so no single window is rewarded merely for
        personally sitting close to center.
      - angular concentration: _axial_concentration's R, scaled by how
        many effectively-distinct masses are actually contributing (so 2
        windows -- always "a line" by construction -- cost nothing; a
        THIRD or later window joining the same line costs progressively
        more).

    `angle_eps` (pixels): a window whose center is closer than this to
    viewport_center has no stable angle (atan2 near the origin is noise)
    and is excluded from the angular term -- it still counts fully in the
    center-of-mass term, which is the right place for "something is
    already sitting exactly at the middle" to be represented.
    """
    if not weighted_points:
        return 0.0
    vx, vy = viewport_center
    com = mass_center(weighted_points)
    if com is None:
        return 0.0
    center_of_mass_cost = math.hypot(com[0] - vx, com[1] - vy)

    weighted_angles = []
    for cx, cy, w in weighted_points:
        dx, dy = cx - vx, cy - vy
        if math.hypot(dx, dy) < angle_eps:
            continue
        weighted_angles.append((math.atan2(dy, dx), w))

    R, n_eff = _axial_concentration(weighted_angles)
    # (n_eff - 2) / (n_eff - 1): exactly 0 at n_eff==2 (any 2 points are
    # trivially "a line," never penalized -- see _axial_concentration's
    # docstring), then ramps up steeply so a genuine THIRD point joining an
    # existing pair on the same axis is already a strong signal (0.5 at
    # n_eff==3) rather than a faint one -- empirically necessary: a gentler
    # ramp left the angular term too weak to outweigh local edge-quality
    # rewards (a clean full-edge join) for the window that actually turns a
    # pair into a stack, which is the exact moment this term needs to act.
    confidence = max(0.0, (n_eff - 2.0) / (n_eff - 1.0)) if n_eff > 1 else 0.0
    angular_cost = ANGULAR_PENALTY_SCALE * R * confidence

    return CENTER_OF_MASS_WEIGHT * center_of_mass_cost + angular_cost


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
    other_points = [(ox + ow / 2, oy + oh / 2, window_mass(ow, oh, reference_area))
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
        total = composition_cost(other_points + [(px, py, cand_mass)], center)
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
    other_points = [(ox + ow / 2, oy + oh / 2, window_mass(ow, oh, reference_area))
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
            total += composition_cost(other_points + [(px, py, cand_mass)], viewport_center)
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
    # One reference area for the WHOLE Stage 2 decision, derived from the
    # actual new window being placed (not whichever eligible window happens
    # to be getting relocated in a given cascade round) -- every mass
    # comparison in this pass needs the same yardstick, or "how prominent
    # is window X" would mean something different depending on which call
    # computed it.
    reference_area = new_size[0] * new_size[1]
    eligible_rects = [(w["at"][0], w["at"][1], w["size"][0], w["size"][1]) for w in eligible]
    target_pos = find_free_position(new_size, fixed_obstacles, center, gap,
                                     layout_others=eligible_rects, reference_area=reference_area)
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

    new_area = new_w * new_h

    # Stage 1: best position without moving anything else.
    pos1 = find_free_position((new_w, new_h), others, center, gap,
                               viewport=(mx0, my0, mx1, my1), layout_others=layout_others,
                               reference_area=new_area)
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
        total_movement = sum(
            math.hypot(nx - orig_at[addr][0], ny - orig_at[addr][1])
            * prominence_weight(addr, eligible_by_addr, new_area)
            for addr, (nx, ny) in moved.items()
        )
        # Stage 1 vs Stage 2 keeps the NEW window's own distance to center
        # (d1/d2) as the primary term -- NOT the full mass-weighted
        # composition_cost of the whole resulting layout. That was tried
        # first and caused a real regression: when a small existing window
        # happens to already sit near center, averaging its position in
        # with a much larger new window's position pulls the WEIGHTED
        # AVERAGE artificially close to center even while the large,
        # visually-dominant new window itself sits meaningfully off to one
        # side -- measured live, a 1400x900 new window landed 517px off
        # center, flush against a tiny 220x140 neighbor, because the
        # average of "huge window far off" and "tiny window at center"
        # scored better than actually evicting the tiny one. The candidate
        # SEARCH within each stage (find_free_position, already
        # composition-aware) is unaffected by this -- only the coarser
        # "is it worth the movement cost to switch plans" decision needed
        # this fix. Composition still influences the choice, just as a
        # secondary term, matching the same "primary distance/movement,
        # secondary composition" shape used everywhere else in this file
        # (see find_least_disruptive_position).
        pos1_mass = window_mass(new_w, new_h, new_area)
        stage1_points = [(ox + ow / 2, oy + oh / 2, window_mass(ow, oh, new_area))
                          for ox, oy, ow, oh in layout_others]
        stage1_points.append((pos1[0] + new_w / 2, pos1[1] + new_h / 2, pos1_mass))
        comp_cost1 = composition_cost(stage1_points, center)

        stage2_points = []
        for w in eligible:
            addr = w["address"]
            ow, oh = w["size"]
            if addr in moved:
                mx, my = moved[addr]
                stage2_points.append((mx + ow / 2, my + oh / 2, window_mass(ow, oh, new_area)))
            else:
                ox, oy = w["at"]
                stage2_points.append((ox + ow / 2, oy + oh / 2, window_mass(ow, oh, new_area)))
        stage2_points.append((pos2[0] + new_w / 2, pos2[1] + new_h / 2, pos1_mass))
        comp_cost2 = composition_cost(stage2_points, center)

        cost1 = d1 + STAGE_DECISION_COMPOSITION_WEIGHT * comp_cost1
        cost2_total = (d2 + MAKE_ROOM_MOVEMENT_WEIGHT * total_movement
                       + STAGE_DECISION_COMPOSITION_WEIGHT * comp_cost2)
        if _DEBUG:
            print(f"DEBUG stage1 d1={d1:.1f} comp={comp_cost1:.1f} cost1={cost1:.1f} | "
                  f"stage2 d2={d2:.1f} moved={len(moved)} total_movement={total_movement:.1f} "
                  f"comp={comp_cost2:.1f} cost2={cost2_total:.1f}",
                  file=sys.stderr, flush=True)
        if cost2_total < cost1:
            use_stage2 = True

    # Stage 3's trigger stays a plain positional check (see
    # RESIZE_TRIGGER_MULTIPLE) -- deliberately NOT the composition cost
    # above, so adding the angular-balance term can't make resize fire more
    # often just because a composition score got numerically bigger. Stage
    # 3 exists for "rearranging couldn't get the new window anywhere near
    # center at all," which is a positional question, not a compositional
    # one -- its own rarity (see try_resize_room's docstring) is preserved
    # unchanged by this file's composition-model changes.
    if use_stage2:
        best_cost = d2 + MAKE_ROOM_MOVEMENT_WEIGHT * total_movement
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
