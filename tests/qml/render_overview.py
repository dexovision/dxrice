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

    # Opening, as it happens: the frame after the keypress (no window data
    # yet: the real desktop, dimmed), the data in (pictures over the real
    # windows), a third of the way (the wallpaper covering the real windows),
    # done -- and a click on a window that is entirely off screen.
    seq = []
    s, layout = load(cases()[3][1], monitor(), hang=True)
    s.ev("findNamed('overview').show()")
    s.wait(1)
    s.ev("findNamed('overview').fade = 1")
    seq.append(label(s.grab(out / "_tmp.png"), "keypress: dim at once, window data not in yet"))
    s.close()
    s, layout = load(cases()[3][1], monitor())
    s.ev("findNamed('overview').show()")
    s.wait(SETTLE)  # let the real animation finish, then step through it by hand
    s.ev("findNamed('overview').progress = 0")
    s.wait(60)
    seq.append(label(s.grab(out / "_tmp.png"), "~10 ms: data in, pictures exactly over the windows"))
    s.ev("findNamed('overview').progress = 0.2")
    s.wait(60)
    seq.append(label(s.grab(out / "_tmp.png"), "zooming: wallpaper fading in over the real windows"))
    s.ev("findNamed('overview').progress = 1")
    s.wait(60)
    seq.append(label(s.grab(out / "_tmp.png"), "zoomed out"))
    r = layout["reserved"]
    off = next(w for w in reversed(layout["windows"])
               if not (w["x"] + r[0] < 1920 and w["x"] + r[0] + w["w"] > 0 and w["y"] + r[1] < 1080 and w["y"] + r[1] + w["h"] > 0))
    from PySide6.QtCore import QPointF
    from PySide6.QtTest import QTest
    QTest.mouseClick(s.view, Qt.LeftButton, Qt.NoModifier,
                     QPointF(off["tx"] + r[0] + off["tw"] / 2, off["ty"] + r[1] + off["th"] / 2).toPoint())
    s.wait(400)
    seq.append(label(s.grab(out / "_tmp.png"), "click on an off-screen window: asks first"))
    s.close()
    (out / "_tmp.png").unlink(missing_ok=True)
    sheet([seq[:3], seq[3:]], out / "overview_opening_sequence.png", scale=0.36)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "/tmp/overview-renders")
