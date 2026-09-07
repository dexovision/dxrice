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


import re
import shutil
import signal
import subprocess
import time

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
gi.require_version("Gtk4LayerShell", "1.0")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Gtk4LayerShell

HOME = os.path.expanduser("~")
PID_FILE = "/tmp/dxrice-quick-settings.pid"


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
# UI helpers
# ---------------------------------------------------------------------------

def make_slider_row(title, initial, on_change):
    row = Adw.ActionRow(title=title)
    scale = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL)
    scale.set_range(0, 100)
    scale.set_value(initial)
    scale.set_draw_value(True)
    scale.set_size_request(160, -1)
    scale.set_valign(Gtk.Align.CENTER)
    scale.connect("value-changed", lambda s: on_change(int(s.get_value())))
    row.add_suffix(scale)
    row.scale = scale
    return row


class PasswordDialog(Adw.Window):
    def __init__(self, parent, ssid, on_submit):
        super().__init__(transient_for=parent, modal=True, title=f"Connect to {ssid}")
        self.set_default_size(360, -1)
        toolbar_view = Adw.ToolbarView()
        toolbar_view.add_top_bar(Adw.HeaderBar())
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        box.set_margin_start(12)
        box.set_margin_end(12)
        entry = Adw.PasswordEntryRow(title="Password")
        entry.connect("entry-activated", lambda e: self._submit(ssid, entry, on_submit))
        box.append(entry)
        btn = Gtk.Button(label="Connect")
        btn.add_css_class("suggested-action")
        btn.connect("clicked", lambda b: self._submit(ssid, entry, on_submit))
        box.append(btn)
        toolbar_view.set_content(box)
        self.set_content(toolbar_view)

    def _submit(self, ssid, entry, on_submit):
        on_submit(ssid, entry.get_text())
        self.close()


# ---------------------------------------------------------------------------
# Main panel
# ---------------------------------------------------------------------------

class QuickSettingsWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Quick Settings")
        self.set_default_size(380, -1)

        Gtk4LayerShell.init_for_window(self)
        Gtk4LayerShell.set_layer(self, Gtk4LayerShell.Layer.OVERLAY)
        Gtk4LayerShell.set_keyboard_mode(self, Gtk4LayerShell.KeyboardMode.ON_DEMAND)
        Gtk4LayerShell.set_anchor(self, Gtk4LayerShell.Edge.TOP, True)
        Gtk4LayerShell.set_anchor(self, Gtk4LayerShell.Edge.RIGHT, True)
        Gtk4LayerShell.set_margin(self, Gtk4LayerShell.Edge.TOP, 60)
        Gtk4LayerShell.set_margin(self, Gtk4LayerShell.Edge.RIGHT, 14)

        escape_controller = Gtk.EventControllerKey()
        escape_controller.connect("key-pressed", self._on_key_pressed)
        self.add_controller(escape_controller)

        toolbar_view = Adw.ToolbarView()
        toolbar_view.add_top_bar(Adw.HeaderBar())
        scroller = Gtk.ScrolledWindow()
        scroller.set_max_content_height(700)
        scroller.set_propagate_natural_height(True)
        page = Adw.PreferencesPage()
        scroller.set_child(page)
        toolbar_view.set_content(scroller)
        self.set_content(toolbar_view)

        self.cpu_monitor = CpuMonitor()

        self._build_stats_group(page)
        self._build_volume_group(page)
        self._build_mic_group(page)
        if has_backlight():
            self._build_brightness_group(page)
        self._build_wifi_group(page)
        self._build_bluetooth_group(page)
        self._build_power_group(page)

        GLib.timeout_add(1500, self._tick)

    # ---- live stats ----

    def _build_stats_group(self, page):
        group = Adw.PreferencesGroup(title="System")
        page.add(group)
        self.cpu_bar = Gtk.LevelBar()
        self.cpu_row = Adw.ActionRow(title="CPU")
        self.cpu_row.add_suffix(self.cpu_bar)
        self.cpu_bar.set_size_request(140, -1)
        self.cpu_bar.set_valign(Gtk.Align.CENTER)
        group.add(self.cpu_row)

        self.mem_bar = Gtk.LevelBar()
        self.mem_row = Adw.ActionRow(title="Memory")
        self.mem_row.add_suffix(self.mem_bar)
        self.mem_bar.set_size_request(140, -1)
        self.mem_bar.set_valign(Gtk.Align.CENTER)
        group.add(self.mem_row)

        self.disk_bar = Gtk.LevelBar()
        self.disk_row = Adw.ActionRow(title="Disk (/)")
        self.disk_row.add_suffix(self.disk_bar)
        self.disk_bar.set_size_request(140, -1)
        self.disk_bar.set_valign(Gtk.Align.CENTER)
        group.add(self.disk_row)

        self._refresh_stats()

    def _refresh_stats(self):
        cpu = self.cpu_monitor.sample()
        self.cpu_bar.set_value(cpu / 100)
        self.cpu_row.set_subtitle(f"{cpu:.0f}%")

        mem = mem_percent()
        self.mem_bar.set_value(mem / 100)
        self.mem_row.set_subtitle(f"{mem:.0f}%")

        disk = disk_percent()
        self.disk_bar.set_value(disk / 100)
        self.disk_row.set_subtitle(f"{disk:.0f}%")

    def _tick(self):
        self._refresh_stats()
        return True

    # ---- volume ----

    def _build_volume_group(self, page):
        group = Adw.PreferencesGroup(title="Volume")
        page.add(group)
        vol, muted = get_volume()
        self.vol_row = make_slider_row("Output", vol, self._on_volume_changed)
        mute_btn = Gtk.ToggleButton(icon_name="audio-volume-muted-symbolic")
        mute_btn.set_active(muted)
        mute_btn.set_valign(Gtk.Align.CENTER)
        mute_btn.connect("toggled", lambda b: toggle_mute("@DEFAULT_AUDIO_SINK@"))
        self.vol_row.add_prefix(mute_btn)
        group.add(self.vol_row)

        devices = list_audio_devices("Sinks")
        if len(devices) > 1:
            names = Gtk.StringList.new([d[1] for d in devices])
            combo = Adw.ComboRow(title="Output device", model=names)
            for i, d in enumerate(devices):
                if d[2]:
                    combo.set_selected(i)
            combo.connect("notify::selected", lambda c, _p: set_default_device(devices[c.get_selected()][0]))
            group.add(combo)

    def _on_volume_changed(self, percent):
        set_volume("@DEFAULT_AUDIO_SINK@", percent)

    # ---- microphone ----

    def _build_mic_group(self, page):
        group = Adw.PreferencesGroup(title="Microphone")
        page.add(group)
        vol, muted = get_volume("@DEFAULT_AUDIO_SOURCE@")
        self.mic_row = make_slider_row("Input", vol, self._on_mic_changed)
        mute_btn = Gtk.ToggleButton(icon_name="microphone-sensitivity-muted-symbolic")
        mute_btn.set_active(muted)
        mute_btn.set_valign(Gtk.Align.CENTER)
        mute_btn.connect("toggled", lambda b: toggle_mute("@DEFAULT_AUDIO_SOURCE@"))
        self.mic_row.add_prefix(mute_btn)
        group.add(self.mic_row)

        devices = list_audio_devices("Sources")
        if len(devices) > 1:
            names = Gtk.StringList.new([d[1] for d in devices])
            combo = Adw.ComboRow(title="Input device", model=names)
            for i, d in enumerate(devices):
                if d[2]:
                    combo.set_selected(i)
            combo.connect("notify::selected", lambda c, _p: set_default_device(devices[c.get_selected()][0]))
            group.add(combo)

    def _on_mic_changed(self, percent):
        set_volume("@DEFAULT_AUDIO_SOURCE@", percent)

    # ---- brightness ----

    def _build_brightness_group(self, page):
        group = Adw.PreferencesGroup(title="Brightness")
        page.add(group)
        row = make_slider_row("Screen", get_brightness_percent(),
                               lambda v: set_brightness_percent(v))
        group.add(row)

    # ---- wifi ----

    def _build_wifi_group(self, page):
        self.wifi_group = Adw.PreferencesGroup(title="Wi-Fi")
        page.add(self.wifi_group)

        self.wifi_switch_row = Adw.SwitchRow(title="Wi-Fi", active=wifi_radio_enabled())
        self.wifi_switch_row.connect("notify::active", self._on_wifi_toggled)
        self.wifi_group.add(self.wifi_switch_row)

        self.wifi_list_group = Adw.PreferencesGroup()
        page.add(self.wifi_list_group)
        self._wifi_rows = []
        self._rebuild_wifi_list()

    def _on_wifi_toggled(self, row, _pspec):
        set_wifi_radio(row.get_active())
        GLib.timeout_add(800, self._rebuild_wifi_list_once)

    def _rebuild_wifi_list_once(self):
        self._rebuild_wifi_list()
        return False

    def _rebuild_wifi_list(self):
        # Adw.PreferencesGroup.remove() only accepts a row it actually
        # tracked as added -- walking get_first_child()/get_next_sibling()
        # can hand back an internal wrapper widget instead and crash with
        # "tried to remove non-child". Track exactly what we added instead.
        for row in self._wifi_rows:
            self.wifi_list_group.remove(row)
        self._wifi_rows = []
        if not wifi_radio_enabled():
            return
        for ssid, sig, security, connected in list_wifi_networks()[:8]:
            row = Adw.ActionRow(title=GLib.markup_escape_text(ssid),
                                 subtitle=f"{sig}%  {'secured' if security and security != '--' else 'open'}")
            if connected:
                row.add_suffix(Gtk.Image.new_from_icon_name("object-select-symbolic"))
                row.set_activatable(False)
            else:
                row.set_activatable(True)
                row.connect("activated", self._on_wifi_row_activated, ssid, security)
            self.wifi_list_group.add(row)
            self._wifi_rows.append(row)

    def _on_wifi_row_activated(self, row, ssid, security):
        needs_password = bool(security and security != "--") and not has_saved_connection(ssid)
        if needs_password:
            PasswordDialog(self, ssid, self._connect_wifi_with_password).present()
        else:
            connect_wifi(ssid)
            GLib.timeout_add(1000, self._rebuild_wifi_list_once)

    def _connect_wifi_with_password(self, ssid, password):
        connect_wifi(ssid, password)
        GLib.timeout_add(1000, self._rebuild_wifi_list_once)

    # ---- bluetooth ----

    def _build_bluetooth_group(self, page):
        self.bt_group = Adw.PreferencesGroup(title="Bluetooth")
        page.add(self.bt_group)
        self.bt_switch_row = Adw.SwitchRow(title="Bluetooth", active=bluetooth_powered())
        self.bt_switch_row.connect("notify::active", self._on_bt_toggled)
        self.bt_group.add(self.bt_switch_row)

        self.bt_list_group = Adw.PreferencesGroup()
        page.add(self.bt_list_group)
        self._bt_rows = []
        self._rebuild_bt_list()

    def _on_bt_toggled(self, row, _pspec):
        set_bluetooth_power(row.get_active())
        GLib.timeout_add(800, self._rebuild_bt_list_once)

    def _rebuild_bt_list_once(self):
        self._rebuild_bt_list()
        return False

    def _rebuild_bt_list(self):
        for row in self._bt_rows:
            self.bt_list_group.remove(row)
        self._bt_rows = []
        if not bluetooth_powered():
            return
        for mac, name, connected in list_bluetooth_devices():
            row = Adw.ActionRow(title=GLib.markup_escape_text(name))
            btn = Gtk.Button(label="Disconnect" if connected else "Connect")
            btn.set_valign(Gtk.Align.CENTER)
            btn.connect("clicked", lambda b, m=mac, c=connected: self._on_bt_connect_clicked(m, c))
            row.add_suffix(btn)
            self.bt_list_group.add(row)
            self._bt_rows.append(row)

    def _on_bt_connect_clicked(self, mac, currently_connected):
        bluetooth_connect(mac, connect=not currently_connected)
        GLib.timeout_add(1500, self._rebuild_bt_list_once)

    # ---- power ----

    def _build_power_group(self, page):
        group = Adw.PreferencesGroup(title="Power")
        page.add(group)
        box = Gtk.Box(spacing=8, homogeneous=True)
        box.set_margin_top(6)
        box.set_margin_bottom(6)
        for label, icon, action, needs_confirm in [
            ("Lock", "system-lock-screen-symbolic", action_lock, False),
            ("Logout", "system-log-out-symbolic", action_logout, True),
            ("Reboot", "system-reboot-symbolic", action_reboot, True),
            ("Shutdown", "system-shutdown-symbolic", action_shutdown, True),
        ]:
            btn = Gtk.Button()
            content = Adw.ButtonContent(icon_name=icon, label=label)
            btn.set_child(content)
            if needs_confirm:
                btn.connect("clicked", lambda b, a=action, l=label: self._confirm_power_action(l, a))
            else:
                btn.connect("clicked", lambda b, a=action: a())
            box.append(btn)
        group.add(box)

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
    _ensure_layer_shell_preloaded()
    main()
