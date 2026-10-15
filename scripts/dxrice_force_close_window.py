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

TERMINATION (this pass): the fallback kill is now held to the same
standard as the per-window close. Before anything is signalled:
  * the window must still exist under the same address AND the same pid
    (a window that closed late, or whose address now belongs to another
    process, is left alone);
  * the target must be readable and owned by this user, and must not be
    part of the desktop itself (PROTECTED_EXES: the compositor, the shell,
    the session bus, audio, portals, the lock screen, polkit agents...)
    nor an ancestor of this script -- refused with a notification;
  * any protected process found INSIDE the app's tree (a service the user
    started from a terminal, say) is left out of it, with its children.
Every target is pinned with a pidfd (falling back to a start-time check
where pidfds aren't available), so a pid that is recycled mid-operation
can never be signalled. It is asked to exit with SIGTERM and given
TERM_GRACE seconds -- watched through the pidfds, not a fixed sleep --
and only what is still alive then gets SIGKILL. A window that shares its
process with another window is still never force-killed; the user is now
told why instead of SUPER+C silently doing nothing.
"""

import os
import select
import shutil
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

# After SIGTERM, how long an app gets to exit on its own (save state, flush
# files) before whatever is left is SIGKILLed.
TERM_GRACE = 1.5
KILL_WAIT = 1.0

# Executables that are part of the desktop session itself. SUPER+C never
# force-terminates one of these, nor anything running under one inside an
# app's process tree. Quickshell's own panels are handled separately (they
# are closed through the shell's IPC instead).
PROTECTED_EXES = frozenset({
    "Hyprland", "hyprland", "Xwayland", "qs", "quickshell",
    "systemd", "dbus-daemon", "dbus-broker", "dbus-broker-launch",
    "pipewire", "pipewire-pulse", "wireplumber", "pulseaudio",
    "xdg-desktop-portal", "xdg-desktop-portal-hyprland", "xdg-desktop-portal-gtk",
    "hyprlock", "hypridle", "hyprpaper", "swaybg", "waybar", "mako",
    "gnome-keyring-daemon", "kwalletd6", "kwalletd5",
    "polkit-kde-authentication-agent-1", "hyprpolkitagent",
    "polkit-gnome-authentication-agent-1", "polkit-mate-authentication-agent-1",
    "lxpolkit", "lxqt-policykit-agent",
    "sddm", "sddm-helper", "login", "sshd", "Xorg",
})


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


# Executables that run OTHER programs: an interpreter, a shell, a shared
# runtime. Two processes of the same one of these are the same application
# only if they run the same script/module -- a Python app started by
# another Python program, or two apps on the system Electron, share the
# executable and nothing else.
_RUNTIME_PREFIXES = ("python", "pypy", "node", "nodejs", "deno", "bun", "java", "perl", "ruby", "php", "lua",
                     "gjs", "electron", "mono", "dotnet", "wine", "bash", "sh", "dash", "zsh", "fish", "bwrap")


def _is_runtime(exe):
    base = os.path.basename(exe or "")
    return any(base == p or base.startswith(p) and not base[len(p):].isalpha() for p in _RUNTIME_PREFIXES)


def _read_cmdline(pid):
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            return [a.decode(errors="replace") for a in f.read().split(b"\0") if a]
    except OSError:
        return None


def _program_of(pid):
    """What a runtime process runs: its first non-option argument (a
    script, an app directory, a jar), or the module after -m / -jar;
    None when it can't be read."""
    args = _read_cmdline(pid)
    if not args:
        return None
    rest = args[1:]
    for i, a in enumerate(rest):
        if a in ("-m", "-jar", "-c") and i + 1 < len(rest):
            return a + " " + rest[i + 1]
        if not a.startswith("-"):
            return a
    return ""


def _find_root(pid):
    """Climb ancestors while the parent is the same program: the same
    executable (folding in an app's own wrapper/relaunch stages) -- and,
    for an interpreter or shared runtime (_is_runtime), the same script or
    module too, so a Python app started by another Python program never
    takes its launcher (and the launcher's other children) with it."""
    exe = _read_exe(pid)
    if exe is None:
        return pid
    runtime = _is_runtime(exe)
    program = _program_of(pid) if runtime else None
    cur = pid
    while True:
        ppid = _read_ppid(cur)
        if not ppid or ppid == 1:
            break
        if _read_exe(ppid) != exe:
            break
        if runtime and (program is None or _program_of(ppid) != program):
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


def _read_starttime(pid):
    """Process start time (clock ticks since boot): together with the pid it
    identifies one process, so a recycled pid shows up as a different
    start time."""
    try:
        with open(f"/proc/{pid}/stat") as f:
            stat = f.read()
        # The command name (field 2) may itself contain spaces or ')'.
        return int(stat[stat.rindex(")") + 2:].split()[19])
    except (OSError, ValueError, IndexError):
        return None


def _owner_uid(pid):
    try:
        return os.stat(f"/proc/{pid}").st_uid
    except OSError:
        return None


def _own_ancestors():
    """This script and every process above it (Hyprland, which ran it)."""
    out, cur = set(), os.getpid()
    while cur and cur not in out:
        out.add(cur)
        cur = _read_ppid(cur)
    return out


def _protection_reason(pid):
    """Why `pid` must not be force-terminated, or None if it may be."""
    if not pid or pid <= 1:
        return "not a real process"
    exe = _read_exe(pid)
    if exe is None or _read_starttime(pid) is None:
        return "its process can't be inspected"
    if _owner_uid(pid) != os.getuid():
        return "it belongs to another user"
    if os.path.basename(exe) in PROTECTED_EXES:
        return f"{os.path.basename(exe)} is part of the desktop itself"
    if pid in _own_ancestors():
        return "it is part of the desktop itself"
    return None


def _notify(summary, body):
    if shutil.which("notify-send"):
        try:
            subprocess.run(["notify-send", "-a", "DXrice", summary, body], timeout=2,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except (OSError, subprocess.TimeoutExpired):
            pass


def _kill_targets(subtree, root):
    """The processes to terminate, as (pid, starttime): the subtree minus
    anything protected (a service started from a terminal inside the app,
    say) and everything below such a process."""
    members = set(subtree)
    excluded = {p for p in subtree if p != root and _protection_reason(p) is not None}
    targets = []
    for p in subtree:
        cur, skip, seen = p, False, set()
        while cur in members and cur not in seen:
            if cur in excluded:
                skip = True
                break
            seen.add(cur)
            if cur == root:
                break
            cur = _read_ppid(cur)
        if skip:
            continue
        start = _read_starttime(p)
        if start is not None:
            targets.append((p, start))
    return targets


class _Pinned:
    """One process, held so that signalling it can never reach a different
    process that later reuses its pid: a pidfd where the kernel offers one,
    otherwise a start-time check immediately before each signal."""

    def __init__(self, pid, starttime):
        self.pid, self.starttime, self.fd = pid, starttime, None
        try:
            self.fd = os.pidfd_open(pid)
        except (AttributeError, OSError):
            self.fd = None
        # Opened after the snapshot: confirm it is still the same process.
        if _read_starttime(pid) != starttime:
            self.close()
            self.valid = False
        else:
            self.valid = True

    def signal(self, sig):
        try:
            if self.fd is not None:
                signal.pidfd_send_signal(self.fd, sig)
            elif _read_starttime(self.pid) == self.starttime:
                os.kill(self.pid, sig)
        except (ProcessLookupError, OSError):
            pass

    def alive(self):
        if self.fd is not None:
            p = select.poll()
            p.register(self.fd, select.POLLIN)
            return not p.poll(0)
        return _read_starttime(self.pid) == self.starttime

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None


def _wait_exit(pinned, timeout):
    deadline = time.monotonic() + timeout
    while True:
        alive = [p for p in pinned if p.alive()]
        if not alive or time.monotonic() >= deadline:
            return alive
        time.sleep(0.02)


def _terminate(targets):
    """SIGTERM, a grace period, then SIGKILL for what is still running."""
    pinned = [p for p in (_Pinned(pid, start) for pid, start in targets) if p.valid]
    try:
        for p in pinned:
            p.signal(signal.SIGTERM)
        survivors = _wait_exit(pinned, TERM_GRACE)
        for p in survivors:
            p.signal(signal.SIGKILL)
        _wait_exit(survivors, KILL_WAIT)
    finally:
        for p in pinned:
            p.close()


def _client(address):
    for c in hyprctl_json(["clients"]) or []:
        if c.get("address") == address:
            return c
    return None


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
    return _windows_sharing(subtree, exclude_address) > 0


def _windows_sharing(subtree, exclude_address):
    """How many OTHER windows belong to a process in this subtree."""
    subtree_set = set(subtree)
    return sum(1 for c in hyprctl_json(["clients"]) or []
               if c.get("address") != exclude_address and c.get("pid") in subtree_set)


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
    # Still the same window, still the same process? A window that closed
    # late needs nothing more; an address that now reports another pid
    # means the target can no longer be trusted.
    current = _client(address) if address else None
    if current is None or current.get("pid") != pid:
        return
    root = _find_root(pid)
    reason = _protection_reason(pid) or _protection_reason(root)
    if reason:
        _notify("SUPER+C: not force-quitting", f"The window ignored the close request, but {reason}.")
        return
    subtree = _collect_subtree(root)
    others = _windows_sharing(subtree, exclude_address=address)
    if others:
        # A sibling window shares this process tree -- there is no safe
        # way to force this one specific window closed without risking
        # the sibling, so this deliberately does nothing further rather
        # than guess. The per-window close request above has already
        # been sent; if the app is going to honor it late, that stands.
        _notify("SUPER+C: not force-quitting",
                f"This window ignored the close request, and its process also runs {others} other "
                f"window{'s' if others != 1 else ''}, which force-quitting would close too. "
                "Quit it from the app, or close its other windows first.")
        return

    targets = _kill_targets(subtree, root)
    # Last check, after every target is identified: the window must still
    # be the one that was asked to close.
    current = _client(address)
    if current is None or current.get("pid") != pid:
        return
    _terminate(targets)


if __name__ == "__main__":
    main()
