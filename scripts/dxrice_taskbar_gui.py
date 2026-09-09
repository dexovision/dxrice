#!/usr/bin/env python3
"""GTK4/Adwaita app for managing DXrice's waybar taskbar shortcuts.

Replaces the old kitty-terminal menu (dxrice-manage-taskbar.sh) with a
native settings window, matching dxrice_theme_gui.py. Edits
~/.config/waybar/config directly (mirrored back into <repo>/waybar/config
so the change survives an `install.sh update`) and restarts waybar.

Shares the same .dx-* CSS design system (theme/dxrice_gtk_style.css.template)
as dxrice_theme_gui.py and dxrice_quick_settings.py, loaded from
~/.config/dxrice/gtk_style.css, and the same widget helpers
(dxrice_gtk_widgets.py), so this app looks and behaves like part of the
same rice instead of a separate stock-Adwaita tool.

Each shortcut carries its own dxrice_label/dxrice_cmd/dxrice_icon_mode
metadata (extra keys waybar itself ignores) so it can be edited later
without having to reverse-engineer waybar's on-click/tooltip-format
fields. icon_mode is one of:
  - "auto":  follow the global "Show icons" switch (glyph or plain text)
  - "text":  always plain text, regardless of the global switch
  - "image": a user-picked picture, rendered as a real waybar `image#`
             module (waybar's `custom` modules can't show images)
Shortcuts from before this metadata existed (or added by hand) are
transparently migrated to "auto" the first time this GUI loads them.
"""
import glob
import json
import os
import re
import shutil
import subprocess
import sys

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dxrice_icons import icon_for
from dxrice_gtk_widgets import (
    label as _label, load_css, make_card, make_row, make_section_title, make_segmented,
)
import dxrice_apply_theme as apply_theme

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(SCRIPTS_DIR)
HOME = os.path.expanduser("~")
CONFIG_PATH = os.path.join(HOME, ".config", "waybar", "config")
ICONS_DIR = os.path.join(HOME, ".config", "waybar", "icons")
CSS_PATH = os.path.join(HOME, ".config", "dxrice", "gtk_style.css")
DEFAULT_ICON_SIZE = 24


def _anim_ms():
    """Reads the user's animation-speed preference straight from the live
    theme.json (edited by the Theme app; seeded on first use from the
    repo's default -- see dxrice_apply_theme.ensure_live_theme) so Revealer
    expand/collapse here matches the rest of the rice instead of a
    hardcoded constant."""
    try:
        with open(apply_theme.ensure_live_theme()) as f:
            return json.load(f).get("anim_duration_ms", 150)
    except (OSError, json.JSONDecodeError):
        return 150


ANIM_MS = _anim_ms()

LAUNCHER_ID = "custom/launcher"
ICON_MODES = ["auto", "text", "image"]
ICON_MODE_LABELS = ["Automatic icon", "Text label", "Custom image"]

# Mic mute now lives in the Quick Settings panel (dxrice_quick_settings.py)
# -- a real mute toggle with live state, not a plain waybar text button.
# Removed here since a standalone taskbar shortcut for it was redundant
# and didn't belong in "manage app shortcuts" conceptually.
_LEGACY_MIC_MUTE_MODID = "custom/micmute"

SYSTEM_MODULE_LABELS = {
    "clock": "Clock",
    "pulseaudio": "Volume",
    "network": "Network",
    "cpu": "CPU",
    "memory": "Memory",
}


# ---------------------------------------------------------------------------
# Config I/O
# ---------------------------------------------------------------------------

