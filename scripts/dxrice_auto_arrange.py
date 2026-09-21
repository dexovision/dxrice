#!/usr/bin/env python3
"""SUPER+D -- Auto Arrange Desktop: a real whole-desktop layout solver.

NOT collision resolution (see dxrice_align_windows.py, kept on disk and
unbound -- rebind SUPER+D to it in hyprland.lua to revert to "only nudge
windows that actually overlap" instead of this real re-layout).

What this does, in order:
  1. Splits floating windows on the workspace into ELIGIBLE (participate in
     the rearrange) and FIXED (fullscreen/maximized -- Hyprland's own
     `fullscreen` field, never 0 for these -- never moved, but still
     obstacles everyone else must avoid).
  2. Reads the ELIGIBLE group's current shape: its centroid, and each
     window's bearing (unit direction) from that centroid. Bearing is
     still computed and available as BEARING_WEIGHT (currently 0 -- see
     that constant's own comment for why) in case a future tuning pass
     wants it back as a tiebreak; the actual "preserve a sensible
     arrangement" job it used to do is now handled more directly by
     MOVEMENT_WEIGHT (don't move a window that's already fine) plus
     composition_cost itself (don't relocate anything unless the overall
     distribution is measurably improved).
  3. Builds a new cluster incrementally in a fixed, deterministic order
     (largest window first, ties broken by address -- never by current
     distance to anything, since that can flip which window goes first
     between two runs on nearly-identical layouts and cascade into a
     different rebuild each time), each window placed via the same
     comprehensive edge-derived candidate search
     dxrice_auto_place_window.py uses for a single new window, scored
     primarily by composition_cost -- is the whole cluster built so far,
     plus this window landing here, a balanced, organic composition
     around its own (not yet externally centered -- see step 4) mass
     center, or does this candidate pile mass onto an axis something else
     already occupies? -- with "how much would this candidate grow the
     cluster's own bounding box" (compactness) and "how little does this
     window have to move from where it already is" (movement) as smaller,
     genuinely secondary tiebreaks. All are SOFT preferences, never hard
     target zones, so the solver is free to break from any of them when
     overlap-avoidance or composition calls for it.
  4. Recenters the WHOLE finished cluster with a single rigid shift (one
     (dx, dy) applied to every eligible window, so nothing about their
     positions relative to each other changes) so the cluster's own
     bounding-box center lands on the viewport center -- this is the one
     step actually responsible for "the group ends up near the current
     view," not something individual placements are relied on to achieve
     by themselves. If applying that shift in full would newly overlap a
     FIXED (fullscreen) window, the shift is scaled down (never enlarged)
     until it doesn't -- "no overlaps" is a hard constraint everywhere in
     this file; "cluster centered on the viewport" is not.
  5. Dispatches every actual position AND size change in ONE batched IPC
     call, so the whole rearrangement happens together rather than windows
     visibly sliding/resizing into place one at a time.

This is a one-shot layout pass, not an ongoing constraint -- dragging a
window wherever you want immediately afterward works exactly as always.
The infinite canvas has no boundary here: the viewport center is a target,
never a containment box, and windows routinely end up (partially or fully)
outside it when that's where the compact arrangement actually lands.

RESIZE: unlike a single new window's own auto-placement (Stage 1/2/3 in
dxrice_auto_place_window.py, where the new window's requested size is
sacred and never touched), SUPER+G is an explicitly user-invoked "organize
my whole desktop" command with no distinguished "just opened" window to
protect -- every eligible window, including the one currently being
incrementally placed, is a legitimate candidate for a MODEST, bounded,
prominence-weighted resize when doing so measurably improves the overall
composition (see the "SUPER+G's resize capability" section below,
_choose_size_and_position). This is NOT tiling: sizes only ever move a
little (a handful of discrete scale steps, never below the same
MIN_USABLE_WIDTH/HEIGHT floor Stage 3 respects, never forcing equal sizes
or a grid), and only when the honest, consistently-scaled comparison says
it genuinely helps -- resizing is an available OPTION the search may pick,
never a forced step every run performs.
"""
import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dxrice_hypr_ipc import hyprctl_json, batch_async, move_window_exact_lua, resize_window_exact_lua
from dxrice_auto_place_window import (get_monitor_bounds, live_gap, rect_for, overlaps,
                                       composition_penalty, composition_cost, window_mass, mass_center,
                                       MIN_USABLE_WIDTH, MIN_USABLE_HEIGHT, MAX_SHRINK_FRACTION,
                                       _flush_coverage, _nearest_for_candidates)

_DEBUG = os.environ.get("DXRICE_DEBUG") == "1"

# How strongly each soft factor counts in a candidate's score, in
# pixel-equivalent units (all terms are summed directly, so they're scaled
# to be roughly comparable): a candidate 1px farther from the window's own
# current position costs 1 point; the other weights are relative to that.
#
# COMPACTNESS_WEIGHT scores how much a candidate would grow the cluster's
# own bounding box beyond its current extent (see score()) -- this
# replaced an earlier "distance from this candidate to the viewport
# center" term (CENTRALITY_WEIGHT) that looked similar but was wrong in a
# way that only showed up on a second run: a per-window pull toward one
# fixed point penalizes EVERY member of a normally spread-out cluster for
# being spread out, since a member near the edge of a well-formed,
# well-centered cluster is still, correctly, some real distance from that
# exact point. That pull was strong enough to relocate a window in an
# already-good arrangement on every re-run (verified live: re-running the
# solver on its own already-centered, non-overlapping output moved every
# window 75-275px for no reason), and the specific window it relocated
# depended on which window happened to be closest to the cluster centroid
# THIS time, which is itself unstable between runs (see ordering note
# below) -- two compounding bugs from the same root cause. Bounding-box
# growth doesn't have this problem: it's ~0 for any candidate that already
# fits within the group's existing footprint, however far that candidate
# sits from any single point, and it's only ever large for a candidate
# that would genuinely make the cluster's overall footprint bigger -- which
# is exactly, and only, what "compact" should mean. It still pulls a truly
# stranded window (thousands of pixels from everything else) back toward
# the group, because leaving it there would cost a large, real bbox
# expansion; it does NOT pull an already-well-placed window closer to a
# fixed point for no reason, because doing so wouldn't shrink anything.
# The final rigid recenter shift (see auto_arrange) remains the only step
# responsible for "the finished cluster ends up near the viewport center"
# -- this per-window score has no opinion about the viewport at all.
#
# MOVEMENT_WEIGHT stays a minor tiebreak, not the primary driver: among
# candidates that are roughly equally compact and equally composition-
# consistent, prefer the one closest to the window's own current spot, so
# a window that's already fine doesn't get nudged for no reason even when
# an equally-valid alternative exists elsewhere.
#
# COMPACTNESS_WEIGHT was lowered from an earlier 1.0 (see the composition
# audit that added the GLOBAL term just below): raw bbox-growth compactness
# is what PRODUCED the rectangle-packing/stacking bias in the first place
# (a straight stack minimizes bbox growth, since a stack literally IS the
# minimum bounding rectangle for its own footprint) -- lowered, not
# removed, so it still only matters as a tiebreak among candidates the
# composition term is already indifferent between, per the explicit
# requirement that compactness become secondary.
#
# BEARING_WEIGHT was lowered to 0 (from an earlier 220), also found during
# the same audit: preserving each window's ORIGINAL bearing from the
# group's centroid actively fights a correction when the ORIGINAL
# arrangement was itself a bad stack -- bearing computed from "wherever the
# input happened to already be" has no way to distinguish "the user
# deliberately arranged things this way" from "this is the exact
# degenerate concentration composition_cost exists to fix," so preserving
# it unconditionally worked against the fix in exactly the cases this pass
# targets (measured live: with bearing active, a new 4th window would not
# reliably break an existing 3-window stack). The soft "preserve existing
# relative arrangement" idea bearing represented is still served, just by a
# different mechanism now: MOVEMENT_WEIGHT already keeps a window that's
# already well-placed from moving for no reason, and composition_cost
# itself won't relocate anything that isn't measurably improving the
# distribution.
COMPACTNESS_WEIGHT = 0.25
MOVEMENT_WEIGHT = 0.3
BEARING_WEIGHT = 0.0

