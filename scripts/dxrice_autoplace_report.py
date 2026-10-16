#!/usr/bin/env python3
"""New-window placement report: opens realistic sequences of windows one at
a time through the REAL place_new_window, against an in-memory Hyprland (no
compositor, nothing on screen), and measures what a user would see.

    python3 scripts/dxrice_autoplace_report.py [--scripts DIR] [--sequences N] [--render OUTDIR]

--scripts points at another checkout's scripts/ to measure that version the
same way (e.g. a worktree of an older commit); the default is this one.

Per sequence also: how far the first window sits from the screen centre
(the spiral's anchor), and the opening-order sweep -- round the first
window, the share of bearing steps from one opened window to the next that
turn the same way (random bearings give about 0.69).

Per open: did an EXISTING window move or change size; is the new window
at the composition spacing from something (dxrice_spiral's range -- up to
its widest_gap, measured with its dist, where the checkout has them;
exactly Hyprland's 5 px gap for a checkout from before the spiral
redesign), and clear of everything. Per finished sequence: shape
(bounding-box aspect -- the screen is 16:9), concave pockets
(dxrice_arrange_report.measure), whether a SUPER+G press keeps it as it
is (at most recentred), how far the
composition's centre sits from the screen's, and how much of the screen
is covered.
"""
import argparse
import importlib
import json
import math
import os
import random
import re
import statistics
import sys
import tempfile

MON = (0, 0, 1920, 1080)
GAP = 5
APPS = {"terminal": (860, 560), "browser": (1600, 1000), "files": (900, 620), "settings": (820, 560),
        "editor": (1300, 850), "chat": (1100, 750), "media": (640, 400), "pip": (550, 300)}


class Hypr:
    def __init__(self, apw):
        self.apw = apw
        self.clients = {}

    def open(self, addr, w, h, cls, pid):
        self.clients[addr] = {"address": addr, "at": [round((MON[2] - w) / 2), round((MON[3] - h) / 2)],
                              "size": [w, h], "floating": True, "fullscreen": 0, "workspace": {"id": 1},
                              "title": addr, "class": cls, "initialClass": cls, "pid": pid}

    def hyprctl_json(self, args, **kw):
        if args and args[0] == "clients":
            return [json.loads(json.dumps(c)) for c in self.clients.values()]
        return {"id": 1} if args and args[0] == "activeworkspace" else None

    def batch_async(self, exprs):
        for e in exprs:
            m = re.search(r'window\.(move|resize)\(\{ window = "address:([^"]+)", x = (-?\d+), y = (-?\d+)', e)
            kind, addr, a, b = m.group(1), m.group(2), int(m.group(3)), int(m.group(4))
            c = self.clients[addr]
            if kind == "move":
                c["at"] = [a, b]
            else:
                cx, cy = c["at"][0] + c["size"][0] / 2, c["at"][1] + c["size"][1] / 2
                c["size"] = [a, b]
                c["at"] = [round(cx - a / 2), round(cy - b / 2)]

    def dispatch_async(self, e):
        self.batch_async([e])

    def move_window_exact_async(self, x, y, addr):
        self.batch_async([self.apw.move_window_exact_lua(x, y, addr)])

    def rows(self):
        return [(a, *c["at"], *c["size"]) for a, c in self.clients.items()]


def sequence(rng):
    out = []
    for i in range(rng.randint(2, 8)):
        cls = rng.choice(list(APPS))
        w, h = (int(v * rng.uniform(0.85, 1.12)) for v in APPS[cls])
        out.append((f"0x{cls}{i}", w, h, cls, 1000 + i))
    return out


def _sep(a, b):
    return max(b[1] - (a[1] + a[3]), a[1] - (b[1] + b[3]), b[2] - (a[2] + a[4]), a[2] - (b[2] + b[4]))


