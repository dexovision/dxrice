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

STAGE 3 -- resize, only when it genuinely helps: evaluated after Stage 1
and Stage 2 have both already been scored, and its candidates are judged
against that same score -- the actual whole-composition cost of the
resulting layout (see composition_cost), not a bare "is the new window
close to center" check (an earlier version used the latter and, per a
live sizing audit, missed real improvements a modest resize could
provide while the new window's own position still looked fine on its
own). Shrinks exactly ONE existing window (never the new one), bounded by
both a fraction of that window's own current size and an absolute
usable-size floor (MIN_USABLE_WIDTH/HEIGHT) that no resize here may ever
cross, with its own per-pixel cost scaled by how prominent that window is
relative to the new one. Only applied when the resulting plan's total
cost genuinely beats the best rearrangement-only plan -- a resize that
doesn't clearly help the real objective is never used.

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
                             batch_async, resize_window_exact_lua, dispatch_async)
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
    total_w = sum(m for _, _, _, _, m in weighted_rects)
    if total_w <= 0:
        return None
    com_x = sum(cx * m for cx, cy, _, _, m in weighted_rects) / total_w
    com_y = sum(cy * m for cx, cy, _, _, m in weighted_rects) / total_w
    return (com_x, com_y)


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
    total = sum(m for _, _, _, _, m in weighted_rects)
    if total <= 0:
        return 0.0, 0.0, 0.0
    Cxx = Cyy = Cxy = 0.0
    for cx, cy, w, h, m in weighted_rects:
        dx, dy = cx - rx, cy - ry
        Cxx += m * (dx * dx + (w * w) / 12.0)
        Cyy += m * (dy * dy + (h * h) / 12.0)
        Cxy += m * (dx * dy)
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


def composition_cost(weighted_rects, viewport_center):
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
    center_of_mass_cost, angular_cost = composition_cost_components(weighted_rects, viewport_center)
    return CENTER_OF_MASS_WEIGHT * center_of_mass_cost + angular_cost


def composition_cost_components(weighted_rects, viewport_center):
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
    best_coverage = None
    for r in layout_rects:
        frac = _flush_coverage(cand, r, gap)
        if frac is not None:
            best_coverage = frac if best_coverage is None else max(best_coverage, frac)
    sliver = SLIVER_PENALTY_MAX * (1.0 - best_coverage) if best_coverage is not None else 0.0
    align = ALIGN_BONUS * _edge_alignment_count(cand, layout_rects)
    dead = _dead_gap_penalty(cand, layout_rects, gap)
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


