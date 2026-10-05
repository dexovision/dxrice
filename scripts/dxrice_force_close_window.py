#!/usr/bin/env python3
"""
dxrice_force_close_window.py
Bound to Super+C. The invariant: SUPER+C closes exactly the currently
FOCUSED WINDOW/TOPLEVEL. It must never mean "kill whatever process owns
this window" -- a second real bug found and fixed here (see ROOT CAUSE
below), on top of the original tray-hide problem this file already
existed to solve.

ORIGINAL PROBLEM this file exists for: a plain Wayland close request
(Hyprland's native closewindow/killactive dispatcher) is only a polite
ASK -- apps like Discord/Steam/Slack intercept it and hide to tray
instead of exiting, so "close" visually does nothing.

ROOT CAUSE of the NEW bug (live-reported): the fix for the tray-hide
problem went straight to PID-based process-tree killing as the ONLY
mechanism, with no attempt at a real per-window close first. hyprctl's
active-window pid identifies a WAYLAND CLIENT CONNECTION (one process),
not a single window -- a browser with two open windows (Brave window A
and window B) runs them both through the SAME process, so climbing to
that process's root and killing its whole subtree (the pre-existing
mechanism below) takes out BOTH windows when the user only asked to
close one. This is a structural mismatch: Hyprland tracks windows and
processes as genuinely different things, and the old code only ever
asked about the process.

THE FIX: Hyprland (via this fork's hl.dsp.window.close) exposes a close
dispatch that targets one TOPLEVEL BY ADDRESS, not a process -- the same
mechanism a native window-manager close button uses, which Wayland's
xdg_toplevel protocol delivers to exactly one surface. This is now
always tried FIRST, address-based, independent of pid. For a normal
multi-window app (the Brave case) this is the whole fix: window A
closes, window B is untouched, because the close event was never
process-scoped to begin with. Falling back to the old process-tree kill
remains necessary ONLY for genuine tray-hide apps that ignore the close
event entirely -- and since that fallback is still PID/process-scoped,
it is now gated on checking hyprctl's OWN client list for any OTHER
window sharing that process subtree first: if one exists, the fallback
refuses to run rather than risk closing a window the user never
targeted. A process-group kill was considered and rejected for that
fallback: apps launched directly by Hyprland (anything that doesn't
self-isolate into a new group, e.g. a plain terminal) inherit Hyprland's
own process group, so signaling the group would risk killing Hyprland
itself. Instead it walks the real parent/child process tree: climbs from
the window's pid to the highest ancestor that is still the same
executable (folding in wrapper/relaunch stages of the same app, stopping
at the first ancestor that is a different program -- so it never reaches
past the app into Hyprland or init), then kills that whole subtree.

LIVE INCIDENT (pre-existing, unchanged by this fix): a settings panel
(Theme/Taskbar/Quick Settings/Calendar) is a focusable Quickshell
surface, so it can be "the active window" the same as any real app --
and every one of those panels belongs to the SAME Quickshell process
that also renders the bars/dock. Force-closing a panel by walking up to
that process's root and killing the whole subtree doesn't close one
panel, it kills the entire shell -- bars, taskbar, everything -- with no
automatic recovery, confirmed live (SUPER+C pressed while editing the
wallpaper in Theme took the whole shell down). Fixed by checking for
this specific case BEFORE ever attempting a close or touching a process
tree: if the root process is Quickshell itself, this asks the shell to
close whatever panel is actually open (the same thing Escape already
does) instead of killing anything.
"""

import os
import signal
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dxrice_hypr_ipc import hyprctl_json, close_window

# How long to give the compositor's per-window close dispatch to actually
# take effect before concluding the app ignored it (tray-hide behavior)
# and falling back to process termination. Short and polled, not a flat
# sleep -- a well-behaved app (the common case, including the Brave
# multi-window case this fix targets) closes in well under this, so
# SUPER+C stays instant for everything except genuine tray-hide apps.
CLOSE_WAIT_TIMEOUT = 0.5
CLOSE_WAIT_POLL = 0.05


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


def _window_is_gone(address):
    clients = hyprctl_json(["clients"]) or []
    return not any(c.get("address") == address for c in clients)


def _wait_for_window_gone(address, timeout=CLOSE_WAIT_TIMEOUT, poll=CLOSE_WAIT_POLL):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _window_is_gone(address):
            return True
        time.sleep(poll)
    return _window_is_gone(address)


def _subtree_owns_another_window(subtree, exclude_address):
    """Does any OTHER Hyprland window (by address) belong to a process in
    this subtree? The only question that must be answered before the
    process-tree kill fallback below is ever allowed to run -- see the
    module docstring's ROOT CAUSE section. `pid` on a hyprctl client is
    the direct process, which may not itself be `root` but IS one of
    root's descendants whenever the window's own process matches or was
    forked from it -- checking subtree membership (not just equality
    with the single resolved pid) is what actually catches the Chromium/
    Electron case, where a window's immediate pid is a renderer, not the
    main process this function climbs to."""
    subtree_set = set(subtree)
    clients = hyprctl_json(["clients"]) or []
    for c in clients:
        if c.get("address") == exclude_address:
            continue
        if c.get("pid") in subtree_set:
            return True
    return False


def main():
    window = hyprctl_json(["activewindow"])
    if not window:
        return
    address = window.get("address")
    pid = window.get("pid")

    # See the module docstring's LIVE INCIDENT note: the active window can
    # be one of this shell's OWN panels, and every panel shares the same
    # process as the bars/dock -- checked here, before any close/kill
    # attempt at all, by the same executable-identity logic the rest of
    # this file already uses.
    if pid:
        root_exe = _read_exe(_find_root(pid))
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

    # PRIMARY path: close exactly the targeted toplevel, by address, via
    # the compositor's own per-window close dispatch -- never process-
    # scoped, so a multi-window app (the Brave window-A/window-B case)
    # only ever loses the one window actually targeted. Tried whenever an
    # address exists at all, independent of whether a pid was resolved --
    # this is also what makes "window whose PID is unavailable" (the
    # test matrix's own case 8) still closable.
    if address:
        close_window(address)
        if _wait_for_window_gone(address):
            return

    # FALLBACK: the app ignored the close request entirely (genuine
    # tray-hide behavior -- Discord/Steam/Slack, the original problem
    # this file was built for). Only reachable once the per-window close
    # has already been given its chance and failed, and only proceeds
    # with a process-tree kill when doing so cannot collaterally close a
    # window the user never targeted.
    if not pid:
        return
    root = _find_root(pid)
    subtree = _collect_subtree(root)
    if _subtree_owns_another_window(subtree, exclude_address=address):
        # A sibling window shares this process tree -- there is no safe
        # way to force this one specific window closed without risking
        # the sibling, so this deliberately does nothing further rather
        # than guess. The per-window close request above has already
        # been sent; if the app is going to honor it late, that stands.
        return

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
