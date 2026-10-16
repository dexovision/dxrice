"""The Galaxy Spiral: one geometric model for new-window placement and SUPER+G.

What it builds: individually floating windows on one continuous spiral that
winds clockwise outward round an anchor, its gaps widening turn by turn --
not a ring, not a packed cloud. The empty space is part of the design and
is never optimised away.

  * The anchor is the first window, centred on the usable area (the monitor
    minus bars and docks), clear of fixed windows.
  * Every later window, in creation order, takes the next place along ONE
    Archimedean spiral of window centres round the anchor's centre --
    stretched a little along the anchor's longer side (`_stretch`), so the
    first turn wraps a wide anchor and the whole fits a wide screen: the
    radius grows continuously with the clockwise angle, by SPIRAL_OPENING
    typical window depths along that bearing (plus the gap) per turn. The
    curve is a guide: each window's own footprint is what must clear
    everything, measured as a true distance between rectangles -- the
    gutter for facing neighbours, corner to corner for diagonal ones
    (`dist`), the same rule in every direction.
  * The gap widens with the spiral: `spacing_at` derives it from the
    window's radial progress (its radius on the spiral, in turns), from
    the target gap (target_gap, ~42 px) on the inner turn to
    SPACING_GROWTH_CAP times it on the outer ones. The minimum of
    read_spacing's range is the hard floor under all of it.
  * A window sits exactly on the curve. Where its spot is closer than the
    gap to another window or a fixed window, it advances along the same
    curve in small steps to the first clear spot -- it is never pushed off
    the curve, drawn inward, or put in a convenient hole.

There is no scoring, no search over alternatives and no remembered state:
the same windows in the same order always give the same layout.
Auto-placement places one window (`join`): the next step after the newest
existing window. SUPER+G (`arrange`) replays every step in creation order,
so on a layout auto-placement built and nobody disturbed it changes
nothing, and a second press never changes anything either.
"""
import json
import math
import os

try:
    import dxrice_xdg
except ImportError:  # pragma: no cover - only for standalone use
    dxrice_xdg = None

# ---- spacing (separate from Hyprland's gaps_in) ----
SPACING_MIN_DEFAULT = 32     # the hard floor: no two windows ever closer
SPACING_MAX_DEFAULT = 56
SPACING_LIMIT = 200          # sanity cap for values read from theme.json
SPACING_MIN_KEY = "window_spacing_min"
SPACING_MAX_KEY = "window_spacing_max"
# The inner turn's gap: this far into the (min, max) range (~42 px).
SPACING_TARGET_FRACTION = 0.42
# How the gap widens outward: target * (1 + GROWTH * p), p the radial
# progress in turns (0 where the spiral starts, 1 a turn out, ...), at most
# CAP * target -- with the default 42 px about 42-50 px on the inner turn,
# 50-59 on the middle one, 59-67 the outer: a gentle, steady widening.
SPACING_GROWTH = 0.2
SPACING_GROWTH_CAP = 2.0


def read_spacing(path=None):
    """(min, max) composition spacing from theme.json, defaults 32/56. A
    missing, unreadable or nonsensical value keeps the default."""
    lo, hi = SPACING_MIN_DEFAULT, SPACING_MAX_DEFAULT
    if path is None and dxrice_xdg is not None:
        path = os.path.join(dxrice_xdg.config_dir(), "theme.json")
    try:
        with open(path) as f:
            data = json.load(f)
        lo = int(data.get(SPACING_MIN_KEY, lo))
        hi = int(data.get(SPACING_MAX_KEY, hi))
    except (OSError, TypeError, ValueError, AttributeError):
        return SPACING_MIN_DEFAULT, SPACING_MAX_DEFAULT
    if not (0 <= lo <= hi <= SPACING_LIMIT):
        return SPACING_MIN_DEFAULT, SPACING_MAX_DEFAULT
    return lo, hi