def atomic_write_json(path, data):
    """Same pattern as dxrice_theme_gui: temp file + os.replace so a crash
    mid-write can never leave a truncated, unparseable config on disk."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = f"{path}.tmp{os.getpid()}"
    try:
        with open(tmp_path, "w") as f:
            json.dump(data, f, indent=4)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise


def load_config():
    with open(CONFIG_PATH) as f:
        cfg = json.load(f)
    normalize_legacy_shortcuts(cfg)
    cleanup_legacy_mic_mute(cfg)
    return cfg


def save_config(cfg):
    # Deliberately does NOT also write <repo>/waybar/config: your own
    # shortcuts are yours, kept only in the live config, never synced into
    # the tracked repo file. That used to be the plan ("survives an
    # install.sh update"), but it meant every personal shortcut you added
    # showed up as an uncommitted change in your own checkout, and for
    # anyone syncing that repo copy to GitHub, permanently marked the live
    # file "hand-edited" the moment they used this GUI even once -- exactly
    # the bug that got someone stuck on an old waybar/config structure.
    #
    # No manifest bookkeeping needed either: dxrice_deploy.py now treats
    # waybar/config like hyprland.lua -- copied in once on a fresh install,
    # then never auto-overwritten again, regardless of hash. That's what
    # actually makes your shortcuts survive an update, not a hash match.
    atomic_write_json(CONFIG_PATH, cfg)


def restart_waybar():
    subprocess.run(["pkill", "-x", "waybar"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def relaunch():
        subprocess.Popen(["setsid", "waybar"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                          stdin=subprocess.DEVNULL, start_new_session=True)
        return False

    GLib.timeout_add(300, relaunch)


# ---------------------------------------------------------------------------
# Shortcut data model (modules-left)
# ---------------------------------------------------------------------------

def slugify(label):
    slug = re.sub(r"[^a-zA-Z0-9]", "", label).lower()
    return slug or f"app{int(GLib.get_monotonic_time())}"


def modid_for(label, mode):
    prefix = "image#" if mode == "image" else "custom/"
    return f"{prefix}{slugify(label)}"


def _unique_modid(cfg, modid, exclude=None):
    if modid not in cfg or modid == exclude:
        return modid
    i = 2
    while f"{modid}{i}" in cfg and f"{modid}{i}" != exclude:
        i += 1
    return f"{modid}{i}"


def _unwrap_shell_cmd(on_click):
    m = re.match(r"^sh -c '(.*) >/dev/null 2>&1 &'$", on_click or "")
    return m.group(1) if m else (on_click or "")


def icons_enabled(cfg):
    return cfg.get("dxrice_icons_enabled", True)


def normalize_legacy_shortcuts(cfg):
    """Backfill dxrice_label/dxrice_cmd/dxrice_icon_mode onto any shortcut
    that predates this metadata (added by hand, or by the old bash menu),
    so every shortcut is uniformly editable without changing how it looks
    or behaves until the user actually touches it."""
    for modid in list(cfg.get("modules-left", [])):
        if modid == LAUNCHER_ID:
            continue
        meta = cfg.get(modid)
        if not meta or "dxrice_label" in meta:
            continue
        label = meta.get("tooltip-format") or re.sub(r"^(custom/|image#)", "", modid)
        meta["dxrice_label"] = label
        meta["dxrice_cmd"] = _unwrap_shell_cmd(meta.get("on-click", ""))
        if modid.startswith("image#"):
            meta["dxrice_icon_mode"] = "image"
            if meta.get("path"):
                meta["dxrice_icon_path"] = meta["path"]
        else:
            meta["dxrice_icon_mode"] = "auto"


def rebuild_module(cfg, modid):
    """Regenerate the waybar-visible fields of a shortcut from its
    dxrice_* metadata -- the single place that decides what a shortcut
    actually looks like."""
    meta = cfg[modid]
    label = meta["dxrice_label"]
    cmd = meta["dxrice_cmd"]
    mode = meta.get("dxrice_icon_mode", "auto")
    on_click = f"sh -c '{cmd} >/dev/null 2>&1 &'"

    if mode == "image" and meta.get("dxrice_icon_path"):
        cfg[modid] = {
            "dxrice_label": label, "dxrice_cmd": cmd,
            "dxrice_icon_mode": "image", "dxrice_icon_path": meta["dxrice_icon_path"],
            "path": meta["dxrice_icon_path"], "size": cfg.get("dxrice_icon_size", DEFAULT_ICON_SIZE),
            "on-click": on_click,
            "tooltip": False,
            "class": "app-icon",
        }
        return

    show_glyph = mode == "auto" and icons_enabled(cfg)
    fmt = icon_for(label, cmd) if show_glyph else label
    cfg[modid] = {
        "dxrice_label": label, "dxrice_cmd": cmd, "dxrice_icon_mode": mode,
        "format": fmt, "on-click": on_click,
        "tooltip": True, "tooltip-format": label, "class": "app-icon",
    }


def add_shortcut(cfg, label, cmd, mode="auto", image_path=None):
    modid = _unique_modid(cfg, modid_for(label, mode))
    cfg[modid] = {"dxrice_label": label, "dxrice_cmd": cmd, "dxrice_icon_mode": mode}
    if mode == "image" and image_path:
        cfg[modid]["dxrice_icon_path"] = image_path
    rebuild_module(cfg, modid)
    cfg.setdefault("modules-left", [])
    cfg["modules-left"].append(modid)
    return modid


def set_icon_mode(cfg, modid, new_mode, image_path=None):
    """Change a shortcut's icon mode, renaming its module id (custom/x <->
    image#x) if the underlying waybar module type needs to change."""
    meta = cfg[modid]
    new_modid = modid_for(meta["dxrice_label"], new_mode)
    if new_modid != modid:
        new_modid = _unique_modid(cfg, new_modid, exclude=modid)
        mods = cfg.get("modules-left", [])
        if modid in mods:
            mods[mods.index(modid)] = new_modid
        del cfg[modid]
        cfg[new_modid] = meta
        modid = new_modid
    meta["dxrice_icon_mode"] = new_mode
    if new_mode == "image" and image_path:
        meta["dxrice_icon_path"] = image_path
    rebuild_module(cfg, modid)
    return modid


