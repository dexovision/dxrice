#!/usr/bin/env python3
"""Expansion -- the Big Bang arrangement. Windows burst outward from one
point and keep their own sizes; nothing is resized, there is no spiral
sequence and no grid.

SUPER+G (arrange):
  the largest window is the core, at the screen's centre. The others keep
  their ORDER around the group's centre (going round, whatever came after
  what still does) but are given evenly spread directions in that order,
  starting from the direction the first of them has now -- so the burst is
  balanced even when the windows started in a cascade or a line. Each one,
  largest first, is pushed out from the centre along its direction until
  it is clear of everything already placed by the composition spacing.
  Then the whole group is shifted so its bounding box is centred on the
  screen (unless that would put it on a fullscreen window). Windows with
  no direction at all (every one at the same point) go round in opening
  order.

A new window (join):
  goes into the widest empty angle around the group -- measured from the
  group's area-weighted centre -- and is pushed out along the middle of
  that angle until it is clear by the spacing. So the group grows evenly
  outward, filling the side that is most open, and no existing window
  moves.

Like the Galaxy Spiral, the group may grow past the screen edges (this is
the infinite desktop); unlike it, nothing follows creation order or a
fixed turning sequence. Rects are (x0, y0, x1, y1) inside this module;
the public functions take and return the callers' formats.
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dxrice_spiral  # noqa: E402  (the shared composition spacing)

STEP = 8            # px per outward step before the 1 px refinement


def spacing(band=None):
    """The gap kept between windows: the middle of the composition band
    (theme.json window_spacing_min/max, default 32-56 -> 44)."""
    lo, hi = band or dxrice_spiral.read_spacing()
    return int(round((lo + hi) / 2))


def _rect_at(cx, cy, w, h):
    x0 = int(round(cx - w / 2))
    y0 = int(round(cy - h / 2))
    return (x0, y0, x0 + w, y0 + h)


def _clear(r, others, gap):
    x0, y0, x1, y1 = r
    for a0, b0, a1, b1 in others:
        if x0 < a1 + gap and a0 < x1 + gap and y0 < b1 + gap and b0 < y1 + gap:
            return False
    return True


def _push_out(origin, angle, w, h, others, gap):
    """The rect of size w x h centred on the ray from `origin` at `angle`,
    at the smallest distance where it is clear of `others` by `gap`."""
    ox, oy = origin
    dx, dy = math.cos(angle), math.sin(angle)
    d = 0
    r = _rect_at(ox, oy, w, h)
    if _clear(r, others, gap):
        return r
    limit = 40000
    while d < limit:
        d += STEP
        r = _rect_at(ox + dx * d, oy + dy * d, w, h)
        if _clear(r, others, gap):
            break
    lo, hi = max(0, d - STEP), d        # refine to the pixel: the first clear distance
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if _clear(_rect_at(ox + dx * mid, oy + dy * mid, w, h), others, gap):
            hi = mid
        else:
            lo = mid
    return _rect_at(ox + dx * hi, oy + dy * hi, w, h)


def _centre(monitor):
    x0, y0, x1, y1 = monitor
    return ((x0 + x1) / 2, (y0 + y1) / 2)


def arrange(windows, fixed, monitor, band=None):
    """SUPER+G. `windows`: [(x, y, w, h)] where they are now; `fixed`:
    [(x0, y0, x1, y1)] to stay clear of (fullscreen, pinned); `monitor`:
    (x0, y0, x1, y1). Returns [(x0, y0, x1, y1)] in the same order."""
    n = len(windows)
    if n == 0:
        return []
    gap = spacing(band)
    centres = [(x + w / 2, y + h / 2) for x, y, w, h in windows]
    gx = sum(c[0] for c in centres) / n
    gy = sum(c[1] for c in centres) / n
    order = sorted(range(n), key=lambda i: (-windows[i][2] * windows[i][3], i))
    core, rest = order[0], order[1:]
    angles = {core: 0.0}
    if rest:
        own = {i: (math.atan2(centres[i][1] - gy, centres[i][0] - gx) % (2 * math.pi)
                   if math.hypot(centres[i][0] - gx, centres[i][1] - gy) >= 1 else None) for i in rest}
        if all(a is None for a in own.values()):
            ring = sorted(rest)                                   # opening order
            start = -math.pi / 2
        else:
            ring = sorted(rest, key=lambda i: (own[i] if own[i] is not None else 0.0, i))
            start = own[ring[0]] if own[ring[0]] is not None else 0.0
        for k, i in enumerate(ring):
            angles[i] = start + 2 * math.pi * k / len(ring)
    origin = _centre(monitor)
    placed = {}
    for i in order:
        _x, _y, w, h = windows[i]
        placed[i] = _push_out(origin, angles[i], w, h, list(placed.values()) + list(fixed), gap)
    rects = [placed[i] for i in range(n)]
    # centre the group's bounding box on the screen, if that is safe
    bx0, by0 = min(r[0] for r in rects), min(r[1] for r in rects)
    bx1, by1 = max(r[2] for r in rects), max(r[3] for r in rects)
    sx = int(round(origin[0] - (bx0 + bx1) / 2))
    sy = int(round(origin[1] - (by0 + by1) / 2))
    shifted = [(a + sx, b + sy, c + sx, d + sy) for a, b, c, d in rects]
    if all(_clear(r, list(fixed), gap) for r in shifted):
        rects = shifted
    return rects


def widest_gap_angle(layout_centres, centre):
    """The middle of the widest empty angle around `centre` between the
    directions of `layout_centres` (ties: the smallest angle from 0, i.e.
    to the right, going clockwise on screen). One direction: the opposite
    one."""
    angles = sorted(math.atan2(cy - centre[1], cx - centre[0]) % (2 * math.pi) for cx, cy in layout_centres)
    if not angles:
        return 0.0
    if len(angles) == 1:
        return (angles[0] + math.pi) % (2 * math.pi)
    best, best_gap = 0.0, -1.0
    for k, a in enumerate(angles):
        b = angles[(k + 1) % len(angles)] + (2 * math.pi if k == len(angles) - 1 else 0)
        gap = b - a
        mid = (a + gap / 2) % (2 * math.pi)
        if gap > best_gap + 1e-9 or (abs(gap - best_gap) <= 1e-9 and mid < best):
            best, best_gap = mid, gap
    return best


def join(new_size, layout, obstacles, monitor, band=None):
    """A new window, every other one held where it is. `layout`: [(x, y,
    w, h)] the group it joins (the windows on screen); `obstacles`: [(x, y,
    w, h)] everything to stay clear of (layout included). Returns its
    integer top-left (x, y)."""
    w, h = int(new_size[0]), int(new_size[1])
    gap = spacing(band)
    others = [(int(x), int(y), int(x + ow), int(y + oh)) for x, y, ow, oh in obstacles]
    if not layout:
        r = _push_out(_centre(monitor), -math.pi / 2, w, h, others, gap)
        return r[0], r[1]
    areas = [lw * lh for _x, _y, lw, lh in layout]
    total = sum(areas) or 1
    cx = sum((x + lw / 2) * a for (x, _y, lw, _lh), a in zip(layout, areas)) / total
    cy = sum((y + lh / 2) * a for (_x, y, _lw, lh), a in zip(layout, areas)) / total
    angle = widest_gap_angle([(x + lw / 2, y + lh / 2) for x, y, lw, lh in layout], (cx, cy))
    r = _push_out((cx, cy), angle, w, h, others, gap)
    return r[0], r[1]


def join_composition(new_size, layout, obstacles, monitor_bounds, gap=None, spacing_band=None):
    """dxrice_auto_place_window's join interface (the same one the Galaxy
    Spiral and Compact take). `gap` (Hyprland's gaps_in) is accepted for
    the callers' sake; Expansion keeps the composition spacing."""
    return join(new_size, layout, obstacles, monitor_bounds, spacing_band)
