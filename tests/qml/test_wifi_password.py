"""The Quick Settings Wi-Fi password goes to dxrice_wifi_connect.py on
stdin, never as a command-line argument (where any local user could read it
in `ps`), and the panel doesn't keep it afterwards.

    python3 tests/qml/test_wifi_password.py
"""
import json
import secrets
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


class WifiPassword(unittest.TestCase):
    def setUp(self):
        self.s = Scene()
        self.s.ev("panels.open('quicksettings')")
        self.s.wait(900)
        self.secret = "dx-test-" + secrets.token_hex(8)  # throwaway

    def tearDown(self):
        self.s.close()

    def test_password_goes_on_stdin_not_argv(self):
        self.assertIsNotNone(self.s.ev("findNamed('wifiBackend')"), "Quick Settings didn't load its Wi-Fi backend")
        self.s.ev("findNamed('wifiBackend').connectTo('HomeNet', 'WPA2')")
        self.s.wait(200)
        self.s.ev(f"findNamed('wifiBackend').connectWithPassword('HomeNet', '{self.secret}')")
        self.s.wait(200)
        runs = [argv for argv in self.s.bridge.run_log if any("dxrice_wifi_connect.py" in a for a in argv)]
        self.assertEqual(len(runs), 1, self.s.bridge.run_log)
        self.assertEqual(runs[0][-2:], ["HomeNet", "WPA2"])
        # every command the shell ran or started detached
        for argv in self.s.bridge.run_log + self.s.bridge.exec_log:
            self.assertNotIn(self.secret, " ".join(argv), "the password was on a command line")
        written = json.loads(self.s.ev("JSON.stringify(findNamed('wifiSecretConnect').written)"))
        self.assertEqual(written, [self.secret + "\n"])
        self.assertEqual(self.s.ev("findNamed('wifiSecretConnect')._secret"), "", "the panel kept the password")


if __name__ == "__main__":
    unittest.main(verbosity=2)
