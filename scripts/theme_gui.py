#!/usr/bin/env python3
"""GTK4/Adwaita settings app for the rice's theme.json.

Edits ~/dotfiles-rice/theme/theme.json and calls apply_theme.py to render +
hot-reload waybar/wofi/mako/kitty/hyprlock/hyprland.lua.
"""
import copy
import json
import os
import subprocess
import sys

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk

HOME = os.path.expanduser("~")
REPO = os.path.join(HOME, "dotfiles-rice")
THEME_DIR = os.path.join(REPO, "theme")
THEME_JSON = os.path.join(THEME_DIR, "theme.json")
PRESETS_DIR = os.path.join(THEME_DIR, "presets")
APPLY_SCRIPT = os.path.join(HOME, "scripts", "apply_theme.py")

BUILTIN_PRESETS = {
    "Glass Charcoal (default)": {
        "glass_bg": "12141a", "glass_bg_active": "232630",
        "glass_text": "e6e6e6", "glass_text_active": "ffffff",
        "glass_border": "ffffff", "accent": "e67878",
        "opacity_idle": 0.55, "opacity_active": 0.85,
        "border_opacity_idle": 0.08, "border_opacity_active": 0.25,
        "radius": 12, "kitty_opacity": 0.7643,
        "hypr_active_border_1": "8090a0", "hypr_active_border_2": "c0a0b0",
        "hypr_inactive_border": "1d2021",
    },
    "Nord": {
        "glass_bg": "2e3440", "glass_bg_active": "3b4252",
        "glass_text": "d8dee9", "glass_text_active": "eceff4",
        "glass_border": "88c0d0", "accent": "bf616a",
        "opacity_idle": 0.55, "opacity_active": 0.85,
        "border_opacity_idle": 0.12, "border_opacity_active": 0.3,
        "radius": 8, "kitty_opacity": 0.85,
        "hypr_active_border_1": "88c0d0", "hypr_active_border_2": "81a1c1",
        "hypr_inactive_border": "3b4252",
    },
    "Dracula": {
        "glass_bg": "282a36", "glass_bg_active": "44475a",
        "glass_text": "f8f8f2", "glass_text_active": "ffffff",
        "glass_border": "bd93f9", "accent": "ff5555",
        "opacity_idle": 0.6, "opacity_active": 0.9,
        "border_opacity_idle": 0.15, "border_opacity_active": 0.35,
        "radius": 10, "kitty_opacity": 0.88,
        "hypr_active_border_1": "ff79c6", "hypr_active_border_2": "bd93f9",
        "hypr_inactive_border": "44475a",
    },
    "Sunset": {
        "glass_bg": "1a1210", "glass_bg_active": "3a2420",
        "glass_text": "f0e0d6", "glass_text_active": "ffffff",
        "glass_border": "ffb385", "accent": "ff6b4a",
        "opacity_idle": 0.55, "opacity_active": 0.85,
        "border_opacity_idle": 0.12, "border_opacity_active": 0.3,
        "radius": 16, "kitty_opacity": 0.8,
        "hypr_active_border_1": "ff7e5f", "hypr_active_border_2": "feb47b",
        "hypr_inactive_border": "2a1d18",
    },
}

COLOR_FIELDS = [
    ("glass_bg", "Panel background", "Waybar/wofi/kitty base color"),
    ("glass_bg_active", "Active panel background", "Focused workspace, selected entries"),
    ("glass_text", "Text", "Base text color"),
    ("glass_text_active", "Active text", "Text on focused/selected elements"),
    ("glass_border", "Panel border", "Hairline border around panels"),
    ("accent", "Accent", "Critical notifications, tray alerts, lock failure"),
]

HYPR_COLOR_FIELDS = [
    ("hypr_active_border_1", "Active border - color 1", "Focused window border gradient start"),
    ("hypr_active_border_2", "Active border - color 2", "Focused window border gradient end"),
    ("hypr_inactive_border", "Inactive border", "Unfocused window border"),
]

