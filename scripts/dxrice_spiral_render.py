#!/usr/bin/env python3
"""Draws real SUPER+G output from a dxrice_spiral_bench.py --json dump:
for each chosen fixture, the layout before, then each side's press-1
result. Windows are labelled; a line through the window centres in
prominence order (largest first) shows the spiral flow; gutters are
coloured by width (green 16-24 px, amber 25-60 px, red < 16 px). Per
panel: rotation / centrality / fill / spacing share / overlaps.

Needs Pillow. Rendering only -- it computes nothing the benchmark didn't.

    python3 scripts/dxrice_spiral_render.py DUMP.json OUT_DIR [--fixtures a,b,...] [--sheet NAME]
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dump")
    ap.add_argument("out")
    ap.add_argument("--fixtures", default="")
    ap.add_argument("--sheet", default="spiral_renders")
    a = ap.parse_args()
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
