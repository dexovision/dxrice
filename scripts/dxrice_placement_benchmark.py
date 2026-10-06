#!/usr/bin/env python3
"""Deterministic benchmark + property-invariant harness for the DXrice
floating-window placement system (Algorithm A: dxrice_auto_place_window.py,
Algorithm B / SUPER+G: dxrice_auto_arrange.py).

Calls the REAL production functions directly (no reimplemented logic).
Fixed random seed -> fully reproducible across runs. No live Hyprland
required; see dxrice_test_placement.py's live-listener/subprocess tests
for the real event-path coverage this harness deliberately doesn't
duplicate.

Usage: python3 dxrice_placement_benchmark.py [--n N] [--out DIR]
  --n     number of generated layouts (default 300)
  --out   directory to write worst-case/summary artifacts (default: cwd)
"""
import argparse
import json
import math
import random
import sys
import time

import dxrice_auto_arrange as arr
import dxrice_auto_place_window as apw

GAP = 5
MONITOR = (0, 0, 1920, 1080)
CENTER = ((MONITOR[0] + MONITOR[2]) / 2, (MONITOR[1] + MONITOR[3]) / 2)

SIZE_BUCKETS = [(1, 3), (4, 6), (7, 10), (11, 15), (16, 20), (21, 30)]

SHAPE_KINDS = [
    "mixed", "identical", "extreme_aspect", "tiny_and_huge", "mostly_large_tiny_dialogs",
    "coherent_grid", "vertical_stack", "horizontal_stack", "l_shape", "t_shape",
    "staircase", "asymmetric_cluster", "scattered", "partially_offscreen",
    "negative_coords", "large_offscreen", "near_center", "far_from_center",
]


def _mk(addr, x, y, w, h):
    return {"address": addr, "at": [x, y], "size": [w, h]}


