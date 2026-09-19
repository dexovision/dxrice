#!/usr/bin/env python3
"""Shared exclusive-instance guard for this rice's event-driven background
listeners (dxrice_auto_place_window.py, dxrice_infinite_desktop_core.py).

Both are meant to have exactly one live copy per Hyprland session -- two
copies of either would both react to the same events and race over the
result (confirmed live, for the window-placement listener: two copies ran
for ~19 minutes during QA, each placing every new window independently).
Both are started the same way (an `hl.exec_cmd` autostart line that isn't
itself guarded against being run twice), so the guard has to live in the
Python process, not the thing that launches it.

flock, not a written PID file: the kernel releases the lock the instant the
holding process exits for ANY reason (clean exit, crash, SIGKILL, the whole
graphical session ending), so there is no stale-lock case to detect or
clean up, and no window where a crashed-but-not-yet-noticed holder blocks a
legitimate restart.
"""
import fcntl
import os

import dxrice_xdg


def claim_single_instance(name: str):
    """`name` identifies which listener this is (e.g. "auto-place-window",
    "infinite-desktop-core") so two DIFFERENT listeners never contend for
    the same lock file, and the Hyprland instance signature is folded into
    the filename so a second, separate compositor session (a different
    HYPRLAND_INSTANCE_SIGNATURE) always gets its own lock rather than being
    refused by one held under a session that's already gone.

    Returns the held file object on success -- the caller MUST keep a
    reference to it for the process's entire lifetime; letting it be
    garbage-collected closes the fd and silently releases the lock early.
    Returns None if another instance already holds it (the caller should
    then log why and exit cleanly, never proceed).
    """
    sig = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE", "nosig")
    runtime = os.environ.get("XDG_RUNTIME_DIR") or dxrice_xdg.state_dir()
    lock_dir = os.path.join(runtime, "dxrice")
    os.makedirs(lock_dir, exist_ok=True)
    path = os.path.join(lock_dir, f"{name}.{sig}.lock")

    f = open(path, "w")
    try:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.close()
        return None
    f.write(str(os.getpid()))
    f.flush()
    return f
