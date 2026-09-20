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
  5. Dispatches every actual position change in ONE batched IPC call, so
     the whole rearrangement happens together rather than windows visibly
     sliding into place one at a time.

This is a one-shot layout pass, not an ongoing constraint -- dragging a
window wherever you want immediately afterward works exactly as always.
Never resizes anything, only repositions. The infinite canvas has no
boundary here: the viewport center is a target, never a containment box,
and windows routinely end up (partially or fully) outside it when that's
where the compact arrangement actually lands.
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dxrice_hypr_ipc import hyprctl_json, batch_async, move_window_exact_lua
from dxrice_auto_place_window import (get_monitor_bounds, live_gap, rect_for, overlaps,
                                       composition_penalty, composition_cost, window_mass, mass_center)

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
            if ring > 500:
                return (cx0 - nw / 2, cy0 - nh / 2)

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

    return min(candidates, key=lambda p: score(*p))


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
    Returns [(address, new_x, new_y), ...] for windows that actually moved.
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

    obstacle_rects = [rect_for(*_xywh(w)) for w in fixed]
    placed = []  # [(address, x, y, w, h)]
    placed_points = []  # [(cx, cy, mass), ...] -- same entries as `placed`, composition-ready
    cluster_bbox = None

    for i, w in enumerate(ordered):
        size = tuple(w["size"])
        if i == 0:
            # Nothing placed yet -- no cluster to be compact with or bear
            # a direction from. Finds the closest free spot to its own
            # current position, respecting only the FIXED obstacles.
            bearing_unit = (0.0, 0.0)
            cluster_centroid = viewport_center  # unused when bearing_unit is (0,0)
        else:
            bearing_unit = bearing_of(w)
            n = len(placed)
            cluster_centroid = (
                sum(p[1] + p[3] / 2 for p in placed) / n,
                sum(p[2] + p[4] / 2 for p in placed) / n,
            )
        pos = _find_best_position(size, obstacle_rects, gap, raw_center(w), bearing_unit, cluster_centroid,
                                   cluster_bbox, placed_points, viewport_center, reference_area)
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
        placed.append((w["address"], pos[0], pos[1], size[0], size[1]))
        rect = rect_for(pos[0], pos[1], size[0], size[1])
        obstacle_rects.append(rect)
        placed_points.append((pos[0] + size[0] / 2, pos[1] + size[1] / 2, size[0], size[1],
                               window_mass(size[0], size[1], reference_area)))
        cluster_bbox = rect if cluster_bbox is None else (
            min(cluster_bbox[0], rect[0]), min(cluster_bbox[1], rect[1]),
            max(cluster_bbox[2], rect[2]), max(cluster_bbox[3], rect[3]),
        )

    # Rigid recenter: one (dx, dy) applied to every eligible window so the
    # cluster's bounding box lands on the viewport center -- scaled down
    # (binary search) if the full shift would newly overlap a fixed window.
    xs0 = [p[1] for p in placed]; ys0 = [p[2] for p in placed]
    xs1 = [p[1] + p[3] for p in placed]; ys1 = [p[2] + p[4] for p in placed]
    bbox_cx, bbox_cy = (min(xs0) + max(xs1)) / 2, (min(ys0) + max(ys1)) / 2
    full_shift = (viewport_center[0] - bbox_cx, viewport_center[1] - bbox_cy)

    fixed_rects = [rect_for(*_xywh(w)) for w in fixed]
    just_rects = [(p[1], p[2], p[3], p[4]) for p in placed]
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
    for address, x, y, w, h in placed:
        results.append((address, x + shift_x, y + shift_y))
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
    THRESHOLD = 1.0  # sub-pixel differences from floating point aren't a real move
    by_addr = {w["address"]: w for w in eligible}
    for address, nx, ny in results:
        w = by_addr[address]
        ox, oy = w["at"]
        if abs(nx - ox) > THRESHOLD or abs(ny - oy) > THRESHOLD:
            exprs.append(move_window_exact_lua(int(round(nx)), int(round(ny)), address))
            moved += 1
        if _DEBUG:
            print(f"DEBUG {w.get('title','')[:30]!r} ({ox},{oy}) -> ({nx:.0f},{ny:.0f})", file=sys.stderr)

    if exprs:
        batch_async(exprs)
    print(f"Arranged {len(eligible)} window(s); {moved} moved, {len(eligible) - moved} already in place.")
    if fixed:
        print(f"Left {len(fixed)} fullscreen/maximized window(s) untouched.")


if __name__ == "__main__":
    main()
