#!/usr/bin/env python3
"""The three window layouts: Expansion, Spiral and Compact.

Pure geometry: no Hyprland, no files. Given a usable area, a gap and the
windows (in creation order, with the index of the one that matters most),
each layout returns one rectangle per window, or None for a window that
doesn't fit at a usable size -- those are left where they are rather than
shrunk to nothing.

  expansion  the primary window gets a generous area; the others share the
             rest, newest first. 1 window: nearly the whole area.
  spiral     each window takes half of what is left, turning clockwise:
             left, top, right, bottom, left...; the last takes the remainder.
  compact    a balanced grid sized to the area's shape, the last row
             stretched to fill it. Nothing gets a bigger share than another.

Rects are (x, y, w, h) integers inside the area, at least `gap` apart.
Deterministic: the same input always gives the same output.
"""
import math

MODES = ("expansion", "spiral", "compact")
DEFAULT_MODE = "expansion"

MIN_W = 280
MIN_H = 180
EXPANSION_FRACTION = {1: 1.0, 2: 0.62}     # primary's width share; 3+ use _fraction()
SOLO_MARGIN = 0.04                          # a single window leaves this much around it


def normalize(mode):
    """A saved value -> a mode we have; anything else is the default."""
    mode = str(mode or "").strip().lower()
    return mode if mode in MODES else DEFAULT_MODE


def _fraction(n):
    """Primary's width share with n windows: 62% for two, then easing
    toward 50% so the rest still get a column worth having."""
    return EXPANSION_FRACTION.get(n, max(0.5, 0.62 - 0.02 * (n - 2)))


def _rect(x0, y0, x1, y1):
    return (int(round(x0)), int(round(y0)), int(round(x1 - x0)), int(round(y1 - y0)))


def _split_even(lo, hi, parts, gap):
    """[lo, hi) into `parts` pieces separated by gap: [(a, b), ...]."""
    total = hi - lo - gap * (parts - 1)
    out, cur = [], lo
    for i in range(parts):
        size = total * (i + 1) // parts - total * i // parts
        out.append((cur, cur + size))
        cur += size + gap
    return out


