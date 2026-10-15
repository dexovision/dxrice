#!/usr/bin/env python3
"""SUPER+G composition report: runs the real auto_arrange on deterministic,
real-world-inspired desktops and measures what the eye judges -- not just
the invariants dxrice_placement_benchmark.py checks.

Per fixture, after the presses a user would make (SUPER+G pressed until it
settles, resize memory carried between presses like main() does):

  overlaps / spacing    pairs overlapping, or closer than the composition
                        spacing minimum (dxrice_spiral, 16 px by default)
  sloppy_gutters        facing neighbours further apart than the spacing
                        maximum but closer than dxrice_spiral.SLIT_MAX --
                        a slit (reads as an accident, not breathing room)
  detached              windows not within the spacing maximum of any other
  fill                  occupied area / bounding-box area
  dead_area / dead_max  concave pockets: empty area a 128px brush can't
                        reach -- a morphological closing of the cluster
                        (gutters up to the spacing maximum fused) minus the
                        cluster itself. Since the spiral redesign the
                        silhouette is staggered on purpose, so this is a
                        measurement of how much negative space sits inside
                        the outline, not a defect count; "holes" is.

Before the spiral redesign the gap here was Hyprland's gaps_in (5 px),
exact, and every other gutter counted as sloppy.
  holes                 empty area fully enclosed by windows, any size
  jaggedness            silhouette perimeter / bounding-box perimeter
                        (1.0 = a plain rectangle; organic shapes sit a bit
                        above, ragged ones well above)
  move / resize         total centre movement and resized windows, press 1
  settle                presses until nothing moves; move on press 2
  ms                    runtime of press 1

Pure measurement on an 8px grid, no third-party modules needed. With
--render DIR (needs Pillow) each layout is drawn to DIR/<fixture>.png,
dead area in red, for looking at -- the numbers are a guide, the pictures
are the judgement.

    python3 scripts/dxrice_arrange_report.py [--render DIR] [--json FILE]
"""
import argparse
import json
import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dxrice_auto_arrange as arr  # noqa: E402
import dxrice_spiral  # noqa: E402

BAND = (dxrice_spiral.SPACING_MIN_DEFAULT, dxrice_spiral.SPACING_MAX_DEFAULT)

GAP = 5
MONITOR = (0, 0, 1920, 1080)
CELL = 8
CLOSE_RADIUS = 64  # px: channels/notches narrower than ~2x this count as dead


def _w(addr, x, y, w, h):
    return {"address": addr, "at": [x, y], "size": [w, h]}


# Desktops people actually have open, at their usual sizes, in the messy
# positions they end up in before SUPER+G. Deterministic by construction.
FIXTURES = {
    "coding": [
        _w("browser", 120, 80, 1280, 900), _w("editor", 700, 200, 1100, 800),
        _w("terminal", 1300, 600, 800, 500), _w("files", -200, 500, 900, 600),
        _w("calc", 1500, 50, 300, 420),
    ],
    "chat_media": [
        _w("discord", 300, 100, 1200, 800), _w("spotify", 900, 500, 1000, 700),
        _w("pavucontrol", 50, 650, 700, 500), _w("settings", 1400, 80, 520, 420),
    ],
    "terminals8": [_w(f"term{i}", 100 + (i * 233) % 1500, 60 + (i * 157) % 800, 640, 400) for i in range(8)],
    "huge_and_dialogs": [
        _w("ide", 60, 40, 1800, 1000), _w("find", 700, 300, 420, 260),
        _w("confirm", 900, 500, 380, 180), _w("picker", 300, 700, 600, 450),
    ],
    "mixed7": [
        _w("browser", 0, 0, 1400, 950), _w("mail", 600, 300, 1000, 700), _w("term", 1200, 700, 700, 450),
        _w("notes", 200, 600, 500, 650), _w("music", 1500, 100, 450, 600), _w("calc", 900, 120, 320, 420),
        _w("viewer", -300, 200, 800, 560),
    ],
    "tall_and_wide": [
        _w("log", 100, 0, 420, 1050), _w("timeline", 300, 820, 1600, 260), _w("chat", 1500, 0, 380, 900),
        _w("doc", 600, 150, 900, 640),
    ],
    "twelve": [
        _w(f"w{i}", (i * 311) % 1700 - 200, (i * 197) % 900 - 100, s[0], s[1])
        for i, s in enumerate([(1200, 800), (900, 650), (800, 500), (640, 400), (640, 400), (500, 700),
                               (1100, 720), (420, 300), (380, 260), (700, 900), (560, 420), (300, 200)])
    ],
    "offscreen_negative": [
        _w("a", -2600, -900, 1000, 700), _w("b", -1500, -1200, 800, 600), _w("c", -3200, 400, 1200, 800),
        _w("d", -900, 300, 600, 500),
    ],
    "two_equal": [_w("left", 200, 200, 900, 700), _w("right", 1000, 300, 900, 700)],
    "three_mixed": [_w("big", 100, 100, 1300, 850), _w("mid", 900, 400, 800, 600), _w("small", 300, 600, 450, 320)],
}

