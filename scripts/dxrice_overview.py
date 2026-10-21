#!/usr/bin/env python3
"""Desktop overview (SUPER+Tab): where every window of the current
workspace is drawn when the desktop is zoomed out to fit the screen.

The overview is a VIEW, not a layout. Quickshell's Overview.qml draws a live
picture of each window (Hyprland's toplevel-export protocol, via
ScreencopyView) over the wallpaper, starting exactly on top of the real
window and animating to the rect this module computes. No window is ever
moved, resized, refocused or touched in any way by opening or closing the
overview, so "restoring the previous view" is exact by construction. This
module only READS Hyprland state; it has no code path that dispatches
anything.

Why not a real compositor zoom: Hyprland has no zoom-out of the desktop.
`cursor:zoom_factor` is a magnifier (zoom in, around the cursor, >= 1);
lowering the monitor's scale makes every client re-render at a new scale,
reflows fullscreen games and layer surfaces, and anchors at the monitor's
top-left so windows at negative coordinates never come into view; the
overview plugins (hyprexpo, Hyprspace) show a grid of workspaces rather than
one workspace zoomed out, and need rebuilding against each Hyprland release.

The shell computes the same thing itself (quickshell/OverviewGeometry.js,
a line-for-line mirror, so opening never waits for a Python interpreter);
this module is the reference implementation, the CLI, and what the tests
check the shell's copy against.

    python3 scripts/dxrice_overview.py [--monitor NAME] [--margin PX]

prints the overview for the focused (or named) monitor as one JSON object:

    {"monitor": {"name", "x", "y", "width", "height"},  # the usable area,
     "reserved": [left, top, right, bottom],           # layout coords
     "workspace": id, "scale": s, "fits": bool, "clipped": bool,
     "windows": [{"address", "class", "title", "x", "y", "w", "h",  # real,
                  "tx", "ty", "tw", "th",                         # overview,
                  "floating", "fullscreen", "pinned", "z"}, ...]}

The overview covers the monitor's usable area -- everything but the strips
the bar and dock reserve, which stay visible above it -- and every rect is
relative to that area's top-left. `windows` is in stacking order, bottom
first.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dxrice_hypr_ipc import hyprctl_json  # noqa: E402

# Breathing room between the outermost windows and the screen edges.
OVERVIEW_MARGIN = 48
# Never zoom out further than this (a huge spiral is then centred and its
# outermost windows may stay partly off screen -- "clipped"); never zoom in.
MIN_SCALE = 0.08
MAX_SCALE = 1.0


def monitor_rect(m):
    """(usable rect, (left, top, right, bottom) reserved) for one monitor in
    layout coordinates: its logical size (scale and rotation applied) minus
    the strips bars and docks reserve -- the area the overview covers.

    The same arithmetic as dxrice_auto_place_window.usable_bounds (a test
    keeps the two in step); not imported from there because that module
    costs ~50 ms to import and this runs on a keypress."""
    w, h = m["width"], m["height"]
    if m.get("transform", 0) in (1, 3, 5, 7):
        w, h = h, w
    try:
        scale = float(m.get("scale") or 1.0)
    except (TypeError, ValueError):
        scale = 1.0
    if scale > 0:
        w, h = round(w / scale), round(h / scale)
    x0, y0 = m["x"], m["y"]
    try:
        left, top, right, bottom = (int(v) for v in (m.get("reserved") or [0, 0, 0, 0]))
    except (TypeError, ValueError):
        left = top = right = bottom = 0
    if not (left + right < w and top + bottom < h):
        left = top = right = bottom = 0
    return (x0 + left, y0 + top, x0 + w - right, y0 + h - bottom), (left, top, right, bottom)


def pick_monitor(monitors, name=None):
    if not monitors:
        return None
    if name:
        for m in monitors:
            if m.get("name") == name:
                return m
    for m in monitors:
        if m.get("focused"):
            return m
    return monitors[0]


def members(clients, monitor):
    """The windows the overview shows on `monitor`: every mapped, visible
    window of its active workspace (tiled, floating, maximized and
    fullscreen alike), plus windows pinned on this monitor (they are shown
    on every workspace). In stacking order, bottom first: tiled, then
    floating/pinned, then fullscreen; within each, least recently focused
    first (Hyprland's focusHistoryID: 0 = most recent)."""
    ws = (monitor.get("activeWorkspace") or {}).get("id")
    special = (monitor.get("specialWorkspace") or {}).get("id") or 0
    out = []
    for c in clients or []:
        if not c.get("mapped", True) or c.get("hidden"):
            continue
        size = c.get("size") or [0, 0]
        if size[0] < 2 or size[1] < 2:
            continue
        cws = (c.get("workspace") or {}).get("id")
        on_monitor = c.get("monitor") == monitor.get("id")
        if not (cws == ws or (special and cws == special) or (c.get("pinned") and on_monitor)):
            continue
        out.append(c)

    def layer(c):
        if c.get("fullscreen"):
            return 2
        return 1 if (c.get("floating") or c.get("pinned")) else 0

    out.sort(key=lambda c: (layer(c), -int(c.get("focusHistoryID", 0) or 0)))
    return out


def fit(rects, area, margin=OVERVIEW_MARGIN, min_scale=MIN_SCALE, max_scale=MAX_SCALE):
    """(scale, dx, dy, fits, clipped): the view transform p' = p*scale + d
    that shows every rect (x0, y0, x1, y1) inside `area` with `margin` to
    spare, centred. Already entirely on screen -> the identity (no zoom,
    no pan). Larger than the area -> zoomed out as far as needed, at most
    to min_scale (then `clipped`: the outermost parts stay off screen)."""
    ax0, ay0, ax1, ay1 = area
    if not rects:
        return 1.0, 0.0, 0.0, True, False
    bx0 = min(r[0] for r in rects)
    by0 = min(r[1] for r in rects)
    bx1 = max(r[2] for r in rects)
    by1 = max(r[3] for r in rects)
    if bx0 >= ax0 and by0 >= ay0 and bx1 <= ax1 and by1 <= ay1:
        return 1.0, 0.0, 0.0, True, False
    avail_w = max(1.0, (ax1 - ax0) - 2 * margin)
    avail_h = max(1.0, (ay1 - ay0) - 2 * margin)
    want = min(avail_w / max(1.0, bx1 - bx0), avail_h / max(1.0, by1 - by0))
    scale = min(max_scale, max(min_scale, want))
    clipped = want < min_scale
    # centre the composition's bounding box on the area
    cx, cy = (ax0 + ax1) / 2.0, (ay0 + ay1) / 2.0
    dx = cx - scale * (bx0 + bx1) / 2.0
    dy = cy - scale * (by0 + by1) / 2.0
    return scale, dx, dy, False, clipped


def overview(clients, monitors, monitor_name=None, margin=OVERVIEW_MARGIN):
    """The overview description (see the module docstring) for one monitor,
    from `hyprctl clients -j` / `hyprctl monitors -j` data."""
    m = pick_monitor(monitors, monitor_name)
    if m is None:
        return {"monitor": None, "reserved": [0, 0, 0, 0], "workspace": None, "scale": 1.0, "dx": 0, "dy": 0, "fits": True,
                "clipped": False, "windows": []}
    (mx0, my0, mx1, my1), reserved = monitor_rect(m)
    wins = members(clients, m)
    local = [(c["at"][0] - mx0, c["at"][1] - my0, c["at"][0] - mx0 + c["size"][0], c["at"][1] - my0 + c["size"][1])
             for c in wins]
    scale, dx, dy, fits, clipped = fit(local, (0, 0, mx1 - mx0, my1 - my0), margin)
    out = []
    for z, (c, r) in enumerate(zip(wins, local)):
        out.append({
            "address": c.get("address", ""),
            "class": c.get("class", ""),
            "title": c.get("title", ""),
            "x": r[0], "y": r[1], "w": r[2] - r[0], "h": r[3] - r[1],
            "tx": round(r[0] * scale + dx, 2), "ty": round(r[1] * scale + dy, 2),
            "tw": round((r[2] - r[0]) * scale, 2), "th": round((r[3] - r[1]) * scale, 2),
            "floating": bool(c.get("floating")), "fullscreen": bool(c.get("fullscreen")),
            "pinned": bool(c.get("pinned")), "z": z,
        })
    return {
        "monitor": {"name": m.get("name", ""), "x": mx0, "y": my0, "width": mx1 - mx0, "height": my1 - my0},
        "reserved": list(reserved),
        "workspace": (m.get("activeWorkspace") or {}).get("id"),
        "scale": scale, "dx": round(dx, 2), "dy": round(dy, 2), "fits": fits, "clipped": clipped, "windows": out,
    }


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--monitor")
    ap.add_argument("--margin", type=float, default=OVERVIEW_MARGIN)
    a = ap.parse_args(argv)
    try:
        clients = hyprctl_json(["clients"]) or []
        monitors = hyprctl_json(["monitors"]) or []
    except Exception as e:  # no compositor: an empty overview, never a traceback
        print(json.dumps({"error": str(e), "monitor": None, "windows": []}))
        return 1
    print(json.dumps(overview(clients, monitors, a.monitor, a.margin)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
