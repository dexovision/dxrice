#!/usr/bin/env python3
"""Resolves overlaps between floating windows on the active workspace --
NOT a full reflow. A window that isn't overlapping anything is left
completely alone, exactly where it is; only a window that's actually
colliding with another gets nudged to the nearest free spot relative to
its OWN current position.

This is deliberately gentle: the infinite canvas is meant to hold windows
wherever you've spread them out (including panned far outside the current
view), and a "tidy up" action that instead gathered everything back
toward the current viewport's center would undo that spreading-out on
every use -- which is exactly what an earlier version of this script did,
and exactly what "joined everything into one screen" was describing. This
version's target point for a colliding window is its own current center,
not the screen's, so a fix only ever moves a window the shortest distance
that actually clears the overlap, never toward some unrelated point.

One-shot, not an ongoing constraint -- run it, overlaps clear, and
dragging windows wherever you want right after works exactly as always.
Never resizes anything, only repositions. Never touches anything that
isn't floating (fullscreen or tiled windows are left alone).

Bound to SUPER+D (replacing the old float/tile toggle -- see
dxrice_floating_tile_toggle.py, still present and runnable by hand if you
want that behavior back on a different bind).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dxrice_hypr_ipc import hyprctl_json, batch_async, move_window_exact_lua
import dxrice_auto_place_window as placer


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

    mx0, my0, mx1, my1 = placer.get_monitor_bounds()
    viewport = (mx0, my0, mx1, my1)
    gap = placer.live_gap()

    def rect(w):
        x, y = w["at"]
        w_, h_ = w["size"]
        return (x, y, x + w_, y + h_)

    def overlaps_with_gap(a, b):
        ax0, ay0, ax1, ay1 = a
        bx0, by0, bx1, by1 = b
        return not (ax1 + gap <= bx0 or ax0 >= bx1 + gap
                    or ay1 + gap <= by0 or ay0 >= by1 + gap)

    # Larger windows first: if a big window and a small one collide,
    # nudging the smaller one out of the way reads as the natural fix, not
    # the other way around.
    ordered = sorted(floating, key=lambda w: w["size"][0] * w["size"][1], reverse=True)

    fixed = []  # [(x, y, w, h), ...] -- windows already decided this run,
                # whether left in place or just moved
    exprs = []
    moved = 0

    for w in ordered:
        my_rect = rect(w)
        others = [f for f in fixed if overlaps_with_gap(my_rect, f)]
        if not others:
            fixed.append(my_rect)
            continue

        # Only this window moves -- target its OWN current center, so the
        # fix is the shortest one that actually clears the collision,
        # never a pull toward some unrelated point on the canvas.
        size = (w["size"][0], w["size"][1])
        own_center = (my_rect[0] + size[0] / 2, my_rect[1] + size[1] / 2)
        others_as_xywh = [(f[0], f[1], f[2] - f[0], f[3] - f[1]) for f in fixed]
        pos = placer.find_free_position(size, others_as_xywh, own_center, gap, viewport=viewport)
        exprs.append(move_window_exact_lua(int(pos[0]), int(pos[1]), w["address"]))
        fixed.append((pos[0], pos[1], pos[0] + size[0], pos[1] + size[1]))
        moved += 1

    if exprs:
        batch_async(exprs)
    if moved:
        print(f"Resolved {moved} overlapping window(s); {len(floating) - moved} were already clear and left alone.")
    else:
        print("No overlapping windows -- nothing to do.")


if __name__ == "__main__":
    main()