def remove_shortcut(cfg, modid):
    mods = cfg.get("modules-left", [])
    if modid in mods:
        mods.remove(modid)
    cfg.pop(modid, None)


def move_shortcut(cfg, modid, direction):
    mods = cfg.get("modules-left", [])
    if modid not in mods:
        return
    idx = mods.index(modid)
    if direction == "up" and idx > 0:
        mods[idx - 1], mods[idx] = mods[idx], mods[idx - 1]
    elif direction == "down" and idx < len(mods) - 1:
        mods[idx + 1], mods[idx] = mods[idx], mods[idx + 1]


def move_shortcut_to(cfg, modid, target_index):
    """Arbitrary reposition, used by drag-and-drop reordering (up/down only
    moves by one). The launcher is never a drag source/target itself, but
    this still refuses to place anything before it (index 0 is pinned) so
    a drop can't accidentally shove a shortcut ahead of it."""
    mods = cfg.get("modules-left", [])
    if modid not in mods:
        return
    mods.remove(modid)
    if LAUNCHER_ID in mods:
        target_index = max(target_index, mods.index(LAUNCHER_ID) + 1)
    target_index = max(0, min(target_index, len(mods)))
    mods.insert(target_index, modid)


def set_icon_size(cfg, size):
    """Global custom-image icon size (px). Re-renders every already-image
    shortcut immediately so the change is visible without re-picking."""
    cfg["dxrice_icon_size"] = size
    for modid in cfg.get("modules-left", []):
        meta = cfg.get(modid)
        if meta and meta.get("dxrice_icon_mode") == "image":
            rebuild_module(cfg, modid)


def refresh_all_icons(cfg):
    """Re-derive every "auto"/"text" shortcut's format after the global
    icons switch changes. Image shortcuts are untouched -- they don't
    depend on it."""
    for modid in cfg.get("modules-left", []):
        if modid == LAUNCHER_ID:
            continue
        meta = cfg.get(modid)
        if not meta or "dxrice_label" not in meta:
            continue
        rebuild_module(cfg, modid)


def store_icon_image(src_path, label):
    """Copies a user-picked image into ~/.config/waybar/icons so it keeps
    working even if the original file moves or is deleted."""
    os.makedirs(ICONS_DIR, exist_ok=True)
    ext = os.path.splitext(src_path)[1] or ".png"
    dst = os.path.join(ICONS_DIR, f"{slugify(label)}{ext}")
    shutil.copyfile(src_path, dst)
    return dst


def list_desktop_apps():
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


# ---------------------------------------------------------------------------
# System modules (modules-right/-center click actions)
# ---------------------------------------------------------------------------

def system_module_ids(cfg):
    ids = []
    for modid in cfg.get("modules-center", []) + cfg.get("modules-right", []):
        if modid in SYSTEM_MODULE_LABELS:
            ids.append(modid)
    return ids


