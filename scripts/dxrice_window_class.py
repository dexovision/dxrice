#!/usr/bin/env python3
"""Which windows new-window placement and SUPER+G may treat as application
windows -- and which are transient surfaces (tooltips, menus, hover cards,
drag icons) that must never be placed, never count as part of the layout,
and never make anything else move.

Why this needs X11 at all: Hyprland reports an XWayland override-redirect
window -- the kind X11 toolkits use for a tooltip, a context menu, or the
hover card a browser shows when the pointer rests on a link or a tab --
through exactly the same `openwindow>>` event and the same `hyprctl
clients` fields as a real application window. Verified on a nested
Hyprland 0.56.2: a GTK override-redirect popup and that app's main window
differ in nothing but geometry (both floating, both "xwayland": true, both
focusable, both tagged by a class=".*" window rule). So hovering a link in
an XWayland app opened a "window", and placement moved it -- and, before
placement stopped moving existing windows, could shove the windows around
it aside to make room for a tooltip.

The X server does know: override_redirect is a window attribute, and
managed windows carry _NET_WM_WINDOW_TYPE and WM_TRANSIENT_FOR. Hyprland
does not reparent XWayland windows, so each client is a direct child of the
root whose geometry equals what `hyprctl clients` reports (verified: same
x/y/width/height to the pixel at scale 1). That geometry is the join key.

Native Wayland surfaces need no lookup: a tooltip or menu with a parent is
an xdg_popup, which Hyprland never reports as a window (verified -- no
`openwindow>>` at all).

libX11 through ctypes rather than python-xlib: the installer does not ship
python-xlib, while libX11 is present wherever XWayland runs. One short-lived
connection per query, closed again, with an error handler installed so a
window that disappears mid-query can't make Xlib exit the process. When X is
unreachable (no DISPLAY, no libX11, XWayland disabled) every lookup returns
UNKNOWN and callers fall back to the Hyprland-side rules only.
"""
import ctypes
import ctypes.util
import os

# What a classification can say about one client.
NORMAL = "normal"            # an application window: place it, lay it out
TRANSIENT = "transient"      # tooltip/menu/popup/drag icon: leave it entirely alone
DIALOG = "dialog"            # a managed dialog/utility window (may have a parent)
SPLASH = "splash"            # an app's splash screen: centred by the app, gone soon
UNKNOWN = "unknown"          # XWayland window the X server couldn't be asked about
SHELL = "shell"              # DXrice's own Quickshell dialogs (the Wi-Fi password prompt)

# Quickshell's FloatingWindow maps as an ordinary toplevel with this app-id
# (verified on the nested compositor). It is shell UI the user summoned from
# a panel, not an application window: it stays where the shell puts it and
# is no part of the composition.
SHELL_CLASSES = {"org.quickshell"}

# _NET_WM_WINDOW_TYPE values that mean "not a window the user arranges".
_TRANSIENT_TYPES = {
    "_NET_WM_WINDOW_TYPE_TOOLTIP", "_NET_WM_WINDOW_TYPE_MENU", "_NET_WM_WINDOW_TYPE_DROPDOWN_MENU",
    "_NET_WM_WINDOW_TYPE_POPUP_MENU", "_NET_WM_WINDOW_TYPE_COMBO", "_NET_WM_WINDOW_TYPE_NOTIFICATION",
    "_NET_WM_WINDOW_TYPE_DND", "_NET_WM_WINDOW_TYPE_DOCK", "_NET_WM_WINDOW_TYPE_DESKTOP",
}
_DIALOG_TYPES = {"_NET_WM_WINDOW_TYPE_DIALOG", "_NET_WM_WINDOW_TYPE_UTILITY", "_NET_WM_WINDOW_TYPE_TOOLBAR"}

# Smaller than this on either axis is never an application window anyone
# arranges (a 1x1 input-method or clipboard helper toplevel, a resize
# handle) -- placing it is all cost and no benefit.
MIN_WINDOW_SIDE = 24


class _XWindowAttributes(ctypes.Structure):
    _fields_ = [("x", ctypes.c_int), ("y", ctypes.c_int), ("width", ctypes.c_int), ("height", ctypes.c_int),
                ("border_width", ctypes.c_int), ("depth", ctypes.c_int), ("visual", ctypes.c_void_p),
                ("root", ctypes.c_ulong), ("class_", ctypes.c_int), ("bit_gravity", ctypes.c_int),
                ("win_gravity", ctypes.c_int), ("backing_store", ctypes.c_int),
                ("backing_planes", ctypes.c_ulong), ("backing_pixel", ctypes.c_ulong),
                ("save_under", ctypes.c_int), ("colormap", ctypes.c_ulong), ("map_installed", ctypes.c_int),
                ("map_state", ctypes.c_int), ("all_event_masks", ctypes.c_long),
                ("your_event_mask", ctypes.c_long), ("do_not_propagate_mask", ctypes.c_long),
                ("override_redirect", ctypes.c_int), ("screen", ctypes.c_void_p)]