FIXED = {
    # A fullscreen window on the monitor everyone else must route around.
    "with_fullscreen": ([_w("vid", 0, 0, 1920, 1080)],
                        [_w("x", 200, 300, 900, 600), _w("y", 900, 500, 800, 600), _w("z", 1300, 100, 600, 400)]),
}


def press_until_settled(eligible, fixed, max_presses=5):
    """Presses SUPER+G repeatedly (carrying resize memory like main()).
    Returns (presses, first_ms) where presses[i] = (rects, movement, resized)."""
    layout = eligible
    state = {}
    presses = []
    first_ms = None
    for i in range(max_presses):
        t0 = time.perf_counter()
        result = arr.auto_arrange(layout, fixed, MONITOR, GAP,
                                  resize_locked=arr._locked_addresses(state, layout))
        ms = 1000 * (time.perf_counter() - t0)
        if first_ms is None:
            first_ms = ms
        before = {w["address"]: (w["at"][0], w["at"][1], w["size"][0], w["size"][1]) for w in layout}
        resized = [a for a, x, y, w, h in result if (w, h) != tuple(before[a][2:])]
        state = arr._next_resize_state(state, set(before), {a: (w, h) for a, x, y, w, h in result}, resized)
        move = sum(math.hypot(x + w / 2 - (before[a][0] + before[a][2] / 2), y + h / 2 - (before[a][1] + before[a][3] / 2))
                   for a, x, y, w, h in result)
        presses.append((list(result), move, resized))
        layout = [_w(a, x, y, w, h) for a, x, y, w, h in result]
        if i > 0 and move < 1 and not resized:
            break
    return presses, first_ms


