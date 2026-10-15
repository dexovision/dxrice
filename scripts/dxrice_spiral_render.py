#!/usr/bin/env python3
"""Draws real SUPER+G output from a dxrice_spiral_bench.py --json dump:
for each chosen fixture, the layout before, then each side's press-1
result. Windows are labelled; a line through the window centres in
prominence order (largest first) shows the spiral flow; gutters are
coloured by width (green 16-24 px, amber 25-60 px, red < 16 px). Per
panel: rotation / centrality / fill / spacing share / overlaps.

Needs Pillow. Rendering only -- it computes nothing the benchmark didn't.

    python3 scripts/dxrice_spiral_render.py DUMP.json OUT_DIR [--fixtures a,b,...] [--sheet NAME]
    python3 scripts/dxrice_spiral_render.py --autoplace NAME=SCRIPTS_DIR[,NAME=SCRIPTS_DIR] OUT_DIR [--sequences 0,1,..]

--autoplace opens windows one at a time through the real place_new_window
against dxrice_autoplace_report's in-memory Hyprland (one column per
scripts directory, e.g. a baseline checkout and this one) and draws the
finished sequence, then the same windows after one SUPER+G press.
"""
import argparse
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dxrice_spiral_bench as bench  # noqa: E402

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

PAL = ["#5b8def", "#9b7bea", "#4fb6a8", "#e39b5b", "#d76d9b", "#6fae5a", "#c9b458", "#5aa9c9",
       "#b07a5a", "#8a8fe0", "#e07a7a", "#7ac9a0"]
BG, CARD, INK, MUTED = "#15171c", "#1f232b", "#e8eaf0", "#9aa1ae"
GOOD, WARN, BAD = "#7fd39a", "#f0b45a", "#e5707a"


def _font(size, bold=False):
    for p in ("/usr/share/fonts/noto/NotoSans-%s.ttf" % ("Bold" if bold else "Regular"),
              "/usr/share/fonts/TTF/DejaVuSans%s.ttf" % ("-Bold" if bold else "")):
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def panel(img, box, title, rows, monitor, colors, metrics_line):
    d = ImageDraw.Draw(img)
    x0, y0, x1, y1 = box
    d.rounded_rectangle(box, 14, fill=CARD)
    d.text((x0 + 14, y0 + 10), title, font=_font(18, True), fill=INK)
    d.text((x0 + 14, y0 + 34), metrics_line, font=_font(13), fill=MUTED)
    ax0, ay0, ax1, ay1 = x0 + 14, y0 + 58, x1 - 14, y1 - 14
    mx0, my0, mx1, my1 = monitor
    lx0 = min([r[1] for r in rows] + [mx0])
    ly0 = min([r[2] for r in rows] + [my0])
    lx1 = max([r[1] + r[3] for r in rows] + [mx1])
    ly1 = max([r[2] + r[4] for r in rows] + [my1])
    sc = min((ax1 - ax0) / (lx1 - lx0), (ay1 - ay0) / (ly1 - ly0))
    ox = ax0 + ((ax1 - ax0) - (lx1 - lx0) * sc) / 2 - lx0 * sc
    oy = ay0 + ((ay1 - ay0) - (ly1 - ly0) * sc) / 2 - ly0 * sc

    def T(x, y):
        return ox + x * sc, oy + y * sc

    # monitor (dashed)
    a, b = T(mx0, my0), T(mx1, my1)
    for xx in range(int(a[0]), int(b[0]), 12):
        d.line([xx, a[1], min(xx + 6, b[0]), a[1]], fill="#5b6273", width=1)
        d.line([xx, b[1], min(xx + 6, b[0]), b[1]], fill="#5b6273", width=1)
    for yy in range(int(a[1]), int(b[1]), 12):
        d.line([a[0], yy, a[0], min(yy + 6, b[1])], fill="#5b6273", width=1)
        d.line([b[0], yy, b[0], min(yy + 6, b[1])], fill="#5b6273", width=1)
    for addr, x, y, w, h in rows:
        p, q = T(x, y), T(x + w, y + h)
        d.rectangle([p[0], p[1], q[0] - 1, q[1] - 1], fill=colors[addr], outline="#0d0f13")
        d.text((p[0] + 4, p[1] + 3), addr[:10], font=_font(12), fill="#111")
    # gutters between facing neighbours
    for i in range(len(rows)):
        for j in range(i + 1, len(rows)):
            A, B = rows[i], rows[j]
            ra = (A[1], A[2], A[1] + A[3], A[2] + A[4])
            rb = (B[1], B[2], B[1] + B[3], B[2] + B[4])
            oy_ = min(ra[3], rb[3]) - max(ra[1], rb[1])
            ox_ = min(ra[2], rb[2]) - max(ra[0], rb[0])
            if oy_ > 40 and ox_ <= 0:
                dist = max(rb[0] - ra[2], ra[0] - rb[2])
                xm = (ra[2] + rb[0]) / 2 if rb[0] >= ra[2] else (rb[2] + ra[0]) / 2
                seg = [T(xm, max(ra[1], rb[1])), T(xm, min(ra[3], rb[3]))]
            elif ox_ > 40 and oy_ <= 0:
                dist = max(rb[1] - ra[3], ra[1] - rb[3])
                ym = (ra[3] + rb[1]) / 2 if rb[1] >= ra[3] else (rb[3] + ra[1]) / 2
                seg = [T(max(ra[0], rb[0]), ym), T(min(ra[2], rb[2]), ym)]
            else:
                continue
            if 0 <= dist <= 60:
                col = GOOD if 16 <= dist <= 24 else (BAD if dist < 16 else WARN)
                d.line(seg, fill=col, width=3)
    # flow: centres in prominence order
    order = sorted((r for r in rows if r[0] != "fixed"), key=lambda r: (-(r[3] * r[4]), r[0]))
    pts = [T(x + w / 2, y + h / 2) for _a, x, y, w, h in order]
    if len(pts) > 1:
        d.line(pts, fill="#ffffff", width=2)
        for (px, py), (qx, qy) in zip(pts, pts[1:]):
            ang = math.atan2(qy - py, qx - px)
            mx, my = (px + qx) / 2, (py + qy) / 2
            for s in (-0.5, 0.5):
                d.line([mx, my, mx - 9 * math.cos(ang + s), my - 9 * math.sin(ang + s)], fill="#ffffff", width=2)
        d.ellipse([pts[0][0] - 5, pts[0][1] - 5, pts[0][0] + 5, pts[0][1] + 5], fill="#ffffff")


