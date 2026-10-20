#!/usr/bin/env python3
"""Puts a workspace's floating windows into one of the three layouts.

Reads Hyprland's windows and monitors, asks dxrice_layouts for the
rectangles, and sends the moves and resizes. Hyprland animates them with its
own window animation, so the change glides; nothing here fakes motion.

  windows      the eligible ones (dxrice_window_class.partition: ordinary
               floating windows, not pinned, fullscreen, hidden, a dialog or
               a menu), in creation order
  per monitor  each monitor's windows are laid out in its own usable area
               (its size minus the bar and dock)
  primary      the window Expansion makes big: the newest one for Auto
               Place, the focused one for SUPER+G
  unplaced     a window too many for the area at a usable size is left
               exactly where it is

Settings (theme.json): layout_auto_place and layout_super_g, each
"expansion" (default), "spiral" or "compact". "galaxy" keeps the old
Galaxy Spiral placement for whoever wants it; it is not offered in Settings.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dxrice_layouts  # noqa: E402
import dxrice_monitor  # noqa: E402
import dxrice_window_class  # noqa: E402
import dxrice_xdg  # noqa: E402
from dxrice_hypr_ipc import (batch_async, hyprctl_json, move_window_exact_lua,  # noqa: E402
                             resize_window_exact_lua)

KEYS = {"auto_place": "layout_auto_place", "super_g": "layout_super_g"}
LEGACY = "galaxy"
THRESHOLD = 1       # px: a window this close to its place isn't touched


def setting(which, path=None):
    """The saved mode for "auto_place" or "super_g": one of
    dxrice_layouts.MODES, or "galaxy". A missing, unreadable or unknown
    value is the default (Expansion), never an error."""
    path = path or os.path.join(dxrice_xdg.config_dir(), "theme.json")
    try:
        with open(path) as f:
            raw = json.load(f).get(KEYS[which])
    except (OSError, ValueError, AttributeError):
        raw = None
    if isinstance(raw, str) and raw.strip().lower() == LEGACY:
        return LEGACY
    return dxrice_layouts.normalize(raw)


def gap_setting(path=None):
    path = path or os.path.join(dxrice_xdg.config_dir(), "theme.json")
    try:
        with open(path) as f:
            return max(0, int(json.load(f).get("hypr_gaps_in", 5)))
    except (OSError, ValueError, TypeError, AttributeError):
        return 5


def _creation_key(c):
    try:
        return int(str(c.get("stableId")), 16)
    except (TypeError, ValueError):
        return 0


def plan(mode, clients, monitors, workspace_id, gap, primary_address=None, newest_is_primary=True):
    """[(address, (x, y, w, h))] for the windows that move or resize, plus
    the addresses left unplaced. Pure: nothing is sent."""
    kinds, _x11 = dxrice_window_class.classify_all(clients)
    eligible, _fixed = dxrice_window_class.partition(clients, workspace_id, kinds)
    eligible.sort(key=_creation_key)
    by_monitor = {}
    for c in eligible:
        by_monitor.setdefault(c.get("monitor"), []).append(c)
    out, unplaced = [], []
    for mon_id, wins in sorted(by_monitor.items(), key=lambda kv: (kv[0] is None, kv[0])):
        m = dxrice_monitor.pick(monitors, mon_id)
        area = dxrice_monitor.usable_bounds(m) if m else dxrice_monitor.FALLBACK_BOUNDS
        primary = len(wins) - 1 if newest_is_primary else None
        if primary_address:
            for i, c in enumerate(wins):
                if c["address"] == primary_address:
                    primary = i
        if primary is None:
            primary = len(wins) - 1
        rects = dxrice_layouts.layout(mode, len(wins), tuple(area), gap, primary)
        for c, r in zip(wins, rects):
            if r is None:
                unplaced.append(c["address"])
                continue
            (cx, cy), (cw, ch) = c["at"], c["size"]
            if (abs(r[0] - cx) > THRESHOLD or abs(r[1] - cy) > THRESHOLD
                    or abs(r[2] - cw) > THRESHOLD or abs(r[3] - ch) > THRESHOLD):
                out.append((c["address"], r))
    return out, unplaced


def apply(mode, workspace_id, primary_address=None, newest_is_primary=True, clients=None, monitors=None, gap=None):
    """Lay the workspace out; returns (moved, unplaced)."""
    clients = clients if clients is not None else (hyprctl_json(["clients"]) or [])
    monitors = monitors if monitors is not None else (hyprctl_json(["monitors"]) or [])
    gap = gap_setting() if gap is None else gap
    moves, unplaced = plan(mode, clients, monitors, workspace_id, gap, primary_address, newest_is_primary)
    exprs = []
    for address, (x, y, w, h) in moves:
        exprs.append(resize_window_exact_lua(w, h, address))     # resize first (it is centre-anchored)...
        exprs.append(move_window_exact_lua(x, y, address))       # ...then to the exact top-left
    if exprs:
        batch_async(exprs)
    return len(moves), unplaced


def save_setting(which, mode, path=None):
    """Writes the choice into theme.json, keeping every other key; atomic."""
    import dxrice_manifest
    path = path or os.path.join(dxrice_xdg.config_dir(), "theme.json")
    try:
        with open(path) as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return False
    except (OSError, ValueError):
        data = {}
    data[KEYS[which]] = mode
    dxrice_manifest.atomic_write_bytes(path, (json.dumps(data, indent=2) + "\n").encode())
    return True


def main(argv=None):
    """SUPER+G; or `--mode MODE [--save]`: lay out with MODE now (the
    overview's layout chips), and with --save make it SUPER+G's choice."""
    argv = list(argv or [])
    explicit = None
    if "--mode" in argv:
        i = argv.index("--mode")
        explicit = dxrice_layouts.normalize(argv[i + 1]) if i + 1 < len(argv) else None
    mode = explicit or setting("super_g")
    if explicit and "--save" in argv:
        save_setting("super_g", explicit)
    if mode == LEGACY:
        import dxrice_auto_arrange
        return dxrice_auto_arrange.main()
    ws = hyprctl_json(["activeworkspace"])
    if not ws:
        print("Could not get the active workspace.", file=sys.stderr)
        return 1
    active = hyprctl_json(["activewindow"]) or {}
    moved, unplaced = apply(mode, ws["id"], primary_address=active.get("address"), newest_is_primary=False)
    msg = f"{mode.capitalize()}: {moved} window(s) moved."
    if unplaced:
        msg += f" {len(unplaced)} left where they are (no room at a usable size)."
    print(msg)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
