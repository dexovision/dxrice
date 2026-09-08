#!/usr/bin/env python3
"""
dxrice_force_close_window.py
Bound to Super+C. Makes "close" actually end the focused app instead of
letting it hide to tray, which Discord/Steam/Slack do to a plain Wayland
close request (Hyprland's killactive dispatcher).

hyprctl's active window pid is only the specific process that owns that
window's surface -- for Chromium/Electron apps that's one renderer among
many sibling processes (GPU process, network/audio utility processes, the
main process). Killing just that pid closes the window but leaves the rest
of the app (and e.g. a Discord call's audio) running.

A process-group kill was considered and rejected: apps launched directly by
Hyprland (anything that doesn't self-isolate into a new group, e.g. a plain
terminal) inherit Hyprland's own process group, so signaling the group would
risk killing Hyprland itself. Instead this walks the real parent/child
process tree: it climbs from the window's pid to the highest ancestor that
is still the same executable (folding in wrapper/relaunch stages of the same
app, stopping at the first ancestor that is a different program -- so it
never reaches past the app into Hyprland or init), then kills that whole
subtree.
"""

import os
import signal
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dxrice_hypr_ipc import hyprctl_json


def _read_ppid(pid):
    try:
        with open(f"/proc/{pid}/status") as f:
            for line in f:
                if line.startswith("PPid:"):
                    return int(line.split()[1])
    except (FileNotFoundError, ProcessLookupError, ValueError):
        return None
    return None


def _read_exe(pid):
    try:
        return os.readlink(f"/proc/{pid}/exe")
    except (FileNotFoundError, ProcessLookupError, PermissionError):
        return None


def _find_root(pid):
    """Climb ancestors while the parent is the same executable."""
    exe = _read_exe(pid)
    if exe is None:
        return pid
    cur = pid
    while True:
        ppid = _read_ppid(cur)
        if not ppid or ppid == 1:
            break
        if _read_exe(ppid) != exe:
            break
        cur = ppid
    return cur


def _collect_subtree(root):
    """All pids in /proc reachable from root via PPid, root included."""
    children = {}
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        pid = int(entry)
        ppid = _read_ppid(pid)
        if ppid is not None:
            children.setdefault(ppid, []).append(pid)

    subtree = []
    stack = [root]
    while stack:
        pid = stack.pop()
        subtree.append(pid)
        stack.extend(children.get(pid, []))
    return subtree


def main():
    window = hyprctl_json(["activewindow"])
    if not window or not window.get("pid"):
        return
    pid = window["pid"]

    root = _find_root(pid)
    subtree = _collect_subtree(root)

    for p in subtree:
        try:
            os.kill(p, signal.SIGTERM)
        except ProcessLookupError:
            pass

    time.sleep(0.3)

    for p in subtree:
        try:
            os.kill(p, signal.SIGKILL)
        except ProcessLookupError:
            pass


if __name__ == "__main__":
    main()
