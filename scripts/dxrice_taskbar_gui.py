#!/usr/bin/env python3
"""GTK4/Adwaita app for managing DXrice's waybar taskbar shortcuts.

Replaces the old kitty-terminal menu (dxrice-manage-taskbar.sh) with a
native settings window, matching dxrice_theme_gui.py. Edits
~/.config/waybar/config directly (mirrored back into <repo>/waybar/config
so the change survives an `install.sh update`) and restarts waybar.
"""
import glob
import json
import os
import re
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

LAUNCHER_ID = "custom/launcher"


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
        return json.load(f)


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


def slugify(label):
    slug = re.sub(r"[^a-zA-Z0-9]", "", label).lower()
    return slug or f"app{int(GLib.get_monotonic_time())}"


def icons_enabled(cfg):
    return cfg.get("dxrice_icons_enabled", True)


def display_format(cfg, label, cmd, icon_hint):
    if icons_enabled(cfg):
        return icon_for(label, cmd, icon_hint)
    return label


def add_shortcut(cfg, label, cmd, icon_hint=""):
    modid = f"custom/{slugify(label)}"
    cfg[modid] = {
        "format": display_format(cfg, label, cmd, icon_hint),
        "on-click": f"sh -c '{cmd} >/dev/null 2>&1 &'",
        "tooltip": True,
        "tooltip-format": label,
        "class": "app-icon",
    }
    cfg.setdefault("modules-left", [])
    if modid not in cfg["modules-left"]:
        cfg["modules-left"].append(modid)


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
    """Re-derive every shortcut's visible format from the current icons
    setting. The launcher is intentionally skipped -- it's a fixture, not
    a user-managed shortcut."""
    for modid in cfg.get("modules-left", []):
        if modid == LAUNCHER_ID or not modid.startswith("custom/"):
            continue
        entry = cfg.get(modid)
        if not entry:
            continue
        label = entry.get("tooltip-format", modid)
        cmd = entry.get("on-click", "")
        entry["format"] = display_format(cfg, label, cmd, "")
        entry["tooltip"] = True
        entry["tooltip-format"] = label
        entry["class"] = "app-icon"


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
        name, cmd, icon_hint = row.app_data
        self.parent_win.add_new_shortcut(name, cmd, icon_hint)
        self.close()

    def on_add_custom(self, _btn):
        name = self.name_row.get_text().strip()
        cmd = self.cmd_row.get_text().strip()
        if not name or not cmd:
            return
        self.parent_win.add_new_shortcut(name, cmd)
        self.close()


class ShortcutRow(Adw.ActionRow):
    def __init__(self, modid, entry, pinned, on_up, on_down, on_remove):
        label = entry.get("tooltip-format", modid)
        cmd = entry.get("on-click", "")
        super().__init__(title=GLib.markup_escape_text(label), subtitle=GLib.markup_escape_text(cmd))
        self.modid = modid

        icon_lbl = Gtk.Label(label=entry.get("format", ""))
        icon_lbl.add_css_class("title-1")
        icon_lbl.set_width_chars(2)
        icon_lbl.set_valign(Gtk.Align.CENTER)
        self.add_prefix(icon_lbl)

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
            up_btn.connect("clicked", lambda _b: on_up(modid))
            down_btn.connect("clicked", lambda _b: on_down(modid))
            remove_btn.connect("clicked", lambda _b: on_remove(modid))

        box.append(up_btn)
        box.append(down_btn)
        box.append(remove_btn)
        self.add_suffix(box)


class TaskbarWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="DXrice Taskbar")
        self.set_default_size(520, 680)

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
            subtitle="Off shows each shortcut's name as plain text instead of a glyph",
            active=icons_enabled(self.cfg),
        )
        self.icons_row.connect("notify::active", self.on_icons_toggled)
        options_group.add(self.icons_row)

        self.shortcuts_group = Adw.PreferencesGroup(title="Taskbar Shortcuts")
        page.add(self.shortcuts_group)
        self._rows = []
        self.rebuild_shortcut_rows()

    def _show_load_error(self, error):
        print(f"Could not read {CONFIG_PATH}: {error}", file=sys.stderr)
        print("Run install.sh first to deploy the waybar config.", file=sys.stderr)

    def rebuild_shortcut_rows(self):
        for row in self._rows:
            self.shortcuts_group.remove(row)
        self._rows = []
        for modid in self.cfg.get("modules-left", []):
            entry = self.cfg.get(modid)
            if not entry:
                continue
            row = ShortcutRow(modid, entry, modid == LAUNCHER_ID,
                               self.on_move_up, self.on_move_down, self.on_remove)
            self.shortcuts_group.add(row)
            self._rows.append(row)

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

    def on_add_clicked(self, _btn):
        AddShortcutDialog(self).present()

    def add_new_shortcut(self, label, cmd, icon_hint=""):
        add_shortcut(self.cfg, label, cmd, icon_hint)
        self.persist()
        self.rebuild_shortcut_rows()

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