_IS_VIEWABLE = 2
_XA_ATOM = 4
_ERROR_HANDLER_T = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)
_libx11 = None
_error_handler = None  # kept referenced: Xlib holds a raw pointer to it


def _load():
    global _libx11, _error_handler
    if _libx11 is not None:
        return _libx11 or None
    try:
        name = ctypes.util.find_library("X11") or "libX11.so.6"
        lib = ctypes.CDLL(name)
        lib.XOpenDisplay.restype = ctypes.c_void_p
        lib.XOpenDisplay.argtypes = [ctypes.c_char_p]
        lib.XCloseDisplay.argtypes = [ctypes.c_void_p]
        lib.XDefaultRootWindow.restype = ctypes.c_ulong
        lib.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
        lib.XQueryTree.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong),
                                   ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.POINTER(ctypes.c_ulong)),
                                   ctypes.POINTER(ctypes.c_uint)]
        lib.XGetWindowAttributes.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(_XWindowAttributes)]
        lib.XInternAtom.restype = ctypes.c_ulong
        lib.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
        lib.XGetAtomName.restype = ctypes.c_void_p
        lib.XGetAtomName.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        lib.XGetWindowProperty.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_long,
                                           ctypes.c_long, ctypes.c_int, ctypes.c_ulong,
                                           ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_int),
                                           ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_ulong),
                                           ctypes.POINTER(ctypes.c_void_p)]
        lib.XGetTransientForHint.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong)]
        lib.XFree.argtypes = [ctypes.c_void_p]
        lib.XSetErrorHandler.restype = ctypes.c_void_p
        lib.XSetErrorHandler.argtypes = [_ERROR_HANDLER_T]
        # The default handler prints and exit()s on BadWindow -- which is
        # exactly what a tooltip closing between XQueryTree and
        # XGetWindowAttributes produces.
        _error_handler = _ERROR_HANDLER_T(lambda _d, _e: 0)
        lib.XSetErrorHandler(_error_handler)
        _libx11 = lib
    except (OSError, AttributeError):
        _libx11 = False
        return None
    return _libx11


def _window_types(lib, dpy, win, atom_type):
    actual_type, actual_format = ctypes.c_ulong(), ctypes.c_int()
    nitems, after, data = ctypes.c_ulong(), ctypes.c_ulong(), ctypes.c_void_p()
    if lib.XGetWindowProperty(dpy, win, atom_type, 0, 32, 0, _XA_ATOM, ctypes.byref(actual_type),
                              ctypes.byref(actual_format), ctypes.byref(nitems), ctypes.byref(after),
                              ctypes.byref(data)) != 0 or not data.value:
        return set()
    try:
        if actual_format.value != 32:
            return set()
        atoms = ctypes.cast(data, ctypes.POINTER(ctypes.c_ulong))
        names = set()
        for i in range(nitems.value):
            p = lib.XGetAtomName(dpy, atoms[i])
            if p:
                names.add(ctypes.string_at(p).decode(errors="replace"))
                lib.XFree(p)
        return names
    finally:
        lib.XFree(data)