def gen_layout(rng, n, kind):
    """Returns (eligible, fixed) -- [{"address","at","size"}, ...] each."""
    fixed = []
    if kind == "identical":
        w, h = rng.randint(250, 700), rng.randint(180, 550)
        eligible = [_mk(f"W{i}", rng.randint(-400, 1900), rng.randint(-400, 1000), w, h) for i in range(n)]
    elif kind == "extreme_aspect":
        eligible = []
        for i in range(n):
            if rng.random() < 0.5:
                w, h = rng.randint(900, 1800), rng.randint(120, 220)
            else:
                w, h = rng.randint(120, 220), rng.randint(700, 1400)
            eligible.append(_mk(f"W{i}", rng.randint(-300, 1800), rng.randint(-300, 900), w, h))
    elif kind == "tiny_and_huge":
        eligible = []
        for i in range(n):
            if i == 0:
                w, h = rng.randint(1200, 1800), rng.randint(800, 1050)
            else:
                w, h = rng.randint(150, 300), rng.randint(120, 220)
            eligible.append(_mk(f"W{i}", rng.randint(0, 1600), rng.randint(0, 900), w, h))
    elif kind == "mostly_large_tiny_dialogs":
        eligible = []
        for i in range(n):
            if rng.random() < 0.8:
                w, h = rng.randint(700, 1400), rng.randint(500, 900)
            else:
                w, h = rng.randint(150, 280), rng.randint(120, 200)
            eligible.append(_mk(f"W{i}", rng.randint(0, 1400), rng.randint(0, 700), w, h))
    elif kind == "coherent_grid":
        cols = max(1, round(math.sqrt(n)))
        w, h = rng.randint(250, 400), rng.randint(180, 300)
        total_w = cols * w + (cols - 1) * GAP
        rows = math.ceil(n / cols)
        total_h = rows * h + (rows - 1) * GAP
        left, top = CENTER[0] - total_w / 2, CENTER[1] - total_h / 2
        eligible = []
        for i in range(n):
            r, c = divmod(i, cols)
            eligible.append(_mk(f"W{i}", left + c * (w + GAP), top + r * (h + GAP), w, h))
    elif kind == "vertical_stack":
        w, h = rng.randint(300, 500), rng.randint(200, 350)
        x = rng.randint(200, 1400)
        y0 = rng.randint(-200, 200)
        eligible = [_mk(f"W{i}", x, y0 + i * (h + GAP), w, h) for i in range(n)]
    elif kind == "horizontal_stack":
        w, h = rng.randint(200, 350), rng.randint(300, 500)
        y = rng.randint(100, 700)
        x0 = rng.randint(-200, 200)
        eligible = [_mk(f"W{i}", x0 + i * (w + GAP), y, w, h) for i in range(n)]
    elif kind == "l_shape":
        w, h = rng.randint(300, 450), rng.randint(220, 350)
        arm = max(2, n // 2)
        eligible = []
        for i in range(n):
            if i < arm:
                eligible.append(_mk(f"W{i}", 660, 240 + i * (h + GAP), w, h))
            else:
                j = i - arm
                eligible.append(_mk(f"W{i}", 660 + (j + 1) * (w + GAP), 240 + (arm - 1) * (h + GAP), w, h))
    elif kind == "t_shape":
        w, h = rng.randint(250, 350), rng.randint(200, 300)
        eligible = [_mk("W0", 660, 240, w * min(n, 3), h)]
        for i in range(1, n):
            eligible.append(_mk(f"W{i}", 660 + (i - 1) * (w + GAP), 240 + h + GAP, w, h))
    elif kind == "staircase":
        w, h = rng.randint(280, 380), rng.randint(200, 280)
        eligible = []
        x, y = 400, 150
        for i in range(n):
            eligible.append(_mk(f"W{i}", x, y, w, h))
            x += w // 2 + GAP
            y += h + GAP
    elif kind == "asymmetric_cluster":
        eligible = [_mk("BIG", 660, 300, 500, 400)]
        x, y = 1165, 300
        for i in range(1, n):
            w, h = rng.randint(200, 300), rng.randint(150, 220)
            eligible.append(_mk(f"W{i}", x, y, w, h))
            y += h + GAP
    elif kind == "scattered":
        eligible = []
        for i in range(n):
            w, h = rng.randint(200, 500), rng.randint(150, 400)
            corner = rng.choice([(0, 0), (1900 - w, 0), (0, 1070 - h), (1900 - w, 1070 - h)])
            jitter = (rng.randint(-100, 100), rng.randint(-100, 100))
            eligible.append(_mk(f"W{i}", corner[0] + jitter[0], corner[1] + jitter[1], w, h))
    elif kind == "partially_offscreen":
        eligible = []
        for i in range(n):
            w, h = rng.randint(300, 700), rng.randint(200, 500)
            x = rng.choice([rng.randint(-500, -100), rng.randint(1700, 2200)])
            y = rng.randint(-200, 900)
            eligible.append(_mk(f"W{i}", x, y, w, h))
    elif kind == "negative_coords":
        eligible = []
        for i in range(n):
            w, h = rng.randint(300, 600), rng.randint(200, 450)
            x = rng.randint(-2000, -400)
            y = rng.randint(-2000, -400)
            eligible.append(_mk(f"W{i}", x, y, w, h))
    elif kind == "large_offscreen":
        eligible = []
        for i in range(n):
            w, h = rng.randint(1000, 1800), rng.randint(700, 1050)
            x = rng.randint(-3000, -1500)
            y = rng.randint(-2000, -1000)
            eligible.append(_mk(f"W{i}", x, y, w, h))
    elif kind == "near_center":
        eligible = []
        for i in range(n):
            w, h = rng.randint(250, 600), rng.randint(180, 450)
            x = CENTER[0] + rng.randint(-150, 150) - w / 2
            y = CENTER[1] + rng.randint(-150, 150) - h / 2
            eligible.append(_mk(f"W{i}", x, y, w, h))
    elif kind == "far_from_center":
        eligible = []
        for i in range(n):
            w, h = rng.randint(250, 600), rng.randint(180, 450)
            x = rng.choice([-3000, 4500]) + rng.randint(-300, 300)
            y = rng.choice([-2500, 3500]) + rng.randint(-300, 300)
            eligible.append(_mk(f"W{i}", x, y, w, h))
    else:  # "mixed"
        eligible = []
        for i in range(n):
            w = rng.randint(200, 1500)
            h = rng.randint(150, 1000)
            x = rng.randint(-500, 1900)
            y = rng.randint(-500, 1000)
            eligible.append(_mk(f"W{i}", x, y, w, h))

    if n >= 6 and rng.random() < 0.15:
        fw, fh = rng.choice([(1920, 1080), (960, 1080)])
        fixed = [_mk("FIXED0", 0 if fw == 1920 else rng.choice([0, 960]), 0, fw, fh)]
    return eligible, fixed


def resolve_overlaps(rects):
    """rects: [(addr,x,y,w,h)]. Nudges apart any that overlap so a generated
    layout is always a legal STARTING point (the algorithm's own job is to
    fix bad ARRANGEMENT, not malformed input)."""
    by_addr = {a: [x, y, w, h] for a, x, y, w, h in rects}
    addrs = list(by_addr.keys())
    for _ in range(len(addrs) * 2):
        changed = False
        for i in range(len(addrs)):
            for j in range(i + 1, len(addrs)):
                a, b = by_addr[addrs[i]], by_addr[addrs[j]]
                ra = (a[0], a[1], a[0] + a[2], a[1] + a[3])
                rb = (b[0], b[1], b[0] + b[2], b[1] + b[3])
                ox = min(ra[2], rb[2]) - max(ra[0], rb[0])
                oy = min(ra[3], rb[3]) - max(ra[1], rb[1])
                if ox > 0 and oy > 0:
                    if ox < oy:
                        b[0] += ox + GAP
                    else:
                        b[1] += oy + GAP
                    changed = True
        if not changed:
            break
    return [(a, *by_addr[a]) for a in addrs]


def metrics(rects, ref_center=CENTER):
    """rects: [(addr,x,y,w,h), ...]. Returns a dict of measured properties."""
    if not rects:
        return dict(overlaps=0, min_gap=None, bbox_area=0, com_err=0.0, aniso=0.0)
    boxes = [(a, x, y, x + w, y + h) for a, x, y, w, h in rects]
    overlap_count = 0
    min_gap = None
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            _, x0, y0, x1, y1 = boxes[i]
            _, X0, Y0, X1, Y1 = boxes[j]
            ox = min(x1, X1) - max(x0, X0)
            oy = min(y1, Y1) - max(y0, Y0)
            if ox > 0 and oy > 0:
                overlap_count += 1
            else:
                xg = max(x0 - X1, X0 - x1, 0)
                yg = max(y0 - Y1, Y0 - y1, 0)
                gap_here = max(xg, yg) if (xg == 0 or yg == 0) else math.hypot(xg, yg)
                if min_gap is None or gap_here < min_gap:
                    min_gap = gap_here
    xs0 = [b[1] for b in boxes]; ys0 = [b[2] for b in boxes]
    xs1 = [b[3] for b in boxes]; ys1 = [b[4] for b in boxes]
    bbox_area = (max(xs1) - min(xs0)) * (max(ys1) - min(ys0))
    ref_area = sorted((x1 - x0) * (y1 - y0) for _, x0, y0, x1, y1 in boxes)[len(boxes) // 2]
    wpts = [((x0 + x1) / 2, (y0 + y1) / 2, x1 - x0, y1 - y0, apw.window_mass(x1 - x0, y1 - y0, ref_area))
            for _, x0, y0, x1, y1 in boxes]
    com = apw.mass_center(wpts)
    com_err = math.hypot(com[0] - ref_center[0], com[1] - ref_center[1]) if com else 0.0
    Cxx, Cyy, Cxy = apw.covariance_matrix(wpts, com) if com else (0, 0, 0)
    l1, l2, _ = apw.principal_axes(Cxx, Cyy, Cxy)
    aniso = apw.anisotropy(l1, l2)
    return dict(overlaps=overlap_count, min_gap=min_gap, bbox_area=bbox_area, com_err=com_err, aniso=aniso)


def run_super_g_chain(eligible, fixed, iterations=6):
    """Feeds auto_arrange's own output back into itself `iterations` times.
    Returns (history, final_rects) -- history is a per-iteration list of
    (movement, resize_count, resize_total_px, metrics); final_rects is the
    [(addr,x,y,w,h), ...] the chain settled on after the last iteration."""
    layout = eligible
    history = []
    final_rects = []
    # The same cross-press resize memory main() keeps on disk, carried here
    # in a dict -- without it this would measure presses no real SUPER+G
    # performs (each one forgetting what the previous one resized).
    resize_state = {}
    for it in range(iterations):
        t0 = time.perf_counter()
        result = arr.auto_arrange(layout, fixed, MONITOR, GAP,
                                  resize_locked=arr._locked_addresses(resize_state, layout))
        t1 = time.perf_counter()
        before = {w["address"]: (w["at"][0], w["at"][1], w["size"][0], w["size"][1]) for w in layout}
        resize_state = arr._next_resize_state(
            resize_state, set(before), {a: (w, h) for a, x, y, w, h in result},
            [a for a, x, y, w, h in result if (w, h) != before[a][2:]])
        movement = 0.0
        resize_count = 0
        resize_total = 0.0
        for a, x, y, w, h in result:
            ox, oy, ow, oh = before[a]
            movement += math.hypot(x - ox, y - oy)
            if (w, h) != (ow, oh):
                resize_count += 1
                resize_total += abs(w - ow) + abs(h - oh)
        final_rects = list(result)
        m = metrics(final_rects)
        history.append(dict(iter=it, movement=movement, resize_count=resize_count,
                             resize_total=resize_total, runtime_ms=1000 * (t1 - t0), **m))
        layout = [_mk(a, x, y, w, h) for a, x, y, w, h in result]
    return history, final_rects


def check_invariants(name, eligible, fixed, history, final_rects):
    """Returns a list of violation strings (empty if none)."""
    problems = []
    m0 = metrics(final_rects)
    if m0["overlaps"] > 0:
        problems.append(f"{m0['overlaps']} unintended overlap(s) in final layout")
    if m0["min_gap"] is not None and m0["min_gap"] < GAP - 1.0:
        problems.append(f"minimum gap {m0['min_gap']:.1f}px violates configured gap {GAP}")
    for w in eligible:
        addr = w["address"]
        ow, oh = w["size"]
        for r in final_rects:
            if r[0] == addr and (r[3] < 100 or r[4] < 60):
                problems.append(f"{addr} shrunk below floor: {r[3]}x{r[4]}")
    if len(history) >= 3:
        moves = [h["movement"] for h in history[1:]]
        if moves[-1] > 1.0 and moves[-1] > moves[0] * 1.05 and moves[0] > 1.0:
            problems.append(f"movement increased across iterations: {[round(x,1) for x in moves]}")
        resizes = [h["resize_total"] for h in history]
        if len(resizes) >= 3 and resizes[-1] > 0 and resizes[-1] >= resizes[1] and resizes[1] > 0:
            problems.append(f"resize did not decay across iterations: {[round(x,1) for x in resizes]}")
        if history[-1]["movement"] > 1.0 or history[-1]["resize_count"] > 0:
            problems.append(f"did not reach a fixed point by iteration {len(history)}: "
                             f"movement={history[-1]['movement']:.1f} resize_count={history[-1]['resize_count']}")
    return problems


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=300)
    ap.add_argument("--seed", type=int, default=20260920)
    ap.add_argument("--out", default=".")
    args = ap.parse_args()

    rng = random.Random(args.seed)
    results = []
    worst_cases = []
    total_runtime = 0.0

    for i in range(args.n):
        lo, hi = rng.choice(SIZE_BUCKETS)
        n = rng.randint(lo, hi)
        kind = rng.choice(SHAPE_KINDS)
        eligible, fixed = gen_layout(rng, n, kind)
        eligible = resolve_overlaps([(w["address"], *w["at"], *w["size"]) for w in eligible])
        eligible = [_mk(a, x, y, w, h) for a, x, y, w, h in eligible]

        history, final_rects = run_super_g_chain(eligible, fixed, iterations=6)
        problems = check_invariants(f"{kind}#{i}(n={n})", eligible, fixed, history, final_rects)
        rec = dict(idx=i, kind=kind, n=n, has_fixed=bool(fixed),
                   first_movement=history[0]["movement"], first_resize_count=history[0]["resize_count"],
                   final_movement=history[-1]["movement"], final_resize_count=history[-1]["resize_count"],
                   runtime_ms=sum(h["runtime_ms"] for h in history), problems=problems)
        results.append(rec)
        total_runtime += rec["runtime_ms"]
        if problems:
            worst_cases.append(dict(kind=kind, n=n, eligible=[(w["address"], w["at"], w["size"]) for w in eligible],
                                     fixed=[(w["address"], w["at"], w["size"]) for w in fixed],
                                     problems=problems, history=history))

    by_kind = {}
    for r in results:
        by_kind.setdefault(r["kind"], []).append(r)

    print(f"Generated {args.n} layouts (seed={args.seed}), total runtime {total_runtime:.0f}ms, "
          f"{total_runtime/args.n:.2f}ms/layout avg")
    print(f"Layouts with invariant violations: {len(worst_cases)}/{args.n}")
    print()
    print(f"{'kind':28s} {'count':>6s} {'avg_1st_move':>13s} {'avg_final_move':>14s} {'violations':>11s}")
    for kind, rs in sorted(by_kind.items()):
        n_viol = sum(1 for r in rs if r["problems"])
        avg1 = sum(r["first_movement"] for r in rs) / len(rs)
        avgf = sum(r["final_movement"] for r in rs) / len(rs)
        print(f"{kind:28s} {len(rs):6d} {avg1:13.1f} {avgf:14.2f} {n_viol:11d}")

    out_path = f"{args.out}/benchmark_worst_cases.json"
    with open(out_path, "w") as f:
        json.dump(worst_cases, f, indent=2)
    print(f"\n{len(worst_cases)} worst-case layout(s) saved to {out_path}")
    return 0 if not worst_cases else 1


if __name__ == "__main__":
    sys.exit(main())