# GLOBAL composition (see composition_cost's own docstring in
# dxrice_auto_place_window.py) is scored INSIDE score() alongside these
# three, at the function's own fixed weights (CENTER_OF_MASS_WEIGHT=1.0,
# ANGULAR_PENALTY_SCALE=2000.0, empirically tuned -- see its own comment)
# -- not re-weighted here, so one set of constants governs "is this
# organic" for both SUPER+G and single-window auto-placement.
#
# Measured against the CLUSTER'S OWN mass center during the incremental
# build (see the composition_cost call inside score() below), never the
# absolute viewport_center, for the same reason COMPACTNESS_WEIGHT's own
# comment gives for bbox growth: "this per-window score has no opinion
# about the viewport at all" -- only the final rigid recenter may. Scoring
# mid-build candidates against the absolute viewport center was tried
# first and broke idempotency: the same final relative shape, built
# starting from a different first-window anchor (which differs between two
# runs whenever that window's own current position differs, e.g. run 2's
# input is run 1's already-shifted output), sits at a different absolute
# offset from viewport_center WHILE STILL BEING BUILT, so later windows in
# the sequence saw a genuinely different angular relationship to that
# fixed external point and could choose differently -- reproduced live: a
# second, no-op SUPER+G run moved a window 285px for no reason. Measuring
# against the cluster's own (translation-invariant) center fixed it.


# How many of the nearest obstacles also contribute STAGGERED (deliberately
# not corner-aligned) candidate positions -- see the block in
# _find_best_position that uses it. Kept small on purpose: these are cheap
# because they're added as explicit pairs rather than cross-multiplied
# (see that block), but they're still work per window per step.
#
# A NOTE ON WHAT IS DELIBERATELY *NOT* HERE. This pass first tried to make
# arrangements less grid-like by adding a global "directional balance"
# score -- the mass-weighted mean resultant length of the directions from
# the cluster centre to each window, penalised when they bunch to one side.
# It was removed after it demonstrably made things worse, and the reason is
# worth keeping: that statistic is blind to collinearity. Opposite
# directions cancel, so a straight vertical stack of three windows scores a
# PERFECT zero on it -- the metric actively rewarded the one arrangement
# this file works hardest to avoid, and a 3-window case that previously
# broke into an L came out as a clean stack instead (caught by
# test_gap_exact_where_adjacent).
#
# composition_cost's covariance/anisotropy term already handles "spread
# along a single axis" correctly, precisely because eigenvalues DO see
# collinearity. So the grid-iness is not fixed by adding another global
# shape metric to argue with the proven one; it is fixed structurally, by
# making non-lattice positions REACHABLE (below) so the existing objective
# can choose them on their real merits.
ORGANIC_STAGGER_ANCHORS = 4


def _find_best_position(size, obstacle_rects, gap, current_pos, bearing_unit, cluster_centroid,
                         cluster_bbox, placed_points, viewport_center, reference_area):
    """Same comprehensive candidate generation as
    dxrice_auto_place_window.find_free_position (every existing obstacle's
    edges crossed in both axes, plus the window's own current position as
    an explicit candidate so "just stay put" is always fairly considered)
    -- but scored by a soft blend of GLOBAL composition (see
    composition_cost), compactness, minimal movement, and bearing
    consistency instead of raw distance-to-a-single-target-point.

    cluster_bbox is None for the very first window placed (nothing to be
    compact WITH yet) and bearing_unit is (0.0, 0.0) for that same first
    window (no cluster centroid yet to have a direction from) -- both
    terms are simply skipped in that case, and the window keeps its own
    current position whenever that's free of the FIXED obstacles already
    in obstacle_rects. `placed_points`: [(cx, cy, mass), ...] for every
    window placed so far in this pass (never the not-yet-placed ones,
    consistent with cluster_bbox's own convention) -- the global
    composition reference this window's candidate is being added to.

    Returns (pos, score) -- the score is exposed (not just the winning
    position) so a caller evaluating this SAME window at several candidate
    SIZES (see _choose_size_and_position) can compare across sizes using
    the identical scoring this function already computes internally,
    rather than needing a second, separately-maintained cost formula.
    """
    nw, nh = size
    cx0, cy0 = current_pos
    cand_mass = window_mass(nw, nh, reference_area)

    def free(x, y):
        cand = (x, y, x + nw, y + nh)
        inflated = (cand[0] - gap, cand[1] - gap, cand[2] + gap, cand[3] + gap)
        return not any(overlaps(inflated, r) for r in obstacle_rects)

    xs = {cx0 - nw / 2}
    ys = {cy0 - nh / 2}
    # See dxrice_auto_place_window.CANDIDATE_ANCHOR_CAP's own comment --
    # same O(n^2)-candidates-times-O(n)-scoring blowup, same fix: only the
    # nearest obstacles (to this window's own current position, the point
    # this search actually cares about being near) get to propose
    # candidate x/y values when there are many more than that could
    # plausibly matter. `free()` and every scoring term above still check
    # every obstacle -- this only prunes which POSITIONS get proposed.
    pruned = _nearest_for_candidates([(x0, y0, x1 - x0, y1 - y0) for x0, y0, x1, y1 in obstacle_rects],
                                      current_pos)
    for ox, oy, ow, oh in pruned:
        ox0, oy0, ox1, oy1 = ox, oy, ox + ow, oy + oh
        xs.update((ox0, ox1, ox0 - nw - gap, ox1 + gap))
        ys.update((oy0, oy1, oy0 - nh - gap, oy1 + gap))

    # STAGGERED candidates, for the nearest few obstacles only.
    #
    # Every value added above is one of an obstacle's own edges (or that
    # edge plus a gap), so every candidate position the search could even
    # SEE was flush-aligned with some existing window on at least one axis.
    # That is a lattice, and a lattice is why the results kept coming out
    # looking like a grid: an organic position was never rejected by the
    # scoring, it was never a candidate in the first place. No weighting
    # change can fix an option that does not exist.
    #
    # These are the missing options: beside a neighbour, but deliberately
    # NOT corner-aligned with it -- centre-aligned against its span, and
    # offset into its thirds. Derived from the neighbour's own geometry, so
    # there is no fixed direction, no ordering and no template; they simply
    # make "touching, but stepped" reachable so the existing objective can
    # choose it when it genuinely scores better.
    #
    # These are added as explicit (x, y) PAIRS below rather than as more
    # values in the xs/ys sets, and that distinction is load-bearing twice
    # over. Feeding them into the sets cross-multiplies them: a staggered x
    # would pair with a staggered y to produce a position diagonally off
    # some corner, flush with nothing, which is dead space by construction
    # -- that regression showed up immediately as a 310px "gap" where 5px
    # was configured. It also squares the candidate count (measured: the
    # suite went from 0.5s to 5.3s). Pairing them explicitly keeps every
    # staggered candidate flush-with-gap on one axis and merely stepped
    # along the other, which is the whole intent, and costs a handful of
    # candidates per anchor instead of a multiple of all of them.
    staggered = []
    for ox, oy, ow, oh in pruned[:ORGANIC_STAGGER_ANCHORS]:
        y_offsets = (oy + (oh - nh) / 2, oy + oh / 3, oy + oh - oh / 3 - nh)
        x_offsets = (ox + (ow - nw) / 2, ox + ow / 3, ox + ow - ow / 3 - nw)
        for sy in y_offsets:
            staggered.append((ox + ow + gap, sy))   # beside it, stepped vertically
            staggered.append((ox - nw - gap, sy))
        for sx in x_offsets:
            staggered.append((sx, oy + oh + gap))   # below/above it, stepped horizontally
            staggered.append((sx, oy - nh - gap))

    candidates = [(x, y) for x in xs for y in ys if free(x, y)]
    candidates.extend(c for c in staggered if free(*c))

    if not candidates:
        # Every edge-derived spot conflicts with something -- spiral
        # outward from the window's own current position (not the cluster
        # centroid: with no other signal left, staying close to where it
        # already was is the least arbitrary fallback) until free.
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
                candidates = free_ring
                break
            ring += 1
            if ring > 500:  # pathological guard, not a real-world limit
                candidates = [(cx0 - nw / 2, cy0 - nh / 2)]
                break

    bx, by = bearing_unit
    ccx, ccy = cluster_centroid

    def score(x, y):
        px, py = x + nw / 2, y + nh / 2
        cand = (x, y, x + nw, y + nh)
        movement = math.hypot(px - cx0, py - cy0)
        total = MOVEMENT_WEIGHT * movement
        # GLOBAL composition: is the whole cluster (everything placed so
        # far, plus this window landing here) well-distributed around the
        # CLUSTER'S OWN mass center, or does this candidate pile it onto an
        # axis something else already occupies? See composition_cost's own
        # docstring -- this is the same function dxrice_auto_place_window.py
        # uses for a single new window, so one definition of "organic"
        # governs both SUPER+G and new-window auto-placement.
        #
        # Measured against the cluster's OWN center, not the absolute
        # viewport_center -- this matters and was the source of a real
        # idempotency bug: the incremental build doesn't establish its
        # position relative to the viewport until the FINAL rigid recenter
        # (see auto_arrange, and COMPACTNESS_WEIGHT's own comment: "this
        # per-window score has no opinion about the viewport at all").
        # Scoring mid-build candidates against the absolute viewport center
        # broke that invariant: the same final relative shape, built
        # starting from a different first-window anchor (which differs
        # between two runs whenever the first window's OWN current position
        # differs -- e.g. run 2's input is run 1's already-shifted output),
        # sits at a different absolute offset from viewport_center WHILE
        # STILL BEING BUILT, so later windows saw a genuinely different
        # angular relationship to that fixed external point and could
        # choose differently -- reproduced live: re-running on your own
        # output moved a window 285px for no reason. Composition, like
        # compactness, needs to be about the cluster's own shape during the
        # build; only the final shift may care where the viewport actually
        # is.
        if placed_points:
            comp_ref = mass_center(placed_points) or viewport_center
            total += composition_cost(placed_points + [(px, py, nw, nh, cand_mass)], comp_ref)
        if cluster_bbox is not None:
            bx0_, by0_, bx1_, by1_ = cluster_bbox
            new_w = max(bx1_, cand[2]) - min(bx0_, cand[0])
            new_h = max(by1_, cand[3]) - min(by0_, cand[1])
            growth = (new_w - (bx1_ - bx0_)) + (new_h - (by1_ - by0_))
            total += COMPACTNESS_WEIGHT * growth
        if (bx, by) != (0.0, 0.0):
            dx, dy = px - ccx, py - ccy
            dist = math.hypot(dx, dy)
            cos_sim = (dx * bx + dy * by) / dist if dist > 1e-6 else 1.0
            total += BEARING_WEIGHT * (1 - cos_sim)  # 0 = aligned, up to 2 = opposite
        # Same "does this read as a clean, intentional composition" terms
        # dxrice_auto_place_window.py uses for a single new window --
        # rewards a candidate that shares a full edge with a neighbor
        # already in the cluster over one that only sliver-touches it, and
        # rewards lining up with an existing window's edge even when not
        # directly touching it. See composition_penalty's own docstring.
        total += composition_penalty(cand, obstacle_rects, gap)
        return total

    def growth_of(x, y):
        if cluster_bbox is None:
            return 0.0
        bx0_, by0_, bx1_, by1_ = cluster_bbox
        cand = (x, y, x + nw, y + nh)
        new_w = max(bx1_, cand[2]) - min(bx0_, cand[0])
        new_h = max(by1_, cand[3]) - min(by0_, cand[1])
        return (new_w - (bx1_ - bx0_)) + (new_h - (by1_ - by0_))

    def alignment_of(x, y):
        return composition_penalty((x, y, x + nw, y + nh), obstacle_rects, gap)

    best = min(candidates, key=lambda p: score(*p))

    # (A "stay-put veto" used to sit here: if the window's own current
    # position was still a legal candidate and was no worse than the
    # winner on bbox growth AND strictly better on edge alignment, it won
    # instead. It was added to stop composition_cost's anisotropy term --
    # a 2nd-moment statistic that a degenerate, near-collinear candidate
    # can game -- from yanking a window out of an already-good 2x2 grid.
    #
    # It has been removed, for two measured reasons. First it is
    # redundant: _shape_is_coherent now catches an already-good
    # arrangement BEFORE the incremental rebuild ever starts, which is a
    # strictly better place to make that decision, and the whole suite
    # passes without the veto. Second, and worse, it was actively
    # harmful -- because it preferred whichever option was more
    # edge-ALIGNED, it systematically preferred staying inside a
    # perfectly-aligned vertical stack, i.e. it protected the exact
    # pathology this file works hardest to break. Measured directly: with
    # the veto in place a 3-window vertical stack survived a full
    # SUPER+G as a stack (axial concentration R=0.97); with it removed
    # the same input breaks into a stepped arrangement (R=0.28) on the
    # first press.)
    return best, score(*best)


