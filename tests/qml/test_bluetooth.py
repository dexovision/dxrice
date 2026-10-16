"""BluetoothBackend: the paired-device list under overlapping refreshes and
when bluetoothctl can't run, through the real Quick Settings QML offscreen
(see harness.py).

    python3 tests/qml/test_bluetooth.py
"""
import json
import sys
import unittest
from pathlib import Path

try:
    import PySide6  # noqa: F401
except ImportError:  # pragma: no cover
    print("SKIP: PySide6 not installed (pip install PySide6-Essentials)")
    sys.exit(0)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import Scene  # noqa: E402

DEVICES = ("Device AA:00:00:00:00:01 Headphones\nDevice AA:00:00:00:00:02 Mouse\n"
           "Device AA:00:00:00:00:03 Keyboard\n")
INFO = {"01": "Connected: yes\nBattery Percentage: 0x50 (80)\n", "02": "Connected: no\n",
        "03": "Connected: no\nBattery Percentage: 0x0a (10)\n"}
WANT = {"Headphones": (True, 80), "Mouse": (False, -1), "Keyboard": (False, 10)}
BT = ("(function(){ const st=[findPanel('currentTab')]; while (st.length) { const it=st.pop(); if (!it) continue;"
      " if (it.toggleConnect !== undefined) return it; const k=it.data!==undefined?it.data:(it.children||[]);"
      " for (let i=0;i<k.length;i++) st.push(k[i]); } })()")


def fixtures(b):
    b.commands.insert(0, ("bluetoothctl devices", DEVICES))
    for k, v in INFO.items():
        b.commands.insert(0, (f"bluetoothctl info AA:00:00:00:00:{k}", v))


class BluetoothList(unittest.TestCase):
    def setUp(self):
        self.s = Scene(setup=fixtures)
        self.s.ev("panels.open('quicksettings')")
        self.s.wait(1200)

    def tearDown(self):
        self.s.close()

    def state(self):
        d = json.loads(self.s.ev("JSON.stringify(" + BT + ".devices)"))
        return {x["name"]: (x["connected"], x["battery"]) for x in d}

    def test_a_refresh_mid_chain_never_mixes_devices_up(self):
        """A second refresh landing while the first is still reading device
        info used to file one device's `bluetoothctl info` under the next
        device's MAC (seen: Headphones disconnected, at the Keyboard's 10%)."""
        self.assertEqual(self.state(), WANT)
        for delay in range(0, 12):
            self.s.ev(BT + ".refresh()")
            self.s.wait(delay)
            self.s.ev(BT + ".refresh()")
            self.s.wait(600)
            self.assertEqual(self.state(), WANT, f"second refresh {delay}ms into the first")

    def test_bluetoothctl_that_cannot_start_ends_the_scan_and_recovers(self):
        self.s.bridge.commands.insert(0, ("bluetoothctl devices", "__FAIL__"))
        self.s.ev(BT + ".refresh()")
        self.s.wait(400)
        self.assertTrue(self.s.ev(BT + ".hasScanned"))
        self.assertEqual(self.state(), {}, "a list that never arrived must read as empty, not stale")
        self.s.bridge.commands.pop(0)
        self.s.ev(BT + ".refresh()")
        self.s.wait(600)
        self.assertEqual(self.state(), WANT, "the backend stayed busy after a failed start")

    def test_an_info_query_that_cannot_start_skips_only_that_device(self):
        self.s.bridge.commands.insert(0, ("bluetoothctl info AA:00:00:00:00:02", "__FAIL__"))
        self.s.ev(BT + ".refresh()")
        self.s.wait(600)
        st = self.state()
        self.assertEqual(st, {"Headphones": (True, 80), "Keyboard": (False, 10)})


if __name__ == "__main__":
    unittest.main(verbosity=2)
