"""The airy-spiral composer shared by SUPER+G and new-window placement.

What it builds: a galaxy of floating windows rather than a packed block.
The most prominent window (largest area) is the hub; every other window, in
order of prominence, is placed where it continues one rotational sweep
around the hub -- each one prefers to sit beside the previous one, its
share of the sweep further round (see SWEEP_TURNS_*), not closer to the hub, so
the composition winds outward with the big windows central and the small
ones on the outer turns. Neighbours sit a composition spacing apart (a
range, see read_spacing), not Hyprland's gaps_in.

The spiral is a scoring preference, never a template: each window takes the
best of many candidate positions beside the windows already placed, and the
bearing/radius preference is weighed against everything that makes a
composition read well --

  * contact: a new window touches the cluster at the composition spacing
    (generated that way), and is rewarded for nestling against a second
    neighbour, so the cloud stays cohesive;
  * slits: two facing windows SPACING_MAX..SLIT_MAX apart look like a
    mistake, not breathing room -- penalised by how long the slit is;
    further apart is open space and fine;
  * seams: edges collinear with other windows' edges are what make rows,
    columns and grids -- penalised, so neighbours stagger;
  * shape: the cluster's bounding box stays near the screen's shape (the
    square root of its aspect, as before) and its mass near its middle;
  * movement: a small pull toward where the window already is relative to
    the hub, so equally good choices keep what the user had.

Which way the sweep turns and where it starts come from the current layout
(the second window's bearing from the hub, the majority turning direction),
and both directions are built and the better one kept -- no fixed compass
direction anywhere.

Everything here is deterministic: no randomness, no time budgets.
"""
import json
import math
import os

try:
    import dxrice_xdg
except ImportError:  # pragma: no cover - only for standalone use
    dxrice_xdg = None

# ---- composition spacing (separate from Hyprland's gaps_in) ----
SPACING_MIN_DEFAULT = 16
SPACING_MAX_DEFAULT = 24
SPACING_LIMIT = 80          # sanity cap for values read from theme.json
SPACING_MIN_KEY = "window_spacing_min"
SPACING_MAX_KEY = "window_spacing_max"