# ============================================================================
# SUPER+G's resize capability: position and size as ONE joint decision
# ============================================================================
#
# Investigated (per an explicit request) whether SUPER+G was making a real
# size-vs-position tradeoff or just repositioning windows around whatever
# sizes they already happened to have. It was the latter -- this file never
# resized anything at all. A sizing audit (see dxrice_auto_place_window.py's
# Stage 3 fix, same session) already established that resize is only worth
# doing when it beats an honest, consistently-scaled comparison against the
# no-resize plan; the same principle applies here, generalized to a
# multi-window incremental build.
#
# Design choice: rather than a separate "arrange, then resize" pass (which
# is exactly the "optimize position first, then independently resize
# afterward" the request explicitly warns produces contradictory
# decisions), resize candidates are additional entries in the SAME
# candidate pool _find_best_position already scores for each window's own
# incremental placement step -- "no resize" is simply the candidate with
# resize cost 0, so the comparison is automatically apples-to-apples by
# construction (this is what the Stage 3 scale-mismatch bug's lesson
# actually demands: don't maintain two separately-weighted formulas that
# have to be kept consistent by hand).
#
# What can be resized, and when: at each incremental step (placing window
# i), the CURRENT window may pick a smaller-than-current size for itself,
# OR exactly one ALREADY-PLACED, not-yet-resized neighbor may be shrunk
# (center-anchored -- Hyprland's own floating-resize behavior, confirmed
# live in dxrice_auto_place_window.py, needs no corrective move for this)
# to make room for the current window's OWN unchanged size. Never both in
# the same step, and each window may be a resize target at most ONCE across
# the whole pass (mirrors Stage 3's own "resize exactly one window" scope,
# generalized to "at most one resize per window per run" rather than
# allowing a window to be progressively whittled down across many steps in
# a way a human wouldn't expect). This is a bounded, deterministic search:
# a handful of scale steps x a handful of already-placed windows, each
# reusing the existing edge-derived candidate search -- not a continuous
# optimizer.

# Deterministic, bounded set of scale factors ever considered for a resize
# candidate -- reuses MAX_SHRINK_FRACTION (Stage 3's own already-tested "how
# much may we ever shrink a window" cap) as the deepest cut, rather than
# inventing an unrelated number. 1.0 (no change) is always implicitly
# available too (every window's baseline candidate); these are the
# additional smaller-than-current options actually tried. Uniform (both
# width and height scaled together) so aspect ratio is preserved -- Stage
# 3's single-axis trims exist to fix a specific one-axis gap next to an
# incoming window, which doesn't apply here; SUPER+G's resize is about
# overall prominence, where a proportionate shrink reads as "the app is
# slightly smaller," not a stretched/skewed window.
RESIZE_SCALE_STEPS = (0.9, 0.8, 1.0 - MAX_SHRINK_FRACTION)

# Pixel-equivalent scale for SUPER+G's resize cost. NOT copied from Stage
# 3's RESIZE_COST_PER_PIXEL -- that constant is calibrated for a linear,
# raw-pixel, single-resize-per-event formulation, which is the wrong shape
# here (see _resize_fraction_cost's own comment for why this one is
# normalized and quadratic instead). Reasoned starting value, same
# convention as this file's other weights -- verified empirically via this
# change's own test scenarios and live validation, not asserted.
SUPER_G_RESIZE_COST_SCALE = 400.0

# A resize (self OR neighbor) is only ever taken when it beats the
# position-only baseline score by at least this FRACTION -- not merely
# scores numerically lower. Explicit requirement: "no tiny numerical wins,
# require a meaningful improvement margin."
#
# This works ALONGSIDE RESIZE_ELIGIBLE_RATIO_FLOOR, not instead of it, to
# make repeated SUPER+G runs idempotent -- this session's own testing found
# each piece alone was insufficient. Without ANY margin, a window resized
# once looked CHEAPER to resize further on the very next run (this script
# has no persistent memory of a window's size from before a prior SUPER+G
# run, so a marginal "improvement" could compound indefinitely, whittling
# a window down a little more each time). But margin alone isn't enough
# either for a window that starts FAR above typical size: window_mass's
# own clamp (bounded to MASS_MAX for the composition math) means a
# deeply-oversized window can still look "just as prominent" after several
# real trims, so the SAME margin comparison can keep passing run after
# run even with a real margin in place. RESIZE_ELIGIBLE_RATIO_FLOOR closes
# that gap using the TRUE (unclamped) size ratio, which strictly decreases
# with every real resize regardless of how the composition math weighs it
# -- together, the margin filters out non-material single-step "wins" and
# the floor guarantees the eligibility question itself eventually says no,
# rather than relying on the margin to do both jobs at once. Verified via
# this change's own repeated-SUPER+G regression tests, including a
# moderately (not pathologically) oversized window converging to a stable
# result within a single re-run.
#
# A PREVIOUS pass raised this to 0.10 after a random-layout benchmark found
# a dominant window among many tiny dialogs losing ~10% on every SEPARATE
# SUPER+G press. That was a symptomatic fix, not the real one, and this
# session's own re-investigation found it: the actual bug was in
# reference_area itself (see _typical_area's own docstring) -- a flat
# population median let 14 tiny dialogs numerically outvote the ONE main
# window, making an entirely ordinary window read as "5x+ oversized" and
# eligible for repeated resizing purely because of how many small windows
# happened to be open. Instrumented directly (per this session's own
# methodology): a TINY window's own incremental placement step was the
# one choosing to shrink the unrelated giant neighbor, purely because a
# skewed reference made that neighbor look "cheap" to shrink relative to
# the (contaminated) typical size -- not because the giant window was
# ever actually in anyone's way. With _typical_area's size-cluster model
# fixing that root cause, raising the margin is no longer needed: reverted
# to 0.02, and the SAME three reproducing layouts that used to compound
# (moderate ~2.8-7x and extreme ~5.4x oversized windows among many tiny
# dialogs) now resize ZERO times across 8 repeated runs at this original
# margin, because they're correctly never considered eligible in the
# first place -- not because the bar to accept a resize got raised, but
# because reference_area no longer says they're oversized at all. Raising
# a margin to paper over a broken reference would have kept passing this
# specific benchmark while leaving the underlying model wrong for every
# other window count and dialog ratio it wasn't tuned against.
SUPER_G_RESIZE_MARGIN_FRACTION = 0.02


