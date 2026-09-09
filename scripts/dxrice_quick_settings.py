#!/usr/bin/env python3
"""DXrice Quick Settings -- a layer-shell control center panel.

Opened by clicking the volume/wifi/CPU/RAM cluster in waybar (SUPER+Shift+A
opens the taskbar manager instead; this is its own thing). Docks under the
top-right corner of the bar via gtk4-layer-shell instead of opening as a
normal window. A second launch while one is already open closes it instead
of opening a duplicate (see the PID-file toggle at the bottom).

Sections: volume + output device, mic + input device, wifi, bluetooth,
brightness (only if a backlight exists), live CPU/RAM/disk, and power
actions (lock/logout/reboot/shutdown).
"""
import os
import sys


def _ensure_layer_shell_preloaded():
    """gtk4-layer-shell works by intercepting GDK's Wayland setup at the
    shared library level, which only works if it's loaded (via LD_PRELOAD)
    before GTK touches the display connection at all -- too late to fix
    once a window/app object exists. Only relevant when this script is
    actually run (not when imported, e.g. for testing its plain functions),
    so this is called from __main__ below, before main() touches GTK."""
    if os.environ.get("DXRICE_LAYER_SHELL_PRELOADED"):
        return
    lib = next((p for p in (
        "/usr/lib/libgtk4-layer-shell.so",
        "/usr/lib64/libgtk4-layer-shell.so",
        "/usr/lib/x86_64-linux-gnu/libgtk4-layer-shell.so",
    ) if os.path.exists(p)), None)
    if not lib:
        return
    env = os.environ.copy()
    existing = env.get("LD_PRELOAD", "")
    env["LD_PRELOAD"] = f"{lib}:{existing}" if existing else lib
    env["DXRICE_LAYER_SHELL_PRELOADED"] = "1"
    os.execvpe(sys.executable, [sys.executable, os.path.abspath(__file__)] + sys.argv[1:], env)


# Called here, before `import gi` below, so the (common) case of a missing
# preload re-execs immediately instead of first paying for a full GTK/Adwaita
# import in this doomed process and then paying it again in the real one.
if __name__ == "__main__":
    _ensure_layer_shell_preloaded()

import re
import shutil
import signal
import subprocess
import threading
import time

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
gi.require_version("Gtk4LayerShell", "1.0")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Gtk4LayerShell, Pango

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dxrice_gtk_widgets import label as _label, load_css, make_card, make_debounced

HOME = os.path.expanduser("~")
PID_FILE = "/tmp/dxrice-quick-settings.pid"
CSS_PATH = os.path.join(HOME, ".config", "dxrice", "gtk_style.css")


def run(args, timeout=3):
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except (subprocess.TimeoutExpired, OSError):
        return None


def run_ok(args, timeout=5):
    r = run(args, timeout=timeout)
    return bool(r and r.returncode == 0)


# ---------------------------------------------------------------------------
# Audio (wpctl)
# ---------------------------------------------------------------------------

def get_volume(node="@DEFAULT_AUDIO_SINK@"):
    r = run(["wpctl", "get-volume", node])
    if not r or r.returncode != 0:
        return 0, False
    m = re.search(r"Volume:\s*([\d.]+)(\s*\[MUTED\])?", r.stdout)
    if not m:
        return 0, False
    return round(float(m.group(1)) * 100), bool(m.group(2))


def set_volume(node, percent):
    percent = max(0, min(150, percent))
    run_ok(["wpctl", "set-volume", node, f"{percent}%"])


def toggle_mute(node):
    run_ok(["wpctl", "set-mute", node, "toggle"])


def list_audio_devices(kind):
    """kind is 'Sinks' or 'Sources'. Returns [(id, name, is_default), ...]."""
    r = run(["wpctl", "status"])
    if not r or r.returncode != 0:
        return []
    lines = r.stdout.splitlines()
    devices = []
    in_section = False
    for line in lines:
        if re.match(rf"\s*├─\s*{kind}:", line) or re.match(rf"\s*└─\s*{kind}:", line):
            in_section = True
            continue
        if in_section:
            if re.match(r"\s*[├└]─", line):
                break
            m = re.match(r"\s*[│ ]\s*(\*?)\s*(\d+)\.\s*(.+?)\s*\[vol:", line)
            if m:
                star, devid, name = m.groups()
                devices.append((devid, name.strip(), bool(star)))
    return devices


def set_default_device(devid):
    run_ok(["wpctl", "set-default", devid])


# ---------------------------------------------------------------------------
# Wifi (nmcli)
# ---------------------------------------------------------------------------

def wifi_radio_enabled():
    r = run(["nmcli", "radio", "wifi"])
    return bool(r and r.stdout.strip() == "enabled")


def set_wifi_radio(enabled):
    run_ok(["nmcli", "radio", "wifi", "on" if enabled else "off"])