def metrics_line(rows):
    m = bench.shape_metrics(rows)
    g = m["gaps"]
    band = sum(16 <= x <= 24 for x in g) / len(g) if g else float("nan")
    rot = m.get("rotation")
    cen = m.get("centrality")
    return (f"rotation {rot:.2f}  " if rot is not None else "rotation n/a  ") + \
           (f"centrality {cen:+.2f}  " if cen is not None else "") + \
           f"fill {m['fill']:.2f}  16-24px {band:.0%}  overlaps {m['overlaps']}"


def autoplace_rows(scripts, seq_indices, seed=7):
    """[(sequence index, rows after opening, rows after one SUPER+G)] from
    a worker process importing `scripts` (its own module versions)."""
    import subprocess
    code = (
        "import sys, json, random, os, importlib\n"
        f"sys.path.insert(0, {scripts!r}); sys.path.insert(1, {os.path.dirname(os.path.abspath(__file__))!r})\n"
        "import dxrice_autoplace_report as R\n"
        "R.os.environ['XDG_RUNTIME_DIR'] = __import__('tempfile').mkdtemp()\n"
        "R.os.environ['XDG_CONFIG_HOME'] = __import__('tempfile').mkdtemp()\n"
        "apw = importlib.import_module('dxrice_auto_place_window'); arr = importlib.import_module('dxrice_auto_arrange')\n"
        "apw.get_monitor_bounds = lambda: R.MON; apw.time.sleep = lambda s: None\n"
        f"rng = random.Random({seed}); want = set({list(seq_indices)!r}); out = []\n"
        f"for k in range(max(want) + 1):\n"
        "    h = R.Hypr(apw)\n"
        "    apw.hyprctl_json, apw.batch_async = h.hyprctl_json, h.batch_async\n"
        "    apw.dispatch_async, apw.move_window_exact_async = h.dispatch_async, h.move_window_exact_async\n"
        "    for addr, w, hh, cls, pid in R.sequence(rng):\n"
        "        h.open(addr, w, hh, cls, pid); apw.place_new_window(addr, 1, R.GAP)\n"
        "    if k in want:\n"
        "        rows = h.rows(); el = [{'address': a, 'at': [x, y], 'size': [w, hh]} for a, x, y, w, hh in rows]\n"
        "        out.append([k, rows, [list(r) for r in arr.auto_arrange(el, [], R.MON, R.GAP)]])\n"
        "print(json.dumps(out))\n")
    res = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    return json.loads(res.stdout.strip().splitlines()[-1])