def read_spacing(path=None):
    """(min, max) composition spacing from theme.json, defaults 16/24. A
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


# Window size (sqrt of area) at which a pair gets the low / high end of the
# spacing range: small windows sit closer, big ones breathe more.
SPACING_SMALL_SIDE = 380.0
SPACING_LARGE_SIDE = 1000.0


def pair_spacing(area_a, area_b, band):
    lo, hi = band
    side = math.sqrt(min(area_a, area_b))
    t = (side - SPACING_SMALL_SIDE) / (SPACING_LARGE_SIDE - SPACING_SMALL_SIDE)
    return int(round(lo + (hi - lo) * min(1.0, max(0.0, t))))


# ---- the spiral preference ----
# The sweep: all windows but the hub share SWEEP_TURNS full turns around
# it, each a slice proportional to its size (sqrt of area), so the arm goes
# all the way round -- balanced on every side -- and the bigger windows take
# more of it. More windows wind further (a second, outer turn).
SWEEP_TURNS_BASE = 0.75
SWEEP_TURNS_PER_WINDOW = 0.1
SWEEP_TURNS_RANGE = (0.9, 1.75)
CHAIN_BONUS = 420.0         # touching the previous window of the sweep
RADIUS_FLOOR = 1.0          # never closer to the hub than the previous window
ANGLE_WEIGHT = 1100.0       # per pi radians off the preferred bearing
RADIUS_WEIGHT = 0.55        # per px of distance from the hub (compactness)
INVERSION_WEIGHT = 4.0      # per px closer to the hub than the previous window
NESTLE_BONUS = 160.0        # per extra neighbour touched at the spacing
SLIT_MAX = 60               # facing windows further apart than this: open space
SLIT_WEIGHT = 2.5           # per px of slit length
SEAM_TOL = 6
SEAM_WEIGHT = 800.0         # per collinear edge shared with another window
ASPECT_WEIGHT = 420.0       # per unit of |log(aspect / target)| of the cluster
# The cluster's target shape: the screen's aspect ratio to this power (0.5:
# about 4:3 on a 16:9 screen -- the full screen shape stretches small sets
# into strips, a square makes tall columns on a wide screen).
SHAPE_ASPECT_EXPONENT = 0.5
BALANCE_WEIGHT = 700.0      # per unit of mass-centre offset / bbox half-diagonal
MOVE_WEIGHT = 0.04          # per px from the window's current hub-relative spot
MIN_SHARED_FRACTION = 0.3   # a neighbour shares >= this much of the shorter side
ANCHOR_CAP = 5              # neighbours to build candidates beside, per window
SLIDE_FRACTIONS = (-0.4, -0.2, 0.0, 0.2, 0.4)

# Whole-composition score (variant choice, keep-or-rebuild gate).
FLOW_WEIGHT = 1600.0
CENTRALITY_WEIGHT = 500.0
TIGHT_GAP_WEIGHT = 4000.0   # per pair closer than the spacing minimum
SLIT_PAIR_WEIGHT = 260.0    # per facing pair SPACING_MAX..SLIT_MAX apart
FILL_RANGE = (0.5, 0.8)
FILL_WEIGHT = 2500.0
WHOLE_MOVE_WEIGHT = 0.25    # per px of mean (centroid-aligned) movement
# A new window that would open mostly hidden pays up to JOIN_VISIBLE_WEIGHT
# x JOIN_VISIBLE_SHARE: a tie-breaker, not a reason to leave the sweep --
# beside an anchor that nearly fills the screen every next spot along it is
# mostly off-screen, and the infinite desktop pans to it.
JOIN_VISIBLE_WEIGHT = 1200.0  # per unit of the window's area hidden beyond...
JOIN_VISIBLE_SHARE = 0.25     # ...this much of it visible
JOIN_CENTRE_WEIGHT = 1.5      # new window: per px the composition's centre is off the screen's
START_VARIANTS = 4          # start bearings tried per press (x2 directions)
START_OFFSET = math.pi / 4  # ...on the diagonals, so no start favours a screen edge
RECENTER_PARTIAL_MIN = 8.0  # px; see recenter_shift
ANCHOR_MARGIN = 32          # px the anchor is kept inside the usable area's edges
RECENTER_TOLERANCE = 0.15   # of the viewport's short side: a kept layout this close isn't shifted
KEEP_MARGIN = 0.04          # a rebuild must beat the current layout by this
KEEP_MARGIN_MIN = 60.0


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


class _Win:
    __slots__ = ("addr", "w", "h", "area", "cur")

    def __init__(self, addr, w, h, cur):
        self.addr, self.w, self.h = addr, int(w), int(h)
        self.area = float(w) * float(h)
        self.cur = cur  # current centre (x, y)


def prominence_order(wins):
    return sorted(wins, key=lambda w: (-w.area, w.addr))


def orientation(wins):
    """(start bearing, turning direction) read from the current layout: the
    second window's bearing from the hub, and the way the prominence-ordered
    windows mostly turn around it (+1 when tied)."""
    order = prominence_order(wins)
    if len(order) < 2:
        return 0.0, 1
    hx, hy = order[0].cur
    angles = [math.atan2(w.cur[1] - hy, w.cur[0] - hx) for w in order[1:]]
    turn = sum(_wrap(b - a) for a, b in zip(angles, angles[1:]))
    return angles[0], (1 if turn >= 0 else -1)


class Composer:
    def __init__(self, band, fixed_rects, monitor):
        self.band = band
        self.fixed = list(fixed_rects)
        mx0, my0, mx1, my1 = monitor
        self.monitor = monitor
        self.view_center = ((mx0 + mx1) / 2.0, (my0 + my1) / 2.0)
        self.aspect_target = ((mx1 - mx0) / (my1 - my0)) ** SHAPE_ASPECT_EXPONENT if my1 > my0 and mx1 > mx0 else 1.0

    # -- feasibility --
    def _clear(self, r, placed):
        """At least the spacing minimum from everything placed and fixed."""
        lo = self.band[0]
        x0, y0, x1, y1 = r
        for group in (placed, self.fixed):
            for q in group:
                # _sep(r, q) < lo, inlined: the hottest loop of a build
                if q[0] - x1 < lo and x0 - q[2] < lo and q[1] - y1 < lo and y0 - q[3] < lo:
                    return False
        return True

    # -- candidates beside a neighbour --
    def _beside(self, win, q, q_area, hub, theta):
        s = pair_spacing(win.area, q_area, self.band)
        w, h = win.w, win.h
        out = []
        qw, qh = q[2] - q[0], q[3] - q[1]
        for side in (0, 1, 2, 3):  # right, left, below, above
            if side < 2:
                x = q[2] + s if side == 0 else q[0] - s - w
                need = MIN_SHARED_FRACTION * min(h, qh)
                lo_y, hi_y = q[1] - h + need, q[3] - need
                if lo_y > hi_y:
                    continue
                ys = {q[1], q[3] - h}
                cy_mid = (q[1] + q[3]) / 2.0
                for f in SLIDE_FRACTIONS:
                    ys.add(cy_mid + f * (qh + h) / 2.0 - h / 2.0)
                c = math.cos(theta)
                if abs(c) > 1e-6:  # where the preferred bearing crosses this side
                    ys.add(hub[1] + math.sin(theta) / c * (x + w / 2.0 - hub[0]) - h / 2.0)
                for y in ys:
                    y = int(round(min(hi_y, max(lo_y, y))))
                    out.append(_rect(x, y, w, h))
            else:
                y = q[3] + s if side == 2 else q[1] - s - h
                need = MIN_SHARED_FRACTION * min(w, qw)
                lo_x, hi_x = q[0] - w + need, q[2] - need
                if lo_x > hi_x:
                    continue
                xs = {q[0], q[2] - w}
                cx_mid = (q[0] + q[2]) / 2.0
                for f in SLIDE_FRACTIONS:
                    xs.add(cx_mid + f * (qw + w) / 2.0 - w / 2.0)
                sn = math.sin(theta)
                if abs(sn) > 1e-6:
                    xs.add(hub[0] + math.cos(theta) / sn * (y + h / 2.0 - hub[1]) - w / 2.0)
                for x in xs:
                    x = int(round(min(hi_x, max(lo_x, x))))
                    out.append(_rect(x, y, w, h))
        return out

    # -- per-candidate score --
    @staticmethod
    def _bearing_cost(r, hub, theta, r_prev):
        """The spiral terms alone: bearing, distance from the hub, and
        falling inside the previous window's radius."""
        cx, cy = _center(r)
        dx, dy = cx - hub[0], cy - hub[1]
        rad = math.hypot(dx, dy)
        total = ANGLE_WEIGHT * abs(_wrap(math.atan2(dy, dx) - theta)) / math.pi
        total += RADIUS_WEIGHT * rad
        if rad < r_prev:
            total += INVERSION_WEIGHT * (r_prev - rad)
        return total

    def _pick(self, cands, extra, win, placed, areas, hub, theta, r_prev, bbox, mass, rel_cur, prev_rect,
              obstacles=None):
        """The lowest-scoring free candidate, ties to the smallest rect.
        Candidates are tried in order of their spiral terms alone; every
        other term is >= 0 except the contact bonuses (at most CHAIN_BONUS
        + NESTLE_BONUS per extra neighbour), so once a candidate's spiral
        terms minus that bound exceed the best full score, none after it can
        win -- the same pick as scoring all of them, far fewer scored.
        `extra(c)` adds caller terms (>= 0); obstacles: what c must clear
        (default: placed + fixed)."""
        bound = CHAIN_BONUS + NESTLE_BONUS * max(0, len(placed) - 1)
        ranked = sorted((self._bearing_cost(c, hub, theta, r_prev), c) for c in set(cands))
        best, best_s = None, None
        for cheap, c in ranked:
            if best_s is not None and cheap - bound > best_s:
                break
            if not self._clear(c, placed if obstacles is None else obstacles):
                continue
            s = self._score(c, win, placed, areas, hub, theta, r_prev, bbox, mass, rel_cur, prev_rect, cheap)
            if extra is not None:
                s += extra(c)
            if best_s is None or s < best_s or (s == best_s and c < best):
                best, best_s = c, s
        return best, best_s

    def _score(self, r, win, placed, areas, hub, theta, r_prev, bbox, mass, rel_cur, prev_rect=None, cheap=None):
        total = self._bearing_cost(r, hub, theta, r_prev) if cheap is None else cheap
        x0, y0, x1, y1 = r
        cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
        dx, dy = cx - hub[0], cy - hub[1]
        near = self.band[1] + 1
        rw, rh = x1 - x0, y1 - y0
        r_short = rw if rw < rh else rh
        contacts = seams = 0
        chained = False
        # one pass over the neighbours: contacts and slits (facing pairs,
        # see _facing), the previous window of the sweep, collinear edges
        for q in placed:
            qx0, qy0, qx1, qy1 = q
            if -SEAM_TOL <= x0 - qx0 <= SEAM_TOL:
                seams += 1
            if -SEAM_TOL <= y0 - qy0 <= SEAM_TOL:
                seams += 1
            if -SEAM_TOL <= x1 - qx1 <= SEAM_TOL:
                seams += 1
            if -SEAM_TOL <= y1 - qy1 <= SEAM_TOL:
                seams += 1
            oy = (y1 if y1 < qy1 else qy1) - (y0 if y0 > qy0 else qy0)
            ox = (x1 if x1 < qx1 else qx1) - (x0 if x0 > qx0 else qx0)
            if oy > 0 and ox <= 0:
                d, span = (qx0 - x1 if qx0 - x1 > x0 - qx1 else x0 - qx1), oy
            elif ox > 0 and oy <= 0:
                d, span = (qy0 - y1 if qy0 - y1 > y0 - qy1 else y0 - qy1), ox
            else:
                continue
            if d <= near:
                qw, qh = qx1 - qx0, qy1 - qy0
                if span >= MIN_SHARED_FRACTION * min(r_short, qw, qh):
                    contacts += 1
                    if q is prev_rect:
                        chained = True
            elif d <= SLIT_MAX:
                total += SLIT_WEIGHT * span
        if contacts > 1:
            total -= NESTLE_BONUS * (contacts - 1)
        if chained:  # prev_rect, when given, is one of `placed`
            total -= CHAIN_BONUS
        total += SEAM_WEIGHT * seams
        # cluster shape after adding r
        bx0, by0, bx1, by1 = min(bbox[0], r[0]), min(bbox[1], r[1]), max(bbox[2], r[2]), max(bbox[3], r[3])
        bw, bh = bx1 - bx0, by1 - by0
        total += ASPECT_WEIGHT * abs(math.log((bw / bh) / self.aspect_target))
        m, mx, my = mass
        a = win.area
        mcx, mcy = (mx + a * cx) / (m + a), (my + a * cy) / (m + a)
        half_diag = math.hypot(bw, bh) / 2.0
        total += BALANCE_WEIGHT * math.hypot(mcx - (bx0 + bx1) / 2.0, mcy - (by0 + by1) / 2.0) / half_diag
        if rel_cur is not None:
            total += MOVE_WEIGHT * math.hypot(dx - rel_cur[0], dy - rel_cur[1])
        return total

    def _hub_rect(self, win):
        vx, vy = self.view_center
        r = _rect(int(round(vx - win.w / 2.0)), int(round(vy - win.h / 2.0)), win.w, win.h)
        if self._clear(r, []):
            return r
        # beside the fixed obstacles, nearest the viewport centre
        best, best_d = None, None
        hub_like = _Win(win.addr, win.w, win.h, win.cur)
        for q in self.fixed:
            for c in self._beside(hub_like, q, win.area, self.view_center, 0.0):
                if self._clear(c, []):
                    d = math.hypot(*(a - b for a, b in zip(_center(c), self.view_center)))
                    if best_d is None or d < best_d:
                        best, best_d = c, d
        return best or r

    def place_next(self, win, placed, areas, hub, theta, r_prev, bbox, mass, rel_cur, prev_rect,
                   extra=None, obstacles=None):
        """THE spiral step, shared by SUPER+G's build and new-window
        placement: where `win` goes next in the sweep around the hub
        centre `hub`, preferring bearing `theta`, no closer to the hub than
        `r_prev`, beside the previous window of the sweep (`prev_rect`).
        Candidates beside the neighbours nearest that frontier first, the
        rest only if none of those is free. Returns (rect, score) or
        (None, None)."""
        target = (hub[0] + math.cos(theta) * (r_prev / RADIUS_FLOOR + 300),
                  hub[1] + math.sin(theta) * (r_prev / RADIUS_FLOOR + 300))
        anchors = sorted(range(len(placed)), key=lambda i: (placed[i] is not prev_rect, math.hypot(
            _center(placed[i])[0] - target[0], _center(placed[i])[1] - target[1])))
        for group in (anchors[:ANCHOR_CAP], anchors[ANCHOR_CAP:]):
            cands = [c for i in group for c in self._beside(win, placed[i], areas[i], hub, theta)]
            best, s = self._pick(cands, extra, win, placed, areas, hub, theta, r_prev, bbox, mass, rel_cur,
                                 prev_rect, obstacles)
            if best is not None:
                return best, s
        return None, None

    def build(self, wins, theta0, direction):
        """{addr: rect} -- the whole composition, hub at the viewport centre
        (or the nearest free spot), every other window by the spiral
        preference. Returns None if some window found no free spot."""
        order = prominence_order(wins)
        hub_win = order[0]
        hub_rect = self._hub_rect(hub_win)
        placed = [hub_rect]
        areas = [hub_win.area]
        out = {hub_win.addr: hub_rect}
        hub = _center(hub_rect)
        bbox = hub_rect
        mass = (hub_win.area, hub_win.area * hub[0], hub_win.area * hub[1])
        r_prev = 0.0
        hcx, hcy = hub_win.cur
        prev_rect = hub_rect
        bearings = _sweep_offsets(order)
        for k, win in enumerate(order[1:], start=1):
            theta = theta0 + direction * bearings[k - 1]
            rel_cur = (win.cur[0] - hcx, win.cur[1] - hcy) if win.cur is not None else None
            best, _s = self.place_next(win, placed, areas, hub, theta, r_prev, bbox, mass, rel_cur, prev_rect)
            if best is None:
                return None
            placed.append(best)
            areas.append(win.area)
            out[win.addr] = best
            cx, cy = _center(best)
            r_prev = RADIUS_FLOOR * math.hypot(cx - hub[0], cy - hub[1])
            prev_rect = best
            bbox = (min(bbox[0], best[0]), min(bbox[1], best[1]), max(bbox[2], best[2]), max(bbox[3], best[3]))
            mass = (mass[0] + win.area, mass[1] + win.area * cx, mass[2] + win.area * cy)
        return out

    # -- whole composition --
    def whole_score(self, rects, wins, current=None):
        """Lower is better. rects: {addr: rect}; current: {addr: centre}."""
        items = [(w, rects[w.addr]) for w in wins]
        lo, hi = self.band
        total = 0.0
        rs = [r for _w, r in items]
        for i in range(len(rs)):
            for j in range(i + 1, len(rs)):
                s = _sep(rs[i], rs[j])
                if s < lo - 0.5:
                    total += TIGHT_GAP_WEIGHT if s >= 0 else 1e6
                    continue
                f = _facing(rs[i], rs[j])
                if f is not None and hi < f[0] <= SLIT_MAX and f[1] > 40:
                    total += SLIT_PAIR_WEIGHT
        n = len(items)
        cs = [_center(r) for r in rs]
        mx, my = sum(c[0] for c in cs) / n, sum(c[1] for c in cs) / n
        if n >= 4:
            pts = sorted((math.hypot(c[0] - mx, c[1] - my), math.atan2(c[1] - my, c[0] - mx)) for c in cs)[1:]
            steps = [_wrap(b[1] - a[1]) for a, b in zip(pts, pts[1:])]
            if steps:
                pos = sum(s > 0 for s in steps)
                total += FLOW_WEIGHT * (1.0 - max(pos, len(steps) - pos) / len(steps))
            radii = [math.hypot(c[0] - mx, c[1] - my) for c in cs]
            total += CENTRALITY_WEIGHT * (1.0 - _spearman([-w.area for w, _r in items], radii)) / 2.0
        bx0, by0 = min(r[0] for r in rs), min(r[1] for r in rs)
        bx1, by1 = max(r[2] for r in rs), max(r[3] for r in rs)
        bw, bh = bx1 - bx0, by1 - by0
        total += ASPECT_WEIGHT * abs(math.log((bw / bh) / self.aspect_target))
        fill = sum(w.area for w, _r in items) / float(bw * bh)
        if fill < FILL_RANGE[0]:
            total += FILL_WEIGHT * (FILL_RANGE[0] - fill)
        elif fill > FILL_RANGE[1]:
            total += FILL_WEIGHT * (fill - FILL_RANGE[1])
        m = sum(w.area for w, _r in items)
        mcx = sum(w.area * _center(r)[0] for w, r in items) / m
        mcy = sum(w.area * _center(r)[1] for w, r in items) / m
        total += BALANCE_WEIGHT * math.hypot(mcx - (bx0 + bx1) / 2.0, mcy - (by0 + by1) / 2.0) / (math.hypot(bw, bh) / 2.0)
        seams = 0
        for i in range(len(rs)):
            for j in range(i + 1, len(rs)):
                for e in (0, 1, 2, 3):
                    if abs(rs[i][e] - rs[j][e]) <= SEAM_TOL:
                        seams += 1
        total += SEAM_WEIGHT * 0.5 * seams
        if current:
            ccx = sum(current[w.addr][0] for w, _r in items) / n
            ccy = sum(current[w.addr][1] for w, _r in items) / n
            mv = sum(math.hypot((_center(r)[0] - mx) - (current[w.addr][0] - ccx),
                                (_center(r)[1] - my) - (current[w.addr][1] - ccy)) for w, r in items) / n
            total += WHOLE_MOVE_WEIGHT * mv
        return total

    # -- recentring: the bounding box on the viewport centre, as nearly as
    # the anchor (the window the spiral winds round) allows: it must keep
    # covering the centre point, and stay ANCHOR_MARGIN inside the usable
    # area where it fits -- centring a composition bigger than the screen
    # used to cut the anchor off. Scaled back if it would run into a fixed
    # window. --
    def recenter_shift(self, rects, anchor=None):
        rs = list(rects)
        bx0, by0 = min(r[0] for r in rs), min(r[1] for r in rs)
        bx1, by1 = max(r[2] for r in rs), max(r[3] for r in rs)
        full = [self.view_center[0] - (bx0 + bx1) / 2.0, self.view_center[1] - (by0 + by1) / 2.0]
        if anchor is not None:
            mx0, my0, mx1, my1 = self.monitor
            for axis, (lo_edge, hi_edge) in enumerate(((mx0, mx1), (my0, my1))):
                a0, a1 = anchor[axis], anchor[axis + 2]
                c = self.view_center[axis]
                # the anchor keeps covering the centre point (so it stays
                # the anchor, see anchor_index)...
                lo, hi = c - a1, c - a0
                # ...and comfortably inside the usable area where it fits
                vlo, vhi = lo_edge + ANCHOR_MARGIN - a0, hi_edge - ANCHOR_MARGIN - a1
                if vlo <= vhi and max(lo, vlo) <= min(hi, vhi):
                    lo, hi = max(lo, vlo), min(hi, vhi)
                full[axis] = min(hi, max(lo, full[axis]))

        def safe(dx, dy):
            for r in rs:
                sr = (r[0] + dx, r[1] + dy, r[2] + dx, r[3] + dy)
                for q in self.fixed:
                    if _sep(sr, q) < self.band[0] and _sep(r, q) >= self.band[0]:
                        return False
            return True

        dx, dy = round(full[0]), round(full[1])
        if not self.fixed or safe(dx, dy):
            return dx, dy
        lo, hi = 0.0, 1.0
        for _ in range(20):
            mid = (lo + hi) / 2
            if safe(full[0] * mid, full[1] * mid):
                lo = mid
            else:
                hi = mid
        dx, dy = math.trunc(full[0] * lo), math.trunc(full[1] * lo)
        # a partial shift that small is the last pixel or two of room next
        # to a fixed window -- taking it would creep a pixel every press
        if math.hypot(dx, dy) < RECENTER_PARTIAL_MIN:
            return 0, 0
        return (dx, dy) if safe(dx, dy) else (0, 0)


