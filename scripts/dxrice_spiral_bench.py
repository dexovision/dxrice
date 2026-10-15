#!/usr/bin/env python3
"""SUPER+G / auto-placement composition benchmark: the airy-spiral metrics.

Measures what the audit's SUPER+G section (D) asked for, on deterministic
realistic desktops, for one or two copies of the scripts directory -- so a
baseline and a candidate can be compared under identical conditions:

  rotation    share of radius-ordered steps turning the same way, about the
              unweighted mean centre, innermost window skipped, n >= 4
              (0.5-0.6 = no flow, 1.0 = a spiral). Random angles score
              `rotation_random` on the same window counts.
  centrality  Spearman rank correlation size -> nearness to the centre
              (+1 = the biggest windows are the central ones)
  spacing     every pair 0-60 px apart along a shared span > 40 px; share
              exactly 5 px, share 16-24 px, share 25-60 px ("slits")
  fill        occupied area / bounding-box area (1 - fill = negative space)
  aspect      bounding box, long side / short side
  overlaps    pairs overlapping or closer than 1 px
  move        mean window-centre displacement on press 1, after aligning
              the two layouts' centroids (pure recentring isn't movement)
  resized     windows resized on press 1; `reshrunk` = a window shrunk again
              on press 2 or 3
  settle      layouts still moving on press 2 / press 3
  ms          per-press runtime, p50 / p95 / max per window-count bucket
  rigid       layouts still a grid/block after press 1 (dxrice_spiral's
              cross junctions + full-span seams -- a diagnostic, not the
              objective)

The metric definitions are the audit's (scripts it ran on 2026-10-12),
unchanged, so baseline numbers are comparable with the ones it reported.

Each side runs in its own worker process (its own imports); layouts are
interleaved between the two so background load hits both alike.

    python3 scripts/dxrice_spiral_bench.py --side NAME=SCRIPTS_DIR [--side ...]
        [--per-bucket N] [--json FILE]
"""
import argparse
import json
import math
import os
import random
import statistics as st
import subprocess
import sys
import time

MONITOR = (0, 0, 1920, 1080)
GAP = 5  # Hyprland gaps_in, what main() passes

# Realistic app windows (the audit's generator): (w range, h range, weight).
TEMPL = {"browser": ((1500, 1900), (850, 1050), 3), "editor": ((1100, 1600), (750, 1000), 2),
         "discord": ((950, 1300), (650, 850), 2), "terminal": ((650, 1000), (400, 650), 4),
         "files": ((800, 1000), (550, 700), 2), "spotify": ((900, 1200), (600, 800), 1),
         "settings": ((700, 900), (500, 650), 1), "dialog": ((350, 600), (180, 400), 2),
         "pip": ((480, 640), (270, 360), 1)}
BUCKETS = [(3, 4), (5, 6), (7, 9), (10, 12), (13, 20)]

REPORTED_SIX = [("a", 909, 424, 826, 369), ("b", 909, 798, 826, 493), ("c", -161, 424, 1065, 867),
                ("d", -161, 1788, 854, 360), ("e", -161, 1296, 1030, 487), ("f", 874, 1296, 954, 390)]


def _w(a, x, y, w, h):
    return {"address": a, "at": [x, y], "size": [w, h]}