def run(scripts, n, render_dir=None, seed=7):
    sys.path.insert(0, scripts)
    os.environ["XDG_RUNTIME_DIR"] = tempfile.mkdtemp()
    os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
    apw = importlib.import_module("dxrice_auto_place_window")
    arr = importlib.import_module("dxrice_auto_arrange")
    report = importlib.import_module("dxrice_arrange_report")
    if os.path.exists(os.path.join(scripts, "dxrice_spiral.py")):
        spiral = importlib.import_module("dxrice_spiral")
        lo, hi = spiral.SPACING_MIN_DEFAULT, spiral.SPACING_MAX_DEFAULT
        if hasattr(spiral, "widest_gap"):  # the expanding spiral: gaps widen outward
            hi = spiral.widest_gap((lo, hi))
    else:  # a checkout from before the spiral redesign: exact gaps_in
        lo = hi = GAP
        spiral = None
    sep = _sep
    if spiral is not None and hasattr(spiral, "dist"):  # corner to corner for diagonal pairs
        def sep(a, b):
            return spiral.dist((a[1], a[2], a[1] + a[3], a[2] + a[4]), (b[1], b[2], b[1] + b[3], b[2] + b[4]))
    rigidity_yardstick = spiral is not None and hasattr(spiral, "rigidity")
    apw.get_monitor_bounds = lambda *_: MON
    apw.time.sleep = lambda s: None
    rng = random.Random(seed)
    per = []
    opens = moved = not_flush = overlaps = hidden = 0
    for k in range(n):
        h = Hypr(apw)
        apw.hyprctl_json, apw.batch_async = h.hyprctl_json, h.batch_async
        apw.dispatch_async, apw.move_window_exact_async = h.dispatch_async, h.move_window_exact_async
        for addr, w, hh, cls, pid in sequence(rng):
            before = {a: (tuple(c["at"]), tuple(c["size"])) for a, c in h.clients.items()}
            h.open(addr, w, hh, cls, pid)
            apw.place_new_window(addr, 1, GAP)
            opens += 1
            moved += any((tuple(h.clients[a]["at"]), tuple(h.clients[a]["size"])) != v for a, v in before.items())
            rows = h.rows()
            new = next(r for r in rows if r[0] == addr)
            seps = [sep(new, r) for r in rows if r[0] != addr]
            vis = (max(0, min(new[1] + new[3], MON[2]) - max(new[1], MON[0]))
                   * max(0, min(new[2] + new[4], MON[3]) - max(new[2], MON[1])))
            hidden += vis < 0.5 * new[3] * new[4]
            if seps:
                overlaps += min(seps) < lo - 0.5
                not_flush += not (lo - 0.5 <= min(seps) <= hi + 0.5)
        rows = h.rows()
        m, dead = report.measure(rows)
        bw, bh = m["bbox"]
        bx0 = min(r[1] for r in rows); by0 = min(r[2] for r in rows)
        off = math.hypot(bx0 + bw / 2 - 960, by0 + bh / 2 - 540)
        cover = sum(max(0, min(x + w, 1920) - max(x, 0)) * max(0, min(y + hh, 1080) - max(y, 0))
                    for _a, x, y, w, hh in rows) / (1920 * 1080)
        el = [{"address": a, "at": [x, y], "size": [w, hh]} for a, x, y, w, hh in rows]
        kept = arr.auto_arrange(el, [], MON, GAP)
        deltas = {(x - e["at"][0], y - e["at"][1], w - e["size"][0], hh2 - e["size"][1])
                  for (_a, x, y, w, hh2), e in zip(kept, el)}
        accepted = len(deltas) == 1 and next(iter(deltas))[2:] == (0, 0)
        # the spiral as it grew: the first window's distance from the screen
        # centre, and -- round it, in opening order -- the share of bearing
        # steps turning the same way (needs 4+ windows: 2+ steps)
        fx, fy = rows[0][1] + rows[0][3] / 2, rows[0][2] + rows[0][4] / 2
        ang = [math.atan2(y + hh2 / 2 - fy, x + w / 2 - fx) for _a, x, y, w, hh2 in rows[1:]]
        steps = [((b - a + math.pi) % (2 * math.pi)) - math.pi for a, b in zip(ang, ang[1:])]
        pos = sum(st > 0 for st in steps)
        sweep = max(pos, len(steps) - pos) / len(steps) if len(steps) >= 2 else None
        per.append(dict(aspect=bw / bh, dead=m["dead_area"], coherent=accepted,
                        off_center=off, cover=min(cover, 1.0), n=len(rows),
                        first_off=math.hypot(fx - (MON[0] + MON[2]) / 2, fy - (MON[1] + MON[3]) / 2), sweep=sweep,
                        rigid=(spiral.rigidity([(x, y, x + w, y + hh2) for _a, x, y, w, hh2 in rows]) > 0)
                        if rigidity_yardstick else False))
        if render_dir and k < 8:
            os.makedirs(render_dir, exist_ok=True)
            report.render(os.path.join(render_dir, f"seq{k:02d}.png"), rows, [], dead,
                          f"seq {k}: {len(rows)} windows opened one by one")
    return dict(
        sequences=n, opens=opens,
        opens_that_moved_or_resized_an_existing_window=moved,
        new_window_overlapping=overlaps, new_window_not_at_the_spacing_from_anything=not_flush,
        new_window_opened_mostly_off_screen=hidden,
        aspect_median=round(statistics.median(p["aspect"] for p in per), 2),
        taller_than_wide=sum(p["aspect"] < 1 for p in per),
        dead_area_mean_px2=round(statistics.mean(p["dead"] for p in per)),
        super_g_accepts_as_is=sum(p["coherent"] for p in per),
        off_center_median_px=round(statistics.median(p["off_center"] for p in per)),
        screen_covered_median=round(statistics.median(p["cover"] for p in per), 3),
        first_window_off_centre_median_px=round(statistics.median(p["first_off"] for p in per)),
        opening_order_sweep_mean=round(statistics.mean(p["sweep"] for p in per if p["sweep"] is not None), 2),
        rigid_after_opening=sum(p["rigid"] for p in per))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scripts", default=os.path.dirname(os.path.abspath(__file__)))
    ap.add_argument("--sequences", type=int, default=200)
    ap.add_argument("--render")
    a = ap.parse_args()
    print(json.dumps(run(os.path.abspath(a.scripts), a.sequences, a.render), indent=1))


if __name__ == "__main__":
    main()
