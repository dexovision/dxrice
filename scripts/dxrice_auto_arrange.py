#!/usr/bin/env python3
"""SUPER+G -- arrange the desktop as an airy spiral.

Rearranges the floating windows of the active workspace into one
composition: the most prominent window at the hub, the rest winding round
it in a single sweep, bigger windows nearer the middle, neighbours a
composition spacing apart (16-24 px by default, theme.json's
window_spacing_min/max -- separate from Hyprland's gaps_in). The composer
itself, shared with new-window placement, is dxrice_spiral; this file is
SUPER+G's side of it:

  1. Splits the workspace's floating windows into ELIGIBLE (arranged) and
     FIXED (fullscreen/maximized: never moved, still obstacles everyone
     else stays clear of) -- dxrice_window_class.partition.
  2. Composes (auto_arrange): the spiral build, or the current layout kept
     as it is when a rebuild would be no real improvement -- which is also
     what makes a second press a no-op. The composition's bounding box is
     recentred on the viewport (one rigid shift; scaled back if it would
     run into a fixed window). The infinite canvas has no boundary: the
     viewport centre is a target, never a containment box.
  3. Resizes conservatively: sizes are kept, except that one window per
     set of windows -- the most oversized one -- may shrink one bounded
     step when that makes the whole composition better including the
     cost of the shrink. A window DXrice has resized is locked
     (dxrice_resize_memory), and once any window of the set is, presses
     only move: nothing is ever trimmed twice.
  4. Dispatches every move and resize in one batch, re-planning positions
     against the sizes the clients actually took when a resize lands
     differently (main()), so the layout planned is the layout shown.

A one-shot pass, not an ongoing constraint: dragging a window anywhere
afterwards works as always.
"""
import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dxrice_hypr_ipc import hyprctl_json, batch_async, move_window_exact_lua, resize_window_exact_lua
import dxrice_window_class
import dxrice_spiral
from dxrice_resize_memory import (resize_state_path as _resize_state_path,
                                  load_resize_state as _load_resize_state,
                                  save_resize_state as _save_resize_state,
                                  size_matches as _size_matches,
                                  locked_addresses as _locked_addresses,
                                  next_resize_state as _next_resize_state)
from dxrice_auto_place_window import (get_monitor_bounds, live_gap, rect_for, window_mass,
                                       MIN_USABLE_WIDTH, MIN_USABLE_HEIGHT, MAX_SHRINK_FRACTION)

_DEBUG = os.environ.get("DXRICE_DEBUG") == "1"


# ---- SUPER+G's bounded resize ----
#
# Sizes are kept by default. One window per set of windows may shrink: the
# most oversized one (RESIZE_ELIGIBLE_RATIO_FLOOR against the typical size,
# _typical_area), by one of RESIZE_SCALE_STEPS (never below the usable
# floor), and only when the whole composition including the shrink's own
# cost (_resize_fraction_cost) beats the move-only composition by
# SUPER_G_RESIZE_MARGIN_FRACTION. A window DXrice resized is locked
# (dxrice_resize_memory); while any window of the set is locked, or when
# the current layout is kept as already composed, nothing is resized.

# Scale factors tried for that one window (uniform, so the aspect ratio is
# kept), the deepest being MAX_SHRINK_FRACTION -- auto_arrange tries the
# first two.
RESIZE_SCALE_STEPS = (0.9, 0.8, 1.0 - MAX_SHRINK_FRACTION)

# Pixel-equivalent scale of a shrink's cost (see _resize_fraction_cost).
SUPER_G_RESIZE_COST_SCALE = 400.0