def _grid(rects, inflate):
    x0 = min(r[1] for r in rects) - 2 * CLOSE_RADIUS
    y0 = min(r[2] for r in rects) - 2 * CLOSE_RADIUS
    x1 = max(r[1] + r[3] for r in rects) + 2 * CLOSE_RADIUS
    y1 = max(r[2] + r[4] for r in rects) + 2 * CLOSE_RADIUS
    cols, rows = int((x1 - x0) // CELL) + 1, int((y1 - y0) // CELL) + 1
    grid = [bytearray(cols) for _ in range(rows)]
    for _, x, y, w, h in rects:
        c0 = max(0, int((x - inflate - x0) // CELL)); c1 = min(cols, int(math.ceil((x + w + inflate - x0) / CELL)))
        r0 = max(0, int((y - inflate - y0) // CELL)); r1 = min(rows, int(math.ceil((y + h + inflate - y0) / CELL)))
        for r in range(r0, r1):
            grid[r][c0:c1] = b"\x01" * (c1 - c0)
    return grid, (x0, y0), cols, rows


def _box_any(grid, cols, rows, rad):
    """1 where any cell within a (2rad+1)^2 box is set (dilation)."""
    pre = [[0] * (cols + 1) for _ in range(rows + 1)]
    for r in range(rows):
        acc = 0
        row, prow, nrow = grid[r], pre[r], pre[r + 1]
        for c in range(cols):
            acc += row[c]
            nrow[c + 1] = prow[c + 1] + acc
    out = [bytearray(cols) for _ in range(rows)]
    for r in range(rows):
        ra, rb = max(0, r - rad), min(rows, r + rad + 1)
        pa, pb, o = pre[ra], pre[rb], out[r]
        for c in range(cols):
            ca, cb = max(0, c - rad), min(cols, c + rad + 1)
            if pb[cb] - pa[cb] - pb[ca] + pa[ca]:
                o[c] = 1
    return out


def _closing(grid, cols, rows, rad):
    dil = _box_any(grid, cols, rows, rad)
    inv = [bytearray(1 - v for v in row) for row in dil]
    ero_inv = _box_any(inv, cols, rows, rad)
    return [bytearray(1 - v for v in row) for row in ero_inv]


def _components(mask, cols, rows):
    seen = [bytearray(cols) for _ in range(rows)]
    comps = []
    for r in range(rows):
        for c in range(cols):
            if mask[r][c] and not seen[r][c]:
                stack, cells = [(r, c)], []
                seen[r][c] = 1
                while stack:
                    a, b = stack.pop()
                    cells.append((a, b))
                    for na, nb in ((a + 1, b), (a - 1, b), (a, b + 1), (a, b - 1)):
                        if 0 <= na < rows and 0 <= nb < cols and mask[na][nb] and not seen[na][nb]:
                            seen[na][nb] = 1
                            stack.append((na, nb))
                comps.append(cells)
    return comps


def measure(rects, band=BAND):
    lo, hi = band
    n = len(rects)
    overlaps = spacing = sloppy = 0
    for i in range(n):
        for j in range(i + 1, n):
            _, ax, ay, aw, ah = rects[i]
            _, bx, by, bw, bh = rects[j]
            ox = min(ax + aw, bx + bw) - max(ax, bx)
            oy = min(ay + ah, by + bh) - max(ay, by)
            if ox > 0 and oy > 0:
                overlaps += 1
                continue
            # Facing pair: separated on one axis, overlapping on the other.
            if oy > 0.3 * min(ah, bh):
                d = max(bx - (ax + aw), ax - (bx + bw))
            elif ox > 0.3 * min(aw, bw):
                d = max(by - (ay + ah), ay - (by + bh))
            else:
                continue
            if d < lo - 0.5:
                spacing += 1
            elif hi + 0.5 < d <= dxrice_spiral.SLIT_MAX:
                sloppy += 1
    detached = sum(1 for r in rects if n > 1 and min(
        max(o[1] - (r[1] + r[3]), r[1] - (o[1] + o[3]), o[2] - (r[2] + r[4]), r[2] - (o[2] + o[4]))
        for o in rects if o is not r) > hi + 1)
    union, (gx, gy), cols, rows = _grid(rects, inflate=hi / 2 + 1)
    occupied = sum(sum(row) for row in union) * CELL * CELL
    bx0 = min(r[1] for r in rects); by0 = min(r[2] for r in rects)
    bx1 = max(r[1] + r[3] for r in rects); by1 = max(r[2] + r[4] for r in rects)
    bbox_area = (bx1 - bx0) * (by1 - by0)
    closed = _closing(union, cols, rows, CLOSE_RADIUS // CELL)
    dead_mask = [bytearray(c & (1 - u) for c, u in zip(crow, urow)) for crow, urow in zip(closed, union)]
    dead = _components(dead_mask, cols, rows)
    dead_sizes = sorted((len(c) * CELL * CELL for c in dead), reverse=True)
    free = [bytearray(1 - v for v in row) for row in union]
    holes = 0
    for comp in _components(free, cols, rows):
        if not any(a in (0, rows - 1) or b in (0, cols - 1) for a, b in comp):
            holes += len(comp) * CELL * CELL
    perim = 0
    for r in range(rows):
        for c in range(cols):
            if union[r][c]:
                for na, nb in ((r + 1, c), (r - 1, c), (r, c + 1), (r, c - 1)):
                    if not (0 <= na < rows and 0 <= nb < cols) or not union[na][nb]:
                        perim += CELL
    return dict(overlaps=overlaps, spacing=spacing, sloppy_gutters=sloppy, detached=detached,
                fill=round(min(1.0, occupied / bbox_area), 3) if bbox_area else 0,
                dead_area=sum(dead_sizes), dead_max=dead_sizes[0] if dead_sizes else 0,
                holes=holes, jaggedness=round(perim / (2 * ((bx1 - bx0) + (by1 - by0))), 3),
                bbox=(bx1 - bx0, by1 - by0)), (dead_mask, (gx, gy))


def render(path, rects, fixed, dead, title):
    from PIL import Image, ImageDraw
    mask, (gx, gy) = dead
    allr = rects + [(w["address"], w["at"][0], w["at"][1], w["size"][0], w["size"][1]) for w in fixed]
    x0 = min(min(r[1] for r in allr), MONITOR[0]) - 80; y0 = min(min(r[2] for r in allr), MONITOR[1]) - 80
    x1 = max(max(r[1] + r[3] for r in allr), MONITOR[2]) + 80; y1 = max(max(r[2] + r[4] for r in allr), MONITOR[3]) + 80
    scale = min(1.0, 1100 / max(x1 - x0, y1 - y0))
    img = Image.new("RGB", (int((x1 - x0) * scale), int((y1 - y0) * scale) + 24), (24, 26, 31))
    d = ImageDraw.Draw(img)
    T = lambda x, y: ((x - x0) * scale, (y - y0) * scale + 24)  # noqa: E731
    d.text((6, 4), title, fill=(230, 230, 230))
    d.rectangle([*T(*MONITOR[:2]), *T(*MONITOR[2:])], outline=(90, 110, 140), width=2)
    for r, row in enumerate(mask):
        for c, v in enumerate(row):
            if v:
                px, py = gx + c * CELL, gy + r * CELL
                d.rectangle([*T(px, py), *T(px + CELL, py + CELL)], fill=(170, 50, 50))
    for w in fixed:
        x, y = w["at"]; ww, hh = w["size"]
        d.rectangle([*T(x, y), *T(x + ww, y + hh)], outline=(200, 160, 60), width=2)
    for a, x, y, w, h in rects:
        d.rectangle([*T(x, y), *T(x + w, y + h)], fill=(70, 78, 92), outline=(210, 214, 222), width=1)
        d.text((T(x, y)[0] + 4, T(x, y)[1] + 3), f"{a} {w}x{h}", fill=(235, 235, 235))
    img.save(path)


def run_all(render_dir=None):
    out = {}
    cases = [(k, v, []) for k, v in FIXTURES.items()] + [(k, e, f) for k, (f, e) in FIXED.items()]
    for name, eligible, fixed in cases:
        presses, ms = press_until_settled(eligible, fixed)
        rects = presses[-1][0]
        m, dead = measure(rects)
        m.update(move=round(presses[0][1]), resized=len(presses[0][2]), presses=len(presses),
                 move2=round(presses[1][1]) if len(presses) > 1 else 0, ms=round(ms, 1))
        out[name] = m
        if render_dir:
            render(os.path.join(render_dir, f"{name}.png"), rects, fixed, dead,
                   f"{name}: fill {m['fill']}  dead {m['dead_area']}  holes {m['holes']}  jag {m['jaggedness']}")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--render")
    ap.add_argument("--json")
    args = ap.parse_args()
    if args.render:
        os.makedirs(args.render, exist_ok=True)
    res = run_all(args.render)
    cols = ["overlaps", "spacing", "sloppy_gutters", "detached", "fill", "dead_area", "dead_max", "holes", "jaggedness",
            "move", "resized", "presses", "move2", "ms"]
    print(f"{'fixture':20s} " + " ".join(f"{c[:9]:>9s}" for c in cols))
    for name, m in res.items():
        print(f"{name:20s} " + " ".join(f"{m[c]!s:>9s}" for c in cols))
    tot = {c: sum(m[c] for m in res.values()) for c in ("dead_area", "holes", "sloppy_gutters", "detached", "overlaps", "spacing")}
    print("totals:", tot)
    if args.json:
        with open(args.json, "w") as f:
            json.dump(res, f, indent=1)


if __name__ == "__main__":
    main()