def _sweep_offsets(order):
    """Bearing of each non-hub window (prominence order) from the first
    one's, in radians along the sweep (see SWEEP_TURNS_*)."""
    sides = [math.sqrt(w.area) for w in order[1:]]
    if not sides:
        return []
    lo, hi = SWEEP_TURNS_RANGE
    turns = min(hi, max(lo, SWEEP_TURNS_BASE + SWEEP_TURNS_PER_WINDOW * (len(order) - 1)))
    shares = [2 * math.pi * turns * s / sum(sides) for s in sides]
    out = [0.0]
    for a, b in zip(shares, shares[1:]):
        out.append(out[-1] + (a + b) / 2.0)
    return out


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


def _spearman(x, y):
    n = len(x)
    if n < 3:
        return 0.0
    rx = {v: i for i, v in enumerate(sorted(range(n), key=lambda k: (x[k], k)))}
    ry = {v: i for i, v in enumerate(sorted(range(n), key=lambda k: (y[k], k)))}
    d2 = sum((rx[i] - ry[i]) ** 2 for i in range(n))
    return 1 - 6 * d2 / (n * (n * n - 1))


def compose(eligible, fixed_rects, monitor, band, sizes=None):
    """Positions for every eligible window: [(addr, x, y, w, h), ...].

    eligible: [{"address", "at", "size"}]; sizes overrides a window's size
    ({addr: (w, h)}, for resize variants). Keeps the current layout
    (recentred) unless a rebuild is a real improvement on it. Returns
    (rows, composer, windows, kept) -- kept: the current layout was kept."""
    sizes = sizes or {}
    wins = []
    current_rects = {}
    for e in eligible:
        w, h = sizes.get(e["address"], e["size"])
        cx, cy = e["at"][0] + e["size"][0] / 2.0, e["at"][1] + e["size"][1] / 2.0
        wins.append(_Win(e["address"], w, h, (cx, cy)))
        current_rects[e["address"]] = _rect(e["at"][0], e["at"][1], e["size"][0], e["size"][1])
    comp = Composer(band, fixed_rects, monitor)
    current_centres = {w.addr: w.cur for w in wins}

    _theta0, direction = orientation(wins)
    best, best_score = None, None
    # A small fixed search: the sweep starting on each of START_VARIANTS
    # evenly spread bearings, turning either way (the current layout's own
    # turning direction first, so it wins ties); the whole-composition score,
    # which also charges movement, picks. The same set of starts on every
    # press is what makes the next press reproduce this one's result rather
    # than search somewhere new. Deterministic and bounded: 8 builds.
    for start in range(START_VARIANTS):
        for d in (direction, -direction):
            built = comp.build(wins, START_OFFSET + start * 2 * math.pi / START_VARIANTS, d)
            if built is None:
                continue
            s = comp.whole_score(built, wins, current_centres)
            if best_score is None or s < best_score - 1e-9:
                best, best_score = built, s

    resized = any(tuple(sizes.get(e["address"], e["size"])) != tuple(e["size"]) for e in eligible)
    kept = False
    if not resized and len(wins) > 1:
        # keep the current layout unless the rebuild is clearly better
        cur_score = comp.whole_score(current_rects, wins, current_centres)
        if best is None or best_score > cur_score - max(KEEP_MARGIN_MIN, KEEP_MARGIN * abs(cur_score)):
            best, kept = current_rects, True
    if best is None:
        best, kept = current_rects, True
    anchor_rect = best[wins[anchor_index([best[w.addr] for w in wins], comp.view_center)].addr]
    dx, dy = comp.recenter_shift(best.values(), anchor_rect)
    if kept:
        # a finished layout already about on screen stays exactly where it is
        mx0, my0, mx1, my1 = monitor
        if math.hypot(dx, dy) <= RECENTER_TOLERANCE * min(mx1 - mx0, my1 - my0):
            dx, dy = 0, 0
    return [(w.addr, best[w.addr][0] + dx, best[w.addr][1] + dy, best[w.addr][2] - best[w.addr][0],
             best[w.addr][3] - best[w.addr][1]) for w in wins], comp, wins, kept