def target_gap(band):
    """The inner turn's edge-to-edge gap: ~42 px of the default 32-56."""
    lo, hi = band
    return int(round(lo + (hi - lo) * SPACING_TARGET_FRACTION))


def spacing_at(progress, band):
    """The gap at `progress` turns out from the anchor: widening smoothly
    with the spiral, never under the range's minimum."""
    g0 = target_gap(band)
    p = max(0.0, progress)
    return max(float(band[0]), g0 * min(SPACING_GROWTH_CAP, 1.0 + SPACING_GROWTH * p))


def widest_gap(band):
    """The widest gap the spiral ever aims for (its outer turns): the most a
    window is from its nearest neighbour when nothing is in the way."""
    return target_gap(band) * SPACING_GROWTH_CAP


# Kept for callers that size one pair (a dialog beside its parent): the
# inner turn's gap.
def pair_spacing(area_a, area_b, band):
    return target_gap(band)


# ---- the spiral ----
SPIRAL_START = math.radians(-55)   # the second window's bearing: upper right
SPIRAL_TURN = 1                    # +1 clockwise on screen (y grows downward)
MARCH_STEP = math.radians(1.0)     # how far along the curve each try advances
MARCH_REFINE = 12                  # bisection steps narrowing it to the first clear spot
MARCH_MAX = math.radians(360 * 8)  # cap on how far round one window may go
# How far apart the turns are: the radius gained per turn, in typical window
# depths along the bearing (plus the gap). 1 would just clear the turn
# inside; more opens the spiral so it reads as one, not as stacked rings.
SPIRAL_OPENING = 1.8
# How much the spiral is stretched along the anchor's longer side: the
# anchor's aspect ratio to this power (0 round, 1 the anchor's own shape).
SPIRAL_STRETCH = 0.75
SPIRAL_STRETCH_MAX = 1.6           # never flatter than this, however long the anchor

# A slit (a facing gap too wide to read as spacing, too narrow to read as
# space) does not exist in this design: every placed gap is the gap at its
# turn or more, and wider ones are the intended negative space.
SLIT_MAX = SPACING_MAX_DEFAULT
# Shape exponent of the composition's preferred aspect; unused by the
# spiral itself, kept for tooling.
SHAPE_ASPECT_EXPONENT = 0.5
# How far inside the usable area's edges an anchor is kept.
ANCHOR_MARGIN = 32


def _rect(x, y, w, h):
    return (x, y, x + w, y + h)


def _center(r):
    return ((r[0] + r[2]) / 2.0, (r[1] + r[3]) / 2.0)


def _sep(a, b):
    """Axis separation: <0 overlapping, else the larger of the horizontal and
    vertical clearances (the gutter they'd show). Diagnostics only; spacing
    is `dist`."""
    return max(a[0] - b[2], b[0] - a[2], a[1] - b[3], b[1] - a[3])


def dist(a, b):
    """Edge-to-edge distance between two rects, the same in every
    direction: the gutter for neighbours that face each other, corner to
    corner for diagonal ones; <= 0 when they touch or overlap."""
    dx = max(a[0] - b[2], b[0] - a[2], 0)
    dy = max(a[1] - b[3], b[1] - a[3], 0)
    if dx == 0 and dy == 0:
        return _sep(a, b)
    return math.hypot(dx, dy)


def _facing(a, b):
    """(distance, shared span) when a and b face each other across a gutter,
    else None."""
    oy = min(a[3], b[3]) - max(a[1], b[1])
    ox = min(a[2], b[2]) - max(a[0], b[0])
    if oy > 0 and ox <= 0:
        return max(b[0] - a[2], a[0] - b[2]), oy
    if ox > 0 and oy <= 0:
        return max(b[1] - a[3], a[1] - b[3]), ox
    return None


def _wrap(a):
    return (a + math.pi) % (2 * math.pi) - math.pi


def _at(center, theta, radius, w, h):
    """The w x h rect centred `radius` from `center` at bearing `theta`."""
    cx = center[0] + radius * math.cos(theta)
    cy = center[1] + radius * math.sin(theta)
    return _rect(int(round(cx - w / 2.0)), int(round(cy - h / 2.0)), w, h)