def _resize_fraction_cost(scale, prominence):
    """scale: the fraction of a window's ORIGINAL size a candidate keeps
    (1.0 = unchanged, 0.8 = 20% smaller in each dimension). Returns a
    pixel-equivalent cost, exactly 0 at scale=1.0.

    Normalized to a FRACTION of the window's own dimension, not raw pixels
    removed -- a flat per-pixel rate (Stage 3's own model) would make an
    identical PROPORTIONAL trim look artificially more expensive on a large
    window than a small one, when the actual visual/usability disruption
    ("this app got noticeably smaller") scales with the fraction removed,
    not the window's absolute size. Quadratic in that fraction, not linear
    -- per the explicit requirement that a shallow trim (shrinking a
    prominent app 5%) stay cheap while a deep one (30%) become prohibitive:
    a flat per-percent rate can't express that escalation on its own, since
    it would price a 30% cut at exactly 6x a 5% cut rather than
    disproportionately more. Scaled by `prominence` (see
    _choose_size_and_position's own comment on why that's window_mass, not
    Stage 2/3's unbounded prominence_weight), so a window well above the
    group's typical size resists shrinking more than one at or below it --
    without the resistance growing without limit as that difference grows.
    """
    fraction_removed = 1.0 - scale
    return SUPER_G_RESIZE_COST_SCALE * (fraction_removed ** 2) * prominence


def _usable_scaled_size(w, h, scale):
    """Returns (round(w*scale), round(h*scale)) or None if that would cross
    MIN_USABLE_WIDTH/HEIGHT -- the same absolute floor Stage 3 respects,
    applied here too so SUPER+G's resize can never produce a smaller result
    than a single-window auto-placement resize ever could."""
    nw, nh = round(w * scale), round(h * scale)
    if nw < MIN_USABLE_WIDTH or nh < MIN_USABLE_HEIGHT:
        return None
    return nw, nh


# How far above the group's own typical size (reference_area) a window
# must genuinely be, by its TRUE (unclamped) size ratio, to be considered
# for a resize AT ALL. Deliberately NOT window_mass's own clamped output
# (bounded to MASS_MAX=2.5 for the composition math elsewhere in this
# file) -- this needed the real, uncapped ratio instead, and the
# difference matters: this-session testing found that with the CLAMPED
# value as the eligibility check, a window many times larger than typical
# stayed reading as "mass 2.5, still eligible" for MANY successive resize
# steps even as it was progressively shrunk, because the clamp hides how
# much smaller it's actually gotten -- repeated SUPER+G presses kept
# finding "one more moderate trim" numerically worthwhile indefinitely,
# which is exactly the "second run should produce zero further resize"
# requirement failing. The TRUE ratio (sqrt(area/reference_area), no cap)
# strictly decreases with every real resize regardless of how the
# composition math elsewhere weighs it, so it's what actually converges:
# once a window's real size ratio drops to this floor or below, it stops
# being offered as a candidate at all, independent of how many prior
# SUPER+G runs it took to get there.
RESIZE_ELIGIBLE_RATIO_FLOOR = 1.5


def _mass_ratio(w, h, reference_area):
    """The TRUE (unclamped) size ratio to reference_area -- see
    RESIZE_ELIGIBLE_RATIO_FLOOR's own comment for why this, and not
    window_mass, is what gates resize eligibility."""
    if reference_area <= 0:
        return 1.0
    return math.sqrt((w * h) / reference_area)


def _choose_size_and_position(w, current_pos, bearing_unit, cluster_centroid, cluster_bbox,
                               placed, fixed_rects, viewport_center, reference_area, gap, resized_addrs,
                               allow_resize=True):
    """The joint decision for ONE window's incremental placement step:
    among (a) its own current size with no resize, (b) its own size
    shrunk to one of RESIZE_SCALE_STEPS, and (c) its own unchanged size
    with exactly one not-yet-resized already-placed neighbor shrunk
    instead, pick whichever (position, size-configuration) pair scores
    lowest on the IDENTICAL objective _find_best_position already uses,
    plus that configuration's own resize cost (0 for (a)).

    `placed`: {address: (x, y, w, h)} for every window placed so far in
    this pass (mutable only by the caller, after this function returns
    which configuration won). `fixed_rects` are the permanent obstacles
    (never resized, never a candidate here). `resized_addrs`: set of
    addresses already used as a resize target earlier in this pass --
    excluded from being offered again (see this section's own module
    comment for why).

    Returns (chosen_own_size, chosen_pos, neighbor_resize) where
    neighbor_resize is None or (address, new_x, new_y, new_w, new_h) for
    the one already-placed window this step decided to shrink instead of
    the current window.
    """
    own_w, own_h = w["size"]
    own_area = own_w * own_h
    addr = w["address"]

    def obstacle_rects_for(overrides=None):
        """Every OTHER window's rect (fixed + already-placed), with an
        optional {address: (x, y, w, h)} override for a neighbor being
        trial-resized. Rebuilt fresh each time rather than incrementally
        maintained, since several different trial configurations need
        their own version within the same step -- cheap at realistic
        desktop window counts, and immune to ever drifting out of sync
        with `placed`."""
        rects = list(fixed_rects)
        for a, (x, y, ww, hh) in placed.items():
            if overrides and a in overrides:
                x, y, ww, hh = overrides[a]
            rects.append(rect_for(x, y, ww, hh))
        return rects

    def placed_points_for(overrides=None):
        pts = []
        for a, (x, y, ww, hh) in placed.items():
            if overrides and a in overrides:
                x, y, ww, hh = overrides[a]
            pts.append((x + ww / 2, y + hh / 2, ww, hh, window_mass(ww, hh, reference_area)))
        return pts

    best = None  # (score, own_size, pos, neighbor_resize)

    # (a) baseline -- own size, no resize at all. Always evaluated first
    # and always available, matching "if position-only already produces an
    # excellent composition, resize nothing."
    pos, score = _find_best_position((own_w, own_h), obstacle_rects_for(), gap, current_pos, bearing_unit,
                                      cluster_centroid, cluster_bbox, placed_points_for(),
                                      viewport_center, reference_area)
    best = (score, (own_w, own_h), pos, None)
    # Any resize (self or neighbor) must beat the position-only baseline by
    # at least this fraction to be taken at all -- see
    # SUPER_G_RESIZE_MARGIN_FRACTION's own comment for why this is a fixed
    # bar against the TRUE do-nothing score, not just "better than whatever
    # else was found so far."
    resize_threshold = score * (1.0 - SUPER_G_RESIZE_MARGIN_FRACTION)

    # (b) shrink the CURRENT window itself -- only meaningful once a
    # cluster actually exists to be compact with (cluster_bbox is None for
    # the very first window, which has nothing yet to resize itself
    # smaller FOR).
    # window_mass, NOT prominence_weight -- see this section's own
    # investigation (a live scenario found prominence_weight's UNBOUNDED
    # sqrt(area ratio) growth made the single most oversized, most
    # obviously-worth-shrinking window in a set the MOST resistant to any
    # resize at all: an 8x area difference gave a ~7x cost multiplier,
    # pricing even a 10% trim far above any realistic composition benefit.
    # window_mass computes the exact same ratio but clamps it to
    # [MASS_MIN, MASS_MAX] -- "bigger resists more, smaller resists less"
    # without the runaway growth that made the intended use case (a
    # dominant window CAN be resized when it genuinely helps) unreachable.
    self_prominence = window_mass(own_w, own_h, reference_area)
    # A second, real bug this same investigation found: a low-mass (small)
    # window is CHEAP to shrink by this formula (correctly -- "much less
    # resize resistance"), which meant the search took the path of least
    # resistance and nibbled away at already-modest windows for a marginal
    # score win, while leaving the ACTUAL oversized window untouched --
    # live evidence: an oversized 2000x1300 window sitting among three
    # 450x350 ones left the 2000x1300 alone and shrank two of the
    # 450x350s instead (one down to 270x210, a 40% area cut on a window
    # that was never the problem). "Cheap to shrink" is not the same
    # question as "is this the window actually causing the imbalance" --
    # a window at or below the group's own typical size was never the
    # dominant one, so it is never offered as a shrink candidate AT ALL,
    # regardless of how cheap the formula would otherwise price it.
    if allow_resize and cluster_bbox is not None and _mass_ratio(own_w, own_h, reference_area) > RESIZE_ELIGIBLE_RATIO_FLOOR:
        for scale in RESIZE_SCALE_STEPS:
            sized = _usable_scaled_size(own_w, own_h, scale)
            if sized is None:
                continue
            pos_s, score_s = _find_best_position(sized, obstacle_rects_for(), gap, current_pos, bearing_unit,
                                                  cluster_centroid, cluster_bbox, placed_points_for(),
                                                  viewport_center, reference_area)
            total = score_s + _resize_fraction_cost(scale, self_prominence)
            if total < resize_threshold and total < best[0]:
                best = (total, sized, pos_s, None)

    # (c) shrink exactly one already-placed, not-yet-resized neighbor
    # instead, center-anchored, keeping the CURRENT window at its own
    # unchanged size.
    for n_addr, (nx, ny, nw_, nh_) in ({} if not allow_resize else placed).items():
        if n_addr in resized_addrs:
            continue
        n_prominence = window_mass(nw_, nh_, reference_area)
        if _mass_ratio(nw_, nh_, reference_area) <= RESIZE_ELIGIBLE_RATIO_FLOOR:
            continue  # see self_prominence's own comment above -- never shrink an at-or-below-floor window
        ncx, ncy = nx + nw_ / 2, ny + nh_ / 2
        for scale in RESIZE_SCALE_STEPS:
            sized_n = _usable_scaled_size(nw_, nh_, scale)
            if sized_n is None:
                continue
            snw, snh = sized_n
            # Center-anchored shrink: Hyprland's own floating-resize
            # behavior, so no corrective move is needed for the neighbor
            # beyond the position this computes directly.
            override = {n_addr: (round(ncx - snw / 2), round(ncy - snh / 2), snw, snh)}
            pos_n, score_n = _find_best_position((own_w, own_h), obstacle_rects_for(override), gap, current_pos,
                                                  bearing_unit, cluster_centroid, cluster_bbox,
                                                  placed_points_for(override), viewport_center, reference_area)
            total = score_n + _resize_fraction_cost(scale, n_prominence)
            if total < resize_threshold and total < best[0]:
                nx2, ny2, _, _ = override[n_addr]
                best = (total, (own_w, own_h), pos_n, (n_addr, nx2, ny2, snw, snh))

    _, chosen_size, chosen_pos, neighbor_resize = best
    return chosen_size, chosen_pos, neighbor_resize


