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

LIVE INCIDENT: a settings panel (Theme/Taskbar/Quick Settings/Calendar) is
a focusable Quickshell surface, so it can be "the active window" the same
as any real app -- and every one of those panels belongs to the SAME
Quickshell process that also renders the bars/dock. Force-closing a panel
by walking up to that process's root and killing the whole subtree doesn't
close one panel, it kills the entire shell -- bars, taskbar, everything --
with no automatic recovery, confirmed live (SUPER+C pressed while editing
the wallpaper in Theme took the whole shell down). Fixed by checking for
this specific case BEFORE ever touching a process tree: if the root
process is Quickshell itself, this asks the shell to close whatever panel
is actually open (the same thing Escape already does) instead of killing
anything -- which is also just the correct behavior for "close what I'm
looking at" here, not merely a guard against the crash.
"""

import os
import signal
import subprocess
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


def _quickshell_repo_dir():
    state_path = os.path.expanduser("~/.local/state/dxrice/repo_path")
    try:
        with open(state_path) as f:
            repo = f.read().strip()
            if repo:
                return repo
    except OSError:
        pass
    return os.path.expanduser("~/dxrice")


def main():
    window = hyprctl_json(["activewindow"])
    if not window or not window.get("pid"):
        return
    pid = window["pid"]

    root = _find_root(pid)

    # See the module docstring's LIVE INCIDENT note: the active window can
    # be one of this shell's OWN panels, and every panel shares the same
    # process as the bars/dock -- checked here, before any kill, by the
    # same executable-identity logic the rest of this file already uses.
    root_exe = _read_exe(root)
    if root_exe is not None and os.path.basename(root_exe) == "qs":
        repo = _quickshell_repo_dir()
        try:
            subprocess.run(
                ["qs", "-p", f"{repo}/quickshell/shell.qml", "ipc", "call", "shell", "closeCurrent"],
                timeout=2, capture_output=True,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass
        return

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