def _median(v):
    v = sorted(v)
    if not v:
        return 0.0
    m = len(v) // 2
    return v[m] if len(v) % 2 else (v[m - 1] + v[m]) / 2.0


def first_rect(size, fixed, monitor, band=(SPACING_MIN_DEFAULT, SPACING_MAX_DEFAULT)):
    """Where the anchor goes: centred on the usable area, or -- if a fixed
    window is within the gap of that spot -- moved straight out from the
    centre, along the shortest of eight directions, until clear of every
    fixed window by the gap."""
    w, h = int(size[0]), int(size[1])
    gap = target_gap(band)
    mx0, my0, mx1, my1 = monitor
    c = ((mx0 + mx1) / 2.0, (my0 + my1) / 2.0)
    r0 = _rect(int(round(c[0] - w / 2.0)), int(round(c[1] - h / 2.0)), w, h)
    if all(dist(r0, f) >= gap for f in fixed):
        return r0
    best = None
    for k in range(8):
        th = -math.pi / 2 + k * math.pi / 4
        r = 0.0
        while True:  # step out, then settle on the first clear radius
            cand = _at(c, th, r, w, h)
            if all(dist(cand, f) >= gap for f in fixed):
                break
            r += 8.0
        lo = max(0.0, r - 8.0)
        for _ in range(10):
            mid = (lo + r) / 2.0
            if all(dist(_at(c, th, mid, w, h), f) >= gap for f in fixed):
                r = mid
            else:
                lo = mid
        if best is None or r < best[0]:
            best = (r, _at(c, th, r, w, h))
    return best[1]


def _stretch(anchor):
    """(ex, ey), ex * ey = 1: how the spiral's radius is scaled along x and
    y -- the anchor's aspect to SPIRAL_STRETCH, at most SPIRAL_STRETCH_MAX --
    so the first turn wraps a wide anchor's ends instead of skipping them."""
    e = ((anchor[2] - anchor[0]) / float(max(1, anchor[3] - anchor[1]))) ** SPIRAL_STRETCH
    e = min(SPIRAL_STRETCH_MAX, max(1.0 / SPIRAL_STRETCH_MAX, e))
    return math.sqrt(e), 1.0 / math.sqrt(e)


def _polar(anchor, rect):
    """(angle, radius) of a window's centre in the spiral's own frame."""
    ex, ey = _stretch(anchor)
    ac, c = _center(anchor), _center(rect)
    dx, dy = (c[0] - ac[0]) / ex, (c[1] - ac[1]) / ey
    return math.atan2(dy, dx), math.hypot(dx, dy)


def spiral_coords(rects):
    """For a layout in creation order (rects[0] the anchor): each later
    window's (cumulative clockwise angle from window 2 in radians, radius)
    in the spiral's own frame -- what the model keeps continuous and
    growing. Diagnostics (tests, the benchmark)."""
    out, phi, last = [], 0.0, None
    for r in rects[1:]:
        a, rad = _polar(rects[0], r)
        if last is not None:
            phi += (SPIRAL_TURN * (a - last)) % (2 * math.pi)
        last = a
        out.append((phi, rad))
    return out


