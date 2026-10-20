#!/usr/bin/env python3
"""Lists the wallpaper images the theme editor can offer: the pictures in
~/Pictures/Wallpapers and in the folder of the wallpaper in use. Prints a
JSON array of {"path", "name"}, sorted by name. QML has no directory
listing of its own, so Settings > Wallpaper runs this.

    python3 dxrice_list_wallpapers.py [CURRENT_WALLPAPER]
"""
import json
import os
import sys

EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp")
LIMIT = 60


def list_wallpapers(current="", home=None):
    home = home or os.path.expanduser("~")
    dirs = [os.path.join(home, "Pictures", "Wallpapers")]
    if current:
        dirs.append(os.path.dirname(os.path.abspath(current)))
    seen, out = set(), []
    for d in dirs:
        try:
            names = sorted(os.listdir(d))
        except OSError:
            continue
        for n in names:
            path = os.path.join(d, n)
            real = os.path.realpath(path)
            if real in seen or not n.lower().endswith(EXTENSIONS) or not os.path.isfile(path):
                continue
            seen.add(real)
            out.append({"path": path, "name": os.path.splitext(n)[0]})
    out.sort(key=lambda w: w["name"].lower())
    return out[:LIMIT]


if __name__ == "__main__":
    print(json.dumps(list_wallpapers(sys.argv[1] if len(sys.argv) > 1 else "")))