def set_module_click(cfg, modid, key, value):
    entry = cfg.setdefault(modid, {})
    if value:
        entry[key] = value
    else:
        entry.pop(key, None)


def cleanup_legacy_mic_mute(cfg):
    """One-time removal for anyone who toggled on the short-lived
    standalone mic-mute shortcut before it moved into Quick Settings."""
    mods = cfg.get("modules-right", [])
    if _LEGACY_MIC_MUTE_MODID in mods:
        mods.remove(_LEGACY_MIC_MUTE_MODID)
    cfg.pop(_LEGACY_MIC_MUTE_MODID, None)


PANEL_WIDTH = 480


# ---------------------------------------------------------------------------
# Add-shortcut dialog
# ---------------------------------------------------------------------------

class AddShortcutDialog(Adw.Window):
    def __init__(self, parent):
        super().__init__(transient_for=parent, modal=True, title="Add Shortcut")
        self.set_default_size(420, 560)
        self.parent_win = parent

        escape_controller = Gtk.EventControllerKey()
        escape_controller.connect("key-pressed", self._on_key_pressed)
        self.add_controller(escape_controller)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        root.add_css_class("dx-root")
        self.set_content(root)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        header.add_css_class("dx-header")
        header.append(_label("Add Shortcut", "dx-header-title", ellipsize=False))
        close_btn = Gtk.Button(icon_name="window-close-symbolic")
        close_btn.add_css_class("dx-close")
        close_btn.set_hexpand(True)
        close_btn.set_halign(Gtk.Align.END)
        close_btn.connect("clicked", lambda _b: self.close())
        header.append(close_btn)
        root.append(header)

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        body.add_css_class("dx-body")
        root.append(body)

        self.search_entry = Gtk.Entry(placeholder_text="Search installed apps...")
        self.search_entry.add_css_class("dx-entry")
        self.search_entry.connect("changed", self.on_search_changed)
        body.append(self.search_entry)

        scroller = Gtk.ScrolledWindow()
        scroller.set_vexpand(True)
        scroller.set_min_content_height(260)
        scroller.set_margin_top(8)
        self.list_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        scroller.set_child(self.list_box)
        body.append(scroller)

        body.append(make_section_title("Or add a custom shortcut"))
        manual_card = make_card()
        name_row, _ = make_row("Display name")
        self.name_entry = Gtk.Entry()
        self.name_entry.add_css_class("dx-entry")
        self.name_entry.set_hexpand(True)
        name_row.append(self.name_entry)
        manual_card.append(name_row)

        cmd_row, _ = make_row("Command to run")
        self.cmd_entry = Gtk.Entry()
        self.cmd_entry.add_css_class("dx-entry")
        self.cmd_entry.set_hexpand(True)
        cmd_row.append(self.cmd_entry)
        manual_card.append(cmd_row)
        body.append(manual_card)

        add_custom_btn = Gtk.Button(label="Add Custom Shortcut")
        add_custom_btn.add_css_class("dx-btn-primary")
        add_custom_btn.set_margin_top(8)
        add_custom_btn.connect("clicked", self.on_add_custom)
        body.append(add_custom_btn)

        self.all_apps = list_desktop_apps()
        self.populate_list(self.all_apps)

    def _on_key_pressed(self, _controller, keyval, _keycode, _state):
        if keyval == Gdk.KEY_Escape:
            self.close()
            return True
        return False

    def populate_list(self, apps):
        child = self.list_box.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self.list_box.remove(child)
            child = nxt
        for name, cmd, _icon_hint in apps[:200]:
            row_btn = Gtk.Button()
            row_btn.add_css_class("dx-list-row")
            row_btn.add_css_class("flat")
            row, _t = make_row(name, cmd)
            row_btn.set_child(row)
            row_btn.connect("clicked", lambda _b, n=name, c=cmd: self.on_app_chosen(n, c))
            self.list_box.append(row_btn)

    def on_search_changed(self, entry):
        query = entry.get_text().strip().lower()
        apps = self.all_apps if not query else [a for a in self.all_apps if query in a[0].lower()]
        self.populate_list(apps)

    def on_app_chosen(self, name, cmd):
        self.parent_win.add_new_shortcut(name, cmd)
        self.close()

    def on_add_custom(self, _btn):
        name = self.name_entry.get_text().strip()
        cmd = self.cmd_entry.get_text().strip()
        if not name or not cmd:
            return
        self.parent_win.add_new_shortcut(name, cmd)
        self.close()


