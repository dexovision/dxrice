#!/usr/bin/env python3
"""GTK4/Adwaita settings app for the rice's theme.json.

Edits ~/.config/dxrice/theme.json (seeded from <repo>/theme/theme.json the
first time it's needed -- see dxrice_apply_theme.ensure_live_theme) and
calls dxrice_apply_theme.py to render + hot-reload
waybar/wofi/mako/kitty/hyprlock/hyprland.lua. The repo's own theme.json is
only ever read as that seed, never written back to, so your color/opacity/
radius tweaks never show up as a dirty tracked file in your own checkout --
the same separation used for waybar/config and taskbar shortcuts. <repo> is
this script's own parent-of-parent directory -- it runs straight out of the
git checkout (never copied elsewhere), so it always finds its own files no
matter where that checkout lives.

Shares the same .dx-* CSS design system (theme/dxrice_gtk_style.css.template)
as dxrice_taskbar_gui.py and dxrice_quick_settings.py, loaded from
~/.config/dxrice/gtk_style.css, so this app actually looks like the theme
it edits instead of stock GNOME Adwaita.
"""
import json
import os
import shutil
import subprocess
import sys
import threading

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPTS_DIR)
import dxrice_apply_theme as apply_theme
from dxrice_gtk_widgets import (
    label as _label, load_css, make_card, make_debounced, make_row, make_section_title,
)

HOME = os.path.expanduser("~")
REPO = os.path.dirname(SCRIPTS_DIR)
THEME_DIR = os.path.join(REPO, "theme")
THEME_JSON = apply_theme.ensure_live_theme()
PRESETS_DIR = os.path.join(HOME, ".config", "dxrice", "presets")
APPLY_SCRIPT = os.path.join(SCRIPTS_DIR, "dxrice_apply_theme.py")
SYNC_SDDM_SCRIPT = os.path.join(SCRIPTS_DIR, "dxrice_sync_sddm_theme.py")
CSS_PATH = os.path.join(HOME, ".config", "dxrice", "gtk_style.css")