def list_wifi_networks():
    """Returns [(ssid, signal, security, connected), ...], deduped, strongest first."""
    r = run(["nmcli", "-t", "-f", "active,ssid,signal,security", "dev", "wifi", "list"], timeout=8)
    if not r or r.returncode != 0:
        return []
    seen = {}
    for line in r.stdout.splitlines():
        parts = line.split(":")
        if len(parts) < 4 or not parts[1]:
            continue
        active, ssid, signal_str, security = parts[0], parts[1], parts[2], parts[3]
        try:
            sig = int(signal_str)
        except ValueError:
            sig = 0
        connected = active == "yes"
        if ssid not in seen or sig > seen[ssid][1]:
            seen[ssid] = (ssid, sig, security, connected)
    return sorted(seen.values(), key=lambda e: (-e[3], -e[1]))


def has_saved_connection(ssid):
    r = run(["nmcli", "-t", "-f", "NAME", "connection", "show"])
    return bool(r and ssid in r.stdout.splitlines())


def connect_wifi(ssid, password=None):
    if password:
        return run_ok(["nmcli", "device", "wifi", "connect", ssid, "password", password], timeout=15)
    return run_ok(["nmcli", "device", "wifi", "connect", ssid], timeout=15)


def disconnect_wifi():
    run_ok(["nmcli", "device", "disconnect", "wifi"])


# ---------------------------------------------------------------------------
# Bluetooth (bluetoothctl)
# ---------------------------------------------------------------------------

def bluetooth_powered():
    r = run(["bluetoothctl", "show"])
    return bool(r and re.search(r"Powered:\s*yes", r.stdout))


def set_bluetooth_power(on):
    run_ok(["bluetoothctl", "power", "on" if on else "off"])


def list_bluetooth_devices():
    r = run(["bluetoothctl", "devices"])
    if not r or r.returncode != 0:
        return []
    devices = []
    for line in r.stdout.splitlines():
        m = re.match(r"Device\s+(\S+)\s+(.+)", line)
        if m:
            mac, name = m.groups()
            info = run(["bluetoothctl", "info", mac])
            connected = bool(info and re.search(r"Connected:\s*yes", info.stdout))
            devices.append((mac, name, connected))
    return devices


def bluetooth_connect(mac, connect=True):
    run_ok(["bluetoothctl", "connect" if connect else "disconnect", mac], timeout=10)


# ---------------------------------------------------------------------------
# Brightness (brightnessctl) -- only shown if a backlight actually exists
# ---------------------------------------------------------------------------

def has_backlight():
    return shutil.which("brightnessctl") is not None and os.path.isdir("/sys/class/backlight") \
        and bool(os.listdir("/sys/class/backlight"))


def get_brightness_percent():
    r = run(["brightnessctl", "get"])
    m = run(["brightnessctl", "max"])
    if not r or not m:
        return 0
    try:
        return round(int(r.stdout.strip()) / int(m.stdout.strip()) * 100)
    except (ValueError, ZeroDivisionError):
        return 0


def set_brightness_percent(percent):
    run_ok(["brightnessctl", "set", f"{max(1, min(100, percent))}%"])


# ---------------------------------------------------------------------------
# CPU / RAM / disk stats
# ---------------------------------------------------------------------------

def _read_cpu_times():
    with open("/proc/stat") as f:
        fields = f.readline().split()[1:]
    return [int(x) for x in fields]


class CpuMonitor:
    def __init__(self):
        self._prev = _read_cpu_times()

    def sample(self):
        cur = _read_cpu_times()
        prev = self._prev
        self._prev = cur
        prev_idle = prev[3] + prev[4]
        cur_idle = cur[3] + cur[4]
        prev_total = sum(prev)
        cur_total = sum(cur)
        total_delta = cur_total - prev_total
        idle_delta = cur_idle - prev_idle
        if total_delta <= 0:
            return 0.0
        return max(0.0, min(100.0, (total_delta - idle_delta) / total_delta * 100))


def mem_percent():
    info = {}
    with open("/proc/meminfo") as f:
        for line in f:
            key, _, rest = line.partition(":")
            info[key] = int(rest.strip().split()[0])
    total = info.get("MemTotal", 1)
    available = info.get("MemAvailable", total)
    return max(0.0, min(100.0, (total - available) / total * 100))


def disk_percent(path="/"):
    usage = shutil.disk_usage(path)
    return usage.used / usage.total * 100


# ---------------------------------------------------------------------------
# Power actions
# ---------------------------------------------------------------------------

