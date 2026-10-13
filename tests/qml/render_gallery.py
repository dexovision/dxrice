#!/usr/bin/env python3
"""Offscreen gallery: renders every major shell surface at several screen
sizes into PNGs, for looking at -- not a test. Uses the same harness as the
QML suites (real shell QML, stub compositor types, no live desktop).

    python3 tests/qml/render_gallery.py OUTDIR [--sizes 1920x1080,1366x768,...] [--only NAME,...]

Each PNG is OUTDIR/<size>/<scene>.png. Not compositor-accurate: no blur,
no real fonts beyond what Qt finds, no GPU effects (see README.md).
"""
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from harness import Scene
except ImportError as e:  # pragma: no cover
    print(f"SKIP: {e}")
    sys.exit(0)

SIZES = ["1920x1080", "1366x768", "1280x720", "1024x768"]
TE = "surfaces().filter(w => _name(w).indexOf('ThemeEditor') === 0)[0]"


def _settle(s, ms=900):
    s.wait(ms)


def scenes():
    def idle(s):
        _settle(s, 300)

    def panel(name):
        def go(s):
            s.ev(f"panels.open('{name}')")
            _settle(s)
        return go

    def qs_tab(tab):
        def go(s):
            s.ev("panels.open('quicksettings')")
            _settle(s, 500)
            s.ev(f"findPanel('currentTab').currentTab = '{tab}'")
            _settle(s, 500)
        return go

    def add_shortcut(s):
        s.ev("panels.open('taskbar')")
        _settle(s, 600)
        s.ev("findPanel('addPanelOpen').addPanelOpen = true")
        _settle(s)

    def theme(cat):
        def go(s):
            s.ev("panels.open('theme')")
            _settle(s, 600)
            s.ev(f"{TE}.currentCategory = '{cat}'")
            _settle(s, 500)
        return go

    def picker(s):
        theme("colors")(s)
        s.ev(f"(function(){{ const te = {TE}; const sw = findNamed('swatch_accent'); te.pickColor('accent', sw, 'Accent'); }})()")
        _settle(s)

    def osd(s):
        s.ev("findNamed('osd') ? findNamed('osd').trigger('\\uf028', 0.62, '62%') : null")
        _settle(s, 400)

    def lock(s):
        s.ev("(function(){ const l = findNamed('lockScreen'); l.locked = true;"
             " const it = l.surfaceItem; it.screen = undefined;"  # the harness has no screens: be the primary one
             " it.parent = overlay; it.width = overlay.width; it.height = overlay.height; })()")
        _settle(s, 500)

    def dock_tooltip(s):
        s.ev("(function(){ const d = surfaces().filter(w => _name(w).indexOf('Dock') === 0)[0];"
             " d.hoverTile = findNamed('dockTile:Firefox'); })()")
        _settle(s, 900)

    def theme_busy(s):
        s.ev("panels.open('theme')")
        _settle(s, 600)
        s.ev(f"{TE}.applying = true")
        _settle(s, 300)

    def wifi_dialog(s):
        s.ev("panels.open('quicksettings')")
        _settle(s, 600)
        s.ev("(function(){ const qs = findPanel('currentTab');"
             " const st = [qs]; let wifi = null; while (st.length && !wifi) { const o = st.pop(); if (!o) continue;"
             "   if (o.hasScanned !== undefined && o.networks !== undefined && o.passwordNeeded) wifi = o;"
             "   const k = o.data !== undefined ? o.data : []; for (let i = 0; i < k.length; i++) st.push(k[i]); }"
             " wifi.passwordNeeded('CoffeeShop Guest');"
             " const d = qs._activeWifiDialog; d.parent = overlay; d.visible = true;"
             " d.width = d.implicitWidth; d.height = d.implicitHeight;"
             " d.x = (overlay.width - d.width) / 2; d.y = (overlay.height - d.height) / 2; })()")
        _settle(s, 500)

    def qs_scanning(s):
        s.ev("panels.open('quicksettings')")
        _settle(s, 500)
        s.ev("(function(){ const qs = findPanel('currentTab');"
             " const st = [qs]; while (st.length) { const o = st.pop(); if (!o) continue;"
             "   if (o.hasScanned !== undefined && o.networks !== undefined) { o.hasScanned = false; o.networks = []; }"
             "   const k = o.data !== undefined ? o.data : []; for (let i = 0; i < k.length; i++) st.push(k[i]); } })()")
        _settle(s, 400)

    def lock_error(s):
        lock(s)
        s.ev("(function(){ const l = findNamed('lockScreen'); const st = [l.surfaceItem]; while (st.length) { const o = st.pop(); if (!o) continue;"
             " if (o.objectName === 'lockPam') { o.completed(1); return; }"
             " const k = o.data !== undefined ? o.data : []; for (let i = 0; i < k.length; i++) st.push(k[i]); } })()")
        _settle(s, 600)

    def panel_closing(s):
        s.ev("panels.open('quicksettings')")
        _settle(s, 900)
        s.ev("panels.close('quicksettings')")
        s.wait(120)  # mid-close: content already fading, surface retracting

    out = {"idle": idle, "dock_tooltip": dock_tooltip, "theme_busy": theme_busy, "wifi_dialog": wifi_dialog,
           "qs_scanning": qs_scanning, "lock_error": lock_error, "panel_closing": panel_closing, "calendar": panel("calendar"), "taskbar": panel("taskbar"), "add_shortcut": add_shortcut,
           "qs_overview": qs_tab("overview"), "qs_media": qs_tab("media"), "qs_performance": qs_tab("performance"),
           "picker": picker, "osd": osd, "lock": lock}
    for cat in ("colors", "blur", "layout", "lock", "fonts", "experience", "wallpaper"):
        out[f"theme_{cat}"] = theme(cat)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--sizes", default=",".join(SIZES))
    ap.add_argument("--only", default="")
    args = ap.parse_args()
    only = set(filter(None, args.only.split(",")))
    report = {}
    for size in args.sizes.split(","):
        w, h = (int(v) for v in size.split("x"))
        outdir = Path(args.out) / size
        outdir.mkdir(parents=True, exist_ok=True)
        for name, setup in scenes().items():
            if only and name not in only:
                continue
            s = Scene(width=w, height=h)
            try:
                setup(s)
                s.grab(outdir / f"{name}.png")
                report[f"{size}/{name}"] = [w for w in s.warnings if "qrc:" not in w][:5]
            except Exception as e:  # keep going: a broken scene is itself a finding
                report[f"{size}/{name}"] = [f"ERROR: {e}"]
            finally:
                s.close()
    problems = {k: v for k, v in report.items() if v}
    print(json.dumps(problems, indent=1) if problems else "all scenes rendered without QML warnings")


if __name__ == "__main__":
    main()