def _shift_is_safe(placed, shift, fixed_rects, gap):
    dx, dy = shift
    for x, y, w, h in placed:
        moved = (x + dx, y + dy, x + dx + w, y + dy + h)
        inflated = (moved[0] - gap, moved[1] - gap, moved[2] + gap, moved[3] + gap)
        if any(overlaps(inflated, r) for r in fixed_rects):
            return False
    return True


# A layout this session's own investigation kept finding SUPER+G reshuffle
# even though it was already excellent by every human-legible measure (a
# 2x2 grid, then a correctly-centered 3x3 grid) -- not because any single
# candidate step was wrong, but because the incremental largest-first
# REBUILD has no way to represent "this is already fine, stop" short of
# every individual per-window decision happening to agree, and covariance-
# based anisotropy (composition_cost's shape term) turned out NOT to be a
# reliable judge of that at small N (see the stay-put veto's own comment
# for the proof). Rather than chasing that per-candidate fragility further
# with more special-case comparisons -- which broke the resize-settling
# tests the one time it was tried (compares against the wrong baseline
# once a genuine resize is mid-decision) -- this checks for "already
# coherent" ONCE, structurally, before the rebuild ever starts, using
# properties a picture of the layout can be judged by directly rather than
# a 2nd-moment statistic: no invalid overlaps, every eligible window
# reachable from every other through a real (not sliver) shared edge, the
# whole group's own bounding box isn't dramatically elongated, and that
# bbox is already close to the viewport center. A layout meeting all four
# is returned completely unchanged -- true zero movement, zero resize, not
# merely "small" movement -- which is what lets Case I (already-excellent
# -> SUPER+G does nothing) hold for ANY window count and ANY of the
# shapes this was checked against (2x2, 3x3, an L, a T, a staircase, an
# asymmetric packed cluster -- see dxrice_test_placement.py's
# TestAlreadyCoherentLayouts), not just the one 4-window case a narrower,
# per-candidate patch happened to be discovered on.
ADJACENCY_COVERAGE_THRESHOLD = 0.3

# A composition whose overall footprint is more than this much longer than
# it is wide (or vice versa) reads as a stack/row, not a cluster, no matter
# how well-connected its pieces are -- a real stack IS one connected
# component (each window touches its neighbor), so connectivity alone
# can't tell the two apart. Evidenced against this file's own deliberately
# bad inputs: 4/5/6-window vertical stacks measure 3.0/4.1/5.1 by this
# ratio; the 2x2 and 3x3 grids this check exists to protect measure
# 1.5/1.3. Chosen with real margin above the grids and well below the
# stacks, not squeezed between them.
ALREADY_GOOD_ASPECT_RATIO_MAX = 2.2

# How far the composition's bbox center may sit from the viewport center
# and still count as "already centered", as a FRACTION OF THE VIEWPORT's
# shorter side.
#
# This is measured against the VIEWPORT, not against the composition's own
# bbox, and that distinction is the whole point. Scaling the dead zone to
# the composition looks self-relative and reasonable right up until the
# composition is large: a 3130x2585 cluster got a 1292px tolerance, so it
# could sit 400px off-center forever and every press would call it
# centered -- exactly backwards, since a composition bigger than the
# screen is the one case where most of it is off-screen and being centered
# actually matters. The viewport is the thing the user is looking THROUGH,
# so it is the only frame in which "off center" means anything to them.
#
# 0.15 of this display's 1080px short side is ~162px. The number is a
# perceptual threshold, not a fitted one: a composition whose center sits
# within about a sixth of the screen's short side of the screen's own
# center reads as centered to the eye, and moving every window to correct
# a bias that small is churn the user did not ask for. Past it the cluster
# visibly sits off to one side. It is also orders of magnitude above the
# sub-pixel rounding noise that would otherwise nudge a settled workspace
# on every press, and comfortably below the ~400px residual on a large
# composition that exposed the bbox-relative version of this as wrong.
# Recentering is idempotent at any tolerance (after one press the offset
# is exactly zero), so this only decides how much drift is tolerated --
# never whether repeated presses converge.
RECENTER_TOLERANCE_FACTOR = 0.15