BUILTIN_PRESETS = {
    "Glass Charcoal": {
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
    ("accent", "Accent", "Critical notifications, tray alerts, mute/destructive actions"),
]

HYPR_COLOR_FIELDS = [
    ("hypr_active_border_1", "Active border -- color 1", "Focused window border gradient start"),
    ("hypr_active_border_2", "Active border -- color 2", "Focused window border gradient end"),
    ("hypr_inactive_border", "Inactive border", "Unfocused window border"),
]

SLIDER_GROUPS = [
    ("Transparency and Blur", [
        ("opacity_idle", "Panel opacity (idle)", 0, 1, 0.01, 2),
        ("opacity_active", "Panel opacity (active)", 0, 1, 0.01, 2),
        ("border_opacity_idle", "Border opacity (idle)", 0, 1, 0.01, 2),
        ("border_opacity_active", "Border opacity (active)", 0, 1, 0.01, 2),
        ("kitty_opacity", "Terminal opacity", 0, 1, 0.01, 2),
        ("hypr_blur_size", "Window blur size", 0, 20, 1, 0),
        ("hypr_blur_passes", "Window blur passes", 0, 10, 1, 0),
        ("hypr_blur_vibrancy", "Window blur vibrancy", 0, 1, 0.01, 2),
    ]),
    ("Layout", [
        ("radius", "Panel corner radius", 0, 30, 1, 0),
        ("hypr_rounding", "Window corner rounding", 0, 30, 1, 0),
        ("hypr_gaps_in", "Gaps between windows", 0, 40, 1, 0),
        ("hypr_gaps_out", "Gaps to screen edge", 0, 60, 1, 0),
        ("hypr_border_size", "Window border thickness", 0, 10, 1, 0),
        ("hypr_active_opacity", "Focused window opacity", 0, 1, 0.01, 2),
        ("hypr_inactive_opacity", "Unfocused window opacity", 0, 1, 0.01, 2),
        ("hypr_active_border_angle", "Active border gradient angle", 0, 360, 1, 0),
    ]),
    ("Lock Screen", [
        ("lock_blur_passes", "Blur passes", 0, 10, 1, 0),
        ("lock_blur_size", "Blur size", 0, 20, 1, 0),
        ("lock_blur_vibrancy", "Blur vibrancy", 0, 1, 0.01, 4),
        ("lock_bg_opacity", "Input field background opacity", 0, 1, 0.01, 2),
    ]),
    ("Fonts", [
        ("font_size_waybar", "Taskbar text size", 8, 24, 1, 0),
        ("font_size_waybar_icons", "Taskbar app icon size", 8, 40, 1, 0),
        ("font_size_wofi", "App launcher font size", 8, 24, 1, 0),
        ("font_size_mako", "Notification font size", 8, 24, 1, 0),
    ]),
    ("Experience", [
        ("anim_duration_ms", "Animation speed (ms, lower = snappier)", 0, 500, 10, 0),
        ("ui_density", "Settings app spacing", 0.5, 1.5, 0.05, 2),
    ]),
]


DEFAULT_THEME = {
    "glass_bg": "12141a", "glass_bg_active": "232630",
    "glass_text": "e6e6e6", "glass_text_active": "ffffff",
    "glass_border": "ffffff", "accent": "e67878",
    "opacity_idle": 0.55, "opacity_active": 0.85,
    "border_opacity_idle": 0.08, "border_opacity_active": 0.25,
    "radius": 12,
    "font_family": "JetBrainsMono Nerd Font",
    "font_size_waybar": 13, "font_size_waybar_icons": 22,
    "font_size_wofi": 14, "font_size_mako": 11,
    "kitty_opacity": 0.7643,
    "hypr_gaps_in": 5, "hypr_gaps_out": 12, "hypr_border_size": 2,
    "hypr_active_border_1": "8090a0", "hypr_active_border_2": "c0a0b0",
    "hypr_active_border_angle": 45, "hypr_inactive_border": "1d2021",
    "hypr_rounding": 12, "hypr_active_opacity": 0.92, "hypr_inactive_opacity": 0.85,
    "hypr_blur_size": 6, "hypr_blur_passes": 3, "hypr_blur_vibrancy": 0.2,
    "lock_blur_passes": 3, "lock_blur_size": 8, "lock_blur_vibrancy": 0.1696,
    "lock_bg_opacity": 0.7,
    "wallpaper": "~/Pictures/Wallpapers/default.png",
    "anim_duration_ms": 150,
    "ui_density": 1.0,
}


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------

def atomic_write_json(path, data):
    """Write via a temp file + os.replace so a crash/kill mid-write can
    never leave a truncated, unparseable theme.json on disk."""
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


def load_theme(path):
    """Load theme.json, self-healing if it's missing or corrupted instead
    of crashing the window mid-construction (which used to leave a blank,
    unpainted GTK surface -- a silent white-screen hang). Missing newer
    fields (added after a user's theme.json was created) are backfilled
    from DEFAULT_THEME rather than KeyError-ing the first time a slider
    reads them."""
    try:
        with open(path) as f:
            theme = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        if os.path.exists(path):
            corrupt_path = path + ".corrupt"
            try:
                os.replace(path, corrupt_path)
                print(f"theme.json was invalid ({e}); backed up to {corrupt_path} and reset to defaults.",
                      file=sys.stderr)
            except OSError:
                pass
        theme = {}
    changed = False
    for key, value in DEFAULT_THEME.items():
        if key not in theme:
            theme[key] = value
            changed = True
    if changed:
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


def render_preview_css(theme):
    """Builds a tiny CSS string for the live-preview mockup using the exact
    same token math as the real theme pipeline (dxrice_apply_theme.build_vars),
    so the preview never quietly drifts from what Apply will actually
    produce. Scoped to the preview widget only (see PreviewPanel), not
    loaded globally -- it must never affect this app's own chrome, which
    stays on the last *applied* theme until you actually hit Apply."""
    v = apply_theme.build_vars(theme)
    gap = theme.get("hypr_gaps_in", 5)
    return f"""
    .dx-preview-bar {{
        background-color: rgba({v['BG_R']}, {v['BG_G']}, {v['BG_B']}, {v['OPACITY_ACTIVE']});
        border: 1px solid rgba({v['BORDER_R']}, {v['BORDER_G']}, {v['BORDER_B']}, {v['BORDER_OPACITY_ACTIVE']});
        border-radius: {v['RADIUS']}px;
        color: {v['TEXT_COLOR']};
        padding: 6px 10px;
    }}
    .dx-preview-bar-chip {{
        background-color: rgba({v['ACTIVE_R']}, {v['ACTIVE_G']}, {v['ACTIVE_B']}, {v['OPACITY_ACTIVE']});
        color: {v['TEXT_ACTIVE_COLOR']};
        border-radius: {v['ENTRY_RADIUS']}px;
        padding: 2px 8px;
    }}
    .dx-preview-gradient-border {{
        background-image: linear-gradient({theme.get('hypr_active_border_angle', 45)}deg,
            #{theme['hypr_active_border_1']}, #{theme['hypr_active_border_2']});
        border-radius: {theme.get('hypr_rounding', 12)}px;
        padding: {max(1, theme.get('hypr_border_size', 2))}px;
    }}
    .dx-preview-window {{
        background-color: rgba({v['ACTIVE_R']}, {v['ACTIVE_G']}, {v['ACTIVE_B']}, {theme.get('hypr_active_opacity', 0.92)});
        border-radius: {max(0, theme.get('hypr_rounding', 12) - 1)}px;
        color: {v['TEXT_COLOR']};
        min-height: 64px;
        padding: {gap}px;
    }}
    .dx-preview-notif {{
        background-color: rgba({v['BG_R']}, {v['BG_G']}, {v['BG_B']}, {v['OPACITY_ACTIVE']});
        border: 1px solid #{theme['accent']};
        border-radius: {v['RADIUS']}px;
        color: {v['TEXT_COLOR']};
        padding: 6px 10px;
    }}
    .dx-preview-accent-dot {{
        background-color: #{theme['accent']};
        border-radius: 999px;
        min-width: 8px;
        min-height: 8px;
    }}
    """


# ---------------------------------------------------------------------------
# UI helpers (shared style with dxrice_taskbar_gui.py / dxrice_quick_settings.py)
# ---------------------------------------------------------------------------

def make_color_button(initial_hex, on_change):
    btn = Gtk.ColorDialogButton(dialog=Gtk.ColorDialog())
    btn.set_rgba(hex_to_rgba(initial_hex))
    btn.set_valign(Gtk.Align.CENTER)
    btn.connect("notify::rgba", lambda b, _p: on_change(rgba_to_hex(b.get_rgba())))
    return btn


def make_slider_control(initial, minv, maxv, step, digits, on_change):
    scale = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL, hexpand=True)
    scale.set_range(minv, maxv)
    scale.set_value(initial)
    scale.set_draw_value(False)
    scale.set_size_request(90, -1)

    fmt = f"{{:.{digits}f}}" if digits else "{:.0f}"
    val_label = _label(fmt.format(initial), ellipsize=False)
    val_label.set_width_chars(5)
    val_label.set_xalign(1.0)

    debounced = make_debounced(on_change)

    def _on_value_changed(s):
        v = s.get_value()
        val_label.set_label(fmt.format(v))
        debounced(v)

    scale.connect("value-changed", _on_value_changed)

    box = Gtk.Box(spacing=8)
    box.append(scale)
    box.append(val_label)
    return box, scale, val_label