# ---------------------------------------------------------------------------
# Shortcut row -- its own draggable, expandable card
# ---------------------------------------------------------------------------

class ShortcutRow(Gtk.Box):
    def __init__(self, modid, entry, pinned, on_change, on_reorder, on_remove):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.add_css_class("dx-card")
        self.modid = modid
        self.pinned = pinned
        self.on_change = on_change

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        header.add_css_class("dx-row")

        if pinned:
            spacer = Gtk.Label(label="")
            spacer.set_width_chars(2)
            header.append(spacer)
        else:
            handle = Gtk.Image.new_from_icon_name("list-drag-handle-symbolic")
            handle.add_css_class("dx-drag-handle")
            handle.set_cursor_from_name("grab")
            header.append(handle)
            self._attach_drag_source(handle)

        self.icon_lbl = Gtk.Label()
        self.icon_lbl.add_css_class("title-1")
        self.icon_lbl.set_width_chars(2)
        self.icon_lbl.set_valign(Gtk.Align.CENTER)
        header.append(self.icon_lbl)

        text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0, hexpand=True)
        self.title_lbl = _label(entry.get("dxrice_label", modid), "dx-row-title", max_width_chars=20)
        self.sub_lbl = _label(entry.get("dxrice_cmd", ""), "dx-row-subtitle", max_width_chars=28)
        text_box.append(self.title_lbl)
        text_box.append(self.sub_lbl)
        header.append(text_box)

        if pinned:
            pin_pill = _label("Pinned", "dx-pill", ellipsize=False)
            pin_pill.set_valign(Gtk.Align.CENTER)
            header.append(pin_pill)
            self.revealer = None
        else:
            self.expand_btn = Gtk.Button(icon_name="pan-down-symbolic", tooltip_text="Icon settings")
            self.expand_btn.add_css_class("dx-icon-btn")
            self.expand_btn.connect("clicked", self._on_toggle_expand)
            header.append(self.expand_btn)

            remove_btn = Gtk.Button(icon_name="user-trash-symbolic", tooltip_text="Remove")
            remove_btn.add_css_class("dx-icon-btn")
            remove_btn.add_css_class("destructive")
            remove_btn.connect("clicked", lambda _b: on_remove(self.modid))
            header.append(remove_btn)

        self.append(header)

        if not pinned:
            self.revealer = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.SLIDE_DOWN,
                                          transition_duration=ANIM_MS)
            expand_body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            expand_body.set_margin_top(6)
            expand_body.set_margin_bottom(4)

            expand_body.append(_label("Icon", "dx-row-subtitle", ellipsize=False))
            self.seg = make_segmented(ICON_MODE_LABELS, 0, self._on_mode_selected)
            expand_body.append(self.seg)

            self.image_row = Gtk.Box(spacing=8)
            self.image_status = _label("No image chosen", "dx-row-subtitle", max_width_chars=24)
            pick_btn = Gtk.Button(label="Choose...")
            pick_btn.add_css_class("dx-btn-secondary")
            pick_btn.connect("clicked", self._on_pick_image)
            self.image_row.append(self.image_status)
            self.image_row.append(pick_btn)
            expand_body.append(self.image_row)

            self.revealer.set_child(expand_body)
            self.append(self.revealer)

        self._attach_drop_target(on_reorder)
        self.refresh(entry)

    def _attach_drag_source(self, handle):
        drag_source = Gtk.DragSource()
        drag_source.set_actions(Gdk.DragAction.MOVE)
        drag_source.connect(
            "prepare",
            lambda *_a: Gdk.ContentProvider.new_for_value(GObject.Value(str, self.modid)),
        )
        drag_source.connect("drag-begin", lambda *_a: self.add_css_class("dx-dragging"))
        drag_source.connect("drag-end", lambda *_a: self.remove_css_class("dx-dragging"))
        handle.add_controller(drag_source)

    def _attach_drop_target(self, on_reorder):
        drop_target = Gtk.DropTarget.new(str, Gdk.DragAction.MOVE)

        def _on_drop(_t, value, _x, _y):
            on_reorder(value, self.modid)
            return True

        def _on_enter(_t, _x, _y):
            self.add_css_class("dx-drop-target")
            return Gdk.DragAction.MOVE

        drop_target.connect("drop", _on_drop)
        drop_target.connect("enter", _on_enter)
        drop_target.connect("leave", lambda *_a: self.remove_css_class("dx-drop-target"))
        self.add_controller(drop_target)

    def _on_toggle_expand(self, _btn):
        show = not self.revealer.get_reveal_child()
        self.revealer.set_reveal_child(show)
        self.expand_btn.set_icon_name("pan-up-symbolic" if show else "pan-down-symbolic")

    def _on_mode_selected(self, idx):
        self.on_change(self.modid, ICON_MODES[idx], None)

    def _on_pick_image(self, _btn):
        dialog = Gtk.FileDialog(title="Choose an image")
        img_filter = Gtk.FileFilter()
        img_filter.set_name("Images")
        img_filter.add_mime_type("image/png")
        img_filter.add_mime_type("image/jpeg")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(img_filter)
        dialog.set_filters(filters)

        def on_done(dlg, result):
            try:
                gfile = dlg.open_finish(result)
            except GLib.Error:
                return
            if gfile:
                self.on_change(self.modid, "image", gfile.get_path())

        dialog.open(self.get_root(), None, on_done)

    def refresh(self, entry):
        """Repaints this row from the given (fresh) config entry."""
        self.title_lbl.set_label(entry.get("dxrice_label", self.modid))
        self.sub_lbl.set_label(entry.get("dxrice_cmd", ""))
        mode = entry.get("dxrice_icon_mode", "auto")
        if mode == "image":
            self.icon_lbl.set_label("\U0001F5BC")
        else:
            self.icon_lbl.set_label(entry.get("format", ""))

        if self.pinned:
            return
        self.seg.set_selected(ICON_MODES.index(mode))
        self.image_row.set_visible(mode == "image")
        path = entry.get("dxrice_icon_path")
        self.image_status.set_label(path if path else "No image chosen")