def autoplace_sheet(dirs, out, seqs, sheet):
    cols = []
    for spec in dirs:  # NAME=DIR
        name, d = spec.split("=", 1) if "=" in spec else (os.path.basename(spec.rstrip("/")), spec)
        cols.append((name, autoplace_rows(d, seqs)))
    pw, ph = 560, 430
    img = Image.new("RGB", (2 * len(cols) * pw + 20, len(seqs) * ph + 20), BG)
    for row in range(len(seqs)):
        for c, (label, data) in enumerate(cols):
            k, opened, superg = data[row]
            opened = [tuple(r) for r in opened]
            superg = [tuple(r) for r in superg]
            colors = {r[0]: PAL[i % len(PAL)] for i, r in enumerate(sorted(opened, key=lambda r: (-(r[3] * r[4]), r[0])))}
            for p, (title, rows) in enumerate(((f"{label}: opened one by one (#{k})", opened),
                                               (f"{label}: then SUPER+G", superg))):
                x = 10 + (2 * c + p) * pw
                panel(img, (x, 10 + row * ph, x + pw - 10, 10 + row * ph + ph - 10), title, rows,
                      (0, 0, 1920, 1080), colors, metrics_line(rows))
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, sheet + ".png")
    img.save(path)
    print(path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dump", nargs="?")
    ap.add_argument("out")
    ap.add_argument("--fixtures", default="")
    ap.add_argument("--sheet", default="spiral_renders")
    ap.add_argument("--autoplace")
    ap.add_argument("--sequences", default="0,1,2,3")
    a = ap.parse_args()
    if a.autoplace:
        return autoplace_sheet(a.autoplace.split(","), a.out, [int(x) for x in a.sequences.split(",")], a.sheet)
    data = json.load(open(a.dump))
    fx = data["fixtures"]
    sides = list(data["results"])
    want = [n for n in a.fixtures.split(",") if n] or [f["name"] for f in fx][:8]
    idx = {f["name"]: i for i, f in enumerate(fx)}
    os.makedirs(a.out, exist_ok=True)
    cols = 1 + len(sides)
    pw, ph = 620, 470
    sheet = Image.new("RGB", (cols * pw + 20, len(want) * ph + 20), BG)
    for row, name in enumerate(want):
        f = fx[idx[name]]
        before = [(w["address"], w["at"][0], w["at"][1], w["size"][0], w["size"][1]) for w in f["eligible"]]
        colors = {r[0]: PAL[i % len(PAL)] for i, r in enumerate(sorted(before, key=lambda r: (-(r[3] * r[4]), r[0])))}
        fixed = [(w["address"], w["at"][0], w["at"][1], w["size"][0], w["size"][1]) for w in f["fixed"]]
        for fr in fixed:
            colors[fr[0]] = "#3a3f4a"
        panels = [("before  " + name, before + fixed)]
        for s in sides:
            rows = [tuple(r) for r in data["results"][s][idx[name]]["presses"][0]["rows"]]
            panels.append((f"{s}: SUPER+G press 1", rows + fixed))
        for c, (title, rows) in enumerate(panels):
            box = (10 + c * pw, 10 + row * ph, 10 + c * pw + pw - 10, 10 + row * ph + ph - 10)
            panel(sheet, box, title, rows, tuple(f["monitor"]), colors,
                  metrics_line([r for r in rows if r[0] != "fixed"]))
    path = os.path.join(a.out, a.sheet + ".png")
    sheet.save(path)
    print(path)


if __name__ == "__main__":
    main()