def next_rect(size, placed, fixed, band):
    """THE spiral step: where a w x h window goes after `placed` (rects in
    creation order; placed[0] is the anchor, placed[-1] the window before
    it -- the tip), clear of everything in placed and `fixed` by the gap at
    its place on the spiral.

    The window's centre follows an Archimedean spiral round the anchor's
    centre (stretched a little along the anchor's longer side, `_stretch`):
    the radius grows continuously with the clockwise angle, by
    SPIRAL_OPENING typical window depths along that bearing plus the gap
    per turn. It starts from the tip (from SPIRAL_START, just clear of the
    anchor, for window 2) and advances in MARCH_STEP increments until the
    window's footprint is the gap clear of everything, then bisects back to
    the first clear spot."""
    w, h = int(size[0]), int(size[1])
    g0 = target_gap(band)
    anchor = placed[0]
    ac = _center(anchor)
    # a typical window, for the depth of a turn: the medians of the arm's
    # windows and this one
    body = placed[1:] + [_rect(0, 0, w, h)]
    tw = _median([r[2] - r[0] for r in body])
    th_ = _median([r[3] - r[1] for r in body])
    ex, ey = _stretch(anchor)
    # radial progress, in turns (spiral units): 0 where a typical window
    # clears the anchor along its nearer axis, +1 per turn's depth
    turn_ref = SPIRAL_OPENING * (tw + th_) / 2.0 + g0
    base = min(((anchor[2] - anchor[0] + tw) / 2.0 + g0) / ex,
               ((anchor[3] - anchor[1] + th_) / 2.0 + g0) / ey)

    def gap_at(radius):
        return spacing_at((radius - base) / turn_ref, band)

    def scale(theta):
        return math.hypot(ex * math.cos(theta), ey * math.sin(theta))

    def depth(theta):
        """A typical window's depth along the spiral's normal at theta, in
        spiral-radius units."""
        return math.hypot(tw * math.cos(theta), th_ * math.sin(theta)) / scale(theta)

    def rect_at(theta, radius):
        cx = ac[0] + radius * ex * math.cos(theta)
        cy = ac[1] + radius * ey * math.sin(theta)
        return _rect(int(round(cx - w / 2.0)), int(round(cy - h / 2.0)), w, h)

    if len(placed) == 1:
        prev = None
        theta0 = SPIRAL_START
        # window 2 starts where it is just the gap clear of the anchor
        lo, hi = 0.0, 1.0
        while dist(rect_at(theta0, hi), anchor) < gap_at(hi):
            hi *= 2.0
        for _ in range(30):
            mid = (lo + hi) / 2.0
            if dist(rect_at(theta0, mid), anchor) < gap_at(mid):
                lo = mid
            else:
                hi = mid
        r0 = hi
    else:
        prev = placed[-1]
        theta0, r0 = _polar(anchor, prev)
    others = placed + list(fixed)

    def place(phi, radius):
        rect = rect_at(theta0 + SPIRAL_TURN * phi, radius)
        gap = gap_at(radius)
        return all(dist(rect, o) >= gap for o in others), rect

    def grow(phi, radius, dphi):
        """The radius after advancing dphi along the spiral."""
        mid = theta0 + SPIRAL_TURN * (phi + dphi / 2.0)
        return radius + (SPIRAL_OPENING * depth(mid) + gap_at(radius) / scale(mid)) / (2 * math.pi) * dphi

    if prev is None:
        ok, rect = place(0.0, r0)
        if ok:
            return rect
    phi, radius = 0.0, r0
    while phi < MARCH_MAX:
        r1 = grow(phi, radius, MARCH_STEP)
        ok, rect = place(phi + MARCH_STEP, r1)
        if ok:
            lo, hi = 0.0, MARCH_STEP
            for _ in range(MARCH_REFINE):  # the first clear spot, finely
                mid = (lo + hi) / 2.0
                ok_mid, r_mid = place(phi + mid, grow(phi, radius, mid))
                if ok_mid:
                    hi, rect = mid, r_mid
                else:
                    lo = mid
            return rect
        phi, radius = phi + MARCH_STEP, r1
    # Eight turns out and still blocked (only something enormous does
    # that): step straight outward from there until clear -- still never
    # closer than the gap to anything.
    while True:
        ok, rect = place(phi, radius)
        if ok:
            return rect
        radius += 16.0


def arrange(sizes, fixed, monitor, band):
    """SUPER+G: every window's rect, replaying the spiral in creation order
    (sizes: [(w, h)] in that order; the first is the anchor)."""
    placed = []
    for size in sizes:
        placed.append(first_rect(size, fixed, monitor, band) if not placed else next_rect(size, placed, fixed, band))
    return placed