def score_rows(rows, eligible, fixed_rects, monitor, band):
    """Whole-composition score of a finished [(addr, x, y, w, h)] layout,
    movement measured from `eligible`."""
    comp = Composer(band, fixed_rects, monitor)
    wins = [_Win(a, w, h, None) for a, _x, _y, w, h in rows]
    cur = {e["address"]: (e["at"][0] + e["size"][0] / 2.0, e["at"][1] + e["size"][1] / 2.0) for e in eligible}
    return comp.whole_score({a: _rect(x, y, w, h) for a, x, y, w, h in rows}, wins, cur)


def anchor_index(rects, view_center):
    """Which window a composition winds round, read from geometry alone (no
    remembered state to go stale when windows close or workspaces change):
    the window covering the usable area's centre point -- where new-window
    placement puts the first window and SUPER+G puts its hub, and where
    recentring keeps it (Composer.recenter_shift). When none does (the user
    panned away), the most central one: the smallest mean distance to the
    others, to the pixel; ties nearest the centre, then the larger, then
    the first listed."""
    cx, cy = view_center
    covering = [i for i, r in enumerate(rects) if r[0] <= cx <= r[2] and r[1] <= cy <= r[3]]
    if covering:
        return min(covering, key=lambda i: (math.hypot(_center(rects[i])[0] - cx, _center(rects[i])[1] - cy), i))
    cs = [_center(r) for r in rects]
    n = len(cs)
    if n == 1:
        return 0

    def key(i):
        mean = sum(math.hypot(cs[i][0] - c[0], cs[i][1] - c[1]) for c in cs) / (n - 1)
        own = math.hypot(cs[i][0] - cx, cs[i][1] - cy)
        r = rects[i]
        return (round(mean), round(own, 3), -(r[2] - r[0]) * (r[3] - r[1]), i)
    return min(range(n), key=key)


