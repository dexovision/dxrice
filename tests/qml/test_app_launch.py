#!/usr/bin/env python3
"""Apps the shell launches go through scripts/dxrice_launch.sh (their own
systemd scope), so a shell crash or restart no longer kills them.

Started with a bare Quickshell.execDetached they stayed in
dxrice-quickshell.service's cgroup, which systemd kills on every stop and
crash-restart. scripts/dxrice_test_launch_systemd.sh shows the systemd side
with a stand-in service; this checks the shell actually uses the launcher.

    python3 tests/qml/test_app_launch.py
"""
import json
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from harness import Scene, REPO
except ImportError as e:  # PySide6 missing
    print(f"SKIP: {e}")
    sys.exit(0)

QML_DIR = REPO / "quickshell"

# Short-lived helpers: they finish with the action, so staying in the
# shell's cgroup costs nothing. Anything else started with a bare
# execDetached is a long-lived app and must use Launcher.launch instead.
SHORT_LIVED = {"brightnessctl", "bluetoothctl", "nmcli", "makoctl", "loginctl", "systemctl"}


class DockLaunchTest(unittest.TestCase):
    def test_dock_tile_launches_through_the_scope_launcher(self):
        s = Scene(width=1920, height=1080)
        try:
            pos = json.loads(s.ev('(function(){ const t = findNamed("dockTile:Firefox");'
                                  ' const p = t.mapToItem(null, t.width / 2, t.height / 2);'
                                  ' return JSON.stringify([p.x, p.y]); })()'))
            s.bridge.exec_log.clear()
            owner = s.click(int(pos[0]), int(pos[1]))
            self.assertEqual(owner, "Dock", "the click didn't reach the dock")
            s.wait(50)
            self.assertEqual(s.bridge.exec_log,
                             [[f"{s.shell}/../scripts/dxrice_launch.sh", "dock", "sh", "-c", "firefox"]])
        finally:
            s.close()


class NoBareAppLaunchTest(unittest.TestCase):
    def test_only_short_lived_helpers_use_bare_execDetached(self):
        problems = []
        for path in sorted(QML_DIR.glob("*.qml")):
            src = path.read_text()
            for m in re.finditer(r"Quickshell\.execDetached\(\[\s*\"([^\"]+)\"", src):
                prog = m.group(1)
                tail = src[m.end():m.end() + 300]
                if prog in SHORT_LIVED:
                    continue
                if prog == "sh" and "loginctl terminate-session" in tail:
                    continue  # Log Out: ends the session itself
                line = src.count("\n", 0, m.start()) + 1
                problems.append(f"{path.name}:{line}: execDetached([\"{prog}\", ...]) -- use Launcher.launch")
        self.assertEqual(problems, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
