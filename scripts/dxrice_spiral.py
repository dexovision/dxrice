"""The Galaxy Spiral: one geometric model for new-window placement and SUPER+G.

What it builds: individually floating windows on a predictable, widening
spiral around one anchor, with real breathing room between them -- not a
packed cloud. The empty space is part of the design and is never optimised
away.

  * The anchor is the first window. It sits at the centre of the usable
    area (the monitor minus bars and docks), clear of fixed windows.
  * Every later window, in the order the windows were created, takes the
    next place on one spiral around the anchor. The spiral starts at
    SPIRAL_START (upper right) and always turns SPIRAL_TURN (clockwise on
    screen). Its parameter is the window's edge-to-edge clearance from the
    anchor, which grows smoothly with the bearing: SPIRAL_PITCH_FACTOR of a
    typical window's size per full turn, so each turn clears the one inside
    it. Window dimensions enter through that clearance -- a wide window and
    a tall one at the same bearing keep the same distance from the anchor's
    outline.
  * Spacing is a hard geometric constraint: a window is never placed
    closer than the target gap (target_gap, about 42 px, inside the
    32-56 px range read_spacing gives) to any other window or fixed
    obstacle. At each bearing a window is pushed outward past anything of
    an earlier turn or an obstacle; if the window placed just before it is
    still too close, the next bearing along the spiral is tried. Nothing is
    ever drawn in to fill space.

There is no scoring, no search over alternatives and no remembered state:
the same windows in the same order always give the same layout.
Auto-placement places one window (`join`): the next step after the
newest existing window. SUPER+G (`arrange`) replays every step in creation
order, so on a layout auto-placement built and nobody disturbed, it changes
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
SPACING_MIN_DEFAULT = 32
SPACING_MAX_DEFAULT = 56
SPACING_LIMIT = 200          # sanity cap for values read from theme.json
SPACING_MIN_KEY = "window_spacing_min"
SPACING_MAX_KEY = "window_spacing_max"
# Where in the range a window is placed: the march stops at the first spot
# this far from everything, so every gap lands at or a little above it.
SPACING_TARGET_FRACTION = 0.42


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
    """The edge-to-edge gap every placement keeps: ~42 px of the default
    32-56 range."""
    lo, hi = band
    return int(round(lo + (hi - lo) * SPACING_TARGET_FRACTION))


# Kept for callers that size one pair (a dialog beside its parent): the
# same gap as everything else.
def pair_spacing(area_a, area_b, band):
    return target_gap(band)


# ---- the spiral ----
SPIRAL_START = math.radians(-55)   # the second window's bearing: upper right
SPIRAL_TURN = 1                    # +1 clockwise on screen (y grows downward)
# Clearance from the anchor's outline gained per full turn, as a multiple of
# the windows' typical short side: each turn sits one window's depth (plus
# the gap) outside the one before.
SPIRAL_PITCH_FACTOR = 1.0
# How far past the spiral's guide a window may be pushed outward at one
# bearing (to clear an earlier turn), as a fraction of a turn's pitch;
# beyond that it advances along the spiral instead of leaping outward.
PUSH_LIMIT_FRACTION = 0.5
MARCH_STEP = math.radians(1.5)     # bearing step when the previous window is in the way
MARCH_REFINE = 10                  # bisection steps narrowing it to the first clear bearing
MARCH_MAX = math.radians(720)      # never more than two turns past the previous window
FIXED_DETOUR = math.radians(45)    # how far round a fixed window the arm goes rather than be pushed past it

# A slit (a facing gap too wide to read as spacing, too narrow to read as
# space) does not exist in this design: every placed gap is target_gap or
# more, and wider ones are the intended negative space.
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
    """Separation between two rects: <0 overlapping, else the larger of the
    horizontal and vertical clearances (the gutter they'd show)."""
    return max(a[0] - b[2], b[0] - a[2], a[1] - b[3], b[1] - a[3])


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


def _radius_for_clearance(anchor, theta, w, h, clearance):
    """How far from the anchor's centre, along bearing `theta`, a w x h
    window's edges are exactly `clearance` from the anchor's (_sep)."""
    aw, ah = anchor[2] - anchor[0], anchor[3] - anchor[1]
    c, s = abs(math.cos(theta)), abs(math.sin(theta))
    out = []
    if c > 1e-9:
        out.append((clearance + (aw + w) / 2.0) / c)
    if s > 1e-9:
        out.append((clearance + (ah + h) / 2.0) / s)
    return min(out)


def _clearance_of(anchor, theta, r, w, h):
    """The inverse: edge clearance from the anchor of a w x h window
    centred r along bearing theta."""
    aw, ah = anchor[2] - anchor[0], anchor[3] - anchor[1]
    return max(r * abs(math.cos(theta)) - (aw + w) / 2.0, r * abs(math.sin(theta)) - (ah + h) / 2.0)


def _blocked_spans(center, theta, w, h, blockers, gap):
    """Radii along bearing `theta` where a w x h window centred there would
    come closer than `gap` to one of `blockers`: [(r_in, r_out)], sorted."""
    ux, uy = math.cos(theta), math.sin(theta)
    spans = []
    for b in blockers:
        # the window's centre must stay out of b grown by gap + half the window
        x0, y0 = b[0] - gap - w / 2.0, b[1] - gap - h / 2.0
        x1, y1 = b[2] + gap + w / 2.0, b[3] + gap + h / 2.0
        lo, hi = -math.inf, math.inf
        for p, d, a0, a1 in ((center[0], ux, x0, x1), (center[1], uy, y0, y1)):
            if abs(d) < 1e-12:
                if not (a0 < p < a1):
                    lo, hi = 1.0, 0.0
                    break
                continue
            t0, t1 = (a0 - p) / d, (a1 - p) / d
            if t0 > t1:
                t0, t1 = t1, t0
            lo, hi = max(lo, t0), min(hi, t1)
        if lo < hi and hi > 0:
            spans.append((max(lo, 0.0), hi))
    return sorted(spans)


def _push_out(center, theta, r, w, h, blockers, gap):
    """The smallest radius >= r along bearing `theta` clear of every blocker
    by `gap` (pushing outward past each in turn)."""
    for r_in, r_out in _blocked_spans(center, theta, w, h, blockers, gap):
        if r_in < r + 1e-6 < r_out:
            r = r_out + 0.5
    return r


def typical_side(rects):
    """The median short side of the windows: how deep one turn of the spiral
    is."""
    sides = sorted(min(r[2] - r[0], r[3] - r[1]) for r in rects)
    if not sides:
        return 400.0
    mid = len(sides) // 2
    return sides[mid] if len(sides) % 2 else (sides[mid - 1] + sides[mid]) / 2.0


def first_rect(size, fixed, monitor, band=(SPACING_MIN_DEFAULT, SPACING_MAX_DEFAULT)):
    """Where the anchor goes: centred on the usable area, or -- if a fixed
    window is within the gap of that spot -- pushed out of it (and every
    other fixed window) by the gap, along the shortest of eight directions."""
    w, h = int(size[0]), int(size[1])
    gap = target_gap(band)
    mx0, my0, mx1, my1 = monitor
    c = ((mx0 + mx1) / 2.0, (my0 + my1) / 2.0)
    r0 = _rect(int(round(c[0] - w / 2.0)), int(round(c[1] - h / 2.0)), w, h)
    if not any(_sep(r0, f) < gap for f in fixed):
        return r0
    best = None
    for k in range(8):  # the nearest of eight directions out of the obstacles
        th = -math.pi / 2 + k * math.pi / 4
        r = _push_out(c, th, 0.0, w, h, fixed, gap)
        cand = _at(c, th, r, w, h)
        d = math.hypot(*(a - b for a, b in zip(_center(cand), c)))
        if best is None or d < best[0]:
            best = (d, cand)
    return best[1]


def next_rect(size, placed, fixed, band):
    """THE spiral step: where a w x h window goes after `placed` (rects in
    creation order; placed[0] is the anchor, placed[-1] the window before
    it), clear of everything in placed and `fixed` by target_gap."""
    w, h = int(size[0]), int(size[1])
    gap = target_gap(band)
    anchor = placed[0]
    ac = _center(anchor)
    pitch = SPIRAL_PITCH_FACTOR * typical_side(placed[1:] + [_rect(0, 0, w, h)]) + gap
    per_rad = pitch / (2 * math.pi)
    if len(placed) == 1:
        theta0, q0, prev = SPIRAL_START, float(gap), None
    else:
        prev = placed[-1]
        pc = _center(prev)
        theta0 = math.atan2(pc[1] - ac[1], pc[0] - ac[0])
        q0 = max(float(gap), _sep(prev, anchor))
    arm = [p for p in placed[1:] if p is not prev]
    blockers = placed + list(fixed)

    def place(dtheta, past_fixed):
        theta = theta0 + SPIRAL_TURN * dtheta
        q = q0 + per_rad * dtheta
        r_guide = _radius_for_clearance(anchor, theta, w, h, q)
        r_arm = _push_out(ac, theta, r_guide, w, h, arm, gap)
        r = _push_out(ac, theta, r_arm, w, h, arm + list(fixed), gap) if past_fixed else r_arm
        rect = _at(ac, theta, r, w, h)
        # a push past an earlier turn is fine; a leap far beyond the guide
        # is not -- the window goes further round instead
        ok = (_clear(rect, blockers, gap)
              and (prev is None or _sep(rect, prev) >= gap)
              and _clearance_of(anchor, theta, r, w, h) - q <= PUSH_LIMIT_FRACTION * pitch)
        return ok, rect, r > r_arm + 0.25

    def march(start, limit, past_fixed):
        """The first clear bearing in [start, limit] (to a fraction of a
        degree): (dtheta, rect, pushed past a fixed window), or None."""
        if prev is None and start == 0.0:
            ok, rect, pushed = place(0.0, past_fixed)
            if ok:
                return 0.0, rect, pushed
        lo, d = start, start + MARCH_STEP
        while d <= limit:
            ok, rect, pushed = place(d, past_fixed)
            if ok:
                hi = d
                for _ in range(MARCH_REFINE):
                    mid = (lo + hi) / 2.0
                    ok_mid, r_mid, p_mid = place(mid, past_fixed)
                    if ok_mid:
                        hi, rect, pushed = mid, r_mid, p_mid
                    else:
                        lo = mid
                return hi, rect, pushed
            lo, d = d, d + MARCH_STEP
        return None

    # Fixed windows (fullscreen, pinned, ...) can push the window outward
    # like an earlier turn does; but if a short detour along the arm gets
    # round one without the push, the arm goes round it instead -- a push
    # past a fixed window leaves this window off the spiral and every later
    # window inflated, while a long detour would strand it on the far side.
    found = march(0.0, MARCH_MAX, True)
    if found is not None:
        d, rect, pushed = found
        if pushed:
            around = march(d, d + FIXED_DETOUR, False)
            if around is not None:
                return around[1]
        return rect
    # Never reached in practice (two turns out, nothing is in the way any
    # more); still never closer than the gap to anything.
    theta = theta0 + SPIRAL_TURN * MARCH_MAX
    r = _push_out(ac, theta, _radius_for_clearance(anchor, theta, w, h, q0 + per_rad * MARCH_MAX),
                  w, h, placed + list(fixed), gap)
    return _at(ac, theta, r, w, h)


def _clear(rect, others, gap):
    x0, y0, x1, y1 = rect
    for q in others:
        if q[0] - x1 < gap and x0 - q[2] < gap and q[1] - y1 < gap and y0 - q[3] < gap:
            return False
    return True


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
