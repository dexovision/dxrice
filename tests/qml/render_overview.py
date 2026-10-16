"""Before/after renders of the desktop overview, offscreen.

Each case is a synthetic workspace (the Galaxy Spiral's own placement,
dxrice_spiral.arrange, or hand-made windows), drawn as the normal desktop
-- the monitor showing what is on it, the bar and dock on top -- and then
with the overview open, through the real shell (Overview.qml, reading
synthetic `hyprctl -j clients/monitors` output and computing the geometry in
OverviewGeometry.js). Window pictures are stand-ins (the
ScreencopyView stub); the wallpaper is a synthetic gradient.

    python3 tests/qml/render_overview.py OUT_DIR
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from harness import Scene  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QColor, QFont, QImage, QLinearGradient, QPainter  # noqa: E402
import dxrice_overview as ov  # noqa: E402
import dxrice_spiral as sp  # noqa: E402
from test_overview import PAL, MIXED, monitor, clients_for  # noqa: E402

BAND = (32, 56)
REF = [(381, 225)] + [(262, 125)] * 31
WIDE = [(1500, 420), (1300, 300), (900, 260), (1600, 340), (1100, 280), (1400, 360), (1000, 300), (1500, 320)]
TALL = [(700, 900), (380, 900), (300, 760), (420, 1000), (340, 820), (400, 940), (320, 780), (360, 880)]
SETTLE = 1100


def spiral(sizes, usable=(0, 52, 1920, 1012)):
    return clients_for(sp.arrange(sizes, [], usable, BAND))


def cases():
    full = spiral(MIXED[:6])
    fs = clients_for([tuple(r) for r in [(0, 0, 1920, 1080)]])[0]
    fs.update({"address": "0xf00", "fullscreen": 2, "floating": False, "focusHistoryID": 0, "title": "Fullscreen game"})
    pin = clients_for([(1460, 90, 1880, 400)])[0]
    pin.update({"address": "0xf01", "pinned": True, "workspace": {"id": 9}, "title": "Pinned (all workspaces)"})
    return [
        ("one window: already on screen, nothing zooms", clients_for([(410, 182, 1510, 882)]), monitor()),
        ("6 mixed windows", spiral(MIXED[:6]), monitor()),
        ("16 windows, reference proportions", spiral(REF[:16]), monitor()),
        ("16 mixed application windows", spiral(MIXED), monitor()),
        ("32 windows: a spiral far past the screen", spiral(REF), monitor()),
        ("8 very wide windows", spiral(WIDE), monitor()),
        ("8 very tall windows", spiral(TALL), monitor()),
        ("a fullscreen window and a pinned one", full + [pin, fs], monitor()),
        ("a 2560x1440 monitor, bar only (no dock)", spiral(MIXED[:12], (0, 40, 2560, 1440)),
         monitor("HDMI-A-1", 2560, 1440, (0, 40, 0, 0))),
    ]


def wallpaper(bridge, w, h):
    path = str(bridge.config_home.parent / "wall.png")
    img = QImage(w, h, QImage.Format_RGB32)
    p = QPainter(img)
    g = QLinearGradient(0, 0, w, h)
    g.setColorAt(0, QColor("#24324a")); g.setColorAt(0.5, QColor("#3d2f4a")); g.setColorAt(1, QColor("#1b2a2a"))
    p.fillRect(0, 0, w, h, g)
    p.end()
    img.save(path)
    t = bridge.config_home / "dxrice" / "theme.json"
    d = json.loads(t.read_text())
    d["wallpaper"] = path
    t.write_text(json.dumps(d))
    bridge.wall = path


def load(clients, mon, hang=False):
    s = Scene("OverviewDesktop.qml", width=mon["width"], height=mon["height"],
              setup=lambda b: wallpaper(b, mon["width"], mon["height"]))
    s.ev("wallpaper = " + json.dumps(s.bridge.wall))
    layout = ov.overview(clients, [mon])
    if hang:
        s.set_command("hyprctl -j clients", "__HANG__")
    s.set_command("hyprctl -j clients", json.dumps(clients))
    s.set_command("hyprctl -j monitors", json.dumps([mon]))
    r = layout["reserved"]
    colour = {}
    for i, w in enumerate(layout["windows"]):
        colour[w["address"]] = "#6b6f78" if w["fullscreen"] else ("#8a6a3a" if w["pinned"] else PAL[i % len(PAL)])
    s.ev("fakeWindows = " + json.dumps([{"x": w["x"] + r[0], "y": w["y"] + r[1], "w": w["w"], "h": w["h"],
                                          "color": colour[w["address"]], "title": w["title"]}
                                         for w in layout["windows"]]))
    s.ev("hypr.toplevels = ({ values: " + json.dumps([
        {"address": w["address"].replace("0x", ""),
         "wayland": {"color": colour[w["address"]], "title": w["title"], "logicalWidth": w["w"]}}
        for w in layout["windows"]]) + " })")
    s.wait(300)
    return s, layout


def label(img, text, sub=""):
    p = QPainter(img)
    p.fillRect(0, 0, img.width(), 40, QColor(16, 18, 22, 230))
    p.setPen(QColor("#e8eaf0"))
    f = QFont(); f.setPixelSize(18); f.setBold(True); p.setFont(f)
    p.drawText(14, 27, text)
    if sub:
        f.setBold(False); f.setPixelSize(15); p.setFont(f); p.setPen(QColor("#9aa1ae"))
        p.drawText(img.width() - 14 - p.fontMetrics().horizontalAdvance(sub), 27, sub)
    p.end()
    return img


def sheet(rows, path, scale=0.42):
    """rows: [[QImage, ...], ...] -> one PNG, every image scaled alike."""
    imgs = [[i.scaledToWidth(int(i.width() * scale), Qt.SmoothTransformation) for i in r] for r in rows]
    W = max(sum(i.width() for i in r) + 12 * (len(r) + 1) for r in imgs)
    H = sum(max(i.height() for i in r) + 12 for r in imgs) + 12
    out = QImage(W, H, QImage.Format_RGB32)
    out.fill(QColor("#101216"))
    p = QPainter(out)
    y = 12
    for r in imgs:
        x = 12
        for i in r:
            p.drawImage(x, y, i)
            x += i.width() + 12
        y += max(i.height() for i in r) + 12
    p.end()
    out.save(str(path))
    print(path)


def main(out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for title, clients, mon in cases():
        s, layout = load(clients, mon)
        before = label(s.grab(out / "_tmp.png"), title, "normal desktop")
        s.ev("findNamed('overview').show()")
        s.wait(SETTLE)
        sub = ("no zoom needed" if layout["fits"] else f"overview, {layout['scale'] * 100:.0f}% scale"
               + (" (minimum: clipped)" if layout["clipped"] else ""))
        after = label(s.grab(out / "_tmp.png"), title, sub)
        rows.append([before, after])
        s.close()
    (out / "_tmp.png").unlink(missing_ok=True)
    sheet(rows[:5], out / "overview_before_after_1.png")
    sheet(rows[5:], out / "overview_before_after_2.png")

    # the zoom itself: the opening fade done, then the zoom at 0..100%
    s, layout = load(cases()[3][1], monitor())
    s.ev("findNamed('overview').show()")
    s.wait(60)
    s.ev("findNamed('overview').fade = 1")
    frames = []
    for p in (0.0, 0.25, 0.5, 0.75, 1.0):
        s.ev("findNamed('overview').progress = " + str(p))
        s.wait(80)
        frames.append(label(s.grab(out / "_tmp.png"), f"zoom {int(p * 100)}%"))
    s.close()
    (out / "_tmp.png").unlink(missing_ok=True)
    sheet([frames[:3], frames[3:]], out / "overview_zoom_frames.png", scale=0.36)

    timelines(out)
    one_click_sequence(out)
    timing_chart(out)


def _bezier(x1, y1, x2, y2, u):
    def c(t, a, b):
        return 3 * a * t * (1 - t) ** 2 + 3 * b * t * t * (1 - t) + t ** 3
    lo, hi = 0.0, 1.0
    for _ in range(60):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if c(mid, x1, x2) < u else (lo, mid)
    return c((lo + hi) / 2, y1, y2)


# The shipped motion at the theme's default speed (anim_duration_ms 150):
# the dim fades in over 150 ms (OutCubic) from the keypress; the window data
# lands ~10 ms in; the zoom (300 ms, cubic-bezier 0.4 0 0.2 1) starts then.
# Closing: zoom back and fade out together, 300 ms.
ZOOM_MS, DATA_MS, FADE_MS = 300, 10, 150


def open_state(t):
    fade = 1 - (1 - min(1.0, t / FADE_MS)) ** 3
    prog = _bezier(0.4, 0.0, 0.2, 1.0, min(1.0, max(0.0, (t - DATA_MS) / ZOOM_MS)))
    return fade, prog


def close_state(t):
    u = min(1.0, t / ZOOM_MS)
    return 1 - u * u, 1 - _bezier(0.4, 0.0, 0.2, 1.0, u)


def _set(s, fade, prog):
    s.ev(f"findNamed('overview').fade = {fade}")
    s.ev(f"findNamed('overview').progress = {prog}")
    s.wait(50)


def timelines(out):
    """The opening and closing as they unfold, frame by frame at the given
    times after the keypress (the real curves, stepped by hand so the
    offscreen renderer's pacing doesn't blur them)."""
    rows = []
    for name, fn, times in (("open", open_state, (0, 16, 60, 120, 180, 310)),
                            ("close", close_state, (0, 60, 120, 180, 240, 300))):
        s, layout = load(cases()[3][1], monitor())
        s.ev("findNamed('overview').show()")
        s.wait(SETTLE)
        row = []
        for t in times:
            if name == "open" and t == 0:
                s.ev("findNamed('overview').progress = 0")
                s.ev("findNamed('overview').fade = 0.05")
                s.wait(50)
                row.append(label(s.grab(out / "_tmp.png"), "keypress + 1 frame: the dim begins"))
                continue
            fade, prog = fn(t)
            _set(s, fade, prog)
            row.append(label(s.grab(out / "_tmp.png"), f"{name} +{t} ms", f"zoom {prog * 100:.0f}%"))
        rows.append(row)
        s.close()
    (out / "_tmp.png").unlink(missing_ok=True)
    sheet([rows[0][:3], rows[0][3:], rows[1][:3], rows[1][3:]], out / "overview_timeline.png", scale=0.3)


def one_click_sequence(out):
    """One click on a window entirely off screen: the desktop pans as one
    piece (every floating window by the same delta), the overview closes
    onto the windows in their new places, and that window has focus."""
    s, layout = load(cases()[3][1], monitor())
    r = layout["reserved"]
    W, H = layout["monitor"]["width"], layout["monitor"]["height"]
    target = next(w for w in reversed(layout["windows"])
                  if w["x"] + w["w"] < 0 or w["x"] > W or w["y"] + w["h"] < 0 or w["y"] > H)
    frames = [label(s.grab(out / "_tmp.png"), "the desktop: the target window is off screen")]
    s.ev("findNamed('overview').show()")
    s.wait(SETTLE)
    from PySide6.QtCore import QPointF
    from PySide6.QtTest import QTest
    pt = QPointF(target["tx"] + r[0] + target["tw"] / 2, target["ty"] + r[1] + target["th"] / 2).toPoint()
    QTest.mouseMove(s.view, pt)
    s.wait(80)
    frames.append(label(s.grab(out / "_tmp.png"), "zoomed out: one click on it"))
    QTest.mouseClick(s.view, Qt.LeftButton, Qt.NoModifier, pt)
    s.wait(1)
    # the compositor applies the pan the overview sent
    moves = [d for d in json.loads(s.ev("JSON.stringify(hypr.dispatchLog)")) if d.startswith("hl.dsp.window.move")]
    import re
    moved = {}
    for d in moves:
        m = re.search(r'address:([^"]+)", x = (-?\d+), y = (-?\d+)', d)
        moved[m.group(1)] = (int(m.group(2)), int(m.group(3)))
    fake = json.loads(s.ev("JSON.stringify(fakeWindows)"))
    for fw, w in zip(fake, layout["windows"]):
        if w["address"] in moved:
            ax, ay = moved[w["address"]]
            fw["x"], fw["y"] = ax - layout["monitor"]["x"] + r[0], ay - layout["monitor"]["y"] + r[1]
        if w["address"] == target["address"]:
            fw["color"] = "#c9d2e8"
    s.ev("fakeWindows = " + json.dumps(fake))
    s.ev("findNamed('overview').fade = 0.6")
    s.ev("findNamed('overview').progress = 0.45")
    s.wait(60)
    frames.append(label(s.grab(out / "_tmp.png"), "closing onto the panned desktop"))
    s.wait(SETTLE)
    frames.append(label(s.grab(out / "_tmp.png"), "done: panned as one piece, the window in view (highlighted)"))
    s.close()
    (out / "_tmp.png").unlink(missing_ok=True)
    sheet([frames[:2], frames[2:]], out / "overview_one_click.png", scale=0.36)


def timing_chart(out):
    """Zoom progress over time from the keypress, before (fdb3111) and now."""
    from PySide6.QtGui import QPen
    W, H, L, B = 1500, 620, 80, 70
    img = QImage(W, H, QImage.Format_RGB32)
    img.fill(QColor("#15171c"))
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    f = QFont(); f.setPixelSize(20); f.setBold(True); p.setFont(f); p.setPen(QColor("#e8eaf0"))
    p.drawText(20, 34, "Zoom progress after the keypress: before (fdb3111) and now")
    span = 700.0
    X = lambda t: L + (W - L - 30) * t / span
    Y = lambda v: H - B - (H - B - 70) * v
    p.setPen(QColor("#4a5163"))
    p.drawLine(int(X(0)), int(Y(0)), int(X(span)), int(Y(0)))
    p.drawLine(int(X(0)), int(Y(0)), int(X(0)), int(Y(1)))
    f.setBold(False); f.setPixelSize(14); p.setFont(f)
    for t in range(0, 701, 100):
        p.setPen(QColor("#9aa1ae")); p.drawText(int(X(t)) - 14, H - B + 22, f"{t} ms")
    for v in (0, 0.5, 1):
        p.drawText(20, int(Y(v)) + 5, f"{int(v * 100)}%")

    def old_open(t):  # fdb3111: python-free data ~40 ms after the key, zoom 420 ms curveStandard
        t0 = 40
        return _bezier(0.2, 0.0, 0.0, 1.0, min(1, max(0, (t - t0) / 420)))

    def new_open(t):  # now: ~40 ms (key IPC 30 + data 10), zoom 300 ms ease-in-out
        t0 = 40
        return _bezier(0.4, 0.0, 0.2, 1.0, min(1, max(0, (t - t0) / 300)))

    def old_close(t):  # fdb3111: InOutCubic 360 ms, then a 120 ms fade-out before the surface goes
        u = min(1, t / 360)
        return 1 - (4 * u ** 3 if u < 0.5 else 1 - (-2 * u + 2) ** 3 / 2)

    def new_close(t):
        return 1 - _bezier(0.4, 0.0, 0.2, 1.0, min(1, t / 300))

    for fn, col, dash, name in ((old_open, "#9aa1ae", True, "open, before"), (new_open, "#7fb0ff", False, "open, now"),
                                (old_close, "#c49a6c", True, "close, before (+120 ms fade after)"),
                                (new_close, "#f0b45a", False, "close, now (fade alongside)")):
        pen = QPen(QColor(col)); pen.setWidth(3)
        if dash:
            pen.setStyle(Qt.DashLine)
        p.setPen(pen)
        pts = [(X(t), Y(fn(t))) for t in range(0, 701, 4)]
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            p.drawLine(int(x0), int(y0), int(x1), int(y1))
    yy = 64
    for col, name in (("#9aa1ae", "open, before: 420 ms decelerating"), ("#7fb0ff", "open, now: 300 ms ease-in-out"),
                      ("#c49a6c", "close, before: 360 ms, then a 120 ms fade"), ("#f0b45a", "close, now: 300 ms, fade alongside")):
        p.fillRect(W - 430, yy - 10, 24, 6, QColor(col)); p.setPen(QColor("#cfd3dc")); p.drawText(W - 396, yy, name); yy += 26
    p.end()
    img.save(str(out / "overview_timing.png"))
    print(out / "overview_timing.png")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "/tmp/overview-renders")
