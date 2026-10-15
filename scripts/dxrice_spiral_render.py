#!/usr/bin/env python3
"""Draws real SUPER+G output from a dxrice_spiral_bench.py --json dump:
for each chosen fixture, the layout before, then each side's press-1
result. Windows are labelled; a line through the window centres in
creation order (the order the spiral is built in) shows the arm; gutters
between facing neighbours are thin lines coloured against the composer's
spacing band (dxrice_spiral.SPACING_MIN/MAX_DEFAULT, 32-56 px): green
inside it, amber wider (up to twice the maximum), red narrower. Per panel:
each window's gap to its nearest neighbour (min / median / share inside
the band) and overlaps.

Needs Pillow. Rendering only -- it computes nothing the benchmark didn't.

    python3 scripts/dxrice_spiral_render.py DUMP.json OUT_DIR [--fixtures a,b,...] [--sheet NAME]
    python3 scripts/dxrice_spiral_render.py --autoplace NAME=SCRIPTS_DIR[,NAME=SCRIPTS_DIR] OUT_DIR [--sequences 0,1,..]

--growth SCRIPTS_DIR draws a frame per window opened (--sizes WxH,...), the
flow line in opening order -- the spiral as auto-placement grows it.

--geometry SCRIPTS_DIR [--reference PNG] draws the acceptance sheets of
the Galaxy Spiral geometry: growth at 1-12 windows (reference proportions
and mixed sizes), closing windows, an oversized composition, fixed and
fullscreen windows -- all through the real place_new_window / SUPER+G --
and, given the reference image, the two side by side.

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
import dxrice_spiral  # noqa: E402

BAND = (dxrice_spiral.SPACING_MIN_DEFAULT, dxrice_spiral.SPACING_MAX_DEFAULT)
USABLE = (0, 52, 1920, 1012)  # a 1920x1080 screen minus a 52px bar and a 68px dock

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


def panel(img, box, title, rows, monitor, colors, metrics_line, order=None):
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
        d.text((p[0] + 4, p[1] + 3), addr[:10], font=_font(12), fill="#111" if addr not in FIXED_NAMES else INK)
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
            if 0 <= dist <= 2 * BAND[1] and A[0] not in FIXED_NAMES and B[0] not in FIXED_NAMES:
                col = GOOD if BAND[0] <= dist <= BAND[1] else (BAD if dist < BAND[0] else WARN)
                d.line(seg, fill=col, width=2)
    # the arm: centres in creation order
    if order is None:  # the rows' own order (SUPER+G returns creation order)
        order = [r for r in rows if r[0] not in FIXED_NAMES]
    else:              # the given order (opening order, for growth frames)
        by = {r[0]: r for r in rows}
        order = [by[a] for a in order if a in by]
    pts = [T(x + w / 2, y + h / 2) for _a, x, y, w, h in order]
    if len(pts) > 1:
        d.line(pts, fill="#ffffff", width=2)
        for (px, py), (qx, qy) in zip(pts, pts[1:]):
            ang = math.atan2(qy - py, qx - px)
            mx, my = (px + qx) / 2, (py + qy) / 2
            for s in (-0.5, 0.5):
                d.line([mx, my, mx - 9 * math.cos(ang + s), my - 9 * math.sin(ang + s)], fill="#ffffff", width=2)
        d.ellipse([pts[0][0] - 5, pts[0][1] - 5, pts[0][0] + 5, pts[0][1] + 5], fill="#ffffff")


FIXED_NAMES = {"fixed", "pinned", "fullscreen"}


def _sep(a, b):
    return max(b[1] - (a[1] + a[3]), a[1] - (b[1] + b[3]), b[2] - (a[2] + a[4]), a[2] - (b[2] + b[4]))


def metrics_line(rows):
    """Each window's gap to its nearest neighbour (fixed windows count as
    neighbours): min / median / share inside the band; overlaps."""
    near = [min(_sep(r, o) for o in rows if o is not r) for r in rows if r[0] not in FIXED_NAMES] if len(rows) > 1 else []
    over = sum(_sep(rows[i], rows[j]) < 0 for i in range(len(rows)) for j in range(i + 1, len(rows)))
    if not near:
        return f"{len(rows)} window  overlaps {over}"
    inband = sum(BAND[0] <= g <= BAND[1] for g in near) / len(near)
    return (f"nearest gap min {min(near):.0f} median {sorted(near)[len(near) // 2]:.0f}px  "
            f"in {BAND[0]}-{BAND[1]}px {inband:.0%}  overlaps {over}")


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


def growth_rows(scripts, sizes):
    """Rows after each window opened (real place_new_window, in-memory
    Hyprland, usable area of a 1920x1080 screen with a 52px bar and a 68px
    dock), in a worker importing `scripts`."""
    import subprocess
    code = (
        "import sys, json, os, importlib, tempfile\n"
        f"sys.path.insert(0, {scripts!r}); sys.path.insert(1, {os.path.dirname(os.path.abspath(__file__))!r})\n"
        "import dxrice_autoplace_report as R\n"
        "os.environ['XDG_RUNTIME_DIR'] = tempfile.mkdtemp(); os.environ['XDG_CONFIG_HOME'] = tempfile.mkdtemp()\n"
        "apw = importlib.import_module('dxrice_auto_place_window')\n"
        "apw.get_monitor_bounds = lambda: (0, 52, 1920, 1012); apw.time.sleep = lambda s: None\n"
        "h = R.Hypr(apw); apw.hyprctl_json, apw.batch_async = h.hyprctl_json, h.batch_async\n"
        "apw.dispatch_async, apw.move_window_exact_async = h.dispatch_async, h.move_window_exact_async\n"
        f"frames = []\nfor i, (w, hh) in enumerate({list(map(list, sizes))!r}):\n"
        "    addr = f'w{i + 1}'\n"
        "    h.open(addr, w, hh, 'app' + addr, 1000 + i); apw.place_new_window(addr, 1, R.GAP)\n"
        "    frames.append(h.rows())\n"
        "print(json.dumps(frames))\n")
    res = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    return json.loads(res.stdout.strip().splitlines()[-1])


def scenario_rows(scripts, ops):
    """Rows after each op, run through the real place_new_window and
    auto_arrange (in-memory Hyprland, usable area USABLE) in a worker
    importing `scripts`. ops: ["open", addr, w, h] | ["close", addr] |
    ["fixed", addr, x, y, w, h, "pinned"|"fullscreen"] | ["press"]."""
    import subprocess
    code = (
        "import sys, json, os, importlib, tempfile\n"
        f"sys.path.insert(0, {scripts!r}); sys.path.insert(1, {os.path.dirname(os.path.abspath(__file__))!r})\n"
        "import dxrice_autoplace_report as R\n"
        "os.environ['XDG_RUNTIME_DIR'] = tempfile.mkdtemp(); os.environ['XDG_CONFIG_HOME'] = tempfile.mkdtemp()\n"
        "apw = importlib.import_module('dxrice_auto_place_window'); arr = importlib.import_module('dxrice_auto_arrange')\n"
        f"U = {USABLE!r}\n"
        "apw.get_monitor_bounds = lambda: U; apw.time.sleep = lambda s: None\n"
        "h = R.Hypr(apw); apw.hyprctl_json, apw.batch_async = h.hyprctl_json, h.batch_async\n"
        "apw.dispatch_async, apw.move_window_exact_async = h.dispatch_async, h.move_window_exact_async\n"
        "frames = []\n"
        f"for op in {ops!r}:\n"
        "    if op[0] == 'open':\n"
        "        h.open(op[1], op[2], op[3], 'app' + op[1], 1000 + len(h.clients)); apw.place_new_window(op[1], 1, R.GAP)\n"
        "    elif op[0] == 'close':\n"
        "        del h.clients[op[1]]\n"
        "    elif op[0] == 'fixed':\n"
        "        h.open(op[1], op[4], op[5], op[1], 900); c = h.clients[op[1]]; c['at'] = [op[2], op[3]]\n"
        "        c.update(fullscreen=2) if op[6] == 'fullscreen' else c.update(pinned=True)\n"
        "    elif op[0] == 'press':\n"
        "        cl = list(h.clients.values()); fx = [c for c in cl if c.get('fullscreen') or c.get('pinned')]\n"
        "        el = [c for c in cl if c not in fx]\n"
        "        for a, x, y, w, hh in arr.auto_arrange(el, fx, U, R.GAP):\n"
        "            h.clients[a]['at'] = [x, y]\n"
        "    frames.append(h.rows())\n"
        "print(json.dumps(frames))\n")
    res = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    return [[tuple(r) for r in f] for f in json.loads(res.stdout.strip().splitlines()[-1])]


def _sheet(panels, out, sheet, cols, pw=560, ph=430, colors=None, header=None):
    """panels: [(title, rows, order)] laid out `cols` per row."""
    rows_n = (len(panels) + cols - 1) // cols
    top = 50 if header else 0
    img = Image.new("RGB", (cols * pw + 20, rows_n * ph + 20 + top), BG)
    if header:
        ImageDraw.Draw(img).text((16, 14), header, font=_font(22, True), fill=INK)
    for k, (title, rows, order) in enumerate(panels):
        cmap = dict(colors or {})
        for i, r in enumerate(rows):
            cmap.setdefault(r[0], "#3a3f4a" if r[0] in FIXED_NAMES else PAL[i % len(PAL)])
        x, y = 10 + (k % cols) * pw, 10 + top + (k // cols) * ph
        panel(img, (x, y, x + pw - 10, y + ph - 10), title, rows, USABLE, cmap, metrics_line(rows), order=order)
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, sheet + ".png")
    img.save(path)
    print(path)
    return path


# Reference proportions: the reference image's anchor (~305x180) and ring
# windows (~210x100) on a 1536-wide picture, scaled to a 1920-wide screen.
REF_SIZES = [(381, 225)] + [(262, 125)] * 11
MIXED = [(1100, 700), (860, 560), (640, 400), (900, 620), (550, 300), (1000, 650), (820, 560),
         (480, 320), (700, 460), (760, 480), (600, 380), (920, 600)]
COUNTS = (1, 2, 3, 4, 6, 8, 12)


def geometry_sheets(scripts, out, reference=None):
    names = [f"w{i + 1}" for i in range(12)]
    colors = {a: PAL[i % len(PAL)] for i, a in enumerate(names)}
    paths = []
    for label, sizes, sheet in (("reference proportions (381x225 anchor, 262x125 windows)", REF_SIZES, "growth_reference"),
                                ("mixed application sizes", MIXED, "growth_mixed")):
        frames = scenario_rows(scripts, [["open", a, w, h] for a, (w, h) in zip(names, sizes)] + [["press"]])
        panels = [(f"{n} window{'s' if n > 1 else ''}", frames[n - 1], names[:n]) for n in COUNTS]
        panels.append(("12 windows, then SUPER+G", frames[-1], names))
        paths.append(_sheet(panels, out, sheet, 4, colors=colors, header=f"Galaxy Spiral growth -- {label}"))
    # closing windows: middle, tip, anchor; then SUPER+G
    eight = [["open", a, w, h] for a, (w, h) in zip(names, MIXED[:8])]
    panels = []
    for title, closed in (("w4 (middle) closed", "w4"), ("w8 (tip) closed", "w8"), ("w1 (anchor) closed", "w1")):
        f = scenario_rows(scripts, eight + [["close", closed], ["open", "n9", 700, 460], ["press"]])
        order = [a for a in names[:8] if a != closed] + ["n9"]
        panels += [("8 windows", f[7], names[:8]), (f"{title}, n9 opened", f[9], order),
                   ("then SUPER+G", f[10], order)]
    paths.append(_sheet(panels, out, "closing", 3, colors=dict(colors, n9="#ffffff"),
                        header="Closing windows: nothing moves; the arm carries on; SUPER+G rebuilds from creation order"))
    # oversized, fixed and fullscreen
    six = [["open", f"t{i + 1}", 826, 493] for i in range(6)]
    f_big = scenario_rows(scripts, six + [["press"]])
    f_pin = scenario_rows(scripts, [["fixed", "pinned", 1400, 90, 460, 330, "pinned"]]
                          + [["open", a, w, h] for a, (w, h) in zip(names, MIXED[:7])])
    f_fs = scenario_rows(scripts, [["fixed", "fullscreen", 0, 0, 1920, 1080, "fullscreen"]]
                         + [["open", a, w, h] for a, (w, h) in zip(names, MIXED[:4])])
    f_huge = scenario_rows(scripts, [["open", "w1", 1900, 1000]] + [["open", a, w, h] for a, (w, h) in zip(names[1:], MIXED[1:6])])
    panels = [("6 terminals 826x493 (the live test)", f_big[5], [f"t{i + 1}" for i in range(6)]),
              ("same, then SUPER+G", f_big[6], [f"t{i + 1}" for i in range(6)]),
              ("a pinned window in the arm's way", f_pin[-1], names[:7]),
              ("a fullscreen window over the screen", f_fs[-1], names[:4]),
              ("an anchor as big as the screen", f_huge[-1], names[:6])]
    paths.append(_sheet(panels, out, "special_cases", 3, colors=dict(colors, **{f"t{i + 1}": PAL[i] for i in range(6)}),
                        header="Oversized, fixed and fullscreen: never overlapped, anchor kept on screen"))
    if reference:
        ref = Image.open(reference).convert("RGB")
        ref = ref.resize((900, int(900 * ref.height / ref.width)))
        r12 = scenario_rows(scripts, [["open", a, w, h] for a, (w, h) in zip(names, REF_SIZES)])[-1]
        m12 = scenario_rows(scripts, [["open", a, w, h] for a, (w, h) in zip(names, MIXED)])[-1]
        pw, ph = 900, ref.height
        img = Image.new("RGB", (3 * pw + 40, ph + 70), BG)
        d = ImageDraw.Draw(img)
        d.text((16, 14), "Reference (left) vs the model: 12 windows at reference proportions, and mixed sizes",
               font=_font(22, True), fill=INK)
        img.paste(ref, (10, 60))
        for c, (title, rows) in enumerate((("12 windows, reference proportions", r12), ("12 windows, mixed sizes", m12))):
            x = 20 + (c + 1) * pw
            panel(img, (x, 60, x + pw - 10, 60 + ph), title, rows, USABLE, colors, metrics_line(rows), order=names)
        os.makedirs(out, exist_ok=True)
        path = os.path.join(out, "reference_vs_model.png")
        img.save(path)
        print(path)
        paths.append(path)
        paths.append(_spacing_sheet(ref, out, colors, names))
    return paths


def _spacing_sheet(ref, out, colors, names, airy=(64, 112)):
    """The reference beside the model at the default spacing band and at a
    wider one (theme.json window_spacing_min/max) -- the composer's own
    arrange, drawn against each band."""
    global BAND
    pw, ph = 900, ref.height
    img = Image.new("RGB", (3 * pw + 40, ph + 70), BG)
    ImageDraw.Draw(img).text((16, 14), f"Spacing: the default {BAND[0]}-{BAND[1]} px vs window_spacing_min/max "
                             f"{airy[0]}/{airy[1]} in theme.json", font=_font(22, True), fill=INK)
    img.paste(ref, (10, 60))
    default = BAND
    try:
        for c, band in enumerate((default, airy)):
            BAND = band
            rects = dxrice_spiral.arrange(REF_SIZES, [], USABLE, band)
            rows = [(n, r[0], r[1], r[2] - r[0], r[3] - r[1]) for n, r in zip(names, rects)]
            x = 20 + (c + 1) * pw
            panel(img, (x, 60, x + pw - 10, 60 + ph), f"12 windows, reference proportions, spacing {band[0]}-{band[1]} px",
                  rows, USABLE, colors, metrics_line(rows), order=names)
    finally:
        BAND = default
    path = os.path.join(out, "spacing_default_vs_airy.png")
    img.save(path)
    print(path)
    return path


def growth_sheet(scripts, sizes, out, sheet, frames=None, cols=4):
    data = growth_rows(scripts, sizes)
    pick = frames or list(range(1, len(data) + 1))
    pw, ph = 520, 400
    rows_n = (len(pick) + cols - 1) // cols
    img = Image.new("RGB", (cols * pw + 20, rows_n * ph + 20), BG)
    names = [f"w{i + 1}" for i in range(len(sizes))]
    colors = {a: PAL[i % len(PAL)] for i, a in enumerate(names)}
    usable = (0, 52, 1920, 1012)
    for k, n in enumerate(pick):
        rows = [tuple(r) for r in data[n - 1]]
        x, y = 10 + (k % cols) * pw, 10 + (k // cols) * ph
        panel(img, (x, y, x + pw - 10, y + ph - 10), f"{n} window{'s' if n > 1 else ''} opened", rows, usable,
              colors, metrics_line(rows), order=names[:n])
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, sheet + ".png")
    img.save(path)
    print(path)


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
    ap.add_argument("--growth", help="SCRIPTS_DIR: frames of windows opened one by one")
    ap.add_argument("--sizes", default="1500x950,860x560,1100x750,640x400,900x620,550x300,1300x850,820x560")
    ap.add_argument("--frames", default="")
    ap.add_argument("--geometry", help="SCRIPTS_DIR: the geometry acceptance sheets")
    ap.add_argument("--reference", help="the visual reference image, drawn beside the model")
    a = ap.parse_args()
    if a.geometry:
        return geometry_sheets(a.geometry, a.out, a.reference)
    if a.growth:
        sizes = [tuple(int(v) for v in t.split("x")) for t in a.sizes.split(",")]
        return growth_sheet(a.growth, sizes, a.out, a.sheet, [int(f) for f in a.frames.split(",") if f])
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