def join(new_size, layout, obstacles, monitor, band):
    """New-window placement: where a newly opened window goes, every
    existing window held where it is. `layout`: the composition's windows
    as (x, y, w, h) IN CREATION ORDER -- layout[0] is the anchor, layout[-1]
    the newest; `obstacles`: everything it must stay clear of (the layout
    included). An empty layout makes the new window the anchor. Returns its
    integer top-left (x, y)."""
    fixed = [_rect(*o) for o in obstacles]
    if not layout:
        r = first_rect(new_size, fixed, monitor, band)
        return r[0], r[1]
    placed = [_rect(int(x), int(y), int(w), int(h)) for x, y, w, h in layout]
    others = [f for f in fixed if f not in placed]
    r = next_rect(new_size, placed, others, band)
    return r[0], r[1]


# ---- rigidity diagnostics (tests and the benchmark; not the objective) ----
JUNCTION_TOL = 12           # corners / gutters this close read as one line
SEAM_SPAN_FRACTION = 0.9    # a gutter across this much of the layout is a seam
SEAM_MIN_WINDOWS = 4


def cross_junctions(rects, band=(SPACING_MIN_DEFAULT, SPACING_MAX_DEFAULT)):
    """Points where four windows' corners meet across two gutters -- the
    signature of a grid. rects: (x0, y0, x1, y1)."""
    hi, t = band[1], JUNCTION_TOL
    count = 0
    for r in rects:
        trs = [q for q in rects if r[2] < q[0] <= r[2] + hi + t and abs(q[3] - r[3]) <= t]
        bls = [q for q in rects if r[3] < q[1] <= r[3] + hi + t and abs(q[2] - r[2]) <= t]
        if any(abs(q[0] - tr[0]) <= t and abs(q[1] - bl[1]) <= t
               for tr in trs for bl in bls for q in rects if q is not r and q is not tr and q is not bl):
            count += 1
    return count


def full_span_seams(rects, band=(SPACING_MIN_DEFAULT, SPACING_MAX_DEFAULT)):
    """Straight gutters running across SEAM_SPAN_FRACTION of the whole
    composition (4+ windows) -- rows and columns."""
    if len(rects) < SEAM_MIN_WINDOWS:
        return 0
    hi = band[1]
    count = 0
    for axis in (0, 1):  # 0: vertical gutters, 1: horizontal
        a0, a1, b0, b1 = (0, 2, 1, 3) if axis == 0 else (1, 3, 0, 2)
        extent = max(r[b1] for r in rects) - min(r[b0] for r in rects)
        segs = []
        for r in rects:
            for q in rects:
                d = q[a0] - r[a1]
                if q is r or not (0 <= d <= hi + 0.5):  # any gutter, packed ones too
                    continue
                s0, s1 = max(r[b0], q[b0]), min(r[b1], q[b1])
                if s1 > s0:
                    segs.append(((r[a1] + q[a0]) / 2.0, s0, s1))
        segs.sort()
        lines, cur = [], []
        for seg in segs:
            if cur and seg[0] - cur[0][0] > JUNCTION_TOL:
                lines.append(cur)
                cur = []
            cur.append(seg)
        if cur:
            lines.append(cur)
        for line in lines:
            best, run_lo, run_hi = 0.0, None, None
            for _c, s0, s1 in sorted(line, key=lambda t: t[1]):
                if run_hi is not None and s0 <= run_hi + hi + JUNCTION_TOL:
                    run_hi = max(run_hi, s1)
                else:
                    run_lo, run_hi = s0, s1
                best = max(best, run_hi - run_lo)
            if best >= SEAM_SPAN_FRACTION * extent:
                count += 1
    return count


def rigidity(rects, band=(SPACING_MIN_DEFAULT, SPACING_MAX_DEFAULT)):
    return cross_junctions(rects, band) + full_span_seams(rects, band)
