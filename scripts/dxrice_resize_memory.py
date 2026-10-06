"""Shared memory of the sizes DXrice itself gave windows.

Both automatic resizers -- SUPER+G (dxrice_auto_arrange.py) and new-window
auto-placement's Stage 3 (dxrice_auto_place_window.py) -- are pure functions
of the windows' CURRENT geometry. On their own neither can tell "a window the
user made this size" from "a window DXrice already shrank", so their
per-decision guarantees (each window resized at most once, never past
MAX_SHRINK_FRACTION of its original size) silently reset on every press or
every new window. This is the missing memory: the size DXrice last GAVE each
window, keyed by Hyprland address. A window still at exactly that size is
resize-locked for BOTH resizers (it may move, never re-shrink). The moment
its size differs -- the user resized it -- the entry is dropped and the
user's own size is the new baseline, exactly as if DXrice had never touched
it.

Lives in $XDG_RUNTIME_DIR (per-login, tmpfs), so it can never outlive the
Hyprland session whose addresses it names. Writers use an atomic rename; two
writers racing (a SUPER+G press while a window opens) can at worst drop the
other's newest entry, which only costs that one lock, never correctness.
"""
import json
import os
import sys

RESIZE_STATE_SIZE_TOLERANCE = 1.0


def resize_state_path():
    base = os.environ.get("XDG_RUNTIME_DIR") or f"/tmp/dxrice-{os.getuid()}"
    return os.path.join(base, "dxrice", "resize_memory.json")


def load_resize_state(path):
    """{address: (w, h)}; an unreadable/corrupt/missing file is simply "no
    memory" -- a resize decision must never fail because of its own bookkeeping."""
    try:
        with open(path) as f:
            raw = json.load(f)
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    state = {}
    for addr, size in raw.items():
        if (isinstance(addr, str) and isinstance(size, list) and len(size) == 2
                and all(isinstance(v, (int, float)) for v in size)):
            state[addr] = (size[0], size[1])
    return state


def size_matches(a, b, tol=RESIZE_STATE_SIZE_TOLERANCE):
    return abs(a[0] - b[0]) <= tol and abs(a[1] - b[1]) <= tol


def locked_addresses(state, eligible):
    """The windows in `eligible` still at the exact size DXrice last gave
    them -- auto_arrange's resize_locked, and try_resize_room's."""
    return frozenset(w["address"] for w in eligible
                     if w["address"] in state and size_matches(tuple(w["size"]), state[w["address"]]))


def next_resize_state(state, alive_addrs, current_sizes, resized_now):
    """The state to persist after this decision.

    current_sizes: {address: (w, h)} for every window this decision SAW, at
    the size it ends with. resized_now: addresses this decision resized.
    An entry survives only while its window exists and, if this press saw
    it, is still at the recorded size; windows on other workspaces (alive
    but unseen) keep their entry until a press that can see them decides."""
    nxt = {}
    for addr, size in state.items():
        if addr not in alive_addrs:
            continue
        if addr in current_sizes and not size_matches(current_sizes[addr], size):
            continue
        nxt[addr] = size
    for addr in resized_now:
        if addr in current_sizes:
            nxt[addr] = tuple(current_sizes[addr])
    return nxt


def save_resize_state(path, state):
    """Atomic (temp file + rename in the same directory) so a crash or a
    concurrent press can never leave a half-written file; failure to save
    only costs the memory, never the arrangement that was just dispatched."""
    try:
        os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
        tmp = f"{path}.{os.getpid()}.tmp"
        with open(tmp, "w") as f:
            json.dump({a: [int(round(w)), int(round(h))] for a, (w, h) in state.items()}, f)
        os.replace(tmp, path)
    except OSError as e:
        print(f"Could not save DXrice resize memory ({e}); continuing.", file=sys.stderr)
