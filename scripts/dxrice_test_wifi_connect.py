#!/usr/bin/env python3
"""Joining a secured Wi-Fi network never exposes the password.

dxrice_wifi_connect.py runs against a fake `nmcli` that records every
argument list it gets and, while "activating", scans every process's
/proc/PID/cmdline for the secret, so a password on any command line --
nmcli's, the helper's own, a shell's -- is caught. The secret is a random
throwaway token, never a real password.

Also checked: the secret reaches nmcli only through a 0600 passwd-file that
is gone afterwards; a failed join deletes the profile it created; WPA3,
WEP and existing profiles; 802.1X is refused; nothing echoes the secret on
stdout or stderr. And statically, that neither front end (QuickSettings
QML or the GTK app) passes a password argument to nmcli any more.

  python3 scripts/dxrice_test_wifi_connect.py
"""
import json
import os
import re
import secrets
import subprocess
import sys
import tempfile
import textwrap
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
HELPER = os.path.join(HERE, "dxrice_wifi_connect.py")

FAKE_NMCLI = textwrap.dedent('''\
    #!/usr/bin/env python3
    import json, os, stat, sys
    state = os.environ["FAKE_STATE"]
    log = os.environ["FAKE_LOG"]
    secret = os.environ["FAKE_SECRET_PROBE"]
    args = sys.argv[1:]
    entry = {"argv": args}
    with open(state) as f:
        names = json.load(f)
    if args[:5] == ["-t", "-f", "NAME", "connection", "show"]:
        print("\\n".join(names))
    elif args[:2] == ["connection", "add"]:
        names.append(args[args.index("con-name") + 1])
    elif args[:2] == ["connection", "delete"]:
        names.remove(args[-1])
    elif args[:2] == ["connection", "up"]:
        path = args[args.index("passwd-file") + 1]
        entry["passwd_file"] = open(path).read()
        entry["passwd_mode"] = oct(stat.S_IMODE(os.stat(path).st_mode))
        hits = []
        for pid in os.listdir("/proc"):
            if not pid.isdigit():
                continue
            try:
                with open(f"/proc/{pid}/cmdline", "rb") as c:
                    if secret.encode() in c.read():
                        hits.append(pid)
            except OSError:
                pass
        entry["cmdline_hits"] = hits
        if os.environ.get("FAKE_UP_FAIL"):
            print("Error: Connection activation failed: Secrets were required, but not provided.", file=sys.stderr)
            with open(log, "a") as f:
                f.write(json.dumps(entry) + "\\n")
            sys.exit(4)
    with open(state, "w") as f:
        json.dump(names, f)
    with open(log, "a") as f:
        f.write(json.dumps(entry) + "\\n")
''')


class Rig:
    def __init__(self, existing=()):
        self.tmp = tempfile.mkdtemp(prefix="dxrice-wifi-")
        self.bin = os.path.join(self.tmp, "bin")
        self.run_dir = os.path.join(self.tmp, "run")
        os.makedirs(self.bin)
        os.makedirs(self.run_dir, mode=0o700)
        path = os.path.join(self.bin, "nmcli")
        with open(path, "w") as f:
            f.write(FAKE_NMCLI)
        os.chmod(path, 0o755)
        self.state = os.path.join(self.tmp, "state.json")
        self.log = os.path.join(self.tmp, "log.jsonl")
        with open(self.state, "w") as f:
            json.dump(list(existing), f)
        open(self.log, "w").close()
        self.secret = "dx-test-" + secrets.token_hex(12)  # throwaway, never a real password

    def run(self, ssid, security, fail=False):
        env = dict(os.environ, PATH=self.bin + os.pathsep + os.environ.get("PATH", ""),
                   XDG_RUNTIME_DIR=self.run_dir, FAKE_STATE=self.state, FAKE_LOG=self.log,
                   FAKE_SECRET_PROBE=self.secret)
        env.pop("FAKE_UP_FAIL", None)
        if fail:
            env["FAKE_UP_FAIL"] = "1"
        return subprocess.run([sys.executable, HELPER, ssid, security], input=self.secret + "\n",
                              capture_output=True, text=True, env=env, timeout=30, check=False)

    def calls(self):
        with open(self.log) as f:
            return [json.loads(line) for line in f if line.strip()]

    def profiles(self):
        with open(self.state) as f:
            return json.load(f)

    def leftovers(self):
        found = []
        for root, _dirs, files in os.walk(self.run_dir):
            found += [os.path.join(root, n) for n in files]
        return found