SPIN_FIELDS = {
    "Transparency and Blur": [
        ("opacity_idle", "Panel opacity (idle)", 0, 1, 0.01, 2),
        ("opacity_active", "Panel opacity (active)", 0, 1, 0.01, 2),
        ("border_opacity_idle", "Border opacity (idle)", 0, 1, 0.01, 2),
        ("border_opacity_active", "Border opacity (active)", 0, 1, 0.01, 2),
        ("kitty_opacity", "Terminal opacity", 0, 1, 0.01, 2),
        ("hypr_blur_size", "Window blur size", 0, 20, 1, 0),
        ("hypr_blur_passes", "Window blur passes", 0, 10, 1, 0),
        ("hypr_blur_vibrancy", "Window blur vibrancy", 0, 1, 0.01, 2),
    ],
    "Layout": [
        ("radius", "Panel corner radius", 0, 30, 1, 0),
        ("hypr_rounding", "Window corner rounding", 0, 30, 1, 0),
        ("hypr_gaps_in", "Gaps between windows", 0, 40, 1, 0),
        ("hypr_gaps_out", "Gaps to screen edge", 0, 60, 1, 0),
        ("hypr_border_size", "Window border thickness", 0, 10, 1, 0),
        ("hypr_active_opacity", "Focused window opacity", 0, 1, 0.01, 2),
        ("hypr_inactive_opacity", "Unfocused window opacity", 0, 1, 0.01, 2),
        ("hypr_active_border_angle", "Active border gradient angle", 0, 360, 1, 0),
    ],
    "Lock Screen": [
        ("lock_blur_passes", "Blur passes", 0, 10, 1, 0),
        ("lock_blur_size", "Blur size", 0, 20, 1, 0),
        ("lock_blur_vibrancy", "Blur vibrancy", 0, 1, 0.01, 4),
        ("lock_bg_opacity", "Input field background opacity", 0, 1, 0.01, 2),
    ],
    "Fonts": [
        ("font_size_waybar", "Taskbar font size", 8, 24, 1, 0),
        ("font_size_wofi", "App launcher font size", 8, 24, 1, 0),
        ("font_size_mako", "Notification font size", 8, 24, 1, 0),
    ],
}


DEFAULT_THEME = {
    "glass_bg": "12141a", "glass_bg_active": "232630",
    "glass_text": "e6e6e6", "glass_text_active": "ffffff",
    "glass_border": "ffffff", "accent": "e67878",
    "opacity_idle": 0.55, "opacity_active": 0.85,
    "border_opacity_idle": 0.08, "border_opacity_active": 0.25,
    "radius": 12,
    "font_family": "JetBrainsMono Nerd Font",
    "font_size_waybar": 13, "font_size_wofi": 14, "font_size_mako": 11,
    "kitty_opacity": 0.7643,
    "hypr_gaps_in": 5, "hypr_gaps_out": 12, "hypr_border_size": 2,
    "hypr_active_border_1": "8090a0", "hypr_active_border_2": "c0a0b0",
    "hypr_active_border_angle": 45, "hypr_inactive_border": "1d2021",
    "hypr_rounding": 12, "hypr_active_opacity": 0.92, "hypr_inactive_opacity": 0.85,
    "hypr_blur_size": 6, "hypr_blur_passes": 3, "hypr_blur_vibrancy": 0.2,
    "lock_blur_passes": 3, "lock_blur_size": 8, "lock_blur_vibrancy": 0.1696,
    "lock_bg_opacity": 0.7,
    "wallpaper": "~/Pictures/Wallpapers/default.png",
}


def atomic_write_json(path, data):
    """Write via a temp file + os.replace so a crash/kill mid-write can
    never leave a truncated, unparseable theme.json on disk."""
    tmp_path = f"{path}.tmp{os.getpid()}"
    with open(tmp_path, "w") as f:
        json.dump(data, f, indent=4)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, path)


def load_theme(path):
    """Load theme.json, self-healing if it's missing or corrupted instead
    of crashing the window mid-construction (which used to leave a blank,
    unpainted GTK surface -- a silent white-screen hang)."""
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        if os.path.exists(path):
            corrupt_path = path + ".corrupt"
            try:
                os.replace(path, corrupt_path)
                print(f"theme.json was invalid ({e}); backed up to {corrupt_path} and reset to defaults.",
                      file=sys.stderr)
            except OSError:
                pass
        theme = dict(DEFAULT_THEME)
        atomic_write_json(path, theme)
        return theme


def hex_to_rgba(h):
    h = h.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    rgba = Gdk.RGBA()
    rgba.red, rgba.green, rgba.blue, rgba.alpha = r, g, b, 1.0
    return rgba