class PreviewPanel(Gtk.Box):
    """A small mockup of a waybar-like bar, a focused window's border, and
    a notification -- restyled live from *draft* theme values via a CSS
    provider scoped to just this widget, so editing sliders shows the
    effect immediately without ever touching the real, applied theme
    until Apply is actually pressed."""

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.add_css_class("dx-preview-frame")
        self._provider = Gtk.CssProvider()
        self.get_style_context().add_provider(self._provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        bar = Gtk.Box(spacing=8)
        bar.add_css_class("dx-preview-bar")
        launcher = _label("", ellipsize=False)
        bar.append(launcher)
        chip = _label("Firefox", "dx-preview-bar-chip", ellipsize=False)
        bar.append(chip)
        clock = _label("12:34", ellipsize=False)
        clock.set_hexpand(True)
        clock.set_xalign(0.5)
        bar.append(clock)
        vol = _label("Vol 72%", "dx-preview-bar-chip", ellipsize=False)
        bar.append(vol)
        self.append(bar)

        gradient_wrap = Gtk.Box()
        gradient_wrap.add_css_class("dx-preview-gradient-border")
        window_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, hexpand=True)
        window_box.add_css_class("dx-preview-window")
        window_box.append(_label("Focused Window", ellipsize=False))
        gradient_wrap.append(window_box)
        self.append(gradient_wrap)

        notif = Gtk.Box(spacing=8)
        notif.add_css_class("dx-preview-notif")
        dot = Gtk.Box()
        dot.add_css_class("dx-preview-accent-dot")
        dot.set_valign(Gtk.Align.CENTER)
        notif.append(dot)
        notif.append(_label("Notification -- new message", ellipsize=False))
        self.append(notif)

    def update(self, theme):
        css = render_preview_css(theme)
        self._provider.load_from_data(css.encode())


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

