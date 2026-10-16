#!/usr/bin/env python3
"""Monitor geometry and the infinite desktop's movable windows, shared by
the keybind scripts and the daemons.

Hyprland reports a monitor's `width`/`height` in mode pixels, while window
positions are in layout (logical) coordinates: a 2880x1620 panel at scale 1.5
is 1920x1080 in the layout, and a 90/270-degree transform swaps the two. Code
that compares windows against the raw numbers centres them off-centre and
finds the screen edge in the wrong place on any scaled or rotated monitor.
"""


def logical_size(m):
    """(width, height) of a `hyprctl monitors -j` entry in layout coordinates."""
    w, h = m["width"], m["height"]
    if m.get("transform", 0) in (1, 3, 5, 7):
        w, h = h, w
    try:
        scale = float(m.get("scale") or 1.0)
    except (TypeError, ValueError):
        scale = 1.0
    if scale > 0:
        w, h = round(w / scale), round(h / scale)
    return w, h


def usable_bounds(m):
    """(x0, y0, x1, y1): the part of the monitor windows are meant to use, in
    layout coordinates -- its logical size minus the space reserved by bars
    and docks (`reserved`: left, top, right, bottom)."""
    w, h = logical_size(m)
    x0, y0 = m["x"], m["y"]
    res = m.get("reserved") or [0, 0, 0, 0]
    try:
        left, top, right, bottom = (int(v) for v in res)
    except (TypeError, ValueError):
        left = top = right = bottom = 0
    if left + right < w and top + bottom < h:
        return (x0 + left, y0 + top, x0 + w - right, y0 + h - bottom)
    return (x0, y0, x0 + w, y0 + h)


def pick(monitors, monitor_id=None):
    """The monitor with `monitor_id`, else the focused one, else the first;
    None if there are none."""
    if not monitors:
        return None
    if monitor_id is not None:
        for m in monitors:
            if m.get("id") == monitor_id:
                return m
    for m in monitors:
        if m.get("focused"):
            return m
    return monitors[0]


FALLBACK_BOUNDS = (0, 0, 1920, 1080)


def bounds(monitors, monitor_id=None):
    """usable_bounds of pick(...), or a 1920x1080 guess with no monitors."""
    m = pick(monitors, monitor_id)
    return usable_bounds(m) if m else FALLBACK_BOUNDS


def pans_with_desktop(w, workspace_id):
    """Whether window `w` (a `hyprctl clients -j` entry) moves when the
    infinite desktop pans: a floating window of that workspace. Pinned
    windows (shown on every workspace, e.g. picture-in-picture) and
    fullscreen ones belong to the screen, not the desktop, and stay put --
    the same rule the overview's pan uses."""
    return (bool(w.get("floating")) and not w.get("pinned") and not w.get("fullscreen")
            and w.get("workspace", {}).get("id") == workspace_id)