def rgba_to_hex(rgba):
    return "{:02x}{:02x}{:02x}".format(
        round(rgba.red * 255), round(rgba.green * 255), round(rgba.blue * 255)
    )


class ThemeWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Rice Theme")
        self.set_default_size(560, 720)

        # Super+C (this rice's WM close-window keybind) force-kills the
        # Wayland surface at the compositor level without the normal
        # xdg_toplevel close handshake, so GTK's close-request signal never
        # fires and the process is left running invisibly. Escape gives a
        # guaranteed clean close from inside the app instead.
        escape_controller = Gtk.EventControllerKey()
        escape_controller.connect("key-pressed", self._on_key_pressed)
        self.add_controller(escape_controller)

        self.theme = load_theme(THEME_JSON)
        self.dirty = False
        self.color_widgets = {}
        self.spin_widgets = {}
        self.font_row = None

        toolbar_view = Adw.ToolbarView()
        header = Adw.HeaderBar()
        toolbar_view.add_top_bar(header)

        self.apply_btn = Gtk.Button(label="Apply")
        self.apply_btn.add_css_class("suggested-action")
        self.apply_btn.connect("clicked", self.on_apply)
        header.pack_end(self.apply_btn)

        revert_btn = Gtk.Button(label="Revert")
        revert_btn.connect("clicked", self.on_revert)
        header.pack_start(revert_btn)

        scroller = Gtk.ScrolledWindow()
        page = Adw.PreferencesPage()
        scroller.set_child(page)
        toolbar_view.set_content(scroller)
        self.set_content(toolbar_view)

        self.build_presets_group(page)
        self.build_colors_group(page, "Glass Palette", COLOR_FIELDS)
        self.build_colors_group(page, "Window Border Gradient", HYPR_COLOR_FIELDS)
        for title, fields in SPIN_FIELDS.items():
            self.build_spin_group(page, title, fields)
        self.build_font_group(page)
        self.build_wallpaper_group(page)

    # ---- generic row builders ----

    def mark_dirty(self):
        self.dirty = True
        self.apply_btn.set_label("Apply*")

    def build_colors_group(self, page, title, fields):
        group = Adw.PreferencesGroup(title=title)
        page.add(group)
        for key, name, subtitle in fields:
            row = Adw.ActionRow(title=name, subtitle=subtitle)
            btn = Gtk.ColorDialogButton(dialog=Gtk.ColorDialog())
            btn.set_rgba(hex_to_rgba(self.theme[key]))
            btn.set_valign(Gtk.Align.CENTER)

            def on_notify(b, _pspec, key=key):
                self.theme[key] = rgba_to_hex(b.get_rgba())
                self.mark_dirty()

            btn.connect("notify::rgba", on_notify)
            row.add_suffix(btn)
            group.add(row)
            self.color_widgets[key] = btn

    def build_spin_group(self, page, title, fields):
        group = Adw.PreferencesGroup(title=title)
        page.add(group)
        for key, name, minv, maxv, step, digits in fields:
            adj = Gtk.Adjustment(value=self.theme[key], lower=minv, upper=maxv,
                                  step_increment=step, page_increment=step * 5)
            row = Adw.SpinRow(title=name, adjustment=adj, digits=digits)
            row.set_value(self.theme[key])

            def on_changed(r, key=key):
                self.theme[key] = round(r.get_value(), 4)
                self.mark_dirty()

            row.connect("notify::value", on_changed)
            group.add(row)
            self.spin_widgets[key] = row

    def build_font_group(self, page):
        group = Adw.PreferencesGroup(title="Font")
        page.add(group)
        row = Adw.EntryRow(title="Font family")
        row.set_text(self.theme["font_family"])

        def on_changed(r):
            self.theme["font_family"] = r.get_text()
            self.mark_dirty()

        row.connect("changed", on_changed)
        group.add(row)
        self.font_row = row

    def build_wallpaper_group(self, page):
        group = Adw.PreferencesGroup(title="Wallpaper")
        page.add(group)
        self.wallpaper_row = Adw.ActionRow(
            title="Current wallpaper", subtitle=self.theme["wallpaper"]
        )
        btn = Gtk.Button(label="Choose...")
        btn.set_valign(Gtk.Align.CENTER)
        btn.connect("clicked", self.on_choose_wallpaper)
        self.wallpaper_row.add_suffix(btn)
        group.add(self.wallpaper_row)

    def on_choose_wallpaper(self, _btn):
        dialog = Gtk.FileDialog(title="Choose wallpaper")
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
                path = gfile.get_path()
                self.theme["wallpaper"] = path
                self.wallpaper_row.set_subtitle(path)
                self.mark_dirty()

        dialog.open(self, None, on_done)

    def build_presets_group(self, page):
        group = Adw.PreferencesGroup(title="Presets")
        page.add(group)

        names = list(BUILTIN_PRESETS.keys())
        os.makedirs(PRESETS_DIR, exist_ok=True)
        for fname in sorted(os.listdir(PRESETS_DIR)):
            if fname.endswith(".json"):
                names.append(fname[:-5])

        self.preset_model = Gtk.StringList.new(names)
        combo = Adw.ComboRow(title="Load preset", model=self.preset_model)
        combo.connect("notify::selected", self.on_preset_selected)
        group.add(combo)
        self.preset_combo = combo

        save_row = Adw.EntryRow(title="Save current theme as...")
        save_btn = Gtk.Button(icon_name="document-save-symbolic")
        save_btn.set_valign(Gtk.Align.CENTER)
        save_btn.add_css_class("flat")

        def on_save(_btn):
            name = save_row.get_text().strip()
            if not name:
                return
            path = os.path.join(PRESETS_DIR, name + ".json")
            atomic_write_json(path, self.theme)
            self.preset_model.append(name)
            save_row.set_text("")

        save_btn.connect("clicked", on_save)
        save_row.add_suffix(save_btn)
        group.add(save_row)

    def on_preset_selected(self, combo, _pspec):
        idx = combo.get_selected()
        if idx == Gtk.INVALID_LIST_POSITION:
            return
        name = self.preset_model.get_string(idx)
        if name in BUILTIN_PRESETS:
            overrides = BUILTIN_PRESETS[name]
        else:
            path = os.path.join(PRESETS_DIR, name + ".json")
            if not os.path.exists(path):
                return
            with open(path) as f:
                overrides = json.load(f)
        self.theme.update(overrides)
        self.sync_ui_from_theme()
        self.mark_dirty()

    def sync_ui_from_theme(self):
        for key, btn in self.color_widgets.items():
            if key in self.theme:
                btn.set_rgba(hex_to_rgba(self.theme[key]))
        for key, row in self.spin_widgets.items():
            if key in self.theme:
                row.set_value(self.theme[key])
        if self.font_row is not None:
            self.font_row.set_text(self.theme["font_family"])
        self.wallpaper_row.set_subtitle(self.theme["wallpaper"])

    def _on_key_pressed(self, _controller, keyval, _keycode, _state):
        if keyval == Gdk.KEY_Escape:
            self.close()
            return True
        return False

    def on_revert(self, _btn):
        self.theme = load_theme(THEME_JSON)
        self.dirty = False
        self.apply_btn.set_label("Apply")
        self.sync_ui_from_theme()

    def on_apply(self, _btn):
        atomic_write_json(THEME_JSON, self.theme)
        self.apply_btn.set_sensitive(False)
        self.apply_btn.set_label("Applying...")

        def run():
            try:
                subprocess.run([sys.executable, APPLY_SCRIPT, THEME_JSON], timeout=15)
            except subprocess.TimeoutExpired:
                pass
            GLib.idle_add(self.on_applied)

        import threading
        threading.Thread(target=run, daemon=True).start()

    def on_applied(self):
        self.dirty = False
        self.apply_btn.set_sensitive(True)
        self.apply_btn.set_label("Apply")
        return False


class ThemeApp(Adw.Application):
    def __init__(self):
        # NON_UNIQUE: this is launched ad-hoc from a keybind, not a
        # session-integrated single-instance app. Without this flag, a
        # window force-closed by the compositor (e.g. Super+C) while a
        # background reload is still running can leave a stuck instance
        # registered on the session bus -- the next launch then silently
        # reactivates that dead instance instead of opening a fresh one.
        super().__init__(application_id="dev.dexo.RiceTheme",
                          flags=Gio.ApplicationFlags.NON_UNIQUE)

    def do_activate(self):
        win = self.props.active_window
        if not win:
            win = ThemeWindow(self)
            win.connect("close-request", self._on_close_request)
        win.present()

    def _on_close_request(self, _win):
        self.quit()
        return False


if __name__ == "__main__":
    app = ThemeApp()
    app.run(sys.argv)
