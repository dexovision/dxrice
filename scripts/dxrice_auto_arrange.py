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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dxrice_hypr_ipc import hyprctl_json, batch_async, move_window_exact_lua, resize_window_exact_lua
from dxrice_auto_place_window import (get_monitor_bounds, live_gap, rect_for, overlaps,
                                       composition_penalty, composition_cost, window_mass, mass_center,
                                       MIN_USABLE_WIDTH, MIN_USABLE_HEIGHT, MAX_SHRINK_FRACTION)

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
    for (ox0, oy0, ox1, oy1) in obstacle_rects:
        xs.update((ox0, ox1, ox0 - nw - gap, ox1 + gap))
        ys.update((oy0, oy1, oy0 - nh - gap, oy1 + gap))

    candidates = [(x, y) for x in xs for y in ys if free(x, y)]

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

    best = min(candidates, key=lambda p: score(*p))
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
                               placed, fixed_rects, viewport_center, reference_area, gap, resized_addrs):
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
    if cluster_bbox is not None and _mass_ratio(own_w, own_h, reference_area) > RESIZE_ELIGIBLE_RATIO_FLOOR:
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
    for n_addr, (nx, ny, nw_, nh_) in placed.items():
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


def auto_arrange(eligible, fixed, monitor_bounds, gap):
    """eligible / fixed: [{"address":..., "at":[x,y], "size":[w,h]}, ...].
    Returns [(address, new_x, new_y, new_w, new_h), ...] for EVERY eligible
    window (not just ones that changed -- the caller compares against each
    window's own original position/size to decide what actually needs
    dispatching). Size differs from the input only for a window this pass
    decided to resize (see _choose_size_and_position); every other window's
    size is returned unchanged.
    """
    if not eligible:
        return []

    mx0, my0, mx1, my1 = monitor_bounds
    viewport_center = ((mx0 + mx1) / 2, (my0 + my1) / 2)

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

    # A shared "typical window size" for the whole pass, so every window's
    # mass in the global composition term is weighed against the same
    # yardstick regardless of placement order -- median rather than mean
    # so one unusually large or small window in the group doesn't skew
    # what "typical" means for everyone else's weighting.
    areas = sorted(w["size"][0] * w["size"][1] for w in eligible)
    mid = len(areas) // 2
    reference_area = areas[mid] if len(areas) % 2 else (areas[mid - 1] + areas[mid]) / 2

    fixed_rects = [rect_for(*_xywh(w)) for w in fixed]
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
            placed, fixed_rects, viewport_center, reference_area, gap, resized_addrs)
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

    results = []
    for address, (x, y, w, h) in placed.items():
        results.append((address, x + shift_x, y + shift_y, w, h))
    return results


def _xywh(w):
    return (w["at"][0], w["at"][1], w["size"][0], w["size"][1])


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

    exprs = []
    moved = 0
    resized = 0
    THRESHOLD = 1.0  # sub-pixel differences from floating point aren't a real move/resize
    by_addr = {w["address"]: w for w in eligible}
    for address, nx, ny, nw, nh in results:
        w = by_addr[address]
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
            resized += 1
        if size_changed or pos_changed:
            exprs.append(move_window_exact_lua(int(round(nx)), int(round(ny)), address))
            if not size_changed:
                moved += 1
        if _DEBUG:
            print(f"DEBUG {w.get('title','')[:30]!r} ({ox},{oy},{ow}x{oh}) -> "
                  f"({nx:.0f},{ny:.0f},{nw:.0f}x{nh:.0f})", file=sys.stderr)

    if exprs:
        batch_async(exprs)
    print(f"Arranged {len(eligible)} window(s); {moved} moved, {resized} resized, "
          f"{len(eligible) - moved - resized} already in place.")
    if fixed:
        print(f"Left {len(fixed)} fullscreen/maximized window(s) untouched.")


if __name__ == "__main__":
    main()
