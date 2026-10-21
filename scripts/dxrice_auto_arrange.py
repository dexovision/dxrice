#!/usr/bin/env python3
"""SUPER+G -- arrange the desktop as a Galaxy Spiral.

Rearranges the floating windows of the active workspace into the same
spiral new-window placement grows (dxrice_spiral): the first-created window
as the anchor at the centre of the usable area, every other window, in the
order the windows were created, on one expanding clockwise spiral around
it, with gaps that widen gently turn by turn (~42 px on the inner turn,
up to twice that outward; theme.json's window_spacing_min/max, separate
from Hyprland's gaps_in) and never under the minimum.

  1. Splits the workspace's floating windows into ELIGIBLE (arranged) and
     FIXED (fullscreen/maximized/pinned: never moved, still obstacles) --
     dxrice_window_class.partition. Dialogs attached to a parent move with
     it; transient popups are left alone.
  2. Replays the spiral (auto_arrange): deterministic, from the windows'
     creation order and sizes alone, so a layout new-window placement built
     is reproduced exactly (nothing moves) and a second press never moves
     anything. Sizes are always kept.
  3. Dispatches every move in one batch.

A one-shot pass, not an ongoing constraint: dragging a window anywhere
afterwards works as always.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dxrice_hypr_ipc import hyprctl_json, batch_async, move_window_exact_lua, resize_window_exact_lua
import dxrice_window_class
import dxrice_viewport
import dxrice_spiral
from dxrice_resize_memory import (resize_state_path as _resize_state_path,
                                  load_resize_state as _load_resize_state,
                                  save_resize_state as _save_resize_state,
                                  size_matches as _size_matches,
                                  locked_addresses as _locked_addresses,
                                  next_resize_state as _next_resize_state)
from dxrice_auto_place_window import get_monitor_bounds, live_gap, rect_for, _creation_key

_DEBUG = os.environ.get("DXRICE_DEBUG") == "1"


def auto_arrange(eligible, fixed, monitor_bounds, gap, allow_resize=True, resize_locked=frozenset(),
                 spacing=None):
    """SUPER+G: [(address, x, y, w, h), ...] for every eligible window -- the
    Galaxy Spiral replayed in creation order (dxrice_spiral.arrange): the
    first-created window is the anchor at the usable area's centre.

    Creation order is Hyprland's stableId when the clients carry one, else
    the order given (Hyprland lists clients in creation order). Sizes are
    always kept: `allow_resize` / `resize_locked` are accepted for main()'s
    sake and change nothing. `gap` is Hyprland's gaps_in; the composition
    spacing is `spacing` = (min, max), default theme.json's
    window_spacing_min/max (dxrice_spiral.read_spacing)."""
    if not eligible:
        return []
    band = spacing or dxrice_spiral.read_spacing()
    fixed_rects = [rect_for(*_xywh(w)) for w in fixed]
    ordered = sorted(eligible, key=_creation_key)
    rects = dxrice_spiral.arrange([tuple(w["size"]) for w in ordered], fixed_rects, monitor_bounds, band)
    return [(w["address"], r[0], r[1], r[2] - r[0], r[3] - r[1]) for w, r in zip(ordered, rects)]


def join_composition(new_size, layout, obstacles, monitor_bounds, gap, spacing=None):
    """Where a newly opened window joins the composition: the next step of
    the same spiral SUPER+G replays (dxrice_spiral.join), every existing
    window held where it is -- opening a window never moves or resizes
    another one.

    `layout`: [(x, y, w, h), ...] the composition's windows IN CREATION
    ORDER (layout[0] is the anchor); `obstacles`: every rect it must stay
    clear of (layout + fixed/fullscreen + others). `gap` (Hyprland's
    gaps_in) is accepted for the callers' sake; the spacing is the
    composition spacing. Returns the new window's integer top-left (x, y)."""
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
    # A press that only recentred the composition (every window moved by the
    # same amount, nothing resized) moved the camera: the desktop's widgets
    # follow it. A real rearrangement is not a camera move and isn't reported.
    if exprs and not resized:
        shift = dxrice_viewport.uniform_shift(
            [(by_addr[a]["at"][0], by_addr[a]["at"][1], nx, ny) for a, nx, ny, _w, _h in results if a in by_addr])
        if shift:
            try:
                dxrice_viewport.add_steps(dxrice_viewport.default_path(), {workspace_id: shift})
            except OSError:
                pass

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
    # SUPER+G: the saved layout mode (Expansion unless set otherwise);
    # "galaxy" runs the classic arrangement above.
    import dxrice_layout_apply
    sys.exit(dxrice_layout_apply.main())