def _shape_is_coherent(eligible, fixed_rects, gap):
    """Is the composition's own SHAPE already good -- overlap validity,
    adjacency-graph connectivity, per-cluster aspect ratio? Deliberately
    says NOTHING about where that composition sits relative to the
    viewport -- that half is _recenter_shift's job.

    The split matters and is the whole basis of SUPER+G's viewport
    behavior: on an infinite canvas "this arrangement is good" and "this
    arrangement is currently on screen" are independent facts. A perfectly
    good composition that the user has simply panned away from is not a
    layout problem at all -- it needs the CAMERA brought back, not the
    windows rebuilt. Before this split, being off-screen made the whole
    check return False, which sent a perfectly good arrangement through a
    full incremental rebuild and reshuffled it for no reason, purely
    because the viewport had moved. `fixed_rects`: already-converted
    (x0,y0,x1,y1) rects."""
    if len(eligible) <= 1:
        return True
    rects = {w["address"]: rect_for(w["at"][0], w["at"][1], w["size"][0], w["size"][1]) for w in eligible}
    all_rects = list(rects.values())

    for i in range(len(all_rects)):
        inflated = (all_rects[i][0] - gap, all_rects[i][1] - gap, all_rects[i][2] + gap, all_rects[i][3] + gap)
        for j in range(len(all_rects)):
            if i != j and overlaps(inflated, all_rects[j]):
                return False
        for f in fixed_rects:
            if overlaps(inflated, f):
                return False

    addrs = list(rects.keys())
    adjacency = {a: set() for a in addrs}
    for i in range(len(addrs)):
        for j in range(i + 1, len(addrs)):
            a, b = addrs[i], addrs[j]
            coverage = _flush_coverage(rects[a], rects[b], gap)
            if coverage is not None and coverage >= ADJACENCY_COVERAGE_THRESHOLD:
                adjacency[a].add(b)
                adjacency[b].add(a)

    # Connected COMPONENTS, plural -- not one required global component.
    # Live-verified false negative: two individually-perfect, already-
    # centered 2x2 grids sitting apart from each other (e.g. one app's
    # windows grouped on the left, an unrelated app's grouped on the
    # right -- a deliberate, sensible arrangement, not a mistake) used to
    # get rearranged into one supercluster, moving every window by
    # thousands of pixels, purely because requiring ALL windows to share
    # ONE component conflated "coherent" with "connected to everything
    # else," which are not the same claim (see this function's own module
    # comment). Multiple components are fine PROVIDED each non-trivial one
    # (2+ windows) is itself a reasonably-shaped local cluster, and most
    # windows aren't each their own isolated singleton -- that second
    # condition is what still correctly rejects a genuinely SCATTERED
    # desktop (many windows with no real neighbor at all), which is a
    # real bad case this check must not start calling "coherent" just for
    # having relaxed the single-component requirement.
    unvisited = set(addrs)
    components = []
    while unvisited:
        start = next(iter(unvisited))
        seen, stack = set(), [start]
        while stack:
            addr = stack.pop()
            if addr in seen:
                continue
            seen.add(addr)
            stack.extend(adjacency[addr] - seen)
        components.append(seen)
        unvisited -= seen

    def edge_gap(r1, r2):
        xg = max(r1[0] - r2[2], r2[0] - r1[2], 0)
        yg = max(r1[1] - r2[3], r2[1] - r1[3], 0)
        return math.hypot(xg, yg) if (xg and yg) else max(xg, yg)

    singletons = [c for c in components if len(c) == 1]
    # At most a small handful of genuinely isolated windows (an
    # intentional standalone dialog or two) may coexist with real
    # clusters; if MOST windows have no real neighbor at all, that's a
    # scattered desktop, not a collection of deliberate small clusters.
    if len(singletons) > max(1, len(addrs) // 4):
        return False
    # A singleton only reads as a DELIBERATE standalone dialog when it
    # actually sits apart -- live-verified false positive: a window
    # merely a few dozen pixels past its would-be flush-adjacency gap
    # (72px, on a 400x300 window) still reads as "should be tucked into
    # the cluster it's right next to," not "intentionally separate,"
    # even though it technically fails the strict flush-adjacency test.
    # Self-relative (own smaller dimension), not a flat pixel count, so
    # this scales sensibly across dialog and main-window sizes alike.
    for singleton in singletons:
        addr = next(iter(singleton))
        r = rects[addr]
        own_short = max(min(r[2] - r[0], r[3] - r[1]), 1.0)
        nearest = min((edge_gap(r, rects[other]) for other in addrs if other != addr), default=float("inf"))
        if nearest < own_short:
            return False  # close enough to a neighbor that it reads as unfinished, not deliberate

    for component in components:
        if len(component) < 2:
            continue
        member_rects = [rects[a] for a in component]
        cxs0 = [r[0] for r in member_rects]; cys0 = [r[1] for r in member_rects]
        cxs1 = [r[2] for r in member_rects]; cys1 = [r[3] for r in member_rects]
        c_w, c_h = max(cxs1) - min(cxs0), max(cys1) - min(cys0)
        c_long, c_short = max(c_w, c_h), max(min(c_w, c_h), 1.0)
        if c_long / c_short > ALREADY_GOOD_ASPECT_RATIO_MAX:
            return False  # this specific cluster is itself a bad (e.g. axis-concentrated) shape

    return True


def _recenter_shift(eligible, fixed_rects, viewport_center, viewport_size, gap):
    """The single rigid (dx, dy) that brings the composition's own bounding
    box center onto `viewport_center` -- i.e. what moving the CAMERA to look
    at the workspace would amount to, expressed the only way a compositor
    with no camera of its own can express it.

    Returns (0.0, 0.0) when the composition is already within tolerance, so
    an already-centered workspace is left byte-identical rather than nudged
    by a pixel or two every press.

    This is deliberately ONE uniform translation applied to every window:
    every relative position, gap and adjacency in the composition is
    preserved exactly, which is what makes it a viewport move rather than a
    re-layout. Scaled down (never up) if applying it in full would push the
    group into a FIXED fullscreen obstacle -- "no overlaps" outranks
    "centered," the same precedence auto_arrange's own final recenter
    already uses."""
    if not eligible:
        return (0.0, 0.0)
    rects = [rect_for(w["at"][0], w["at"][1], w["size"][0], w["size"][1]) for w in eligible]
    xs0 = [r[0] for r in rects]; ys0 = [r[1] for r in rects]
    xs1 = [r[2] for r in rects]; ys1 = [r[3] for r in rects]
    viewport_short_side = max(min(viewport_size[0], viewport_size[1]), 1.0)

    bbox_cx, bbox_cy = (min(xs0) + max(xs1)) / 2, (min(ys0) + max(ys1)) / 2
    dx = viewport_center[0] - bbox_cx
    dy = viewport_center[1] - bbox_cy
    if math.hypot(dx, dy) <= viewport_short_side * RECENTER_TOLERANCE_FACTOR:
        return (0.0, 0.0)

    just_rects = [(w["at"][0], w["at"][1], w["size"][0], w["size"][1]) for w in eligible]
    if fixed_rects and not _shift_is_safe(just_rects, (dx, dy), fixed_rects, gap):
        lo, hi = 0.0, 1.0
        for _ in range(20):
            mid = (lo + hi) / 2
            if _shift_is_safe(just_rects, (dx * mid, dy * mid), fixed_rects, gap):
                lo = mid
            else:
                hi = mid
        dx, dy = dx * lo, dy * lo
    return (float(round(dx)), float(round(dy)))


# A window's area ratio to the next larger one, above which they're
# considered different SIZE CLASSES rather than variations of the same
# class -- e.g. a 1600x1000 main window and a 250x150 dialog (ratio ~43x)
# are obviously different classes; four 900x700 windows and one 850x680
# one (ratio ~1.1x) are obviously the same class. 2.25 matches
# RESIZE_ELIGIBLE_RATIO_FLOOR's own area-ratio (1.5 linear, squared) --
# the same "meaningfully bigger" boundary already established and tested
# for deciding whether ONE window is oversized is reused here to decide
# whether TWO windows belong to the same size class, rather than
# inventing an unrelated second number.
SIZE_CLASS_RATIO = RESIZE_ELIGIBLE_RATIO_FLOOR ** 2


def _typical_area(eligible):
    """The reference "typical window size" for the whole pass -- used both
    for composition mass-weighting (window_mass) and resize eligibility
    (_mass_ratio). NOT a flat population median: a live random-layout
    benchmark found a real bug in that model -- 14 tiny dialogs
    numerically outvoting the ONE main window drags a population median
    down near the dialogs' own size, making an entirely ordinary main
    window look "5x oversized" and eligible for repeated SUPER+G
    resizing purely because of how many small utility windows happened to
    be open, not because it was actually too big for anything.

    Fixed by asking a different, more representative question: which
    SIZE CLASS actually occupies the most of the desktop, by total area,
    not by window count? Windows are grouped into classes by area ratio
    (see SIZE_CLASS_RATIO); the class with the greatest COMBINED area
    wins, and that class's own median area is the reference. This
    correctly recognizes a lone 1600x1000 window as its own, entirely
    legitimate size class (its class's total area, 1.6M, beats 14 tiny
    dialogs' combined ~400-500K, so it becomes its own reference and
    reads as "typical," not "oversized") while still correctly picking
    the dominant class when there genuinely are several similarly-large
    windows (8x 900x700 outweighs 1 tiny dialog by total area either
    way, same as the old median already handled correctly). Verified
    against both distributions explicitly, not assumed.

    Falls back to the single-cluster case (equivalent to a population
    median within that one cluster) whenever every window's area is
    within SIZE_CLASS_RATIO of its neighbors -- i.e. this is a strict
    refinement of the old model for the case it got right, not a
    different formula that happens to also work there.
    """
    areas = sorted(w["size"][0] * w["size"][1] for w in eligible)
    if not areas:
        return 1.0
    clusters = [[areas[0]]]
    for a in areas[1:]:
        if a / clusters[-1][-1] <= SIZE_CLASS_RATIO:
            clusters[-1].append(a)
        else:
            clusters.append([a])
    dominant = max(clusters, key=sum)
    mid = len(dominant) // 2
    return dominant[mid] if len(dominant) % 2 else (dominant[mid - 1] + dominant[mid]) / 2


def auto_arrange(eligible, fixed, monitor_bounds, gap, allow_resize=True):
    """eligible / fixed: [{"address":..., "at":[x,y], "size":[w,h]}, ...].
    Returns [(address, new_x, new_y, new_w, new_h), ...] for EVERY eligible
    window (not just ones that changed -- the caller compares against each
    window's own original position/size to decide what actually needs
    dispatching). Size differs from the input only for a window this pass
    decided to resize (see _choose_size_and_position); every other window's
    size is returned unchanged.

    allow_resize=False computes POSITIONS ONLY against the sizes given,
    proposing no size changes at all. main() uses this for its second pass
    after a resize has actually landed, so the final positions are always
    computed against the sizes windows REALLY ended up with rather than the
    ones that were requested -- see main() for the gap bug that requires.
    """
    if not eligible:
        return []

    mx0, my0, mx1, my1 = monitor_bounds
    viewport_center = ((mx0 + mx1) / 2, (my0 + my1) / 2)

    fixed_rects_precheck = [rect_for(w["at"][0], w["at"][1], w["size"][0], w["size"][1]) for w in fixed]
    if _shape_is_coherent(eligible, fixed_rects_precheck, gap):
        # The arrangement itself is already good. The only things that can
        # still be wrong are WHERE THE CAMERA IS, and whether some window is
        # disproportionately sized.
        #
        # Taking the camera-only shortcut is provably equivalent to the full
        # path exactly when no window is even resize-ELIGIBLE: eligibility
        # (see RESIZE_ELIGIBLE_RATIO_FLOOR) is a hard precondition for every
        # resize candidate the incremental build can generate, so if nothing
        # clears it there is definitively no size decision available to
        # make, and the rebuild could only ever have reproduced the same
        # sizes it started with. When something IS eligible, fall through
        # and let the real objective -- including the whole-composition
        # resize comparison -- decide, rather than silently skipping a size
        # question this shortcut isn't entitled to answer.
        dx, dy = _recenter_shift(eligible, fixed_rects_precheck, viewport_center,
                                 (mx1 - mx0, my1 - my0), gap)
        unchanged = [(w["address"], w["at"][0], w["at"][1], w["size"][0], w["size"][1])
                     for w in eligible]
        if (dx, dy) == (0.0, 0.0):
            # Good shape AND already on screen: nothing to do, full stop.
            # This unconditional no-op is also what keeps repeated presses
            # from compounding a resize -- once a pass has settled a window
            # to a new size and centred the result, the next press must not
            # get another opinion about that size.
            return unchanged
        reference_area = _typical_area(eligible)
        nothing_resizable = all(
            _mass_ratio(w["size"][0], w["size"][1], reference_area) <= RESIZE_ELIGIBLE_RATIO_FLOOR
            for w in eligible)
        if nothing_resizable:
            return [(a, x + dx, y + dy, w, h) for a, x, y, w, h in unchanged]

    def raw_center(w):
        return (w["at"][0] + w["size"][0] / 2, w["at"][1] + w["size"][1] / 2)

    orig_cx = sum(raw_center(w)[0] for w in eligible) / len(eligible)
    orig_cy = sum(raw_center(w)[1] for w in eligible) / len(eligible)

    def bearing_of(w):
        cx, cy = raw_center(w)
        dx, dy = cx - orig_cx, cy - orig_cy
        dist = math.hypot(dx, dy)
        return (0.0, 0.0) if dist < 1e-6 else (dx / dist, dy / dist)

    # Deterministic, position-independent order -- NOT distance to any
    # centroid, which depends on where the windows currently are and can
    # rank them differently between two runs on nearly-identical layouts
    # (a small position difference reshuffles who's "closest"), cascading
    # into a genuinely different rebuild each time even when nothing
    # actually needed to change. Largest window first (matching the
    # convention dxrice_align_windows.py's own resolver already used),
    # ties broken by address, so the exact same set of windows always
    # processes in the exact same order regardless of their positions.
    def sort_key(w):
        return (-(w["size"][0] * w["size"][1]), w["address"])

    ordered = sorted(eligible, key=sort_key)

    reference_area = _typical_area(eligible)
    fixed_rects = [rect_for(*_xywh(w)) for w in fixed]

    def _build(allow_resize):
        """Runs the full incremental build once, either allowing resize
        decisions or not, and returns the finished [(addr,x,y,w,h), ...].
        Factored out so auto_arrange can run it TWICE (see the real
        whole-composition comparison right after this function) -- see
        that comparison's own comment for why a second run is necessary
        at all."""
        placed = {}  # {address: (x, y, w, h)} -- FINAL geometry, mutated in place when
                     # a neighbor is chosen as a resize target at a later step
        resized_addrs = set()  # each window may be a resize target at most once per pass
        cluster_bbox = None

        for i, w in enumerate(ordered):
            addr = w["address"]
            if i == 0:
                # Nothing placed yet -- no cluster to be compact with or bear
                # a direction from, and no already-placed neighbor exists to
                # offer as a resize candidate either. Finds the closest free
                # spot to its own current position, respecting only the FIXED
                # obstacles.
                bearing_unit = (0.0, 0.0)
                cluster_centroid = viewport_center  # unused when bearing_unit is (0,0)
            else:
                bearing_unit = bearing_of(w)
                n = len(placed)
                cluster_centroid = (
                    sum(x + ww / 2 for x, y, ww, hh in placed.values()) / n,
                    sum(y + hh / 2 for x, y, ww, hh in placed.values()) / n,
                )
            chosen_size, pos, neighbor_resize = _choose_size_and_position(
                w, raw_center(w), bearing_unit, cluster_centroid, cluster_bbox,
                placed, fixed_rects, viewport_center, reference_area, gap, resized_addrs,
                allow_resize=allow_resize)
            # Rounded to integers THE MOMENT a position is decided, before it
            # can be used as the geometric basis (an edge/corner candidate) for
            # any LATER window in this same pass. Found live: two windows meant
            # to be exactly gap-apart came out 1px short after dispatch --
            # traced to a fractional position surviving from one window's own
            # placement, inherited by a later window's candidate generation
            # (which crosses EVERY already-placed window's edges), then
            # compounding through the chain. A fractional pixel offset the same
            # for two windows cancels out of their gap exactly; two DIFFERENT
            # fractional offsets, each independently rounded at dispatch time,
            # do not. Rounding here, once, keeps every candidate downstream
            # exact-integer, so relative gaps can never drift.
            pos = (round(pos[0]), round(pos[1]))
            if neighbor_resize is not None:
                n_addr, nx2, ny2, snw, snh = neighbor_resize
                placed[n_addr] = (nx2, ny2, snw, snh)
                resized_addrs.add(n_addr)
            placed[addr] = (pos[0], pos[1], chosen_size[0], chosen_size[1])
            rect = rect_for(pos[0], pos[1], chosen_size[0], chosen_size[1])
            cluster_bbox = rect if cluster_bbox is None else (
                min(cluster_bbox[0], rect[0]), min(cluster_bbox[1], rect[1]),
                max(cluster_bbox[2], rect[2]), max(cluster_bbox[3], rect[3]),
            )

        # Rigid recenter: one (dx, dy) applied to every eligible window's
        # POSITION (never its size -- resize decisions are already final by
        # this point) so the cluster's bounding box lands on the viewport
        # center -- scaled down (binary search) if the full shift would newly
        # overlap a fixed window.
        xs0 = [v[0] for v in placed.values()]; ys0 = [v[1] for v in placed.values()]
        xs1 = [v[0] + v[2] for v in placed.values()]; ys1 = [v[1] + v[3] for v in placed.values()]
        bbox_cx, bbox_cy = (min(xs0) + max(xs1)) / 2, (min(ys0) + max(ys1)) / 2
        full_shift = (viewport_center[0] - bbox_cx, viewport_center[1] - bbox_cy)

        just_rects = list(placed.values())
        if fixed_rects and not _shift_is_safe(just_rects, full_shift, fixed_rects, gap):
            lo, hi = 0.0, 1.0
            for _ in range(20):
                mid = (lo + hi) / 2
                trial = (full_shift[0] * mid, full_shift[1] * mid)
                if _shift_is_safe(just_rects, trial, fixed_rects, gap):
                    lo = mid
                else:
                    hi = mid
            full_shift = (full_shift[0] * lo, full_shift[1] * lo)

        # Rounded once, applied to every window identically -- since `placed`
        # is already exact-integer (see above), adding the SAME integer shift
        # to all of them can never perturb a relative gap between any two.
        shift_x, shift_y = round(full_shift[0]), round(full_shift[1])
        # A fixed-obstacle-scaled shift (the branch above) was deliberately
        # found to be exactly at the edge of safe -- rounding it could in
        # principle nudge it the wrong way. "No overlaps" is a hard, always-on
        # invariant in this file (see this function's own module docstring),
        # so re-verify after rounding and fall back to truncating toward zero
        # (strictly more conservative than round-to-nearest, never less) if
        # rounding-to-nearest happened to cross the line.
        if fixed_rects and not _shift_is_safe(just_rects, (shift_x, shift_y), fixed_rects, gap):
            shift_x, shift_y = math.trunc(full_shift[0]), math.trunc(full_shift[1])

        return [(address, x + shift_x, y + shift_y, w, h) for address, (x, y, w, h) in placed.items()]

    result = _build(allow_resize=allow_resize)

    orig_sizes = {w["address"]: tuple(w["size"]) for w in eligible}
    any_resize = any((w, h) != orig_sizes[a] for a, x, y, w, h in result)
    if not any_resize:
        return result

    # A resize decided by ONE incremental step is only ever compared
    # against THAT step's own local baseline (see _choose_size_and_position
    # and its resize_threshold) -- a real, live-instrumented investigation
    # (per an explicit request to prove resize necessity, not just assume
    # the per-step margin already guarantees it) found this is NOT the
    # same claim as "the resize made the FINAL, WHOLE composition better":
    # across 20 seeded variations of "1 lone large window + several
    # medium/typical ones," resize fired in 16 and the completed result's
    # own composition_cost was actually WORSE than simply disabling resize
    # entirely in 9 of those 16 -- a later window's incremental step can
    # locally justify shrinking an earlier-placed neighbor using only the
    # geometry visible AT THAT STEP, while the REST of the incremental
    # build (still to come) ends up not needing the freed space the way
    # that one step's local comparison assumed it would. This is exactly
    # the gap between "compare the candidate's local score" and "compare
    # the two COMPLETE alternatives" -- closed here by actually building
    # BOTH complete alternatives (this function already has everything
    # needed to do so cheaply, since it's the exact same _build call with
    # allow_resize toggled) and only keeping the resize-enabled result
    # when it's a REAL, whole-composition improvement -- not merely
    # "resize fired," which the evidence above shows is not sufficient.
    # Only pays this doubled cost on the minority of calls where a resize
    # was even considered; the common (no resize) case returns above.
    result_moveonly = _build(allow_resize=False)

    def _final_cost(built):
        by_addr = {a: (x, y, w, h) for a, x, y, w, h in built}
        pts = [(x + w / 2, y + h / 2, w, h, window_mass(w, h, reference_area)) for x, y, w, h in by_addr.values()]
        comp = composition_cost(pts, viewport_center)
        movement = sum(
            math.hypot(x + w / 2 - (orig["at"][0] + orig["size"][0] / 2),
                       y + h / 2 - (orig["at"][1] + orig["size"][1] / 2))
            * window_mass(orig["size"][0], orig["size"][1], reference_area)
            for orig in eligible for x, y, w, h in [by_addr[orig["address"]]]
        )
        return comp + MOVEMENT_WEIGHT * movement

    cost_resize = _final_cost(result)
    cost_moveonly = _final_cost(result_moveonly)
    if cost_resize < cost_moveonly * (1.0 - SUPER_G_RESIZE_MARGIN_FRACTION):
        return result
    return result_moveonly


def _xywh(w):
    return (w["at"][0], w["at"][1], w["size"][0], w["size"][1])


def _settle_sizes(addresses, workspace_id, timeout=1.0, poll=0.02):
    """Re-read this workspace until every address in `addresses` reports the
    same size on two consecutive reads, then return the fresh floating
    client list (or None if it can't be read).

    Waits for STABILITY, never for a specific requested size -- that
    distinction is the entire point. A client may legitimately decline the
    size it was asked for (a terminal quantised to character cells, a
    window with a minimum size), so waiting for the requested size would
    burn the whole timeout AND still hand back geometry that never
    happened. Two consecutive agreeing reads mean "this client has finished
    reacting," whatever it actually decided to become.

    The timeout is a ceiling against a pathologically animated client, not
    an estimate of how long a resize takes; the common case agrees within a
    poll or two."""
    remaining = set(addresses)
    last_seen = {}
    clients = None
    deadline = time.time() + timeout
    while time.time() < deadline:
        fresh = hyprctl_json(["clients"])
        if fresh:
            clients = fresh
            for w in fresh:
                addr = w.get("address")
                if addr in remaining:
                    size = tuple(w.get("size", ()))
                    if last_seen.get(addr) == size:
                        remaining.discard(addr)
                    last_seen[addr] = size
        if not remaining:
            break
        time.sleep(poll)
    if clients is None:
        return None
    return [w for w in clients
            if w.get("floating") and w.get("workspace", {}).get("id") == workspace_id]


def main():
    ws = hyprctl_json(["activeworkspace"])
    if not ws:
        print("Could not get the active workspace.", file=sys.stderr)
        sys.exit(1)
    workspace_id = ws["id"]

    clients = hyprctl_json(["clients"]) or []
    floating = [w for w in clients
                if w.get("floating") and w.get("workspace", {}).get("id") == workspace_id]
    if len(floating) < 2:
        print("Fewer than 2 floating windows here -- nothing to arrange.")
        return

    eligible = [w for w in floating if not w.get("fullscreen")]
    fixed = [w for w in floating if w.get("fullscreen")]

    if _DEBUG:
        print(f"DEBUG eligible={len(eligible)} fixed(fullscreen)={len(fixed)}", file=sys.stderr)

    if len(eligible) < 1:
        print("Nothing eligible to arrange (everything is fullscreen/maximized).")
        return

    gap = live_gap()
    monitor = get_monitor_bounds()

    results = auto_arrange(eligible, fixed, monitor, gap)

    THRESHOLD = 1.0  # sub-pixel differences from floating point aren't a real move/resize
    by_addr = {w["address"]: w for w in eligible}
    resize_exprs = []
    for address, nx, ny, nw, nh in results:
        ow, oh = by_addr[address]["size"]
        if abs(nw - ow) > THRESHOLD or abs(nh - oh) > THRESHOLD:
            resize_exprs.append((address, int(round(nw)), int(round(nh))))

    resized = len(resize_exprs)
    if resize_exprs:
        # A window is free to NOT become the size it was asked for. Clients
        # with size increments (a terminal quantised to whole character
        # cells) or a minimum size land on their own nearest legal size
        # instead -- and every neighbour's position in `results` was
        # computed assuming the REQUESTED size, so whatever the client
        # actually did shows up on screen as a dead strip that no amount of
        # looking at it fixes. (It only ever corrected itself when the user
        # nudged a window and pressed SUPER+G again -- because THAT run
        # finally read the real sizes. This is that bug.)
        #
        # So: land the resizes first, wait for the sizes to stop moving,
        # then compute the final positions against what the windows really
        # became. Second pass is positions-only (allow_resize=False), so
        # this can't turn into a resize feedback loop, and it costs nothing
        # on the overwhelmingly common no-resize path, which returns above
        # without ever getting here.
        batch_async([resize_window_exact_lua(w, h, a) for a, w, h in resize_exprs])
        settled = _settle_sizes([a for a, _, _ in resize_exprs], workspace_id)
        if settled:
            eligible = [w for w in settled
                        if not w.get("fullscreen") and w.get("address") in by_addr]
            fixed = [w for w in settled if w.get("fullscreen")]
            if eligible:
                results = auto_arrange(eligible, fixed, monitor, gap, allow_resize=False)
                by_addr = {w["address"]: w for w in eligible}

    exprs = []
    moved = 0
    for address, nx, ny, nw, nh in results:
        w = by_addr.get(address)
        if not w:
            continue
        ox, oy = w["at"]
        ow, oh = w["size"]
        size_changed = abs(nw - ow) > THRESHOLD or abs(nh - oh) > THRESHOLD
        pos_changed = abs(nx - ox) > THRESHOLD or abs(ny - oy) > THRESHOLD
        if size_changed:
            # Resize first (Hyprland's own floating-window resize is
            # center-anchored, same fact Stage 3 relies on), THEN move to
            # the exact top-left this pass actually scored against -- never
            # rely on Hyprland's own anchor matching what was computed here.
            exprs.append(resize_window_exact_lua(int(round(nw)), int(round(nh)), address))
        if size_changed or pos_changed:
            exprs.append(move_window_exact_lua(int(round(nx)), int(round(ny)), address))
            moved += 1
        if _DEBUG:
            print(f"DEBUG {w.get('title','')[:30]!r} ({ox},{oy},{ow}x{oh}) -> "
                  f"({nx:.0f},{ny:.0f},{nw:.0f}x{nh:.0f})", file=sys.stderr)

    if exprs:
        batch_async(exprs)
    print(f"Arranged {len(eligible)} window(s); {moved} moved, {resized} resized, "
          f"{max(0, len(eligible) - moved)} already in place.")
    if fixed:
        print(f"Left {len(fixed)} fullscreen/maximized window(s) untouched.")


if __name__ == "__main__":
    main()
