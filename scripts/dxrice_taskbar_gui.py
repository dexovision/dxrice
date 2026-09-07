#!/usr/bin/env python3
"""GTK4/Adwaita app for managing DXrice's waybar taskbar shortcuts.

Replaces the old kitty-terminal menu (dxrice-manage-taskbar.sh) with a
native settings window, matching dxrice_theme_gui.py. Edits
~/.config/waybar/config directly (mirrored back into <repo>/waybar/config
so the change survives an `install.sh update`) and restarts waybar.

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
from gi.repository import Adw, Gdk, Gio, GLib, Gtk

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dxrice_icons import icon_for

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(SCRIPTS_DIR)
HOME = os.path.expanduser("~")
CONFIG_PATH = os.path.join(HOME, ".config", "waybar", "config")
REPO_CONFIG_PATH = os.path.join(REPO, "waybar", "config")
ICONS_DIR = os.path.join(HOME, ".config", "waybar", "icons")

LAUNCHER_ID = "custom/launcher"
ICON_MODES = ["auto", "text", "image"]
ICON_MODE_LABELS = ["Automatic icon", "Text label", "Custom image"]

MIC_MUTE_MODID = "custom/micmute"
MIC_MUTE_CMD = "wpctl set-mute @DEFAULT_AUDIO_SOURCE@ toggle"

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
    return cfg


def save_config(cfg):
    atomic_write_json(CONFIG_PATH, cfg)
    atomic_write_json(REPO_CONFIG_PATH, cfg)


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
            "path": meta["dxrice_icon_path"], "size": 24,
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


def add_mic_mute_module(cfg):
    if MIC_MUTE_MODID in cfg:
        return False
    cfg[MIC_MUTE_MODID] = {
        "format": "Mic",
        "on-click": MIC_MUTE_CMD,
        "tooltip": True,
        "tooltip-format": "Toggle mic mute",
    }
    cfg.setdefault("modules-right", []).insert(0, MIC_MUTE_MODID)
    return True


def remove_mic_mute_module(cfg):
    mods = cfg.get("modules-right", [])
    if MIC_MUTE_MODID in mods:
        mods.remove(MIC_MUTE_MODID)
    cfg.pop(MIC_MUTE_MODID, None)


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

        toolbar_view = Adw.ToolbarView()
        header = Adw.HeaderBar()
        toolbar_view.add_top_bar(header)

        self.search_entry = Gtk.SearchEntry()
        self.search_entry.set_placeholder_text("Search installed apps...")
        self.search_entry.connect("search-changed", self.on_search_changed)
        header.set_title_widget(self.search_entry)

        self.all_apps = list_desktop_apps()

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        outer.set_margin_top(12)
        outer.set_margin_bottom(12)
        outer.set_margin_start(12)
        outer.set_margin_end(12)

        scroller = Gtk.ScrolledWindow()
        scroller.set_vexpand(True)
        self.listbox = Gtk.ListBox()
        self.listbox.add_css_class("boxed-list")
        self.listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        self.listbox.connect("row-activated", self.on_row_activated)
        scroller.set_child(self.listbox)
        outer.append(scroller)

        manual_group = Adw.PreferencesGroup(title="Or add a custom shortcut")
        self.name_row = Adw.EntryRow(title="Display name")
        self.cmd_row = Adw.EntryRow(title="Command to run")
        manual_group.add(self.name_row)
        manual_group.add(self.cmd_row)
        outer.append(manual_group)

        add_custom_btn = Gtk.Button(label="Add Custom Shortcut")
        add_custom_btn.add_css_class("suggested-action")
        add_custom_btn.connect("clicked", self.on_add_custom)
        outer.append(add_custom_btn)

        toolbar_view.set_content(outer)
        self.set_content(toolbar_view)

        self.populate_list(self.all_apps)

    def _on_key_pressed(self, _controller, keyval, _keycode, _state):
        if keyval == Gdk.KEY_Escape:
            self.close()
            return True
        return False

    def populate_list(self, apps):
        child = self.listbox.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self.listbox.remove(child)
            child = nxt
        for name, cmd, icon_hint in apps:
            row = Adw.ActionRow(title=name, subtitle=cmd, activatable=True)
            row.app_data = (name, cmd, icon_hint)
            self.listbox.append(row)

    def on_search_changed(self, entry):
        query = entry.get_text().strip().lower()
        apps = self.all_apps if not query else [a for a in self.all_apps if query in a[0].lower()]
        self.populate_list(apps)

    def on_row_activated(self, _listbox, row):
        name, cmd, _icon_hint = row.app_data
        self.parent_win.add_new_shortcut(name, cmd)
        self.close()

    def on_add_custom(self, _btn):
        name = self.name_row.get_text().strip()
        cmd = self.cmd_row.get_text().strip()
        if not name or not cmd:
            return
        self.parent_win.add_new_shortcut(name, cmd)
        self.close()


# ---------------------------------------------------------------------------
# Shortcut row (expandable: icon mode dropdown + image picker)
# ---------------------------------------------------------------------------

class ShortcutRow(Adw.ExpanderRow):
    def __init__(self, modid, entry, pinned, on_change, on_up, on_down, on_remove):
        label = entry.get("dxrice_label", modid)
        cmd = entry.get("dxrice_cmd", "")
        super().__init__(title=GLib.markup_escape_text(label), subtitle=GLib.markup_escape_text(cmd))
        self.modid = modid
        self.on_change = on_change

        self.icon_lbl = Gtk.Label()
        self.icon_lbl.add_css_class("title-1")
        self.icon_lbl.set_width_chars(2)
        self.icon_lbl.set_valign(Gtk.Align.CENTER)
        self.add_prefix(self.icon_lbl)

        box = Gtk.Box(spacing=4, valign=Gtk.Align.CENTER)
        up_btn = Gtk.Button(icon_name="go-up-symbolic", tooltip_text="Move up")
        up_btn.add_css_class("flat")
        down_btn = Gtk.Button(icon_name="go-down-symbolic", tooltip_text="Move down")
        down_btn.add_css_class("flat")
        remove_btn = Gtk.Button(icon_name="user-trash-symbolic", tooltip_text="Remove")
        remove_btn.add_css_class("flat")

        if pinned:
            up_btn.set_sensitive(False)
            down_btn.set_sensitive(False)
            remove_btn.set_sensitive(False)
        else:
            up_btn.connect("clicked", lambda _b: on_up(self.modid))
            down_btn.connect("clicked", lambda _b: on_down(self.modid))
            remove_btn.connect("clicked", lambda _b: on_remove(self.modid))

        box.append(up_btn)
        box.append(down_btn)
        box.append(remove_btn)
        self.add_suffix(box)

        if not pinned:
            self.mode_model = Gtk.StringList.new(ICON_MODE_LABELS)
            self.mode_combo = Adw.ComboRow(title="Icon", model=self.mode_model)
            self.mode_combo.connect("notify::selected", self._on_mode_changed)
            self.add_row(self.mode_combo)

            self.image_row = Adw.ActionRow(title="Custom image", subtitle="No image chosen")
            pick_btn = Gtk.Button(label="Choose...")
            pick_btn.set_valign(Gtk.Align.CENTER)
            pick_btn.connect("clicked", self._on_pick_image)
            self.image_row.add_suffix(pick_btn)
            self.add_row(self.image_row)

        self.refresh(entry)

    def refresh(self, entry):
        """Repaints this row from the given (fresh) config entry without
        firing the combo's change handler again."""
        mode = entry.get("dxrice_icon_mode", "auto")
        if mode == "image":
            self.icon_lbl.set_label("🖼")
        else:
            self.icon_lbl.set_label(entry.get("format", ""))

        if hasattr(self, "mode_combo"):
            self.mode_combo.handler_block_by_func(self._on_mode_changed)
            self.mode_combo.set_selected(ICON_MODES.index(mode))
            self.mode_combo.handler_unblock_by_func(self._on_mode_changed)
            self.image_row.set_visible(mode == "image")
            path = entry.get("dxrice_icon_path")
            self.image_row.set_subtitle(path if path else "No image chosen")

    def _on_mode_changed(self, combo, _pspec):
        idx = combo.get_selected()
        if idx == Gtk.INVALID_LIST_POSITION:
            return
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


