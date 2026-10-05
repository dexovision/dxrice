"""Offscreen render/interaction harness for DXrice's Quickshell QML.

Loads the REAL shell QML files (quickshell/*.qml) against small stub
modules (tests/qml/stubs) that stand in for Quickshell's compositor-facing
types, inside one offscreen QQuickView sized like a monitor. Lets tests:

  * render the actual panels to PNG for visual QA (grab()),
  * drive state through real QML expressions (ev()),
  * advance real animations (wait()),
  * and model compositor INPUT ROUTING: every stub PanelWindow carries the
    same `mask: Region {..}` the real shell declares, and the Region stub
    reproduces Quickshell's own geometry semantics (see stubs/.../Region.qml),
    so input_owner(x, y) answers "would a click here reach a DXrice surface
    or the application underneath it?" the way Hyprland would.

Needs PySide6 (pip install PySide6-Essentials). Nothing here touches a real
Wayland session, Hyprland, or the user's config: XDG_CONFIG_HOME points at a
throwaway directory seeded from the repo's own defaults.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

from PySide6.QtCore import QObject, QPointF, QTimer, QUrl, Qt, Slot, Property, QEventLoop, QRect  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtQml import QQmlExpression, qmlRegisterSingletonInstance  # noqa: E402
from PySide6.QtQuick import QQuickView, QQuickItem  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
SHELL_SRC = Path(os.environ.get("DXRICE_SHELL_SRC", REPO / "quickshell"))
STUBS = Path(__file__).resolve().parent / "stubs"
SCENES = Path(__file__).resolve().parent / "scenes"

DEFAULT_DOCK = {
    "modules-left": ["custom/launcher", "custom/firefox", "custom/kitty", "custom/discord", "custom/files"],
    "modules-center": ["clock"],
    "modules-right": ["pulseaudio", "network", "cpu", "memory"],
    "custom/launcher": {"format": "", "tooltip-format": "Launcher"},
    "custom/firefox": {"dxrice_label": "Firefox", "dxrice_cmd": "firefox", "dxrice_icon_mode": "auto",
                        "format": "", "on-click": "sh -c 'firefox >/dev/null 2>&1 &'", "tooltip-format": "Firefox"},
    "custom/kitty": {"dxrice_label": "Kitty", "dxrice_cmd": "kitty", "dxrice_icon_mode": "auto",
                      "format": "", "on-click": "sh -c 'kitty >/dev/null 2>&1 &'", "tooltip-format": "Kitty"},
    "custom/discord": {"dxrice_label": "Discord", "dxrice_cmd": "discord", "dxrice_icon_mode": "auto",
                        "format": "", "on-click": "sh -c 'discord >/dev/null 2>&1 &'", "tooltip-format": "Discord"},
    "custom/files": {"dxrice_label": "Files", "dxrice_cmd": "nautilus", "dxrice_icon_mode": "auto",
                      "format": "", "on-click": "sh -c 'nautilus >/dev/null 2>&1 &'", "tooltip-format": "Files"},
    "clock": {}, "pulseaudio": {"on-click": "pavucontrol"}, "network": {}, "cpu": {}, "memory": {},
}

# Default fixture outputs for the subprocesses the shell runs. Keys are
# matched as a substring of " ".join(argv); first match wins.
DEFAULT_COMMANDS = [
    ("nmcli radio wifi", "enabled\n"),
    ("bluetoothctl show", "Powered: yes\n"),
    ("makoctl mode", "default\n"),
    ("nmcli -t -f NAME connection show", "HomeNet\nlo\n"),
    ("nmcli -t -f active,ssid,signal,security dev wifi list",
     "yes:HomeNet:82:WPA2\nno:CoffeeShop Guest:64:\nno:Neighbour_5G:41:WPA2\n"),
    ("bluetoothctl devices", "Device AA:BB:CC:DD:EE:01 WH-1000XM4\nDevice AA:BB:CC:DD:EE:02 MX Master 3\n"),
    ("bluetoothctl info AA:BB:CC:DD:EE:01", "Connected: yes\nBattery Percentage: 0x50 (80)\n"),
    ("bluetoothctl info AA:BB:CC:DD:EE:02", "Connected: no\n"),
    ("cliphist list", "1\tgit commit -m 'fix input region'\n2\thttps://example.com/a/very/long/url/that/should/elide/nicely\n3\tHello world\n"),
    ("ls /sys/class/backlight", ""),
    ("gpu_busy_percent", ""),
    ("nvidia-smi", "notanumber"),
    ("df -B1", "Used Size\n212000000000 512000000000\n"),
    ("TZ=$z date", "America/New_York:09:41\nEurope/London:14:41\nAsia/Tokyo:22:41\nAustralia/Sydney:00:41\n"),
    ("dxrice_list_desktop_apps.py", json.dumps([
        {"name": "Firefox", "cmd": "firefox"}, {"name": "Kitty", "cmd": "kitty"},
        {"name": "Visual Studio Code", "cmd": "code"}, {"name": "GIMP", "cmd": "gimp"},
        {"name": "Thunderbird", "cmd": "thunderbird"}, {"name": "Steam", "cmd": "steam"},
    ])),
    ("dxrice_icons.py", ""),
    ("hyprctl activewindow -j", json.dumps({"class": "discord", "title": "#general | Discord"})),
]

DEFAULT_FILES = {
    "/proc/stat": "cpu  100 0 100 800 0 0 0 0 0 0\n",
    "/proc/meminfo": "MemTotal: 16000000 kB\nMemAvailable: 9000000 kB\n",
    "/proc/net/dev": "h\nh\n  eth0: 1000 0 0 0 0 0 0 0 2000 0 0 0 0 0 0 0\n",
    "/etc/os-release": 'PRETTY_NAME="Arch Linux"\n',
    "/proc/sys/kernel/hostname": "dxbox\n",
    "/proc/sys/kernel/osrelease": "6.18.4-arch1-1\n",
    "/proc/uptime": "11000.0 0\n",
}


class HarnessBridge(QObject):
    """One per process (a QML singleton instance can only be registered
    once); Scene.__init__ re-points it at each new scene's config/screen."""

    def __init__(self):
        super().__init__()
        self.configure(1920, 1080, "", Path("/nonexistent"))

    def configure(self, screen_w, screen_h, shell_dir, config_home):
        self._w, self._h = screen_w, screen_h
        self._shell_dir = str(shell_dir)
        self.config_home = config_home
        self.commands = list(DEFAULT_COMMANDS)
        self.files = dict(DEFAULT_FILES)
        self.exec_log: list[list[str]] = []
        self.env_over = {"HOME": str(Path(config_home).parent), "XDG_CONFIG_HOME": str(config_home),
                         "USER": "dexo", "XDG_SESSION_ID": "2"}

    # Not notifiable on purpose: each Scene configures these BEFORE loading
    # any QML, and a fresh QQmlEngine reads them anew.
    @Property(int, constant=True)
    def screenWidth(self):
        return self._w

    @Property(int, constant=True)
    def screenHeight(self):
        return self._h

    @Property(str, constant=True)
    def shellDir(self):
        return self._shell_dir

    @Slot(str, result=str)
    def env(self, name):
        return self.env_over.get(name, "")

    @Slot("QVariantList")
    def exec(self, argv):
        self.exec_log.append([str(a) for a in argv])

    @Slot("QVariantList", result=str)
    def run(self, argv):
        joined = " ".join(str(a) for a in argv)
        for key, out in self.commands:
            if key in joined:
                return out
        return ""

    @Slot(str, result="QVariant")
    def readFile(self, path):
        if path in self.files:
            return self.files[path]
        p = Path(path)
        if str(p).startswith(str(self.config_home)) and p.is_file():
            return p.read_text()
        return None

    @Slot(str, str)
    def writeFile(self, path, text):
        p = Path(path)
        if str(p).startswith(str(self.config_home)):
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)
        else:
            self.files[path] = text