def action_lock():
    subprocess.Popen(["hyprlock"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def action_logout():
    subprocess.Popen(["hyprctl", "dispatch", "exit"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def action_reboot():
    subprocess.Popen(["systemctl", "reboot"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def action_shutdown():
    subprocess.Popen(["systemctl", "poweroff"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# ---------------------------------------------------------------------------
# Idle inhibit ("Keep Awake")
# ---------------------------------------------------------------------------

IDLE_INHIBIT_PID_FILE = "/tmp/dxrice-idle-inhibit.pid"


def idle_inhibit_active():
    try:
        with open(IDLE_INHIBIT_PID_FILE) as f:
            pid = int(f.read().strip())
        # Not just os.kill(pid, 0): if the inhibitor process died without
        # going through set_idle_inhibit(False) -- OOM kill, manual pkill --
        # the stale pid file remains, and the OS can hand that same PID
        # number to an unrelated process later. Confirming it's actually
        # still a systemd-inhibit process avoids a false "active" reading.
        with open(f"/proc/{pid}/comm") as f:
            comm = f.read().strip()
        return comm == "systemd-inhibit"
    except (OSError, ValueError):
        return False


def set_idle_inhibit(enabled):
    """Holds (or releases) a systemd-logind idle/sleep inhibitor by keeping
    a systemd-inhibit-wrapped `sleep infinity` alive -- killing that process
    is systemd-inhibit's normal way of releasing the lock (verified: the
    inhibitor disappears from `systemd-inhibit --list` right after)."""
    if enabled:
        if idle_inhibit_active():
            return
        proc = subprocess.Popen(
            ["systemd-inhibit", "--what=idle:sleep", "--who=DXrice",
             "--why=Quick Settings Keep Awake", "sleep", "infinity"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        with open(IDLE_INHIBIT_PID_FILE, "w") as f:
            f.write(str(proc.pid))
    else:
        try:
            with open(IDLE_INHIBIT_PID_FILE) as f:
                pid = int(f.read().strip())
            os.kill(pid, signal.SIGTERM)
        except (OSError, ValueError):
            pass
        try:
            os.remove(IDLE_INHIBIT_PID_FILE)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Screenshots (grim + slurp)
# ---------------------------------------------------------------------------

SCREENSHOT_DIR = os.path.join(HOME, "Pictures", "Screenshots")


def _screenshot_path():
    os.makedirs(SCREENSHOT_DIR, exist_ok=True)
    return os.path.join(SCREENSHOT_DIR, f"Screenshot-{time.strftime('%Y%m%d-%H%M%S')}.png")


def screenshot_region():
    path = _screenshot_path()
    subprocess.Popen(
        f'geom="$(slurp)" && [ -n "$geom" ] && grim -g "$geom" "{path}" && wl-copy < "{path}"',
        shell=True,
    )


def screenshot_full():
    path = _screenshot_path()
    subprocess.Popen(f'grim "{path}" && wl-copy < "{path}"', shell=True)


# ---------------------------------------------------------------------------
# Media controls (playerctl)
# ---------------------------------------------------------------------------

def player_available():
    return run_ok(["playerctl", "status"], timeout=2)


def player_metadata():
    r = run(["playerctl", "metadata", "--format", "{{title}}\t{{artist}}\t{{status}}"], timeout=2)
    if not r or r.returncode != 0:
        return None
    parts = r.stdout.rstrip("\n").split("\t")
    if len(parts) < 3:
        return None
    title, artist, status = parts
    return {"title": title or "Unknown", "artist": artist, "playing": status == "Playing"}


def player_play_pause():
    run_ok(["playerctl", "play-pause"], timeout=2)


def player_next():
    run_ok(["playerctl", "next"], timeout=2)


def player_previous():
    run_ok(["playerctl", "previous"], timeout=2)


# ---------------------------------------------------------------------------
# Clipboard history (cliphist)
# ---------------------------------------------------------------------------

def list_clipboard_history(limit=15):
    """Returns [(raw_line, preview), ...] -- raw_line is what cliphist decode
    actually expects on stdin (the whole "<id>\\t<preview>" line, not just
    the id -- confirmed against this rice's real cliphist, a bare id fails)."""
    r = run(["cliphist", "list"], timeout=3)
    if not r or r.returncode != 0:
        return []
    entries = []
    for line in r.stdout.splitlines()[:limit]:
        parts = line.split("\t", 1)
        if len(parts) == 2:
            entries.append((line, parts[1]))
    return entries


def copy_clipboard_entry(raw_line):
    try:
        decode = subprocess.run(["cliphist", "decode"], input=raw_line.encode(),
                                 capture_output=True, timeout=3)
    except (subprocess.TimeoutExpired, OSError):
        return
    if decode.returncode != 0:
        return
    try:
        subprocess.run(["wl-copy"], input=decode.stdout, timeout=3)
    except (subprocess.TimeoutExpired, OSError):
        pass


# ---------------------------------------------------------------------------
# Do Not Disturb (mako)
# ---------------------------------------------------------------------------

def mako_running():
    return run_ok(["pgrep", "-x", "mako"], timeout=2)


def dnd_active():
    r = run(["makoctl", "mode"], timeout=2)
    return bool(r and r.returncode == 0 and "dnd" in r.stdout.split())


def set_dnd(enabled):
    run_ok(["makoctl", "mode", "-a" if enabled else "-r", "dnd"], timeout=2)


# ---------------------------------------------------------------------------
# UI helpers
# ---------------------------------------------------------------------------

def run_async(fn, on_done):
    """Runs fn() off the main thread, then calls on_done(result) back on
    the GTK main loop. For anything that shells out to a subprocess whose
    latency scales with real-world state (a wifi scan, one bluetoothctl
    round-trip per paired device) -- without this, opening the panel
    blocks until that call returns instead of appearing instantly."""
    def worker():
        result = fn()
        GLib.idle_add(on_done, result)
    threading.Thread(target=worker, daemon=True).start()


def clear_rows(card, rows):
    for row in rows:
        card.remove(row)
    rows.clear()


def show_loading(card, rows, text):
    row = Gtk.Box()
    row.add_css_class("dx-list-row")
    row.append(_label(text, "dx-row-subtitle", ellipsize=False))
    card.append(row)
    rows.append(row)


def make_icon_button(icon_name, tooltip=None):
    btn = Gtk.Button(icon_name=icon_name)
    btn.add_css_class("dx-icon-btn")
    btn.set_valign(Gtk.Align.CENTER)
    if tooltip:
        btn.set_tooltip_text(tooltip)
    return btn


def make_toggle_button(icon_name, label_text, active, on_toggled):
    """Compact icon-over-label toggle, GNOME-quick-settings style."""
    btn = Gtk.ToggleButton()
    btn.add_css_class("dx-toggle")
    btn.set_active(active)
    if active:
        btn.add_css_class("active")
    inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, halign=Gtk.Align.CENTER)
    inner.append(Gtk.Image.new_from_icon_name(icon_name))
    lbl = Gtk.Label(label=label_text)
    lbl.add_css_class("caption")
    inner.append(lbl)
    btn.set_child(inner)

    def _on_toggled(b):
        if b.get_active():
            b.add_css_class("active")
        else:
            b.remove_css_class("active")
        on_toggled(b.get_active())

    btn.connect("toggled", _on_toggled)
    return btn


def make_action_button(icon_name, label_text, on_clicked):
    """Compact icon-over-label button for a one-shot action (as opposed to
    make_toggle_button's persistent on/off state). Kept to the same
    vertical layout rather than Adw.ButtonContent's horizontal icon+label
    -- a longer label ("Full Screen") in a 2-3 column homogeneous row
    needs real width for a horizontal layout and forces the whole panel
    wider; stacked, it doesn't."""
    btn = Gtk.Button()
    btn.add_css_class("dx-toggle")
    inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, halign=Gtk.Align.CENTER)
    inner.append(Gtk.Image.new_from_icon_name(icon_name))
    lbl = Gtk.Label(label=label_text)
    lbl.add_css_class("caption")
    inner.append(lbl)
    btn.set_child(inner)
    btn.connect("clicked", lambda b: on_clicked())
    return btn


def make_device_menu_button(devices, on_select):
    """A small "..." button that opens a popover listing audio devices --
    kept in a popover (not the main panel's fixed-width layout) so a long
    device name can never force the whole panel wider."""
    menu_btn = Gtk.MenuButton(icon_name="view-more-symbolic")
    menu_btn.add_css_class("dx-icon-btn")
    menu_btn.set_valign(Gtk.Align.CENTER)

    listbox = Gtk.ListBox()
    listbox.add_css_class("boxed-list")
    for devid, name, is_default in devices:
        row = Gtk.Label(label=name, xalign=0)
        row.set_ellipsize(Pango.EllipsizeMode.END)
        row.set_max_width_chars(30)
        row.set_margin_top(6)
        row.set_margin_bottom(6)
        row.set_margin_start(10)
        row.set_margin_end(10)
        listbox.append(row)

    def on_row_activated(_lb, row):
        idx = row.get_index()
        on_select(devices[idx][0])
        popover.popdown()

    listbox.connect("row-activated", on_row_activated)
    popover = Gtk.Popover()
    popover.set_child(listbox)
    menu_btn.set_popover(popover)
    return menu_btn


def make_slider_row(icon_on, icon_off, initial, muted, on_change, on_mute, devices=None, on_device=None):
    row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
    row.add_css_class("dx-row")

    mute_btn = Gtk.ToggleButton()
    mute_btn.set_icon_name(icon_off if muted else icon_on)
    mute_btn.add_css_class("dx-icon-btn")
    mute_btn.add_css_class("flat")
    mute_btn.set_active(muted)
    mute_btn.set_valign(Gtk.Align.CENTER)

    def _on_mute_toggled(b):
        on_mute()
        b.set_icon_name(icon_off if b.get_active() else icon_on)

    mute_btn.connect("toggled", _on_mute_toggled)
    row.append(mute_btn)

    scale = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL, hexpand=True)
    scale.set_range(0, 100)
    scale.set_value(initial)
    scale.set_draw_value(False)
    row.append(scale)

    pct_label = _label(f"{initial}%", ellipsize=False)
    pct_label.set_width_chars(4)
    pct_label.set_xalign(1.0)
    row.append(pct_label)

    # The label/scale still update on every tick while dragging, but
    # wpctl only actually gets called ~80ms after motion pauses, so a
    # fast drag doesn't spawn a subprocess per pixel.
    debounced_change = make_debounced(on_change)

    def _on_value_changed(s):
        v = int(s.get_value())
        pct_label.set_label(f"{v}%")
        debounced_change(v)

    scale.connect("value-changed", _on_value_changed)

    if devices and len(devices) > 1 and on_device:
        row.append(make_device_menu_button(devices, on_device))

    return row, scale, pct_label


class PasswordDialog(Adw.Window):
    def __init__(self, parent, ssid, on_submit):
        super().__init__(transient_for=parent, modal=True, title=f"Connect to {ssid}")
        self.set_default_size(320, -1)

        escape_controller = Gtk.EventControllerKey()
        escape_controller.connect("key-pressed", self._on_key_pressed)
        self.add_controller(escape_controller)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        root.add_css_class("dx-root")
        self.set_content(root)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        header.add_css_class("dx-header")
        title_lbl = _label(f"Connect to {ssid}", "dx-header-title", max_width_chars=26)
        header.append(title_lbl)
        close_btn = Gtk.Button(icon_name="window-close-symbolic")
        close_btn.add_css_class("dx-close")
        close_btn.connect("clicked", lambda _b: self.close())
        header.append(close_btn)
        root.append(header)

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        body.add_css_class("dx-body")
        root.append(body)

        entry = Gtk.PasswordEntry(show_peek_icon=True, placeholder_text="Password")
        entry.add_css_class("dx-entry")
        entry.connect("activate", lambda e: self._submit(ssid, entry, on_submit))
        body.append(entry)

        btn = Gtk.Button(label="Connect")
        btn.add_css_class("dx-btn-primary")
        btn.connect("clicked", lambda b: self._submit(ssid, entry, on_submit))
        body.append(btn)

    def _on_key_pressed(self, _controller, keyval, _keycode, _state):
        if keyval == Gdk.KEY_Escape:
            self.close()
            return True
        return False

    def _submit(self, ssid, entry, on_submit):
        on_submit(ssid, entry.get_text())
        self.close()


# ---------------------------------------------------------------------------
# Main panel
# ---------------------------------------------------------------------------

PANEL_WIDTH = 390


class QuickSettingsWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Quick Settings")
        self.set_default_size(PANEL_WIDTH, -1)
        self.set_resizable(False)

        Gtk4LayerShell.init_for_window(self)
        Gtk4LayerShell.set_namespace(self, "dxrice-quicksettings")
        Gtk4LayerShell.set_layer(self, Gtk4LayerShell.Layer.OVERLAY)
        Gtk4LayerShell.set_keyboard_mode(self, Gtk4LayerShell.KeyboardMode.ON_DEMAND)
        Gtk4LayerShell.set_anchor(self, Gtk4LayerShell.Edge.TOP, True)
        Gtk4LayerShell.set_anchor(self, Gtk4LayerShell.Edge.RIGHT, True)
        Gtk4LayerShell.set_margin(self, Gtk4LayerShell.Edge.TOP, 60)
        Gtk4LayerShell.set_margin(self, Gtk4LayerShell.Edge.RIGHT, 14)

        escape_controller = Gtk.EventControllerKey()
        escape_controller.connect("key-pressed", self._on_key_pressed)
        self.add_controller(escape_controller)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        root.add_css_class("dx-root")
        root.set_size_request(PANEL_WIDTH, -1)
        self.set_content(root)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        header.add_css_class("dx-header")
        title_lbl = _label("Quick Settings", "dx-header-title", ellipsize=False, xalign=0.0)
        title_lbl.set_hexpand(True)
        header.append(title_lbl)
        close_btn = Gtk.Button(icon_name="window-close-symbolic")
        close_btn.add_css_class("dx-close")
        close_btn.connect("clicked", lambda b: self.close())
        header.append(close_btn)
        root.append(header)

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_max_content_height(640)
        scroller.set_propagate_natural_height(True)
        root.append(scroller)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        scroller.set_child(content)

        self.cpu_monitor = CpuMonitor()

        self._build_toggles_card(content)
        self._build_media_card(content)
        self._build_audio_card(content)
        if has_backlight():
            self._build_brightness_card(content)
        self._build_wifi_card(content)
        self._build_bluetooth_card(content)
        self._build_clipboard_card(content)
        self._build_screenshot_card(content)
        self._build_stats_card(content)
        self._build_power_card(content)

        GLib.timeout_add(1500, self._tick)
        GLib.timeout_add(2000, self._tick_media)

    # ---- quick toggles (wifi / bluetooth / dnd) ----

    def _build_toggles_card(self, content):
        card = make_card()
        box = Gtk.Box(spacing=6, homogeneous=True)
        box.append(make_toggle_button("network-wireless-symbolic", "Wi-Fi",
                                       wifi_radio_enabled(), self._on_wifi_toggle))
        box.append(make_toggle_button("bluetooth-active-symbolic", "Bluetooth",
                                       bluetooth_powered(), self._on_bt_toggle))
        box.append(make_toggle_button("weather-clear-night-symbolic", "Awake",
                                       idle_inhibit_active(), self._on_idle_inhibit_toggle))
        self._mako_available = mako_running()
        if self._mako_available:
            box.append(make_toggle_button("notifications-disabled-symbolic", "DND",
                                           dnd_active(), self._on_dnd_toggle))
        card.append(box)
        content.append(card)

    def _on_wifi_toggle(self, active):
        set_wifi_radio(active)
        GLib.timeout_add(800, self._rebuild_wifi_card_once)

    def _on_bt_toggle(self, active):
        set_bluetooth_power(active)
        GLib.timeout_add(800, self._rebuild_bt_card_once)

    def _on_dnd_toggle(self, active):
        set_dnd(active)

    def _on_idle_inhibit_toggle(self, active):
        set_idle_inhibit(active)

    # ---- screenshots ----

    def _build_screenshot_card(self, content):
        card = make_card()
        box = Gtk.Box(spacing=6, homogeneous=True)
        box.append(make_action_button("edit-cut-symbolic", "Region",
                                       lambda: self._take_screenshot(screenshot_region)))
        box.append(make_action_button("view-fullscreen-symbolic", "Full Screen",
                                       lambda: self._take_screenshot(screenshot_full)))
        card.append(box)
        content.append(card)

    def _take_screenshot(self, fn):
        # self.close() alone races: it triggers close-request -> app.quit(),
        # which can end the main loop before a delayed grim call ever gets
        # to run. Hide first (no close-request fires from this), give the
        # compositor a moment to actually unmap the overlay surface so it
        # isn't in the shot, then take it and close for real.
        self.set_visible(False)

        def after_hide():
            fn()
            self.close()
            return False

        GLib.timeout_add(150, after_hide)

    # ---- media (playerctl) ----

    def _build_media_card(self, content):
        self.media_card = make_card()
        content.append(self.media_card)
        self._media_widgets = []
        self._refresh_media()

    def _refresh_media(self):
        clear_rows(self.media_card, self._media_widgets)

        meta = player_metadata()
        self.media_card.set_visible(meta is not None)
        if meta is None:
            return

        text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0, hexpand=True)
        text_box.append(_label(meta["title"], "dx-row-title", max_width_chars=22))
        if meta["artist"]:
            text_box.append(_label(meta["artist"], "dx-row-subtitle", max_width_chars=22))

        controls = Gtk.Box(spacing=4)
        prev_btn = make_icon_button("media-skip-backward-symbolic", "Previous")
        prev_btn.connect("clicked", lambda b: player_previous())
        play_btn = make_icon_button(
            "media-playback-pause-symbolic" if meta["playing"] else "media-playback-start-symbolic",
            "Play/Pause")
        play_btn.connect("clicked", lambda b: player_play_pause())
        next_btn = make_icon_button("media-skip-forward-symbolic", "Next")
        next_btn.connect("clicked", lambda b: player_next())
        for b in (prev_btn, play_btn, next_btn):
            controls.append(b)

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        row.add_css_class("dx-row")
        row.append(text_box)
        row.append(controls)
        self.media_card.append(row)
        self._media_widgets.append(row)

    def _tick_media(self):
        self._refresh_media()
        return True

    # ---- audio (volume + mic) ----

    def _build_audio_card(self, content):
        card = make_card()

        vol, muted = get_volume()
        sinks = list_audio_devices("Sinks")
        vol_row, self.vol_scale, self.vol_pct = make_slider_row(
            "audio-volume-high-symbolic", "audio-volume-muted-symbolic", vol, muted,
            lambda p: set_volume("@DEFAULT_AUDIO_SINK@", p),
            lambda: toggle_mute("@DEFAULT_AUDIO_SINK@"),
            sinks, set_default_device,
        )
        card.append(vol_row)

        mic_vol, mic_muted = get_volume("@DEFAULT_AUDIO_SOURCE@")
        sources = list_audio_devices("Sources")
        mic_row, self.mic_scale, self.mic_pct = make_slider_row(
            "microphone-sensitivity-high-symbolic", "microphone-sensitivity-muted-symbolic",
            mic_vol, mic_muted,
            lambda p: set_volume("@DEFAULT_AUDIO_SOURCE@", p),
            lambda: toggle_mute("@DEFAULT_AUDIO_SOURCE@"),
            sources, set_default_device,
        )
        card.append(mic_row)

        content.append(card)

    # ---- brightness ----

    def _build_brightness_card(self, content):
        card = make_card()
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row.add_css_class("dx-row")
        row.append(Gtk.Image.new_from_icon_name("display-brightness-symbolic"))

        brightness = get_brightness_percent()
        scale = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL, hexpand=True)
        scale.set_range(1, 100)
        scale.set_value(brightness)
        scale.set_draw_value(False)
        row.append(scale)

        pct_label = _label(f"{brightness}%", ellipsize=False)
        pct_label.set_width_chars(4)
        pct_label.set_xalign(1.0)
        row.append(pct_label)

        debounced_change = make_debounced(set_brightness_percent)

        def _on_value_changed(s):
            v = int(s.get_value())
            pct_label.set_label(f"{v}%")
            debounced_change(v)

        scale.connect("value-changed", _on_value_changed)
        card.append(row)
        content.append(card)

    # ---- wifi ----

    def _build_wifi_card(self, content):
        self.wifi_card = make_card()
        content.append(self.wifi_card)
        self._wifi_row_widgets = []
        self._wifi_gen = 0
        self._rebuild_wifi_card()

    def _rebuild_wifi_card_once(self):
        self._rebuild_wifi_card()
        return False

    def _rebuild_wifi_card(self):
        clear_rows(self.wifi_card, self._wifi_row_widgets)
        enabled = wifi_radio_enabled()
        self.wifi_card.set_visible(enabled)
        if not enabled:
            return
        # A wifi scan can take a real amount of time -- show a placeholder
        # and fetch the list off the main thread so the window still opens
        # instantly instead of freezing until nmcli returns. The generation
        # counter discards a stale result if a second rebuild (e.g. the
        # user toggled wifi off then back on) starts and finishes before
        # this one's fetch returns.
        show_loading(self.wifi_card, self._wifi_row_widgets, "Scanning...")
        self._wifi_gen += 1
        gen = self._wifi_gen
        run_async(lambda: list_wifi_networks()[:8], lambda networks: self._on_wifi_networks_ready(gen, networks))

    def _on_wifi_networks_ready(self, gen, networks):
        if gen != self._wifi_gen:
            return False
        clear_rows(self.wifi_card, self._wifi_row_widgets)
        for ssid, sig, security, connected in networks:
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            row.add_css_class("dx-list-row")
            icon_name = ("network-wireless-signal-excellent-symbolic" if sig > 70 else
                         "network-wireless-signal-good-symbolic" if sig > 40 else
                         "network-wireless-signal-weak-symbolic")
            row.append(Gtk.Image.new_from_icon_name(icon_name))
            row.append(_label(ssid, max_width_chars=22))
            if connected:
                row.append(Gtk.Image.new_from_icon_name("object-select-symbolic"))
            else:
                btn = Gtk.Button(label="Connect")
                btn.add_css_class("flat")
                btn.set_valign(Gtk.Align.CENTER)
                btn.connect("clicked", lambda b, s=ssid, sec=security: self._on_wifi_connect_clicked(s, sec))
                row.append(btn)
            self.wifi_card.append(row)
            self._wifi_row_widgets.append(row)
        return False

    def _on_wifi_connect_clicked(self, ssid, security):
        needs_password = bool(security and security != "--") and not has_saved_connection(ssid)
        if needs_password:
            PasswordDialog(self, ssid, self._connect_wifi_with_password).present()
        else:
            connect_wifi(ssid)
            GLib.timeout_add(1000, self._rebuild_wifi_card_once)

    def _connect_wifi_with_password(self, ssid, password):
        connect_wifi(ssid, password)
        GLib.timeout_add(1000, self._rebuild_wifi_card_once)

    # ---- bluetooth ----

    def _build_bluetooth_card(self, content):
        self.bt_card = make_card()
        content.append(self.bt_card)
        self._bt_row_widgets = []
        self._bt_gen = 0
        self._rebuild_bt_card()

    def _rebuild_bt_card_once(self):
        self._rebuild_bt_card()
        return False

    def _rebuild_bt_card(self):
        clear_rows(self.bt_card, self._bt_row_widgets)
        enabled = bluetooth_powered()
        self.bt_card.set_visible(enabled)
        if not enabled:
            return
        # list_bluetooth_devices() runs a separate `bluetoothctl info` per
        # paired device -- with several devices that's easily a
        # multi-second block if done synchronously during window setup.
        # The generation counter discards a stale result if a second
        # rebuild (e.g. connecting to two devices in quick succession)
        # starts and finishes before this one's fetch returns.
        show_loading(self.bt_card, self._bt_row_widgets, "Loading devices...")
        self._bt_gen += 1
        gen = self._bt_gen
        run_async(list_bluetooth_devices, lambda devices: self._on_bt_devices_ready(gen, devices))

    def _on_bt_devices_ready(self, gen, devices):
        if gen != self._bt_gen:
            return False
        clear_rows(self.bt_card, self._bt_row_widgets)
        if not devices:
            row = Gtk.Box()
            row.add_css_class("dx-list-row")
            row.append(_label("No paired devices", "dx-row-subtitle"))
            self.bt_card.append(row)
            self._bt_row_widgets.append(row)
            return False
        for mac, name, connected in devices:
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            row.add_css_class("dx-list-row")
            row.append(_label(name, max_width_chars=22))
            btn = Gtk.Button(label="Disconnect" if connected else "Connect")
            btn.add_css_class("flat")
            btn.set_valign(Gtk.Align.CENTER)
            btn.connect("clicked", lambda b, m=mac, c=connected: self._on_bt_connect_clicked(m, c))
            row.append(btn)
            self.bt_card.append(row)
            self._bt_row_widgets.append(row)
        return False

    def _on_bt_connect_clicked(self, mac, currently_connected):
        bluetooth_connect(mac, connect=not currently_connected)
        GLib.timeout_add(1500, self._rebuild_bt_card_once)

    # ---- clipboard history ----

    def _build_clipboard_card(self, content):
        self.clip_card = make_card()
        header_row = Gtk.Box(spacing=6)
        header_row.append(_label("Clipboard", "dx-row-title", ellipsize=False))
        refresh_btn = make_icon_button("view-refresh-symbolic", "Refresh")
        refresh_btn.connect("clicked", lambda b: self._rebuild_clipboard_card())
        header_row.append(refresh_btn)
        self.clip_card.append(header_row)
        content.append(self.clip_card)
        self._clip_row_widgets = []
        self._rebuild_clipboard_card()

    def _rebuild_clipboard_card(self):
        clear_rows(self.clip_card, self._clip_row_widgets)
        entries = list_clipboard_history(8)
        for raw, preview in entries:
            btn = Gtk.Button()
            btn.add_css_class("flat")
            btn.add_css_class("dx-list-row")
            btn.set_child(_label(preview.replace("\n", " "), max_width_chars=22))
            btn.connect("clicked", lambda b, r=raw: copy_clipboard_entry(r))
            self.clip_card.append(btn)
            self._clip_row_widgets.append(btn)

    # ---- live stats ----

    def _build_stats_card(self, content):
        card = make_card()
        self.cpu_bar, self.cpu_pct = self._add_stat_row(card, "CPU")
        self.mem_bar, self.mem_pct = self._add_stat_row(card, "Memory")
        self.disk_bar, self.disk_pct = self._add_stat_row(card, "Disk")
        content.append(card)
        self._refresh_stats()

    def _add_stat_row(self, card, title):
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        row.add_css_class("dx-row")
        row.append(_label(title, ellipsize=False))
        bar = Gtk.LevelBar(hexpand=True)
        bar.set_valign(Gtk.Align.CENTER)
        row.append(bar)
        pct = _label("0%", ellipsize=False)
        pct.set_width_chars(4)
        pct.set_xalign(1.0)
        row.append(pct)
        card.append(row)
        return bar, pct

    def _refresh_stats(self):
        cpu = self.cpu_monitor.sample()
        self.cpu_bar.set_value(cpu / 100)
        self.cpu_pct.set_label(f"{cpu:.0f}%")

        mem = mem_percent()
        self.mem_bar.set_value(mem / 100)
        self.mem_pct.set_label(f"{mem:.0f}%")

        disk = disk_percent()
        self.disk_bar.set_value(disk / 100)
        self.disk_pct.set_label(f"{disk:.0f}%")

    def _tick(self):
        self._refresh_stats()
        return True

    # ---- power ----

    def _build_power_card(self, content):
        card = make_card()
        box = Gtk.Box(spacing=6, homogeneous=True)
        for icon, tooltip, action, destructive in [
            ("system-lock-screen-symbolic", "Lock", action_lock, False),
            ("system-log-out-symbolic", "Logout", action_logout, True),
            ("system-reboot-symbolic", "Reboot", action_reboot, True),
            ("system-shutdown-symbolic", "Shutdown", action_shutdown, True),
        ]:
            btn = make_icon_button(icon, tooltip)
            btn.add_css_class("dx-power-btn")
            if destructive:
                btn.add_css_class("destructive")
                btn.connect("clicked", lambda b, a=action, l=tooltip: self._confirm_power_action(l, a))
            else:
                btn.connect("clicked", lambda b, a=action: a())
            box.append(btn)
        card.append(box)
        content.append(card)

    def _confirm_power_action(self, label, action):
        dialog = Adw.AlertDialog(heading=f"{label}?", body=f"This will {label.lower()} the system now.")
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("confirm", label)
        dialog.set_response_appearance("confirm", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")

        def on_response(_d, response):
            if response == "confirm":
                action()

        dialog.connect("response", on_response)
        dialog.present(self)

    def _on_key_pressed(self, _controller, keyval, _keycode, _state):
        if keyval == Gdk.KEY_Escape:
            self.close()
            return True
        return False


class QuickSettingsApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id="dev.dexo.DXriceQuickSettings",
                          flags=Gio.ApplicationFlags.NON_UNIQUE)

    def do_startup(self):
        Adw.Application.do_startup(self)
        load_css(CSS_PATH)

    def do_activate(self):
        win = self.props.active_window
        if not win:
            win = QuickSettingsWindow(self)
            win.connect("close-request", self._on_close_request)
        win.present()

    def _on_close_request(self, _win):
        self.quit()
        return False


def _other_instance_pid():
    try:
        with open(PID_FILE) as f:
            pid = int(f.read().strip())
    except (OSError, ValueError):
        return None
    try:
        os.kill(pid, 0)
    except OSError:
        return None
    return pid


def main():
    existing = _other_instance_pid()
    if existing:
        try:
            os.kill(existing, signal.SIGTERM)
        except OSError:
            pass
        return

    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))

    def cleanup(*_args):
        try:
            os.remove(PID_FILE)
        except OSError:
            pass
        sys.exit(0)

    signal.signal(signal.SIGTERM, cleanup)

    app = QuickSettingsApp()
    try:
        app.run(sys.argv)
    finally:
        try:
            os.remove(PID_FILE)
        except OSError:
            pass


if __name__ == "__main__":
    main()