def x11_windows(display=None):
    """Every viewable top-level XWayland window:
    [{"geometry": (x, y, w, h), "override_redirect": bool, "types": {...},
      "transient_for": (x, y, w, h) | None}, ...], or None when the X server
    can't be reached."""
    lib = _load()
    display = display if display is not None else os.environ.get("DISPLAY")
    if lib is None or not display:
        return None
    dpy = lib.XOpenDisplay(display.encode())
    if not dpy:
        return None
    try:
        root = lib.XDefaultRootWindow(dpy)
        root_ret, parent_ret = ctypes.c_ulong(), ctypes.c_ulong()
        children, n = ctypes.POINTER(ctypes.c_ulong)(), ctypes.c_uint()
        if not lib.XQueryTree(dpy, root, ctypes.byref(root_ret), ctypes.byref(parent_ret),
                              ctypes.byref(children), ctypes.byref(n)):
            return None
        wins = [children[i] for i in range(n.value)]
        if children:
            lib.XFree(children)
        atom_type = lib.XInternAtom(dpy, b"_NET_WM_WINDOW_TYPE", 0)
        geom, out = {}, []
        for w in wins:
            attrs = _XWindowAttributes()
            if not lib.XGetWindowAttributes(dpy, w, ctypes.byref(attrs)):
                continue  # gone since XQueryTree
            geom[w] = (attrs.x, attrs.y, attrs.width, attrs.height)
            if attrs.map_state != _IS_VIEWABLE:
                continue
            entry = {"geometry": geom[w], "override_redirect": bool(attrs.override_redirect),
                     "types": set(), "_transient_for": 0}
            if not attrs.override_redirect:
                entry["types"] = _window_types(lib, dpy, w, atom_type)
                parent = ctypes.c_ulong()
                if lib.XGetTransientForHint(dpy, w, ctypes.byref(parent)) and parent.value not in (0, root):
                    entry["_transient_for"] = parent.value
            out.append(entry)
        for e in out:
            e["transient_for"] = geom.get(e.pop("_transient_for"))
        return out
    finally:
        lib.XCloseDisplay(dpy)


def _geometry(client):
    at, size = client.get("at") or (0, 0), client.get("size") or (0, 0)
    return (int(at[0]), int(at[1]), int(size[0]), int(size[1]))


def classify(client, x11=None):
    """NORMAL / TRANSIENT / DIALOG / SPLASH / UNKNOWN for one `hyprctl
    clients` entry. `x11` is x11_windows()'s result (None = unreachable)."""
    w, h = _geometry(client)[2:]
    if w < MIN_WINDOW_SIDE or h < MIN_WINDOW_SIDE:
        return TRANSIENT
    if (client.get("class") or client.get("initialClass") or "") in SHELL_CLASSES:
        return SHELL
    if not client.get("xwayland"):
        return NORMAL
    if x11 is None:
        return UNKNOWN
    matches = [e for e in x11 if e["geometry"] == _geometry(client)]
    if not matches:
        return UNKNOWN
    # Two X windows with identical geometry are vanishingly rare; if one of
    # them is a popup, err on the side of not moving anything.
    if any(e["override_redirect"] or e["types"] & _TRANSIENT_TYPES for e in matches):
        return TRANSIENT
    if any("_NET_WM_WINDOW_TYPE_SPLASH" in e["types"] for e in matches):
        return SPLASH
    if any(e["types"] & _DIALOG_TYPES or e["transient_for"] for e in matches):
        return DIALOG
    return NORMAL


def x11_parent_geometry(client, x11):
    """The WM_TRANSIENT_FOR parent's geometry for an XWayland dialog, if the
    X server says it has one."""
    if not x11 or not client.get("xwayland"):
        return None
    for e in x11:
        if e["geometry"] == _geometry(client) and e["transient_for"]:
            return e["transient_for"]
    return None


def classify_all(clients, display=None, x11_query=None):
    """{address: kind} for every client, asking the X server at most once
    (and not at all when no client is an XWayland one)."""
    x11 = None
    if any(c.get("xwayland") for c in clients):
        x11 = (x11_query or x11_windows)(display)
    return {c.get("address"): classify(c, x11) for c in clients}, x11


def is_arrangeable(kind):
    """May this window be placed by new-window placement / laid out by
    SUPER+G / count as part of the composition?"""
    return kind in (NORMAL, DIALOG, UNKNOWN)


def partition(clients, workspace_id, kinds, exclude=None):
    """Split one workspace's windows into (eligible, fixed) the way both
    placers see them. Eligible: ordinary floating windows -- the
    composition. Fixed: fullscreen/maximized and pinned windows -- never
    moved, but nothing may overlap them. Transient surfaces, splash screens,
    shell dialogs, hidden and unmapped windows are in neither: they are not
    furniture anyone arranges around (a tooltip that happens to be open
    when SUPER+G is pressed must not shape the result)."""
    eligible, fixed = [], []
    for c in clients:
        if c.get("address") == exclude or not c.get("floating"):
            continue
        if (c.get("workspace") or {}).get("id") != workspace_id:
            continue
        if c.get("hidden") or c.get("mapped") is False:
            continue
        if not is_arrangeable(kinds.get(c.get("address"), NORMAL)):
            continue
        (fixed if c.get("fullscreen") or c.get("pinned") else eligible).append(c)
    return eligible, fixed


if __name__ == "__main__":  # diagnostic: what the X server says right now
    import json
    print(json.dumps(x11_windows(), default=sorted, indent=1))