# The shrink is taken only when it beats the move-only composition by at
# least this fraction, not merely scores lower: no tiny numerical wins.
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
    disproportionately more. Scaled by `prominence` (window_mass: bounded,
    unlike Stage 2/3's prominence_weight), so a window well above the
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


def auto_arrange(eligible, fixed, monitor_bounds, gap, allow_resize=True, resize_locked=frozenset(),
                 spacing=None):
    """SUPER+G: [(address, x, y, w, h), ...] for every eligible window -- the
    airy spiral composition (see dxrice_spiral), recentred on the viewport,
    or the current layout recentred when a rebuild is no real improvement.

    `gap` is Hyprland's gaps_in; the composition spacing is separate
    (`spacing` = (min, max), default theme.json's window_spacing_min/max,
    see dxrice_spiral.read_spacing). Sizes are kept, except that at most one
    window -- the most oversized one not already resized by DXrice
    (resize_locked) -- may be shrunk one RESIZE_SCALE_STEPS step, when that
    makes the whole composition better by SUPER_G_RESIZE_MARGIN_FRACTION
    including the cost of the shrink. allow_resize=False: positions only
    (main()'s re-plan after a resize landed differently)."""
    if not eligible:
        return []
    band = spacing or dxrice_spiral.read_spacing()
    fixed_rects = [rect_for(*_xywh(w)) for w in fixed]
    rows, _comp, _wins, kept = dxrice_spiral.compose(eligible, fixed_rects, monitor_bounds, band)
    # A layout kept as already composed is final, sizes included: resizing
    # it would only restart the composition one press later.
    if not allow_resize or kept:
        return rows
    reference_area = _typical_area(eligible)
    oversized = [w for w in eligible if w["address"] not in resize_locked
                 and _mass_ratio(w["size"][0], w["size"][1], reference_area) > RESIZE_ELIGIBLE_RATIO_FLOOR]
    # One resize per set of windows: once DXrice has resized any of them
    # (resize memory), later presses only move -- so a press never trims a
    # second window after the first, and the layout converges.
    if not oversized or len(eligible) < 2 or any(w["address"] in resize_locked for w in eligible):
        return rows
    target = max(oversized, key=lambda w: (_mass_ratio(w["size"][0], w["size"][1], reference_area), w["address"]))
    base = dxrice_spiral.score_rows(rows, eligible, fixed_rects, monitor_bounds, band)
    prominence = window_mass(target["size"][0], target["size"][1], reference_area)
    best, best_cost = rows, base
    for scale in RESIZE_SCALE_STEPS[:2]:
        size = _usable_scaled_size(target["size"][0], target["size"][1], scale)
        if size is None:
            continue
        trial, _c, _w, _k = dxrice_spiral.compose(eligible, fixed_rects, monitor_bounds, band,
                                              sizes={target["address"]: size})
        cost = (dxrice_spiral.score_rows(trial, eligible, fixed_rects, monitor_bounds, band)
                + _resize_fraction_cost(scale, prominence))
        if cost < best_cost:
            best, best_cost = trial, cost
    if best is not rows and best_cost < base * (1.0 - SUPER_G_RESIZE_MARGIN_FRACTION):
        return best
    return rows


def join_composition(new_size, layout, obstacles, monitor_bounds, gap, spacing=None):
    """Where a newly opened window joins the composition: the same spacing,
    candidates and spiral preference as a SUPER+G build step (see
    dxrice_spiral.join), with every existing window held where it is --
    opening a window never moves or resizes another one; rebalancing the
    whole desktop stays SUPER+G's job.

    `layout`: [(x, y, w, h), ...] the visible windows it composes with;
    `obstacles`: every rect it must stay clear of (layout + fixed/fullscreen
    + windows out of view). `gap` (Hyprland's gaps_in) is accepted for the
    callers' sake; the spacing is the composition spacing. Returns the new
    window's integer top-left (x, y)."""
    band = spacing or dxrice_spiral.read_spacing()
    x, y = dxrice_spiral.join(new_size, layout, obstacles, monitor_bounds, band)
    return (int(round(x)), int(round(y)))


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
    # Same classification new-window placement uses: a tooltip, menu or
    # hover card that happens to be open at the moment of the press, or the
    # shell's own Wi-Fi dialog, is neither arranged nor arranged around.
    # Pinned windows are fixed, like fullscreen ones.
    scales = (dxrice_window_class.monitor_scales(hyprctl_json(["monitors"]))
              if any(c.get("xwayland") for c in clients) else [])
    kinds, x11 = dxrice_window_class.classify_all(clients, scales=scales)
    monitor = get_monitor_bounds()
    dxrice_window_class.settle_unknown(kinds, clients, (monitor[2] - monitor[0]) * (monitor[3] - monitor[1]))
    eligible, fixed = dxrice_window_class.partition(clients, workspace_id, kinds)
    # Dialogs that belong to another window (WM_TRANSIENT_FOR) are part of
    # that window, not members of the composition: they move with it.
    attached = dxrice_window_class.attached_children(clients, kinds, x11, scales)
    children = [w for w in eligible if attached.get(w["address"]) in {e["address"] for e in eligible}]
    eligible = [w for w in eligible if w not in children]
    if not eligible and not fixed:
        print("No floating windows here -- nothing to arrange.")
        return

    if _DEBUG:
        print(f"DEBUG eligible={len(eligible)} fixed(fullscreen)={len(fixed)}", file=sys.stderr)

    if len(eligible) < 1:
        print("Nothing eligible to arrange (everything is fullscreen/maximized).")
        return

    gap = live_gap()

    state_path = _resize_state_path()
    resize_state = _load_resize_state(state_path)
    results = auto_arrange(eligible, fixed, monitor, gap,
                           resize_locked=_locked_addresses(resize_state, eligible))

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
        #
        # But only when a client actually deviated. When every window took
        # exactly the size it was asked for, the first pass's positions
        # are ALREADY correct for those sizes -- and they are the layout the
        # resize was chosen FOR (auto_arrange keeps a resize only when its
        # whole finished composition beats the move-only alternative).
        # Rebuilding anyway threw that away: re-running the build from the
        # windows' pre-press positions produced a different composition in
        # 56 of 58 resizing presses on the placement benchmark, with MORE
        # dead-gap/notch penalty than the one that justified the resize in
        # 33 of them -- the windows shrank, the arrangement that made the
        # shrink worth it never appeared.
        batch_async([resize_window_exact_lua(w, h, a) for a, w, h in resize_exprs])
        settled = _settle_sizes([a for a, _, _ in resize_exprs], workspace_id)
        if settled:
            settled_eligible = [w for w in settled
                                if not w.get("fullscreen") and not w.get("pinned") and w.get("address") in by_addr]
            settled_by_addr = {w["address"]: w for w in settled_eligible}
            planned = {a: (w, h) for a, _x, _y, w, h in results}
            deviated = any(
                a not in settled_by_addr
                or not _size_matches(tuple(settled_by_addr[a]["size"]), planned[a], THRESHOLD)
                for a, _, _ in resize_exprs)
            if not deviated:
                # Plan stands; compare against where the resize LEFT each
                # window (Hyprland's resize is centre-anchored), so the
                # dispatch below moves rather than re-resizes.
                by_addr.update(settled_by_addr)
            else:
                eligible = settled_eligible
                fixed = [w for w in settled if w.get("address") in {f["address"] for f in fixed}]
                if eligible:
                    results = auto_arrange(eligible, fixed, monitor, gap, allow_resize=False)
                    by_addr = {w["address"]: w for w in eligible}

    # each attached dialog follows its parent's move
    parent_delta = {a: (nx - by_addr[a]["at"][0], ny - by_addr[a]["at"][1])
                    for a, nx, ny, _w, _h in results if a in by_addr}
    for child in children:
        dx, dy = parent_delta.get(attached[child["address"]], (0, 0))
        if (dx, dy) != (0, 0):
            results.append((child["address"], child["at"][0] + dx, child["at"][1] + dy,
                            child["size"][0], child["size"][1]))
            by_addr[child["address"]] = child

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

    next_state = _next_resize_state(
        resize_state,
        alive_addrs={c.get("address") for c in clients},
        current_sizes={a: (w, h) for a, _x, _y, w, h in results},
        resized_now=[a for a, _, _ in resize_exprs])
    if next_state != resize_state:
        _save_resize_state(state_path, next_state)
    print(f"Arranged {len(eligible)} window(s); {moved} moved, {resized} resized, "
          f"{max(0, len(eligible) - moved)} already in place.")
    if fixed:
        print(f"Left {len(fixed)} fullscreen/maximized window(s) untouched.")


if __name__ == "__main__":
    main()