def realistic(rng, k):
    names = list(TEMPL)
    ws = []
    for i in range(k):
        t = rng.choices(names, [TEMPL[x][2] for x in names])[0]
        (w0, w1), (h0, h1), _ = TEMPL[t]
        w, h = rng.randint(w0, w1), rng.randint(h0, h1)
        ws.append(_w(f"{t}{i}", rng.randint(-300, 1920 - w // 2), rng.randint(-200, 1080 - h // 2), w, h))
    return ws


def packed(rng, k):
    """The old SUPER+G look: realistic sizes packed into rows 5 px apart."""
    ws, x, y, row_h = [], 0, 0, 0
    for w in realistic(rng, k):
        ww, hh = w["size"]
        if x and x + ww > 2600:
            x, y, row_h = 0, y + row_h + GAP, 0
        ws.append(_w(w["address"], x, y, ww, hh))
        x += ww + GAP
        row_h = max(row_h, hh)
    return ws


def fixtures(per_bucket):
    out = []
    rng = random.Random(20261014)
    for lo, hi in BUCKETS:
        count = per_bucket if hi <= 12 else max(10, per_bucket // 3)
        for i in range(count):
            k = rng.randint(lo, hi)
            kind = "packed" if i % 4 == 3 else "realistic"
            el = packed(rng, k) if kind == "packed" else realistic(rng, k)
            out.append({"name": f"{kind}-{k}-{i}", "bucket": f"{lo}-{hi}", "eligible": el, "fixed": [],
                        "monitor": MONITOR})
    # monitor shapes and obstacles (fewer, for the geometry, not the stats)
    for i in range(6):
        k = rng.randint(4, 9)
        out.append({"name": f"wide-{k}-{i}", "bucket": "wide", "eligible": realistic(rng, k), "fixed": [],
                    "monitor": (0, 0, 3440, 1440)})
        out.append({"name": f"tall-{k}-{i}", "bucket": "tall", "eligible": realistic(rng, k), "fixed": [],
                    "monitor": (0, 0, 1080, 1920)})
        out.append({"name": f"obstacle-{k}-{i}", "bucket": "obstacle", "eligible": realistic(rng, k),
                    "fixed": [_w("fixed", 1200, 100, 700, 500)], "monitor": MONITOR})
    for i in range(6):
        k = rng.randint(4, 9)
        out.append({"name": f"fullscreen-{k}-{i}", "bucket": "fullscreen", "eligible": realistic(rng, k),
                    "fixed": [_w("fixed", 0, 0, 1920, 1080)], "monitor": MONITOR})
        huge = [_w("huge", rng.randint(-200, 600), rng.randint(-100, 300), rng.randint(1600, 1900), rng.randint(950, 1100))]
        small = [_w(f"dialog{j}", rng.randint(-300, 1800), rng.randint(-200, 1000), rng.randint(300, 520),
                    rng.randint(180, 360)) for j in range(k)]
        out.append({"name": f"asymmetric-{k + 1}-{i}", "bucket": "asymmetric", "eligible": huge + small,
                    "fixed": [], "monitor": MONITOR})
    out.append({"name": "reported-six", "bucket": "5-6", "eligible": [_w(*r) for r in REPORTED_SIX],
                "fixed": [], "monitor": MONITOR})
    return out


# ---- metrics (the audit's definitions) ----

def gaps(rows):
    g = []
    for i in range(len(rows)):
        for j in range(i + 1, len(rows)):
            a, b = rows[i], rows[j]
            ax0, ay0, ax1, ay1 = a[1], a[2], a[1] + a[3], a[2] + a[4]
            bx0, by0, bx1, by1 = b[1], b[2], b[1] + b[3], b[2] + b[4]
            ox = min(ax1, bx1) - max(ax0, bx0)
            oy = min(ay1, by1) - max(ay0, by0)
            if oy > 40:
                d = max(bx0 - ax1, ax0 - bx1)
                if 0 <= d <= 60:
                    g.append(d)
            elif ox > 40:
                d = max(by0 - ay1, ay0 - by1)
                if 0 <= d <= 60:
                    g.append(d)
    return g


def spearman(x, y):
    rx = {v: i for i, v in enumerate(sorted(range(len(x)), key=lambda k: x[k]))}
    ry = {v: i for i, v in enumerate(sorted(range(len(y)), key=lambda k: y[k]))}
    n = len(x)
    d2 = sum((rx[i] - ry[i]) ** 2 for i in range(n))
    return 1 - 6 * d2 / (n * (n * n - 1)) if n > 2 else 0


def rotation_of(points):
    """points: [(radius, angle), ...] -> share of same-direction steps."""
    order = sorted(points)[1:]
    steps = [((b[1] - a[1] + math.pi) % (2 * math.pi)) - math.pi for a, b in zip(order, order[1:])]
    if not steps:
        return None
    pos = sum(s > 0 for s in steps)
    return max(pos, len(steps) - pos) / len(steps)


def shape_metrics(rows):
    cx = st.mean(x + w / 2 for _, x, y, w, h in rows)
    cy = st.mean(y + h / 2 for _, x, y, w, h in rows)
    pts = [(math.hypot(x + w / 2 - cx, y + h / 2 - cy), math.atan2(y + h / 2 - cy, x + w / 2 - cx), w * h)
           for _, x, y, w, h in rows]
    m = {}
    if len(pts) >= 4:
        m["centrality"] = spearman([-p[2] for p in pts], [p[0] for p in pts])
        m["rotation"] = rotation_of([(p[0], p[1]) for p in pts])
    xs0 = min(x for _, x, y, w, h in rows)
    ys0 = min(y for _, x, y, w, h in rows)
    xs1 = max(x + w for _, x, y, w, h in rows)
    ys1 = max(y + h for _, x, y, w, h in rows)
    m["fill"] = sum(w * h for *_, w, h in rows) / ((xs1 - xs0) * (ys1 - ys0))
    m["aspect"] = max(xs1 - xs0, ys1 - ys0) / min(xs1 - xs0, ys1 - ys0)
    m["gaps"] = gaps(rows)
    ov = 0
    for i in range(len(rows)):
        for j in range(i + 1, len(rows)):
            a, b = rows[i], rows[j]
            if a[1] < b[1] + b[3] + 1 and b[1] < a[1] + a[3] + 1 and a[2] < b[2] + b[4] + 1 and b[2] < a[2] + a[4] + 1:
                ov += 1
    m["overlaps"] = ov
    return m


def random_rotation(counts, seed=1):
    rng = random.Random(seed)
    vals = []
    for n in counts:
        for _ in range(20):
            vals.append(rotation_of([(rng.random(), rng.uniform(-math.pi, math.pi)) for _ in range(n)]))
    return st.median(v for v in vals if v is not None)


def movement(before, after):
    b = {w["address"]: (w["at"][0] + w["size"][0] / 2, w["at"][1] + w["size"][1] / 2) for w in before}
    a = {r[0]: (r[1] + r[3] / 2, r[2] + r[4] / 2) for r in after}
    bx, by = st.mean(p[0] for p in b.values()), st.mean(p[1] for p in b.values())
    ax, ay = st.mean(p[0] for p in a.values()), st.mean(p[1] for p in a.values())
    return st.mean(math.hypot((a[k][0] - ax) - (b[k][0] - bx), (a[k][1] - ay) - (b[k][1] - by)) for k in b)


# ---- worker: one scripts dir, the presses a user makes ----

def worker(scripts_dir):
    sys.path.insert(0, scripts_dir)
    import dxrice_auto_arrange as arr
    for line in sys.stdin:
        job = json.loads(line)
        layout, fixed, mon = job["eligible"], job["fixed"], tuple(job["monitor"])
        original = {w["address"]: tuple(w["size"]) for w in layout}
        locked = set()
        presses = []
        for _ in range(3):
            t = time.perf_counter()
            res = arr.auto_arrange(layout, fixed, mon, GAP, resize_locked=frozenset(locked))
            ms = (time.perf_counter() - t) * 1000
            res = [(a, round(x), round(y), round(w), round(h)) for a, x, y, w, h in res]
            sizes = {w["address"]: tuple(w["size"]) for w in layout}
            locked |= {a for a, _x, _y, w, h in res if (w, h) != sizes[a]}
            presses.append({"rows": res, "ms": ms})
            layout = [_w(*r) for r in res]
        print(json.dumps({"id": job["id"], "presses": presses, "original": {k: list(v) for k, v in original.items()}}),
              flush=True)


def run(sides, fx):
    procs = {}
    for name, d in sides:
        procs[name] = subprocess.Popen([sys.executable, os.path.abspath(__file__), "--worker", d],
                                       stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    out = {name: [] for name, _ in sides}
    for i, f in enumerate(fx):
        order = sides if i % 2 == 0 else list(reversed(sides))
        for name, _d in order:
            p = procs[name]
            p.stdin.write(json.dumps({"id": i, **f}) + "\n")
            p.stdin.flush()
            out[name].append(json.loads(p.stdout.readline()))
    for p in procs.values():
        p.stdin.close()
        p.wait()
    return out


def pct(v, q):
    v = sorted(v)
    return v[min(len(v) - 1, int(math.ceil(q * len(v))) - 1)] if v else float("nan")


def summarize(fx, results):
    by_bucket = {}
    for f, r in zip(fx, results):
        p1, p2, p3 = r["presses"]
        m = shape_metrics(p1["rows"])
        m["move"] = movement(f["eligible"], p1["rows"])
        m["rigid"] = _rigidity(p1["rows"]) > 0
        orig = r["original"]
        m["resized"] = sum(tuple(orig[a]) != (w, h) for a, _x, _y, w, h in p1["rows"])
        s1 = {a: (w, h) for a, _x, _y, w, h in p1["rows"]}
        m["reshrunk"] = any((w * h) < s1[a][0] * s1[a][1] for p in (p2, p3) for a, _x, _y, w, h in p["rows"])
        m["moved2"] = sorted(p2["rows"]) != sorted(p1["rows"])
        m["moved3"] = sorted(p3["rows"]) != sorted(p2["rows"])
        m["ms1"], m["ms2"] = p1["ms"], p2["ms"]
        m["name"] = f["name"]
        by_bucket.setdefault(f["bucket"], []).append(m)
    return by_bucket


def _rigidity(rows):
    """dxrice_spiral's diagnostic (any-size cross junctions + full-span
    seams), the same yardstick for every side."""
    import dxrice_spiral
    return dxrice_spiral.rigidity([(x, y, x + w, y + h) for _a, x, y, w, h in rows])


def report(name, by_bucket):
    lines = [f"== {name}"]
    allm = [m for ms in by_bucket.values() for m in ms]
    stat_m = [m for b, ms in by_bucket.items() if b not in ("13-20",) for m in ms]
    g = [x for m in stat_m for x in m["gaps"]]
    rot = [m["rotation"] for m in stat_m if m.get("rotation") is not None]
    cen = [m["centrality"] for m in stat_m if "centrality" in m]
    lines.append(f"  rotation median {st.median(rot):.2f} mean {st.mean(rot):.2f} | centrality median {st.median(cen):.2f}"
                 f" | fill median {st.median(m['fill'] for m in stat_m):.2f} | aspect median {st.median(m['aspect'] for m in stat_m):.2f}")
    if g:
        lines.append(f"  spacing pairs {len(g)}: exactly 5px {sum(x == 5 for x in g) / len(g):.0%}, 16-24px "
                     f"{sum(16 <= x <= 24 for x in g) / len(g):.0%}, 25-60px {sum(25 <= x <= 60 for x in g) / len(g):.0%}, "
                     f"<16px {sum(x < 16 for x in g) / len(g):.0%}")
    lines.append(f"  overlaps {sum(m['overlaps'] for m in allm)} | moved on press 2 {sum(m['moved2'] for m in allm)}"
                 f" / press 3 {sum(m['moved3'] for m in allm)} of {len(allm)} | resized {sum(m['resized'] for m in allm)}"
                 f" | re-shrunk {sum(m['reshrunk'] for m in allm)} | move median {st.median(m['move'] for m in allm):.0f}px"
                 f" | rigid after press 1 {sum(m['rigid'] for m in allm)}")
    for b, ms in by_bucket.items():
        r = [m["rotation"] for m in ms if m.get("rotation") is not None]
        g = [x for m in ms for x in m["gaps"]]
        lines.append(f"  {b:8s} n={len(ms):3d} press1 ms p50 {pct([m['ms1'] for m in ms], .5):6.0f} p95 {pct([m['ms1'] for m in ms], .95):6.0f}"
                     f" max {max(m['ms1'] for m in ms):6.0f} | press2 p95 {pct([m['ms2'] for m in ms], .95):5.0f}"
                     f" | rotation {st.mean(r) if r else float('nan'):.2f} | 16-24px {sum(16 <= x <= 24 for x in g) / max(1, len(g)):.0%}"
                     f" | fill {st.median(m['fill'] for m in ms):.2f}")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--worker")
    ap.add_argument("--side", action="append", default=[])
    ap.add_argument("--per-bucket", type=int, default=60)
    ap.add_argument("--json")
    a = ap.parse_args()
    if a.worker:
        return worker(a.worker)
    sides = [s.split("=", 1) for s in a.side] or [["current", os.path.dirname(os.path.abspath(__file__))]]
    fx = fixtures(a.per_bucket)
    res = run(sides, fx)
    counts = [len(f["eligible"]) for f in fx if f["bucket"] != "13-20" and len(f["eligible"]) >= 4]
    print(f"fixtures {len(fx)}; random-angle rotation on the same window counts: median {random_rotation(counts):.2f}")
    dump = {}
    for name, _d in sides:
        bb = summarize(fx, res[name])
        print(report(name, bb))
        dump[name] = {b: [{k: v for k, v in m.items()} for m in ms] for b, ms in bb.items()}
    if a.json:
        with open(a.json, "w") as f:
            json.dump({"fixtures": fx, "results": res, "metrics": dump}, f)


if __name__ == "__main__":
    main()
