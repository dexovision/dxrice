#!/usr/bin/env python3
"""Lists launchable, visible .desktop entries -- shared by the Taskbar
manager's "Add Shortcut" search, both the GTK version (imported directly)
and the Quickshell version (run as a subprocess, printing JSON, since QML
has no directory-listing primitive of its own).

Usage as a library: from dxrice_list_desktop_apps import list_desktop_apps
Usage as a CLI:      python3 dxrice_list_desktop_apps.py   # prints a JSON array
"""
import glob
import json
import os
import re

HOME = os.path.expanduser("~")


def list_desktop_apps():
    """Returns [(name, cmd, icon_hint), ...], sorted by name, deduped by
    name (first match wins, matching the search order below: system-wide
    entries before the user's own)."""
    dirs = ["/usr/share/applications", os.path.join(HOME, ".local/share/applications")]
    seen = set()
    entries = []
    for d in dirs:
        for path in sorted(glob.glob(os.path.join(d, "*.desktop"))):
            try:
                text = open(path, encoding="utf-8", errors="ignore").read()
            except OSError:
                continue
            if "NoDisplay=true" in text:
                continue
            name_m = re.search(r"^Name=(.+)$", text, re.MULTILINE)
            exec_m = re.search(r"^Exec=(.+)$", text, re.MULTILINE)
            icon_m = re.search(r"^Icon=(.+)$", text, re.MULTILINE)
            if not name_m or not exec_m:
                continue
            name = name_m.group(1).strip()
            if name in seen:
                continue
            seen.add(name)
            cmd = re.sub(r"%[a-zA-Z]", "", exec_m.group(1)).strip()
            icon_hint = icon_m.group(1).strip() if icon_m else ""
            entries.append((name, cmd, icon_hint))
    entries.sort(key=lambda e: e[0].lower())
    return entries


if __name__ == "__main__":
    print(json.dumps([{"name": n, "cmd": c, "icon": i} for n, c, i in list_desktop_apps()]))