# ---------------------------------------------------------------------------
# System module row (on-click / on-click-right editor)
# ---------------------------------------------------------------------------

class SystemModuleRow(Adw.ExpanderRow):
    def __init__(self, modid, entry, on_change):
        title = SYSTEM_MODULE_LABELS.get(modid, modid)
        super().__init__(title=title, subtitle=entry.get("on-click", "No click action set"))
        self.modid = modid
        self.on_change = on_change

        self.left_row = Adw.EntryRow(title="Left click")
        self.left_row.set_text(entry.get("on-click", ""))
        self.left_row.connect("changed", lambda r: self._on_edit("on-click", r))
        self.add_row(self.left_row)

        self.right_row = Adw.EntryRow(title="Right click")
        self.right_row.set_text(entry.get("on-click-right", ""))
        self.right_row.connect("changed", lambda r: self._on_edit("on-click-right", r))
        self.add_row(self.right_row)

    def _on_edit(self, key, entry_row):
        value = entry_row.get_text().strip()
        self.on_change(self.modid, key, value)
        if key == "on-click":
            self.set_subtitle(value or "No click action set")


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class TaskbarWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="DXrice Taskbar")
        self.set_default_size(560, 760)

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

        toolbar_view = Adw.ToolbarView()
        header = Adw.HeaderBar()
        toolbar_view.add_top_bar(header)

        add_btn = Gtk.Button(icon_name="list-add-symbolic")
        add_btn.set_tooltip_text("Add shortcut")
        add_btn.connect("clicked", self.on_add_clicked)
        header.pack_end(add_btn)

        scroller = Gtk.ScrolledWindow()
        page = Adw.PreferencesPage()
        scroller.set_child(page)
        toolbar_view.set_content(scroller)
        self.set_content(toolbar_view)

        options_group = Adw.PreferencesGroup(title="Options")
        page.add(options_group)
        self.icons_row = Adw.SwitchRow(
            title="Show icons",
            subtitle="Applies to shortcuts left on \"Automatic icon\" below",
            active=icons_enabled(self.cfg),
        )
        self.icons_row.connect("notify::active", self.on_icons_toggled)
        options_group.add(self.icons_row)

        self.shortcuts_group = Adw.PreferencesGroup(title="Taskbar Shortcuts")
        page.add(self.shortcuts_group)
        self._rows = {}
        self.rebuild_shortcut_rows()

        self.system_group = Adw.PreferencesGroup(
            title="System Modules",
            description="Click actions for the volume/network/CPU/RAM/clock modules",
        )
        page.add(self.system_group)

        self.mic_mute_row = Adw.SwitchRow(
            title="Mic mute button",
            subtitle="Adds a button to the right side that toggles your microphone",
            active=MIC_MUTE_MODID in self.cfg,
        )
        self.mic_mute_row.connect("notify::active", self.on_mic_mute_toggled)
        self.system_group.add(self.mic_mute_row)

        self._system_rows = {}
        self.rebuild_system_rows()

    def _show_load_error(self, error):
        print(f"Could not read {CONFIG_PATH}: {error}", file=sys.stderr)
        print("Run install.sh first to deploy the waybar config.", file=sys.stderr)

    # ---- shortcuts (modules-left) ----

    def rebuild_shortcut_rows(self):
        for row in self._rows.values():
            self.shortcuts_group.remove(row)
        self._rows = {}
        for modid in self.cfg.get("modules-left", []):
            entry = self.cfg.get(modid)
            if not entry:
                continue
            row = ShortcutRow(modid, entry, modid == LAUNCHER_ID,
                               self.on_icon_mode_changed, self.on_move_up,
                               self.on_move_down, self.on_remove)
            self.shortcuts_group.add(row)
            self._rows[modid] = row

    def persist(self):
        try:
            save_config(self.cfg)
        except OSError as e:
            print(f"Could not save {CONFIG_PATH}: {e}", file=sys.stderr)
            return
        restart_waybar()

    def on_icons_toggled(self, row, _pspec):
        self.cfg["dxrice_icons_enabled"] = row.get_active()
        refresh_all_icons(self.cfg)
        self.persist()
        self.rebuild_shortcut_rows()

    def on_move_up(self, modid):
        move_shortcut(self.cfg, modid, "up")
        self.persist()
        self.rebuild_shortcut_rows()

    def on_move_down(self, modid):
        move_shortcut(self.cfg, modid, "down")
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
        new_modid = set_icon_mode(self.cfg, modid, new_mode, image_path)
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
        for row in self._system_rows.values():
            self.system_group.remove(row)
        self._system_rows = {}
        for modid in system_module_ids(self.cfg):
            entry = self.cfg.get(modid, {})
            row = SystemModuleRow(modid, entry, self.on_system_click_changed)
            self.system_group.add(row)
            self._system_rows[modid] = row

    def on_system_click_changed(self, modid, key, value):
        set_module_click(self.cfg, modid, key, value)
        self.persist()

    def on_mic_mute_toggled(self, row, _pspec):
        if row.get_active():
            add_mic_mute_module(self.cfg)
        else:
            remove_mic_mute_module(self.cfg)
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