def try_resize_room(new_size, eligible, fixed_obstacles, center, gap, best_cost, best_direct_distance):
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
                best_plan = (cost, pos, w["address"], (int(sx), int(sy)), (int(sw), int(sh)))

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

    mx0, my0, mx1, my1 = get_monitor_bounds()

    same_ws = [w for w in clients
               if w.get("floating") and w.get("workspace", {}).get("id") == workspace_id
               and w.get("address") != address]
    if _DEBUG:
        print(f"DEBUG same_ws count={len(same_ws)} workspace_id={workspace_id}", file=sys.stderr, flush=True)

    # Startup sizing happens BEFORE any placement maths, and the placement
    # then runs against whatever size the window actually ended up at --
    # never against the size it was asked to become. Same reasoning as the
    # settle loop above: a position computed for a size the window does not
    # have is a gap or an overlap on screen, and the client is entitled to
    # refuse (size increments, a minimum size). So dispatch, wait for the
    # size to stop moving, re-read, and carry on with the truth.
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
                break
            new_win = probe
            size_now = tuple(probe.get("size", ()))
            if size_now == stable_since:
                break
            stable_since = size_now
        same_ws = [w for w in clients
                   if w.get("floating") and w.get("workspace", {}).get("id") == workspace_id
                   and w.get("address") != address]

    new_w, new_h = new_win["size"][0], new_win["size"][1]

    if not same_ws:
        return "placed"  # first window on this workspace -- nothing to avoid

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

    # Stage 1's own whole-composition cost -- computed UNCONDITIONALLY
    # (not just when Stage 2 also succeeds) because Stage 3's baseline
    # (`best_cost` below) needs it either way: a sizing audit found that
    # comparing Stage 3 against a bare positional distance (no composition
    # term at all) meant a genuinely bad-looking composition could still
    # read as "good enough, don't bother resizing" as long as the new
    # window itself happened to land near center -- see try_resize_room's
    # own docstring for the concrete case this missed.
    pos1_mass = window_mass(new_w, new_h, new_area)
    stage1_points = [(ox + ow / 2, oy + oh / 2, ow, oh, window_mass(ow, oh, new_area))
                      for ox, oy, ow, oh in layout_others]
    stage1_points.append((pos1[0] + new_w / 2, pos1[1] + new_h / 2, new_w, new_h, pos1_mass))
    com_cost1, shape_cost1 = composition_cost_components(stage1_points, center)
    comp_cost1 = com_cost1 + shape_cost1  # kept for the _DEBUG line below, not the decision itself
    cost1 = d1 + STAGE_DECISION_COMPOSITION_WEIGHT * com_cost1 + shape_cost1

    use_stage2 = False
    stage2 = try_make_room((new_w, new_h), eligible, fixed_only, center, gap) if eligible else None
    cost2_total = None
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
        # (d1/d2) as the primary term, with composition_cost's two
        # ingredients weighted DIFFERENTLY as a secondary term -- not the
        # combined composition_cost dampened by one shared factor. That
        # was tried first (both ingredients at STAGE_DECISION_COMPOSITION_
        # WEIGHT) and had two DIFFERENT failure modes needing different
        # fixes, not one:
        #
        #   1. Damping the CENTER-OF-MASS ingredient is real and necessary:
        #      undamped, a small existing window already sitting near
        #      center pulls the mass-weighted AVERAGE position artificially
        #      close to center even while a much larger, visually-dominant
        #      new window sits meaningfully off to one side -- measured
        #      live, a 1400x900 new window landed 517px off center, flush
        #      against a tiny 220x140 neighbor, because the average of
        #      "huge window far off" and "tiny window at center" scored
        #      better than actually evicting the tiny one.
        #   2. Damping the SHAPE (anisotropy) ingredient by that SAME
        #      factor was the actual bug this comment now documents: a
        #      live benchmark ("Case A" -- two huge windows already
        #      stacked, a new medium window arrives) found the algorithm
        #      moved one huge window 460px just to slot the new window
        #      into the SAME vertical line, because that candidate's much
        #      lower d2 (the new window's own distance to center) outweighed
        #      a real, measured WORSENING of the group's shape (anisotropy
        #      0.18 -> 0.42) once that worsening was dampened down to 30%
        #      of its true scale. Shape was never implicated in bug #1 --
        #      it has no "average masks an offender" failure mode, since
        #      anisotropy measures the group's actual spatial spread, not
        #      a position that can be pulled toward a point by one member.
        #      Damping it was simply the wrong call, not a badly-tuned one.
        #
        # So: center-of-mass stays secondary (bug #1's fix, unchanged);
        # shape now counts at its own full, already-validated scale (the
        # same ANGULAR_PENALTY_SCALE the within-stage candidate SEARCH
        # already uses, via composition_cost_components) -- both fixes
        # verified together: the ORIGINAL 1400x900-vs-tiny-220x140 scenario
        # still correctly evicts the tiny window (that case has only 2
        # windows, so the shape term is confidence-gated to exactly 0
        # regardless -- it was never doing any work there to begin with),
        # while Case A above now correctly leaves the huge window alone.
        stage2_points = []
        for w in eligible:
            addr = w["address"]
            ow, oh = w["size"]
            if addr in moved:
                mx, my = moved[addr]
                stage2_points.append((mx + ow / 2, my + oh / 2, ow, oh, window_mass(ow, oh, new_area)))
            else:
                ox, oy = w["at"]
                stage2_points.append((ox + ow / 2, oy + oh / 2, ow, oh, window_mass(ow, oh, new_area)))
        stage2_points.append((pos2[0] + new_w / 2, pos2[1] + new_h / 2, new_w, new_h, pos1_mass))
        com_cost2, shape_cost2 = composition_cost_components(stage2_points, center)
        comp_cost2 = com_cost2 + shape_cost2  # kept for the _DEBUG line below, not the decision itself

        cost2_total = (d2 + MAKE_ROOM_MOVEMENT_WEIGHT * total_movement
                       + STAGE_DECISION_COMPOSITION_WEIGHT * com_cost2 + shape_cost2)
        if _DEBUG:
            print(f"DEBUG stage1 d1={d1:.1f} comp={comp_cost1:.1f} cost1={cost1:.1f} | "
                  f"stage2 d2={d2:.1f} moved={len(moved)} total_movement={total_movement:.1f} "
                  f"comp={comp_cost2:.1f} cost2={cost2_total:.1f}",
                  file=sys.stderr, flush=True)
        if cost2_total < cost1:
            use_stage2 = True

    # Stage 3's baseline is now the SAME composition-inclusive cost used to
    # choose between Stage 1 and Stage 2 (cost1/cost2_total), not a bare
    # positional distance -- see try_resize_room's own docstring for why
    # that changed (a live audit found the old positional-only trigger
    # missed real, measurable composition improvements a modest resize
    # could provide, purely because the new window's own position looked
    # "fine" even when the overall layout wasn't).
    best_cost = cost2_total if use_stage2 else cost1
    best_direct_distance = d2 if use_stage2 else d1

    # Stage 3: try_resize_room now always evaluates its candidates against
    # this same objective and only returns a plan that genuinely beats it
    # -- "only for outcomes that are genuinely bad" is enforced by that
    # honest comparison, not a separate gate here. Never touches the new
    # window's own size, never touches more than one existing window, and
    # never crosses MIN_USABLE_WIDTH/HEIGHT. Also never fires unless it
    # gets the new window itself meaningfully closer to center than
    # rearrangement alone -- see try_resize_room's own docstring for the
    # live case (Case F) this closes: a resize that only reshapes the
    # EXISTING windows' own composition, without moving the actual new
    # window any closer to a usable spot, isn't doing Stage 3's job no
    # matter how the aggregate score reads.
    stage3 = (try_resize_room((new_w, new_h), eligible, fixed_only, center, gap, best_cost, best_direct_distance)
              if eligible else None)

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
        _settle_moves({
            resize_addr: {"at": (int(resize_xy[0]), int(resize_xy[1])),
                          "size": (int(resize_size[0]), int(resize_size[1]))},
            address: {"at": (int(pos3[0]), int(pos3[1]))},
        })
    elif use_stage2:
        exprs = [move_window_exact_lua(int(pos2[0]), int(pos2[1]), address)]
        expected = {address: {"at": (int(pos2[0]), int(pos2[1]))}}
        for addr, (mx, my) in moved.items():
            exprs.append(move_window_exact_lua(int(mx), int(my), addr))
            expected[addr] = {"at": (int(mx), int(my))}
        if _DEBUG:
            print(f"DEBUG using STAGE 2: pos={pos2} + {len(moved)} window(s) relocated", file=sys.stderr, flush=True)
        batch_async(exprs)
        _settle_moves(expected)
    else:
        if _DEBUG:
            print(f"DEBUG using STAGE 1: pos={pos1} new_size=({new_w},{new_h}) center={center}", file=sys.stderr, flush=True)
        move_window_exact_async(int(pos1[0]), int(pos1[1]), address)
        _settle_moves({address: {"at": (int(pos1[0]), int(pos1[1]))}})
    return "placed"


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
    # Windows seen at openwindow but not placeable at that instant (mapped
    # fullscreen, or mapped tiled), kept so a later state change can be
    # acted on exactly once. {address: workspace_id}.
    _deferred = {}
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
                            print(f"DEBUG t={time.time():.3f} line={line!r}", file=sys.stderr, flush=True)
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
                                    status = place_new_window(addr, ws_id, gap)
                                except Exception as e:
                                    # One window failing to place must never take
                                    # the listener down, but silently swallowing it
                                    # is how this went unnoticed before -- say so.
                                    print(f"placement failed for {addr} on ws {ws_id}: "
                                          f"{type(e).__name__}: {e}", file=sys.stderr, flush=True)
                                    status = None
                                if status in ("fullscreen", "not-floating"):
                                    # Not placeable RIGHT NOW, but it may
                                    # become placeable -- see _deferred below.
                                    _deferred[addr] = ws_id
                                elif status == "placed":
                                    _deferred.pop(addr, None)
                        elif line.startswith("closewindow>>"):
                            _deferred.pop("0x" + line[len("closewindow>>"):].strip(), None)
                        elif line.startswith("fullscreen>>") or line.startswith("changefloatingmode>>"):
                            # An application that MAPS fullscreen or tiled and
                            # only later becomes an ordinary floating window
                            # used to be lost: openwindow was the only event
                            # this listener ever subscribed to, so the window
                            # was judged once, at the one moment it was
                            # guaranteed to be ineligible, and never looked at
                            # again. That is exactly why a game launcher like
                            # Sober -- which comes up fullscreen and is later
                            # dropped to a floating window -- never got placed.
                            #
                            # Re-check only the windows actually deferred
                            # above, and only until one of them is placed
                            # once. Note Hyprland's fullscreen>> carries no
                            # address, which is why this re-checks the
                            # deferred set rather than trusting the payload.
                            #
                            # This cannot feed back on itself: nothing in this
                            # file ever changes a window's fullscreen or
                            # floating state -- it only moves and resizes --
                            # so a placement can never emit the events that
                            # would re-trigger it, and _deferred.pop() makes
                            # each window placeable exactly once regardless.
                            for pending_addr, pending_ws in list(_deferred.items()):
                                try:
                                    status = place_new_window(pending_addr, pending_ws, gap)
                                except Exception as e:
                                    print(f"deferred placement failed for {pending_addr}: "
                                          f"{type(e).__name__}: {e}", file=sys.stderr, flush=True)
                                    continue
                                if status in ("placed", "gone"):
                                    _deferred.pop(pending_addr, None)
        except (ConnectionRefusedError, FileNotFoundError, OSError) as e:
            print(f"socket2 unavailable ({type(e).__name__}: {e}) -- retrying in 1s",
                  file=sys.stderr, flush=True)
            time.sleep(1)


if __name__ == "__main__":
    main()