class TestNoExposure(unittest.TestCase):
    def assert_never_exposed(self, rig, result):
        for call in rig.calls():
            self.assertNotIn(rig.secret, " ".join(call["argv"]), f"secret in nmcli argv: {call['argv']}")
            self.assertEqual(call.get("cmdline_hits", []), [],
                             "secret visible in some process's /proc/PID/cmdline while nmcli ran")
        self.assertNotIn(rig.secret, result.stdout)
        self.assertNotIn(rig.secret, result.stderr)
        self.assertEqual(rig.leftovers(), [], "passwd-file left behind")

    def test_wpa2_join(self):
        rig = Rig()
        r = rig.run("HomeNet", "WPA1 WPA2")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assert_never_exposed(rig, r)
        calls = rig.calls()
        add = next(c for c in calls if c["argv"][:2] == ["connection", "add"])
        self.assertIn("wpa-psk", add["argv"])
        up = next(c for c in calls if c["argv"][:2] == ["connection", "up"])
        self.assertEqual(up["passwd_file"], f"802-11-wireless-security.psk:{rig.secret}\n")
        self.assertEqual(up["passwd_mode"], "0o600")
        self.assertEqual(rig.profiles(), ["HomeNet"], "profile should stay, holding the secret, like device wifi connect")

    def test_wpa3_only_uses_sae(self):
        rig = Rig()
        r = rig.run("Office", "WPA3")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("sae", next(c for c in rig.calls() if c["argv"][:2] == ["connection", "add"])["argv"])
        self.assert_never_exposed(rig, r)

    def test_wep_uses_the_wep_key(self):
        rig = Rig()
        r = rig.run("Old", "WEP")
        self.assertEqual(r.returncode, 0, r.stderr)
        up = next(c for c in rig.calls() if c["argv"][:2] == ["connection", "up"])
        self.assertTrue(up["passwd_file"].startswith("802-11-wireless-security.wep-key0:"))
        self.assert_never_exposed(rig, r)

    def test_an_existing_profile_is_reused(self):
        rig = Rig(existing=["HomeNet"])
        r = rig.run("HomeNet", "WPA2")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(any(c["argv"][:2] == ["connection", "add"] for c in rig.calls()))
        self.assert_never_exposed(rig, r)

    def test_a_failed_join_cleans_up(self):
        rig = Rig()
        r = rig.run("HomeNet", "WPA2", fail=True)
        self.assertEqual(r.returncode, 1)
        self.assertIn("couldn't connect to HomeNet", r.stderr)
        self.assertEqual(rig.profiles(), [], "the profile created for a failed join was kept")
        self.assert_never_exposed(rig, r)

    def test_a_failed_join_keeps_a_profile_it_did_not_create(self):
        rig = Rig(existing=["HomeNet"])
        r = rig.run("HomeNet", "WPA2", fail=True)
        self.assertEqual(r.returncode, 1)
        self.assertEqual(rig.profiles(), ["HomeNet"])
        self.assert_never_exposed(rig, r)

    def test_enterprise_networks_are_refused(self):
        rig = Rig()
        r = rig.run("Corp", "WPA2 802.1X")
        self.assertEqual(r.returncode, 2)
        self.assertEqual(rig.calls(), [])
        self.assert_never_exposed(rig, r)

    def test_no_password_is_a_usage_error(self):
        rig = Rig()
        r = subprocess.run([sys.executable, HELPER, "HomeNet", "WPA2"], input="", capture_output=True,
                           text=True, env=dict(os.environ, PATH=rig.bin + os.pathsep + os.environ["PATH"]),
                           check=False)
        self.assertEqual(r.returncode, 2)


class TestTheProbeWorks(unittest.TestCase):
    """Negative control: the /proc scan does see a password passed the old
    way, as a command-line argument."""

    def test_a_password_in_argv_is_caught(self):
        rig = Rig(existing=["HomeNet"])
        pw = os.path.join(rig.tmp, "pw")
        with open(pw, "w") as f:
            f.write("x")
        env = dict(os.environ, FAKE_STATE=rig.state, FAKE_LOG=rig.log, FAKE_SECRET_PROBE=rig.secret)
        subprocess.run([os.path.join(rig.bin, "nmcli"), "connection", "up", "id", "HomeNet", "passwd-file", pw,
                        "password", rig.secret], env=env, check=True)
        self.assertNotEqual(rig.calls()[-1]["cmdline_hits"], [])


class TestFrontEndsDontPassPasswords(unittest.TestCase):
    """The original exposure, as written in both front ends:
    nmcli ... wifi connect SSID password SECRET."""

    def test_no_nmcli_password_argument_anywhere(self):
        pattern = re.compile(r'nmcli[^\n]*"password"')
        offenders = []
        for d, ext in (("quickshell", ".qml"), ("scripts", ".py")):
            for name in sorted(os.listdir(os.path.join(REPO, d))):
                if not name.endswith(ext) or name.startswith("dxrice_test_"):
                    continue
                with open(os.path.join(REPO, d, name)) as f:
                    for i, line in enumerate(f, 1):
                        if pattern.search(line):
                            offenders.append(f"{d}/{name}:{i}: {line.strip()}")
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
