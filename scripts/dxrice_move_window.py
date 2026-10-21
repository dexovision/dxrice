#!/usr/bin/env python3
"""
dxrice_move_window.py
Moves the active floating window 90px in the given direction.
If it hits a monitor edge, pushes the other windows the opposite way.

Usage: python3 dxrice_move_window.py <left|right|up|down>
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dxrice_hypr_ipc import hyprctl_json, move_window_exact_lua, batch_async, dispatch
import dxrice_monitor
import dxrice_viewport

STEP = 90


def get_monitor_bounds(monitor_id=None):
    """The usable area (logical size, minus bar and dock) of the window's
    monitor."""
    x0, y0, x1, y1 = dxrice_monitor.bounds(hyprctl_json(["monitors"]) or [], monitor_id)
    return {"left": x0, "right": x1, "top": y0, "bottom": y1}


def get_floating_windows(workspace_id):
    """The windows the desktop's camera moves (not pinned or fullscreen)."""
    clients = hyprctl_json(["clients"]) or []
    return [w for w in clients if dxrice_monitor.pans_with_desktop(w, workspace_id)]


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("left", "right", "up", "down"):
        print("Usage: dxrice_move_window.py <left|right|up|down>")
        sys.exit(1)

    direction = sys.argv[1]

    window = hyprctl_json(["activewindow"])
    if not window or not window.get("floating"):
        sys.exit(0)

    ws = hyprctl_json(["activeworkspace"])
    workspace_id = ws["id"] if ws else None
    if workspace_id is None:
        sys.exit(1)

    monitor = get_monitor_bounds(window.get("monitor"))
    addr = window["address"]
    wx, wy = window["at"][0], window["at"][1]
    ww, wh = window["size"][0], window["size"][1]

    dx, dy = 0, 0
    if direction == "left":  dx = -STEP
    elif direction == "right": dx = STEP
    elif direction == "up":    dy = -STEP
    elif direction == "down":  dy = STEP

    new_x = wx + dx
    new_y = wy + dy

    if dx < 0:
        room = wx - monitor["left"]
        actual_dx = -min(STEP, room)
    elif dx > 0:
        room = monitor["right"] - (wx + ww)
        actual_dx = min(STEP, room)
    else:
        actual_dx = 0

    if dy < 0:
        room = wy - monitor["top"]
        actual_dy = -min(STEP, room)
    elif dy > 0:
        room = monitor["bottom"] - (wy + wh)
        actual_dy = min(STEP, room)
    else:
        actual_dy = 0

    hitting_edge = (actual_dx != dx) or (actual_dy != dy)

    if hitting_edge:
        if actual_dx != 0 or actual_dy != 0:
            dispatch(move_window_exact_lua(wx + actual_dx, wy + actual_dy, addr))
        others = [w for w in get_floating_windows(workspace_id) if w["address"] != addr]
        exprs = []
        for w in others:
            ox = w["at"][0] - dx
            oy = w["at"][1] - dy
            exprs.append(move_window_exact_lua(ox, oy, w["address"]))
        batch_async(exprs)
        # the rest of the desktop moved: so do world-attached widgets
        try:
            dxrice_viewport.add_steps(dxrice_viewport.default_path(), {workspace_id: (-dx, -dy)})
        except OSError:
            pass
    else:
        dispatch(move_window_exact_lua(new_x, new_y, addr))


if __name__ == "__main__":
    main()