def _touches(a, b, reach=SPACING_MAX_DEFAULT + 1):
    f = _facing(a, b)
    return f is not None and f[0] <= reach


# A step along an arm advances up to this far round the anchor (SUPER+G
# spreads a few windows over more than a turn, so steps past 180 degrees
# are real).
ARM_STEP_MAX = math.radians(200)


def _arm_score(seq, bearing, rad):
    """How well `seq` reads as one arm round the anchor: the share of steps
    advancing 0..ARM_STEP_MAX one way round, plus the share of steps that
    don't move closer to the anchor (a spiral widens; 10% slack). Returns
    (score, direction)."""
    if len(seq) < 2:
        return 0.0, 1
    best = None
    for d in (1, -1):
        adv = [(d * (bearing[b] - bearing[a])) % (2 * math.pi) for a, b in zip(seq, seq[1:])]
        turn = sum(0 < x <= ARM_STEP_MAX for x in adv) / len(adv)
        if best is None or turn > best[0]:
            best = (turn, d)
    out = sum(rad[b] >= 0.9 * rad[a] for a, b in zip(seq, seq[1:])) / (len(seq) - 1)
    # widening counts double: turning one way within ARM_STEP_MAX is easy
    # for any order of a few windows to pass, a steadily widening one isn't
    return best[0] + 2 * out, best[1]