_PANEL_LINE_STRIP = [
    re.compile(r"^\s*anchors\s*\{\s*(?:(?:top|bottom|left|right)\s*:\s*true\s*;?\s*)+\}\s*$"),
    re.compile(r"^\s*WlrLayershell\.\w+\s*:.*$"),
]


def _prepare_shell(dest: Path):
    """Copy the real shell sources, stripping only window-protocol lines a
    stub Item cannot carry (layer-shell anchors / WlrLayershell.*)."""
    for src in SHELL_SRC.iterdir():
        if src.suffix not in (".qml", "") and src.name != "qmldir":
            continue
        if src.is_dir():
            continue
        text = src.read_text()
        if "PanelWindow {" in text:
            text = "\n".join(
                "" if any(rx.match(line) for rx in _PANEL_LINE_STRIP) else line
                for line in text.split("\n"))
        (dest / src.name).write_text(text)
    for scene in SCENES.glob("*.qml"):
        shutil.copy(scene, dest / scene.name)


_app = None
_bridge = None


def app():
    global _app, _bridge
    if _app is None:
        _app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])
        _bridge = HarnessBridge()
        qmlRegisterSingletonInstance(HarnessBridge, "Harness", 1, 0, "Harness", _bridge)
    return _app


class Scene:
    def __init__(self, scene_name="Desktop.qml", width=1920, height=1080, dock_config=None, setup=None):
        app()
        self.tmp = Path(tempfile.mkdtemp(prefix="dxrice-qml-"))
        self.shell = self.tmp / "shell"
        self.shell.mkdir()
        cfg = self.tmp / "home" / ".config"
        (cfg / "dxrice").mkdir(parents=True)
        (cfg / "waybar").mkdir(parents=True)
        shutil.copy(REPO / "theme" / "theme.json", cfg / "dxrice" / "theme.json")
        (cfg / "waybar" / "config-dock").write_text(json.dumps(dock_config or DEFAULT_DOCK, indent=4))
        _prepare_shell(self.shell)
        self.bridge = _bridge
        self.bridge.configure(width, height, self.shell, cfg)
        if setup:
            setup(self.bridge)
        self.view = QQuickView()
        self.view.engine().addImportPath(str(STUBS))
        self.warnings: list[str] = []
        self.view.engine().warnings.connect(lambda ws: self.warnings.extend(w.toString() for w in ws))
        self.view.setResizeMode(QQuickView.SizeRootObjectToView)
        self.view.resize(width, height)
        self.width, self.height = width, height
        self.view.setSource(QUrl.fromLocalFile(str(self.shell / scene_name)))
        if self.view.status() != QQuickView.Ready:
            raise RuntimeError("scene failed to load:\n" + "\n".join(e.toString() for e in self.view.errors()))
        self.view.show()
        self.root = self.view.rootObject()
        self.wait(400)

    # ---- driving ----
    def ev(self, js, scope=None):
        expr = QQmlExpression(self.view.engine().rootContext(), scope or self.root, js)
        val = expr.evaluate()
        if expr.hasError():
            raise RuntimeError(f"QML eval error in {js!r}: {expr.error().toString()}")
        return val[0] if isinstance(val, tuple) else val

    def wait(self, ms):
        loop = QEventLoop()
        QTimer.singleShot(int(ms), loop.quit)
        loop.exec()

    def grab(self, path, rect=None):
        img = self.view.grabWindow()
        if rect:
            img = img.copy(QRect(*[int(v) for v in rect]))
        img.save(str(path))
        return img

    # ---- compositor input routing model ----
    def input_owner(self, x, y):
        """Name of the shell surface that would receive a pointer event at
        (x, y) per its input mask, or None if it falls through to whatever
        application is underneath."""
        return self.ev(f"inputOwner({x}, {y})")

    def surface_rects(self):
        return self.ev("inputRects()")

    def click(self, x, y):
        """Click as the compositor would route it: into the owning shell
        surface's item tree, or onto the desktop app underneath."""
        owner = self.input_owner(x, y)
        if owner is None:
            self.ev(f"desktopClicked({x}, {y})")
            return None
        from PySide6.QtTest import QTest
        self.ev("desktopBlocked = true")
        QTest.mouseClick(self.view, Qt.LeftButton, Qt.NoModifier, QPointF(x, y).toPoint())
        self.ev("desktopBlocked = false")
        return owner

    def key(self, key):
        from PySide6.QtTest import QTest
        QTest.keyClick(self.view, key)

    def close(self):
        self.view.close()
        self.view.deleteLater()
        shutil.rmtree(self.tmp, ignore_errors=True)
