#!/usr/bin/env python3
"""Standalone diagnostic tool for the SUPER+D floating->tiled investigation.
Not part of the arrangement solver and not wired into hyprland.lua -- run
this by hand, in a spare terminal, the next time the tiling issue is about
to be reproduced.

It watches raw keyboard input directly (the same technique
dxrice_infinite_desktop_core.py already uses for its own SUPER+drag
detection) to detect an actual physical SUPER+D press independently of
Hyprland's own keybind path or dxrice_auto_arrange.py -- so this capture
can never be confused with, or accidentally influenced by, the thing it's
trying to observe. The moment SUPER+D is detected, it snapshots every
floating/tiled window's full state, waits briefly for the real keybind's
own dispatch to run and settle, then snapshots again and prints exactly
what changed.

Usage:
    python3 dxrice_superd_capture.py

Then just use the desktop normally and press SUPER+D when you're ready to
reproduce the issue. Ctrl+C to stop. Every press is captured and compared;
nothing needs to be reproduced in a single run.
"""
import json
import struct
import sys
import time
import os
from evdev import InputDevice, list_devices, ecodes

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dxrice_hypr_ipc import hyprctl_json

EVENT_SIZE = struct.calcsize('llHHi')
EV_KEY = 1
KEY_LEFTMETA = 125
KEY_RIGHTMETA = 126
KEY_D = 32

FIELDS = ["address", "workspace", "at", "size", "floating", "fullscreen", "fullscreenClient", "mapped"]


def snapshot():
    clients = hyprctl_json(["clients"]) or []
    layout = None
    try:
        import subprocess
        out = subprocess.run(["hyprctl", "getoption", "general:layout"],
                              capture_output=True, text=True, timeout=2).stdout
        layout = out.strip()
    except Exception:
        pass
    return {
        "layout": layout,
        "windows": {w["address"]: {k: w.get(k) for k in FIELDS} for w in clients if w.get("mapped")},
    }


def diff_and_report(before, after):
    print("\n" + "=" * 70)
    print("SUPER+D detected -- state comparison")
    print("=" * 70)
    if before["layout"] != after["layout"]:
        print(f"!! LAYOUT MODE CHANGED: {before['layout']!r} -> {after['layout']!r}")
    else:
        print(f"layout mode unchanged: {before['layout']!r}")

    all_addrs = set(before["windows"]) | set(after["windows"])
    any_change = False
    for addr in all_addrs:
        b = before["windows"].get(addr)
        a = after["windows"].get(addr)
        if b is None:
            print(f"  {addr}: NEW window appeared: {a}")
            any_change = True
            continue
        if a is None:
            print(f"  {addr}: window disappeared (closed?) -- was {b}")
            any_change = True
            continue
        changes = {}
        for k in FIELDS:
            if b.get(k) != a.get(k):
                changes[k] = (b.get(k), a.get(k))
        if changes:
            any_change = True
            flags = []
            if "floating" in changes:
                flags.append("*** FLOATING STATE CHANGED ***")
            if "size" in changes:
                flags.append("*** SIZE CHANGED ***")
            if "fullscreen" in changes or "fullscreenClient" in changes:
                flags.append("*** FULLSCREEN STATE CHANGED ***")
            if "workspace" in changes:
                flags.append("*** WORKSPACE CHANGED ***")
            label = f"  {addr} {' '.join(flags)}"
            print(label)
            for k, (bv, av) in changes.items():
                print(f"      {k}: {bv!r} -> {av!r}")
    if not any_change:
        print("  (no window fields changed at all)")
    print("=" * 70 + "\n")


def watch_keyboard(path):
    try:
        fd = open(path, "rb")
    except Exception:
        return
    meta_held = False
    while True:
        try:
            data = fd.read(EVENT_SIZE)
        except Exception:
            break
        if not data or len(data) < EVENT_SIZE:
            break
        _, _, etype, code, value = struct.unpack('llHHi', data)
        if etype != EV_KEY:
            continue
        if code in (KEY_LEFTMETA, KEY_RIGHTMETA):
            meta_held = (value != 0)
        elif code == KEY_D and value == 1 and meta_held:
            before = snapshot()
            print(f"[{time.strftime('%H:%M:%S')}] SUPER+D press detected, capturing...")
            time.sleep(0.6)  # give the real keybind's own dispatch time to run and settle
            after = snapshot()
            diff_and_report(before, after)


def classify_keyboard(path):
    try:
        dev = InputDevice(path)
        caps = dev.capabilities()
        dev.close()
    except Exception:
        return False
    keys = set(caps.get(ecodes.EV_KEY, []))
    return (ecodes.KEY_A in keys and ecodes.KEY_Z in keys and ecodes.KEY_LEFTSHIFT in keys
            and (ecodes.KEY_LEFTMETA in keys or ecodes.KEY_RIGHTMETA in keys))


def main():
    print("Watching for a real physical SUPER+D press (Ctrl+C to stop)...")
    keyboards = [p for p in list_devices() if classify_keyboard(p)]
    if not keyboards:
        print("No keyboard device found/readable.", file=sys.stderr)
        sys.exit(1)
    import threading
    threads = [threading.Thread(target=watch_keyboard, args=(p,), daemon=True) for p in keyboards]
    for t in threads:
        t.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