def sweep_state(rects, anchor, new_area=None):
    """The spiral as it stands, read without remembered state: (others,
    tip, bearing, direction, step). `rects` must be in the order the
    windows were created (Hyprland's stableId / client list order), so a
    spiral auto-placement grew reads in creation order; one SUPER+G built
    reads in its own sweep order, prominence. Of the two, the order that
    reads best as one arm (_arm_score: turning one way round the anchor,
    widening as it goes) is the arm (creation wins ties): its last window
    is the tip and its turning sense the direction. A closed window just drops out of both orders.
    `step` is the bearing to the next window: the tip's and the new
    window's angular half-widths as seen from the anchor (JOIN_ARC_RANGE),
    so the new window sits beside the tip one window further round.
    SUPER+G's build knows every window in advance and shares a planned
    sweep out instead (_sweep_offsets); opening windows one at a time can
    only extend the arm by what is actually there."""
    hub = _center(rects[anchor])
    rad, bearing = {}, {}
    for i in range(len(rects)):
        if i != anchor:
            c = _center(rects[i])
            rad[i] = math.hypot(c[0] - hub[0], c[1] - hub[1])
            bearing[i] = math.atan2(c[1] - hub[1], c[0] - hub[0])
    created = [i for i in range(len(rects)) if i != anchor]
    area = lambda i: (rects[i][2] - rects[i][0]) * (rects[i][3] - rects[i][1])  # noqa: E731
    prominent = sorted(created, key=lambda i: (-area(i), i))
    direction = None
    seq = created
    if len(created) >= 2:
        c_score, c_dir = _arm_score(created, bearing, rad)
        p_score, p_dir = _arm_score(prominent, bearing, rad)
        seq, direction = (prominent, p_dir) if p_score > c_score else (created, c_dir)
    tip = seq[-1] if seq else anchor
    others = seq
    step = None
    if others and new_area is not None:
        side = lambda r: math.sqrt((r[2] - r[0]) * (r[3] - r[1]))  # noqa: E731
        reach = max(rad[tip], side(rects[anchor]) / 2.0, 1.0)
        arc = (math.atan2(side(rects[tip]) / 2.0, reach) + math.atan2(math.sqrt(new_area) / 2.0, reach))
        step = min(JOIN_ARC_RANGE[1], max(JOIN_ARC_RANGE[0], arc))
    return others, tip, bearing, direction, step