def capacity(area, gap, min_w=MIN_W, min_h=MIN_H):
    """How many windows fit at the minimum usable size."""
    x0, y0, x1, y1 = area
    cols = max(0, (x1 - x0 + gap) // (min_w + gap))
    rows = max(0, (y1 - y0 + gap) // (min_h + gap))
    return int(cols * rows)


def _expansion_at(n, area, gap, primary, frac, min_w, min_h):
    x0, y0, x1, y1 = area
    W = x1 - x0
    split = x0 + (W - gap) * frac
    out = [None] * n
    out[primary] = _rect(x0, y0, split, y1)
    rest = [i for i in range(n) if i != primary]
    rest.reverse()                       # newest first, at the top
    rx0, rx1 = split + gap, x1
    k = len(rest)
    # one column of rows while each row stays usable, else more columns
    cols = 1
    while cols < k and (y1 - y0 - gap * (math.ceil(k / cols) - 1)) / math.ceil(k / cols) < min_h:
        cols += 1
    while cols > 1 and (rx1 - rx0 - gap * (cols - 1)) / cols < min_w:
        cols -= 1
    per_col = math.ceil(k / cols)
    xs = _split_even(rx0, rx1, cols, gap)
    idx = 0
    for c in range(cols):
        take = min(per_col, k - idx)
        if take <= 0:
            break
        for (ya, yb), win in zip(_split_even(y0, y1, take, gap), rest[idx:idx + take]):
            out[win] = _rect(xs[c][0], ya, xs[c][1], yb)
        idx += take
    return out


def expansion(n, area, gap, primary=None, min_w=MIN_W, min_h=MIN_H):
    """n rects, index `primary` (default the last, the newest) the big one."""
    if n <= 0:
        return []
    primary = n - 1 if primary is None else max(0, min(n - 1, primary))
    x0, y0, x1, y1 = area
    W, H = x1 - x0, y1 - y0
    if n == 1:
        mx, my = W * SOLO_MARGIN, H * SOLO_MARGIN
        return [_rect(x0 + mx, y0 + my, x1 - mx, y1 - my)]
    # The primary's usual share; if the others don't fit beside it at a
    # usable size, give them more room (down to a third) before leaving any out.
    best = None
    frac = _fraction(n)
    while frac >= 0.33:
        out = _drop_unusable(_expansion_at(n, area, gap, primary, frac, min_w, min_h), min_w, min_h, keep=primary)
        left_out = sum(1 for r in out if r is None)
        if best is None or left_out < best[0]:
            best = (left_out, out)
        if left_out == 0:
            break
        frac -= 0.04
    return _or_grid(best[1], n, area, gap, min_w, min_h)


def _spiral_at(n, area, gap, ratio, min_w, min_h):
    x0, y0, x1, y1 = area
    out = [None] * n
    left, top, right, bottom = x0, y0, x1, y1
    for i in range(n):
        if i == n - 1:
            out[i] = _rect(left, top, right, bottom)
            break
        side = i % 4
        w, h = right - left, bottom - top
        if side in (0, 2):
            cut = (w - gap) * ratio
            if cut < min_w or (w - gap - cut) < min_w or h < min_h:
                return out, i, (left, top, right, bottom)
            if side == 0:
                out[i] = _rect(left, top, left + cut, bottom)
                left = left + cut + gap
            else:
                out[i] = _rect(right - cut, top, right, bottom)
                right = right - cut - gap
        else:
            cut = (h - gap) * ratio
            if cut < min_h or (h - gap - cut) < min_h or w < min_w:
                return out, i, (left, top, right, bottom)
            if side == 1:
                out[i] = _rect(left, top, right, top + cut)
                top = top + cut + gap
            else:
                out[i] = _rect(left, bottom - cut, right, bottom)
                bottom = bottom - cut - gap
    return out, None, None


def spiral(n, area, gap, primary=None, min_w=MIN_W, min_h=MIN_H):
    """n rects in creation order, the first the biggest, turning clockwise.
    Each takes half of what is left; when that would leave later windows
    too small it takes a little less (down to 30%), and when even that
    isn't enough the remainder is shared out as a grid."""
    if n <= 0:
        return []
    for ratio in (0.5, 0.45, 0.4, 0.35, 0.3):
        out, stopped, rem = _spiral_at(n, area, gap, ratio, min_w, min_h)
        if stopped is None:
            return _drop_unusable(out, min_w, min_h)
    out, stopped, rem = _spiral_at(n, area, gap, 0.5, min_w, min_h)
    return _or_grid(_fallback_grid(out, stopped, rem, n, gap, min_w, min_h), n, area, gap, min_w, min_h)


def _fallback_grid(out, start, rem, n, gap, min_w, min_h):
    """What is left of the spiral is too small to halve again: share it out
    as a grid among the windows still to place."""
    left = n - start
    cells = compact(left, rem, gap, min_w=min_w, min_h=min_h)
    for j, c in enumerate(cells):
        out[start + j] = c
    return _drop_unusable(out, min_w, min_h)


def compact(n, area, gap, primary=None, min_w=MIN_W, min_h=MIN_H):
    """n rects as a grid as square as the area allows, rows filled in
    order, the last row stretched to the full width."""
    if n <= 0:
        return []
    x0, y0, x1, y1 = area
    W, H = x1 - x0, y1 - y0
    if n == 1:
        return [_rect(x0, y0, x1, y1)]
    best = None
    for cols in range(1, n + 1):
        rows = math.ceil(n / cols)
        cw = (W - gap * (cols - 1)) / cols
        ch = (H - gap * (rows - 1)) / rows
        if cw < min_w or ch < min_h:
            continue
        # prefer cells near the window-like 16:10, then fewer empty cells
        aspect = abs(math.log((cw / ch) / 1.6))
        waste = rows * cols - n
        score = aspect + 0.12 * waste
        if best is None or score < best[0]:
            best = (score, cols, rows)
    if best is None:                       # nothing fits at the minimum: one row or column
        cols = max(1, min(n, int(W // (min_w + gap)) or 1))
        rows = math.ceil(n / cols)
    else:
        _s, cols, rows = best
    out = []
    ys = _split_even(y0, y1, rows, gap)
    done = 0
    for r in range(rows):
        in_row = min(cols, n - done)
        for xa, xb in _split_even(x0, x1, in_row, gap):
            out.append(_rect(xa, ys[r][0], xb, ys[r][1]))
        done += in_row
    return _drop_unusable(out, min_w, min_h)


def _or_grid(rects, n, area, gap, min_w, min_h):
    """If a layout had to leave windows out, and a plain grid would place
    more of them, the grid: a space too small for a favourite is better
    shared evenly than spent on one."""
    if all(r is not None for r in rects):
        return rects
    grid = compact(n, area, gap, min_w=min_w, min_h=min_h)
    return grid if sum(r is None for r in grid) < sum(r is None for r in rects) else rects


def _drop_unusable(rects, min_w, min_h, keep=None):
    """None for any rect below the usable minimum (never the primary)."""
    out = []
    for i, r in enumerate(rects):
        if r is not None and i != keep and (r[2] < min_w or r[3] < min_h):
            r = None
        out.append(r)
    return out


def layout(mode, n, area, gap, primary=None, min_w=MIN_W, min_h=MIN_H):
    """The rects for `mode` (see the module docstring)."""
    fn = {"expansion": expansion, "spiral": spiral, "compact": compact}[normalize(mode)]
    return fn(n, area, gap, primary, min_w, min_h)
