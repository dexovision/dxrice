#!/usr/bin/env python3
"""Talks to Hyprland's own command socket directly instead of spawning the
`hyprctl` binary for every call.

Measured on this machine: a `hyprctl` subprocess call costs ~5ms (fork+exec+
dynamic-link startup for a whole new process); the equivalent raw socket
connect+write+read costs ~0.04ms -- over 100x cheaper. That gap matters here
specifically because dxrice_infinite_desktop_core.py's pan/drag loops issue
one of these on every animation frame (up to ~144/sec, matching this
machine's actual monitor refresh rate) -- at that rate, subprocess-spawn
overhead alone was competing for real CPU/scheduling time and was a
concrete, measured contributor to the "pan doesn't feel smooth" complaint
this module exists to fix, not just a style preference for avoiding
subprocess.

Protocol (Hyprland's own documented socket IPC, unrelated to this fork's
Lua config layer -- the wire format is the same regardless of what config
language built the running compositor): connect to
$XDG_RUNTIME_DIR/hypr/$HYPRLAND_INSTANCE_SIGNATURE/.socket.sock, write the
same text you'd pass to `hyprctl` (minus the word hyprctl itself -- `j/`
prefix for a JSON query instead of a trailing `-j`, `[[BATCH]]` prefix
joining `;`-separated `dispatch ...` commands instead of `--batch`), read
the reply, close.
"""
import json
import os
import socket


def _socket_path():
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    sig = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
    if not runtime or not sig:
        return None
    return os.path.join(runtime, "hypr", sig, ".socket.sock")


def _send(cmd, timeout=2, want_reply=True):
    path = _socket_path()
    if not path:
        return b""
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    except OSError:
        # e.g. file-descriptor exhaustion -- every caller of every function
        # in this module already wraps its own call in a broad try/except
        # (this is invoked up to ~144 times/sec from the pan/drag loops),
        # but this function's own job is "never raise, return b'' on any
        # failure" -- the socket() call itself was the one line that could
        # still escape that contract.
        return b""
    s.settimeout(timeout)
    try:
        s.connect(path)
        s.sendall(cmd.encode())
        if not want_reply:
            return b""
        chunks = []
        try:
            while True:
                chunk = s.recv(65536)
                if not chunk:
                    break
                chunks.append(chunk)
        except socket.timeout:
            pass
        return b"".join(chunks)
    except OSError:
        return b""
    finally:
        s.close()


def hyprctl_json(args, timeout=2):
    resp = _send("j/" + args[0], timeout=timeout)
    try:
        return json.loads(resp) if resp.strip() else None
    except json.JSONDecodeError:
        return None


def dispatch(lua_expr, timeout=2):
    return _send("dispatch " + lua_expr, timeout=timeout)


def dispatch_async(lua_expr):
    # Fire-and-forget: still a real socket write (Hyprland gets the full
    # command either way), just never waits to read the reply back.
    _send("dispatch " + lua_expr, want_reply=False)


def batch(lua_exprs, timeout=5):
    cmd = "[[BATCH]]" + " ; ".join(f"dispatch {e}" for e in lua_exprs)
    return _send(cmd, timeout=timeout)


def batch_async(lua_exprs):
    if not lua_exprs:
        return
    cmd = "[[BATCH]]" + " ; ".join(f"dispatch {e}" for e in lua_exprs)
    _send(cmd, want_reply=False)


def toggle_floating_lua(address=None):
    w = f', window = "address:{address}"' if address else ""
    return f'hl.dsp.window.float({{ action = "toggle"{w} }})'

def toggle_floating(address=None):
    return dispatch(toggle_floating_lua(address))


def close_window_lua(address):
    # The compositor's own per-TOPLEVEL close dispatch (hl.dsp.window.close,
    # Hyprland's native closewindow-equivalent) -- sends the xdg_toplevel
    # close request to exactly the targeted surface, same as clicking that
    # window's own close button. Critically NOT pid/process-based: a
    # multi-window single-process app (two Brave windows, one browser
    # process) only loses the targeted window, because Wayland delivers the
    # close event to one specific toplevel object, never to "the process."
    # See dxrice_force_close_window.py for why this exists as the PRIMARY
    # close mechanism there, with process termination only as a last resort.
    return f'hl.dsp.window.close({{ window = "address:{address}" }})'

def close_window(address, timeout=2):
    return dispatch(close_window_lua(address), timeout=timeout)


def focus_window_lua(address):
    return f'hl.dsp.focus({{ window = "address:{address}" }})'

def focus_window(address):
    return dispatch(focus_window_lua(address))


def move_focus_lua(direction_lud):
    return f'hl.dsp.focus({{ direction = "{direction_lud}" }})'

def move_focus(direction_lud):
    return dispatch(move_focus_lua(direction_lud))


def move_window_tiled_lua(direction_lud):
    return f'hl.dsp.window.move({{ direction = "{direction_lud}" }})'

def move_window_tiled(direction_lud):
    return dispatch(move_window_tiled_lua(direction_lud))


def exec_cmd_lua(cmd):
    escaped = cmd.replace('\\', '\\\\').replace('"', '\\"')
    return f'hl.dsp.exec_cmd("{escaped}")'


def move_window_exact_lua(x, y, address):
    return (f'hl.dsp.window.move({{ window = "address:{address}", '
            f'x = {int(x)}, y = {int(y)}, relative = false }})')

def move_window_exact(x, y, address, timeout=2):
    return dispatch(move_window_exact_lua(x, y, address), timeout=timeout)

def move_window_exact_async(x, y, address):
    dispatch_async(move_window_exact_lua(x, y, address))


def resize_window_exact_lua(w, h, address):
    return (f'hl.dsp.window.resize({{ window = "address:{address}", '
            f'x = {int(w)}, y = {int(h)}, relative = false }})')

def resize_window_exact(w, h, address, timeout=2):
    return dispatch(resize_window_exact_lua(w, h, address), timeout=timeout)