# Bearing step from the arm's tip to a newly opened window (see sweep_state).
JOIN_ARC_RANGE = (math.radians(30), math.radians(150))


# A closed window can leave an enclosed hole inside the spiral. A new
# window takes it before extending the arm when it fits snugly there: a free
# spot closer to the anchor than the arm's tip, touching at least
# FILL_MIN_CONTACTS windows at the composition spacing, with no slit. Any
# looser test fires during ordinary growth too and scatters the sweep (each
# window dropping into whichever inner nook is nearest the anchor); after a
# close in an airy layout the arm simply continues, which keeps every
# window where it was.
FILL_MIN_CONTACTS = 3
VACANCY_BEARINGS = 12        # projection bearings tried when looking for one
# Auto-placement can never move a window later, so a slit it leaves stays:
# a candidate that makes one is all but ruled out.
JOIN_SLIT_PENALTY = 5000.0


def _slits(c, placed, hi):
    n = 0
    for p in placed:
        f = _facing(c, p)
        if f is not None and hi + 1 < f[0] <= SLIT_MAX and f[1] > 40:
            n += 1
    return n


def _snug_beside(comp, new, q, q_area, placed, areas):
    """Positions beside `q` at the pair's spacing, slid to line up with
    another window's edge at its own spacing -- the spots where a window
    fits snugly between two or three others (a closed window's hole)."""
    w, h = new.w, new.h
    out = []
    qw, qh = q[2] - q[0], q[3] - q[1]
    for side in (0, 1, 2, 3):
        s = pair_spacing(new.area, q_area, comp.band)
        if side < 2:
            x = q[2] + s if side == 0 else q[0] - s - w
            need = MIN_SHARED_FRACTION * min(h, qh)
            lo, hi = q[1] - h + need, q[3] - need
            for p, pa in zip(placed, areas):
                sp_ = pair_spacing(new.area, pa, comp.band)
                for y in (p[3] + sp_, p[1] - sp_ - h):
                    if lo <= y <= hi:
                        out.append(_rect(x, int(y), w, h))
        else:
            y = q[3] + s if side == 2 else q[1] - s - h
            need = MIN_SHARED_FRACTION * min(w, qw)
            lo, hi = q[0] - w + need, q[2] - need
            for p, pa in zip(placed, areas):
                sp_ = pair_spacing(new.area, pa, comp.band)
                for x in (p[2] + sp_, p[0] - sp_ - w):
                    if lo <= x <= hi:
                        out.append(_rect(int(x), y, w, h))
    return out


