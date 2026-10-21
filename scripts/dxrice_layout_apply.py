#!/usr/bin/env python3
"""Which window-arrangement method runs, for new windows and for SUPER+G.

Three methods, each its own algorithm:

  galaxy     the Galaxy Spiral (dxrice_spiral via dxrice_auto_arrange): the
             infinite-desktop cloud, windows keep their size and the arm
             grows outward in a spiral from the first window
  compact    the composition solver with automatic resizing
             (dxrice_compact, recovered from 0af6538): a balanced, compact
             cluster centred on the screen, windows modestly resized where
             that makes it more compact -- never a grid
  expansion  the Big Bang (dxrice_expansion): windows keep their size and
             burst outward from the centre, each along its own direction

ONE setting decides both what a new window does and what SUPER+G does:
theme.json "window_layout". Values:

  "galaxy", "compact", "expansion"
  "spiral"           -> galaxy (Galaxy and Spiral are the same method; an
                        earlier build offered a separate screen-bounded
                        "spiral", which is gone)
  unknown            -> galaxy

Migration from the two settings an earlier build had (layout_auto_place
for new windows, layout_super_g for SUPER+G), applied the same way
everywhere it is read (here, and Theme.windowLayoutOf in the shell):
"window_layout" if the file has it; else "layout_auto_place"; else
"layout_super_g"; else galaxy (what DXrice always did). Reading never
writes. Saving the choice (Settings' Apply, an overview chip) writes
"window_layout" and removes the two old keys, so there is only ever one
value to disagree with.

The earlier build's screen-bounded "expansion" and "compact" (tiling-like
layouts) are gone; those saved values now mean the methods above.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dxrice_xdg  # noqa: E402
from dxrice_hypr_ipc import batch_async, hyprctl_json, move_window_exact_lua  # noqa: E402

KEY = "window_layout"
LEGACY_KEYS = ("layout_auto_place", "layout_super_g")     # in migration order
GALAXY = "galaxy"
CHOICES = (GALAXY, "compact", "expansion")
ALIASES = {"spiral": GALAXY}
DEFAULT = GALAXY
THRESHOLD = 1       # px: a window this close to its place isn't touched


def resolve(raw):
    """A saved or requested value -> one of CHOICES (see the module docstring)."""
    mode = str(raw or "").strip().lower()
    mode = ALIASES.get(mode, mode)
    return mode if mode in CHOICES else DEFAULT


def mode_from(data):
    """The method a theme.json's contents say, by the migration rule above."""
    if not isinstance(data, dict):
        return DEFAULT
    for key in (KEY,) + LEGACY_KEYS:
        if data.get(key) is not None:
            return resolve(data[key])
    return DEFAULT


def _theme_path(path=None):
    return path or os.path.join(dxrice_xdg.config_dir(), "theme.json")


def mode(path=None):
    """The saved method (one for new windows and SUPER+G alike)."""
    try:
        with open(_theme_path(path)) as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = None
    return mode_from(data)


def save_mode(value, path=None):
    """Writes the one choice into theme.json, keeping every unrelated key
    and dropping the two old ones; atomic."""
    import dxrice_manifest
    path = _theme_path(path)
    try:
        with open(path) as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return False
    except (OSError, ValueError):
        data = {}
    data[KEY] = resolve(value)
    for key in LEGACY_KEYS:
        data.pop(key, None)
    dxrice_manifest.atomic_write_bytes(path, (json.dumps(data, indent=2) + "\n").encode())
    return True


# ---- Expansion's SUPER+G (Galaxy and Compact have their own main()) ----

def expansion_moves(eligible, fixed, monitor, band=None):
    """[(address, x, y)] for the windows Expansion moves. Pure."""
    import dxrice_expansion
    windows = [(w["at"][0], w["at"][1], w["size"][0], w["size"][1]) for w in eligible]
    obstacles = [(f["at"][0], f["at"][1], f["at"][0] + f["size"][0], f["at"][1] + f["size"][1]) for f in fixed]
    rects = dxrice_expansion.arrange(windows, obstacles, monitor, band)
    out = []
    for w, r in zip(eligible, rects):
        if abs(r[0] - w["at"][0]) > THRESHOLD or abs(r[1] - w["at"][1]) > THRESHOLD:
            out.append((w["address"], r[0], r[1]))
    return out


def expansion_main():
    import dxrice_window_class
    from dxrice_auto_place_window import get_monitor_bounds
    ws = hyprctl_json(["activeworkspace"])
    if not ws:
        print("Could not get the active workspace.", file=sys.stderr)
        return 1
    clients = hyprctl_json(["clients"]) or []
    scales = (dxrice_window_class.monitor_scales(hyprctl_json(["monitors"]))
              if any(c.get("xwayland") for c in clients) else [])
    kinds, x11 = dxrice_window_class.classify_all(clients, scales=scales)
    monitor = get_monitor_bounds()
    dxrice_window_class.settle_unknown(kinds, clients, (monitor[2] - monitor[0]) * (monitor[3] - monitor[1]))
    eligible, fixed = dxrice_window_class.partition(clients, ws["id"], kinds)
    # dialogs that belong to another window move with it, not on their own
    attached = dxrice_window_class.attached_children(clients, kinds, x11, scales)
    parents = {e["address"] for e in eligible}
    eligible = [w for w in eligible if attached.get(w["address"]) not in parents]
    moves = expansion_moves(eligible, fixed, monitor)
    if moves:
        batch_async([move_window_exact_lua(x, y, a) for a, x, y in moves])
    print(f"Expansion: {len(moves)} window(s) moved.")
    return 0


def main(argv=None):
    """SUPER+G; or `--mode MODE [--save]`: arrange with MODE now (the
    overview's chips), and with --save make it THE choice (new windows
    follow it too)."""
    argv = list(argv or [])
    explicit = None
    if "--mode" in argv:
        i = argv.index("--mode")
        explicit = resolve(argv[i + 1]) if i + 1 < len(argv) else None
    method = explicit or mode()
    if explicit and "--save" in argv:
        save_mode(explicit)
    if method == "compact":
        import dxrice_compact
        return dxrice_compact.main() or 0
    if method == "expansion":
        return expansion_main()
    import dxrice_auto_arrange
    return dxrice_auto_arrange.main() or 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