PANEL_WIDTH = 460


class ThemeWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="DXrice Theme")
        self.set_default_size(PANEL_WIDTH, 780)

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
        self.color_buttons = {}
        self.slider_controls = {}
        self.font_entry = None

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        root.add_css_class("dx-root")
        self.set_content(root)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        header.add_css_class("dx-header")
        title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True)
        title_box.append(_label("Theme", "dx-header-title", ellipsize=False))
        title_box.append(_label("Applies to waybar, wofi, mako, kitty, hyprlock, and Hyprland itself",
                                 "dx-header-subtitle", max_width_chars=34))
        header.append(title_box)

        revert_btn = Gtk.Button(label="Revert")
        revert_btn.add_css_class("dx-btn-secondary")
        revert_btn.connect("clicked", self.on_revert)
        header.append(revert_btn)

        self.apply_btn = Gtk.Button(label="Apply")
        self.apply_btn.add_css_class("dx-btn-primary")
        self.apply_btn.connect("clicked", self.on_apply)
        header.append(self.apply_btn)

        close_btn = Gtk.Button(icon_name="window-close-symbolic")
        close_btn.add_css_class("dx-close")
        close_btn.connect("clicked", lambda b: self.close())
        header.append(close_btn)

        root.append(header)

        scroller = Gtk.ScrolledWindow()
        scroller.set_vexpand(True)
        root.append(scroller)

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        body.add_css_class("dx-body")
        scroller.set_child(body)

        body.append(make_section_title("Live Preview"))
        self.preview = PreviewPanel()
        preview_card = make_card()
        preview_card.append(self.preview)
        body.append(preview_card)

        body.append(make_section_title("Presets"))
        body.append(self.build_presets_card())

        body.append(make_section_title("Glass Palette"))
        body.append(self.build_colors_card(COLOR_FIELDS))

        body.append(make_section_title("Window Border Gradient"))
        body.append(self.build_colors_card(HYPR_COLOR_FIELDS))

        for title, fields in SLIDER_GROUPS:
            body.append(make_section_title(title))
            body.append(self.build_sliders_card(fields))

        body.append(make_section_title("Font"))
        body.append(self.build_font_card())

        body.append(make_section_title("Wallpaper"))
        body.append(self.build_wallpaper_card())

        if shutil.which("sddm"):
            body.append(make_section_title("Login Screen"))
            body.append(self.build_sddm_card())

        self.refresh_preview()

    # ---- state ----

    def mark_dirty(self):
        self.dirty = True
        self.apply_btn.set_label("Apply*")

    def refresh_preview(self):
        self.preview.update(self.theme)

    def on_field_changed(self, key, value):
        self.theme[key] = value
        self.mark_dirty()
        self.refresh_preview()

    # ---- cards ----

    def build_colors_card(self, fields):
        card = make_card()
        for key, name, subtitle in fields:
            row, _ = make_row(name, subtitle)
            btn = make_color_button(self.theme[key], lambda hexval, k=key: self.on_field_changed(k, hexval))
            row.append(btn)
            card.append(row)
            self.color_buttons[key] = btn
        return card

    def build_sliders_card(self, fields):
        card = make_card()
        for key, name, minv, maxv, step, digits in fields:
            row, _ = make_row(name)

            def _on_change(v, k=key, d=digits):
                self.on_field_changed(k, int(round(v)) if d == 0 else round(v, 4))

            control, scale, val_label = make_slider_control(
                self.theme[key], minv, maxv, step, digits, _on_change)
            row.append(control)
            card.append(row)
            self.slider_controls[key] = (scale, val_label, digits)
        return card

    def build_font_card(self):
        card = make_card()
        row, _ = make_row("Font family")
        entry = Gtk.Entry()
        entry.add_css_class("dx-entry")
        entry.set_text(self.theme["font_family"])
        entry.set_hexpand(True)
        entry.connect("changed", lambda e: self.on_field_changed("font_family", e.get_text()))
        row.append(entry)
        card.append(row)
        self.font_entry = entry
        return card

    def build_wallpaper_card(self):
        card = make_card()
        row, self.wallpaper_text = make_row("Current wallpaper", self.theme["wallpaper"])
        btn = Gtk.Button(label="Choose...")
        btn.add_css_class("dx-btn-secondary")
        btn.set_valign(Gtk.Align.CENTER)
        btn.connect("clicked", self.on_choose_wallpaper)
        row.append(btn)
        card.append(row)
        return card

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
                self.wallpaper_text.get_last_child().set_label(path)
                self.mark_dirty()

        dialog.open(self, None, on_done)

    def build_sddm_card(self):
        card = make_card()
        row, _ = make_row("Sync login screen",
                           "Applies your current colors/wallpaper to the SDDM login theme")
        self.sddm_sync_btn = Gtk.Button(label="Sync Now")
        self.sddm_sync_btn.add_css_class("dx-btn-secondary")
        self.sddm_sync_btn.set_valign(Gtk.Align.CENTER)
        self.sddm_sync_btn.connect("clicked", self.on_sync_sddm)
        row.append(self.sddm_sync_btn)
        card.append(row)
        return card

    def on_sync_sddm(self, _btn):
        if not shutil.which("pkexec"):
            print(f"pkexec not found -- run manually: sudo python3 {SYNC_SDDM_SCRIPT}", file=sys.stderr)
            self.sddm_sync_btn.set_label("No pkexec -- see log")
            return
        self.sddm_sync_btn.set_sensitive(False)
        self.sddm_sync_btn.set_label("Syncing...")

        def run():
            try:
                result = subprocess.run(
                    ["pkexec", sys.executable, SYNC_SDDM_SCRIPT],
                    capture_output=True, text=True, timeout=60,
                )
                ok = result.returncode == 0
                if not ok:
                    print(result.stdout, result.stderr, file=sys.stderr)
            except (subprocess.TimeoutExpired, OSError) as e:
                print(f"SDDM sync failed: {e}", file=sys.stderr)
                ok = False
            GLib.idle_add(self.on_sddm_synced, ok)

        threading.Thread(target=run, daemon=True).start()

    def on_sddm_synced(self, ok):
        self.sddm_sync_btn.set_sensitive(True)
        self.sddm_sync_btn.set_label("Synced" if ok else "Failed -- see log")
        if ok:
            GLib.timeout_add(2500, lambda: (self.sddm_sync_btn.set_label("Sync Now"), False)[1])
        return False

    def build_presets_card(self):
        card = make_card()

        flow = Gtk.FlowBox()
        flow.set_selection_mode(Gtk.SelectionMode.NONE)
        flow.set_max_children_per_line(2)
        flow.set_min_children_per_line(1)
        flow.set_row_spacing(8)
        flow.set_column_spacing(8)
        flow.set_homogeneous(True)

        self.preset_swatch_buttons = []

        def add_swatch(name, colors):
            btn = Gtk.Button()
            btn.add_css_class("dx-swatch")
            inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            swatch_row = Gtk.Box(spacing=2, homogeneous=True)
            for hexcol in (colors["glass_bg"], colors["accent"], colors["hypr_active_border_1"]):
                chip = Gtk.Box()
                chip.add_css_class("dx-swatch-preview")
                chip.get_style_context().add_provider(
                    _solid_color_provider(hexcol), Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
                swatch_row.append(chip)
            inner.append(swatch_row)
            inner.append(_label(name, "dx-swatch-label", ellipsize=False))
            btn.set_child(inner)
            btn.connect("clicked", lambda b, c=colors: self.on_preset_selected(c))
            flow.append(btn)
            self.preset_swatch_buttons.append(btn)

        for name, colors in BUILTIN_PRESETS.items():
            add_swatch(name, colors)

        os.makedirs(PRESETS_DIR, exist_ok=True)
        for fname in sorted(os.listdir(PRESETS_DIR)):
            if fname.endswith(".json"):
                name = fname[:-5]
                try:
                    with open(os.path.join(PRESETS_DIR, fname)) as f:
                        colors = json.load(f)
                    add_swatch(name, colors)
                except (OSError, json.JSONDecodeError, KeyError):
                    continue

        card.append(flow)

        save_row = Gtk.Box(spacing=8)
        save_row.set_margin_top(8)
        save_entry = Gtk.Entry(placeholder_text="Save current theme as...")
        save_entry.add_css_class("dx-entry")
        save_entry.set_hexpand(True)
        save_row.append(save_entry)
        save_btn = Gtk.Button(icon_name="document-save-symbolic")
        save_btn.add_css_class("dx-icon-btn")
        save_btn.set_valign(Gtk.Align.CENTER)

        def on_save(_btn):
            name = save_entry.get_text().strip()
            if not name:
                return
            path = os.path.join(PRESETS_DIR, name + ".json")
            atomic_write_json(path, self.theme)
            save_entry.set_text("")

        save_btn.connect("clicked", on_save)
        save_row.append(save_btn)
        card.append(save_row)

        return card

    def on_preset_selected(self, overrides):
        self.theme.update(overrides)
        self.sync_ui_from_theme()
        self.mark_dirty()
        self.refresh_preview()

    def sync_ui_from_theme(self):
        for key, btn in self.color_buttons.items():
            if key in self.theme:
                btn.set_rgba(hex_to_rgba(self.theme[key]))
        for key, (scale, val_label, digits) in self.slider_controls.items():
            if key in self.theme:
                scale.set_value(self.theme[key])
                fmt = f"{{:.{digits}f}}" if digits else "{:.0f}"
                val_label.set_label(fmt.format(self.theme[key]))
        if self.font_entry is not None:
            self.font_entry.set_text(self.theme["font_family"])
        self.wallpaper_text.get_last_child().set_label(self.theme["wallpaper"])

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
        self.refresh_preview()

    def on_apply(self, _btn):
        try:
            atomic_write_json(THEME_JSON, self.theme)
        except Exception as e:
            print(f"Could not save theme.json: {e}", file=sys.stderr)
            self.apply_btn.set_label("Apply (save failed, see log)")
            return
        self.apply_btn.set_sensitive(False)
        self.apply_btn.set_label("Applying...")

        def run():
            try:
                subprocess.run([sys.executable, APPLY_SCRIPT, THEME_JSON], timeout=15)
            except subprocess.TimeoutExpired:
                pass
            GLib.idle_add(self.on_applied)

        threading.Thread(target=run, daemon=True).start()

    def on_applied(self):
        self.dirty = False
        self.apply_btn.set_sensitive(True)
        self.apply_btn.set_label("Apply")
        return False


def _solid_color_provider(hexcol):
    provider = Gtk.CssProvider()
    provider.load_from_data(f"box {{ background-color: #{hexcol}; }}".encode())
    return provider


class ThemeApp(Adw.Application):
    def __init__(self):
        # NON_UNIQUE: this is launched ad-hoc from a keybind, not a
        # session-integrated single-instance app. Without this flag, a
        # window force-closed by the compositor (e.g. Super+C) while a
        # background reload is still running can leave a stuck instance
        # registered on the session bus -- the next launch then silently
        # reactivates that dead instance instead of opening a fresh one.
        super().__init__(application_id="dev.dexo.DXrice",
                          flags=Gio.ApplicationFlags.NON_UNIQUE)

    def do_startup(self):
        Adw.Application.do_startup(self)
        load_css(CSS_PATH)

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