def _vacancy(comp, new, placed, areas, anchor, others, r_tip):
    """The best enclosed hole for `new` (see FILL_MIN_CONTACTS), or None:
    the snuggest -- nearest the anchor, fewest collinear edges."""
    if len(others) < 2:
        return None
    hub = _center(placed[anchor])
    hi = comp.band[1] + 1
    best, best_s = None, None
    cands = set()
    for i, q in enumerate(placed):
        for k in range(VACANCY_BEARINGS):
            cands.update(comp._beside(new, q, areas[i], hub, k * 2 * math.pi / VACANCY_BEARINGS))
        cands.update(_snug_beside(comp, new, q, areas[i], placed, areas))
    for c in sorted(cands):
        if not comp._clear(c, []):
            continue
        cx, cy = _center(c)
        rad = math.hypot(cx - hub[0], cy - hub[1])
        if rad >= r_tip:
            continue
        r_short = min(c[2] - c[0], c[3] - c[1])
        contacts, touches_anchor, seams = 0, False, 0
        for k, p in enumerate(placed):
            seams += sum(abs(c[e] - p[e]) <= SEAM_TOL for e in range(4))
            f = _facing(c, p)
            if f is not None and f[0] <= hi and f[1] >= MIN_SHARED_FRACTION * min(r_short, p[2] - p[0], p[3] - p[1]):
                contacts += 1
                touches_anchor = touches_anchor or k == anchor
        if contacts < FILL_MIN_CONTACTS or _slits(c, comp.fixed, comp.band[1]):
            continue
        sc = rad + SEAM_WEIGHT * seams
        if best_s is None or sc < best_s or (sc == best_s and c < best):
            best, best_s = c, sc
    return best


def join(new_size, layout, obstacles, monitor, band):
    """Where a newly opened window joins the composition, every existing
    window held where it is. The first window becomes the anchor, at the
    usable area's centre (clear of fixed windows). Every later one is the
    next step of the same sweep SUPER+G builds (Composer.place_next): round
    the anchor (anchor_index), beside the arm's outer end, one step further
    round (sweep_state), no closer in -- or into a vacancy a closed window
    left inside the spiral (_vacancy). While the sweep's start or
    turning direction is still open (one or two windows), the same start
    bearings / both directions SUPER+G tries are tried and the best kept.
    layout: [(x, y, w, h)] in the order the windows were created (see
    sweep_state); obstacles: [(x, y, w, h)]. Returns the top-left (x, y)."""
    nw, nh = int(new_size[0]), int(new_size[1])
    obstacle_rects = [_rect(*o) for o in obstacles]
    comp = Composer(band, obstacle_rects, monitor)
    new = _Win("\0new", nw, nh, None)
    if not layout:
        r = comp._hub_rect(new)
        return r[0], r[1]
    placed = [_rect(int(x), int(y), int(w), int(h)) for x, y, w, h in layout]
    areas = [float(w) * float(h) for _x, _y, w, h in layout]
    a = anchor_index(placed, comp.view_center)
    hub = _center(placed[a])
    others, tip, bearing, direction, step = sweep_state(placed, a, nw * nh)
    r_tip = math.hypot(_center(placed[tip])[0] - hub[0], _center(placed[tip])[1] - hub[1])
    hole = _vacancy(comp, new, placed, areas, a, others, r_tip)
    if hole is not None:
        return hole[0], hole[1]
    if not others:
        # the second window: where the sweep starts is still open -- the
        # same start bearings SUPER+G tries; the score (screen shape,
        # balance, staying central) decides
        thetas = [START_OFFSET + k * 2 * math.pi / START_VARIANTS for k in range(START_VARIANTS)]
    else:
        dirs = [direction] if direction is not None else [1, -1]
        thetas = [bearing[tip] + d * step for d in dirs]
    # no radius floor: round a wide anchor the next spot along can be nearer
    # its centre; contact with the tip and the bearing keep the arm going,
    # and it moves outward once the turn round the anchor is full
    r_prev = 0.0
    bbox = (min(r[0] for r in placed), min(r[1] for r in placed), max(r[2] for r in placed), max(r[3] for r in placed))
    m = sum(areas)
    mass = (m, sum(ar * _center(r)[0] for ar, r in zip(areas, placed)), sum(ar * _center(r)[1] for ar, r in zip(areas, placed)))
    mx0, my0, mx1, my1 = monitor
    half = min(mx1 - mx0, my1 - my0) / 2.0

    def extra(c):
        # a new window should open where most of it can be seen -- outer
        # windows may run past the screen edge, but not open mostly hidden
        vis_w = max(0, min(c[2], mx1) - max(c[0], mx0))
        vis_h = max(0, min(c[3], my1) - max(c[1], my0))
        s = JOIN_VISIBLE_WEIGHT * max(0.0, JOIN_VISIBLE_SHARE - (vis_w * vis_h) / float(nw * nh))
        s += JOIN_SLIT_PENALTY * _slits(c, obstacle_rects, comp.band[1])  # every window, seen or not
        # ...and keep the composition about the screen centre (SUPER+G
        # recentres afterwards; opening a window can't move the others)
        gx0, gy0 = min(bbox[0], c[0]), min(bbox[1], c[1])
        gx1, gy1 = max(bbox[2], c[2]), max(bbox[3], c[3])
        # (each axis relative to the usable area's size: a wide screen has
        # more room sideways than up and down)
        return s + JOIN_CENTRE_WEIGHT * half * math.hypot(((gx0 + gx1) / 2.0 - comp.view_center[0]) / (mx1 - mx0) * 2,
                                                          ((gy0 + gy1) / 2.0 - comp.view_center[1]) / (my1 - my0) * 2)

    best, best_s = None, None
    for theta in thetas:
        c, sc = comp.place_next(new, placed, areas, hub, theta, r_prev, bbox, mass, None, placed[tip],
                                extra=extra, obstacles=[])
        if c is not None and (best_s is None or sc < best_s):
            best, best_s = c, sc
    if best is None:
        r = comp._hub_rect(new)
        return r[0], r[1]
    return best[0], best[1]