# ---------------------------------------------------------------------------
# System module row (on-click / on-click-right editor)
# ---------------------------------------------------------------------------

class SystemModuleRow(Gtk.Box):
    def __init__(self, modid, entry, on_change):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.add_css_class("dx-card")
        self.modid = modid
        self.on_change = on_change

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        header.add_css_class("dx-row")
        text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0, hexpand=True)
        text_box.append(_label(SYSTEM_MODULE_LABELS.get(modid, modid), "dx-row-title", max_width_chars=20))
        self.sub_lbl = _label(entry.get("on-click") or "No click action set", "dx-row-subtitle",
                               max_width_chars=32)
        text_box.append(self.sub_lbl)
        header.append(text_box)

        self.expand_btn = Gtk.Button(icon_name="pan-down-symbolic", tooltip_text="Click actions")
        self.expand_btn.add_css_class("dx-icon-btn")
        self.expand_btn.connect("clicked", self._on_toggle_expand)
        header.append(self.expand_btn)
        self.append(header)

        self.revealer = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.SLIDE_DOWN,
                                      transition_duration=ANIM_MS)
        expand_body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        expand_body.set_margin_top(6)
        expand_body.set_margin_bottom(4)

        left_row, _t1 = make_row("Left click")
        self.left_entry = Gtk.Entry()
        self.left_entry.add_css_class("dx-entry")
        self.left_entry.set_hexpand(True)
        self.left_entry.set_text(entry.get("on-click", ""))
        self.left_entry.connect("changed", lambda e: self._on_edit("on-click", e))
        left_row.append(self.left_entry)
        expand_body.append(left_row)

        right_row, _t2 = make_row("Right click")
        self.right_entry = Gtk.Entry()
        self.right_entry.add_css_class("dx-entry")
        self.right_entry.set_hexpand(True)
        self.right_entry.set_text(entry.get("on-click-right", ""))
        self.right_entry.connect("changed", lambda e: self._on_edit("on-click-right", e))
        right_row.append(self.right_entry)
        expand_body.append(right_row)

        self.revealer.set_child(expand_body)
        self.append(self.revealer)

    def _on_toggle_expand(self, _btn):
        show = not self.revealer.get_reveal_child()
        self.revealer.set_reveal_child(show)
        self.expand_btn.set_icon_name("pan-up-symbolic" if show else "pan-down-symbolic")

    def _on_edit(self, key, entry):
        value = entry.get_text().strip()
        self.on_change(self.modid, key, value)
        if key == "on-click":
            self.sub_lbl.set_label(value or "No click action set")


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class TaskbarWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="DXrice Taskbar")
        self.set_default_size(PANEL_WIDTH, 780)

        # Same rationale as dxrice_theme_gui.py's Escape handler: Super+C
        # force-kills the surface without a close-request signal.
        escape_controller = Gtk.EventControllerKey()
        escape_controller.connect("key-pressed", self._on_key_pressed)
        self.add_controller(escape_controller)

        try:
            self.cfg = load_config()
        except (OSError, json.JSONDecodeError) as e:
            self._show_load_error(e)
            self.cfg = {"modules-left": []}

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        root.add_css_class("dx-root")
        self.set_content(root)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        header.add_css_class("dx-header")
        title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True)
        title_box.append(_label("Taskbar", "dx-header-title", ellipsize=False))
        title_box.append(_label("Shortcuts, icons, and click actions for the bar",
                                 "dx-header-subtitle", max_width_chars=36))
        header.append(title_box)

        add_btn = Gtk.Button(icon_name="list-add-symbolic", tooltip_text="Add shortcut")
        add_btn.add_css_class("dx-btn-primary")
        add_btn.connect("clicked", self.on_add_clicked)
        header.append(add_btn)

        close_btn = Gtk.Button(icon_name="window-close-symbolic")
        close_btn.add_css_class("dx-close")
        close_btn.connect("clicked", lambda _b: self.close())
        header.append(close_btn)

        root.append(header)

        scroller = Gtk.ScrolledWindow()
        scroller.set_vexpand(True)
        root.append(scroller)

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        body.add_css_class("dx-body")
        scroller.set_child(body)

        body.append(make_section_title("Options"))
        options_card = make_card()

        icons_row, _t = make_row("Show icons", "Applies to shortcuts left on \"Automatic\"")
        self.icons_switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        self.icons_switch.set_active(icons_enabled(self.cfg))
        self.icons_switch.connect("notify::active", self.on_icons_toggled)
        icons_row.append(self.icons_switch)
        options_card.append(icons_row)

        size_row, _t2 = make_row("Custom icon size", "Applies to shortcuts using a custom image")
        self.size_label = _label(str(self.cfg.get("dxrice_icon_size", DEFAULT_ICON_SIZE)),
                                  ellipsize=False)
        self.size_label.set_width_chars(3)
        self.size_label.set_xalign(1.0)
        size_scale = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL, hexpand=True)
        size_scale.set_range(16, 48)
        size_scale.set_increments(1, 4)
        size_scale.set_value(self.cfg.get("dxrice_icon_size", DEFAULT_ICON_SIZE))
        size_scale.set_draw_value(False)
        size_scale.set_size_request(90, -1)
        size_scale.connect("value-changed", self.on_icon_size_changed)
        size_row.append(size_scale)
        size_row.append(self.size_label)
        options_card.append(size_row)

        body.append(options_card)

        body.append(make_section_title("Taskbar Shortcuts"))
        self.shortcuts_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        body.append(self.shortcuts_box)
        self._rows = {}
        self.rebuild_shortcut_rows()

        body.append(make_section_title("System Modules"))
        body.append(_label("Click actions for the volume/network/CPU/RAM/clock modules",
                            "dx-row-subtitle", max_width_chars=44))
        self.system_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.system_box.set_margin_top(6)
        body.append(self.system_box)
        self._system_rows = {}
        self.rebuild_system_rows()

    def _show_load_error(self, error):
        print(f"Could not read {CONFIG_PATH}: {error}", file=sys.stderr)
        print("Run install.sh first to deploy the waybar config.", file=sys.stderr)

    # ---- shortcuts (modules-left) ----

    def rebuild_shortcut_rows(self):
        child = self.shortcuts_box.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self.shortcuts_box.remove(child)
            child = nxt
        self._rows = {}
        for modid in self.cfg.get("modules-left", []):
            entry = self.cfg.get(modid)
            if not entry:
                continue
            row = ShortcutRow(modid, entry, modid == LAUNCHER_ID,
                               self.on_icon_mode_changed, self.on_reorder, self.on_remove)
            self.shortcuts_box.append(row)
            self._rows[modid] = row

    def persist(self):
        try:
            save_config(self.cfg)
        except OSError as e:
            print(f"Could not save {CONFIG_PATH}: {e}", file=sys.stderr)
            return
        restart_waybar()

    def on_icons_toggled(self, switch, _pspec):
        self.cfg["dxrice_icons_enabled"] = switch.get_active()
        refresh_all_icons(self.cfg)
        self.persist()
        self.rebuild_shortcut_rows()

    def on_icon_size_changed(self, scale):
        size = int(round(scale.get_value()))
        self.size_label.set_label(str(size))
        set_icon_size(self.cfg, size)
        self.persist()
        self.rebuild_shortcut_rows()

    def on_reorder(self, dragged_modid, target_modid):
        if dragged_modid == target_modid:
            return
        mods = self.cfg.get("modules-left", [])
        if target_modid not in mods:
            return
        target_index = mods.index(target_modid)
        move_shortcut_to(self.cfg, dragged_modid, target_index)
        self.persist()
        self.rebuild_shortcut_rows()

    def on_remove(self, modid):
        remove_shortcut(self.cfg, modid)
        self.persist()
        self.rebuild_shortcut_rows()

    def on_icon_mode_changed(self, modid, new_mode, image_path):
        if new_mode == "image" and image_path:
            try:
                image_path = store_icon_image(image_path, self.cfg[modid]["dxrice_label"])
            except OSError as e:
                print(f"Could not copy icon image: {e}", file=sys.stderr)
                return
        elif new_mode == "image" and not self.cfg[modid].get("dxrice_icon_path"):
            # Switched to "Custom image" with no image chosen yet -- wait
            # for the file picker instead of rebuilding with a blank path.
            self._rows[modid].refresh({**self.cfg[modid], "dxrice_icon_mode": "image"})
            return
        set_icon_mode(self.cfg, modid, new_mode, image_path)
        self.persist()
        self.rebuild_shortcut_rows()

    def on_add_clicked(self, _btn):
        AddShortcutDialog(self).present()

    def add_new_shortcut(self, label, cmd):
        add_shortcut(self.cfg, label, cmd)
        self.persist()
        self.rebuild_shortcut_rows()

    # ---- system modules (modules-right/-center) ----

    def rebuild_system_rows(self):
        child = self.system_box.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self.system_box.remove(child)
            child = nxt
        self._system_rows = {}
        for modid in system_module_ids(self.cfg):
            entry = self.cfg.get(modid, {})
            row = SystemModuleRow(modid, entry, self.on_system_click_changed)
            self.system_box.append(row)
            self._system_rows[modid] = row

    def on_system_click_changed(self, modid, key, value):
        set_module_click(self.cfg, modid, key, value)
        self.persist()

    # ---- window ----

    def _on_key_pressed(self, _controller, keyval, _keycode, _state):
        if keyval == Gdk.KEY_Escape:
            self.close()
            return True
        return False


class TaskbarApp(Adw.Application):
    def __init__(self):
        # NON_UNIQUE for the same reason as dxrice_theme_gui.py: launched
        # ad-hoc from a keybind, not session-integrated, so a force-killed
        # window must never block the next launch by reactivating a dead
        # registered instance.
        super().__init__(application_id="dev.dexo.DXriceTaskbar",
                          flags=Gio.ApplicationFlags.NON_UNIQUE)

    def do_startup(self):
        Adw.Application.do_startup(self)
        load_css(CSS_PATH)

    def do_activate(self):
        win = self.props.active_window
        if not win:
            win = TaskbarWindow(self)
            win.connect("close-request", self._on_close_request)
        win.present()

    def _on_close_request(self, _win):
        self.quit()
        return False


if __name__ == "__main__":
    app = TaskbarApp()
    app.run(sys.argv)
