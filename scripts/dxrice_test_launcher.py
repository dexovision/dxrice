#!/usr/bin/env python3
"""The launcher's non-QML parts: its history, the app list's usage counts,
and the SUPER+R bind (template and migration)."""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import dxrice_hypr_migrate as mig  # noqa: E402
import dxrice_launcher_history as hist  # noqa: E402

TEMPLATE = os.path.join(HERE, "..", "hypr", "hyprland.lua")


class History(unittest.TestCase):
    def test_recent_launches_are_kept_newest_first_and_capped(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "dxrice", "launcher_recent.json")
            for i in range(hist.MAX_RECENT + 5):
                hist.touch_recent(f"App {i}", p, now=1000 + i)
            data = hist.load_recent(p)
            self.assertEqual(len(data), hist.MAX_RECENT)
            self.assertEqual(max(data, key=data.get), f"App {hist.MAX_RECENT + 4}")
            self.assertNotIn("App 0", data, "the oldest should be forgotten")
            hist.touch_recent("App 0", p, now=5000)
            self.assertEqual(hist.load_recent(p)["App 0"], 5000)
            with open(p, "w") as f:
                f.write("{torn")
            self.assertEqual(hist.load_recent(p), {})

    def test_bump_counts_and_survives_a_missing_or_torn_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "sub", "h.json")
            self.assertEqual(hist.load(p), {})
            hist.bump("Firefox", p)
            hist.bump("Firefox", p)
            hist.bump("Kitty", p)
            self.assertEqual(hist.load(p), {"Firefox": 2, "Kitty": 1})
            open(p, "w").write('{"torn')
            self.assertEqual(hist.load(p), {})
            hist.bump("Kitty", p)
            self.assertEqual(hist.load(p), {"Kitty": 1})
            open(p, "w").write('[1, 2]')
            self.assertEqual(hist.load(p), {})

    def test_it_never_grows_without_bound(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "h.json")
            for i in range(hist.MAX_ENTRIES + 20):
                hist.bump(f"app{i}", p)
            self.assertLessEqual(len(hist.load(p)), hist.MAX_ENTRIES)

    def test_the_app_list_carries_the_counts(self):
        with tempfile.TemporaryDirectory() as d:
            state = os.path.join(d, "dxrice")
            os.makedirs(state)
            json.dump({"Discord": 7}, open(os.path.join(state, "launcher_history.json"), "w"))
            env = dict(os.environ, XDG_STATE_HOME=d)
            out = subprocess.run([sys.executable, os.path.join(HERE, "dxrice_list_desktop_apps.py")],
                                 capture_output=True, text=True, env=env, timeout=30)
            apps = json.loads(out.stdout)
            self.assertTrue(apps and all("uses" in a for a in apps))
            for a in apps:
                self.assertEqual(a["uses"], 7 if a["name"] == "Discord" else 0)

    def test_the_cli(self):
        with tempfile.TemporaryDirectory() as d:
            env = dict(os.environ, XDG_STATE_HOME=d)
            run = lambda *a: subprocess.run([sys.executable, os.path.join(HERE, "dxrice_launcher_history.py"), *a],  # noqa: E731
                                            capture_output=True, text=True, env=env, timeout=30)
            self.assertEqual(run("bump", "Some", "App").returncode, 0)
            self.assertEqual(json.loads(run("dump").stdout), {"Some App": 1})
            self.assertEqual(run("nonsense").returncode, 2)


class Bind(unittest.TestCase):
    def test_the_template_opens_the_shell_launcher_with_wofi_as_the_fallback(self):
        text = open(TEMPLATE).read()
        m = re.search(r'hl\.bind\(mainMod \.\. " \+ R", hl\.dsp\.exec_cmd\(\s*"sh -c \'qs -p " \.\. repo \.\. "(.*?)" \.\. menu', text, re.S)
        self.assertIsNotNone(m)
        self.assertIn("ipc call launcher toggle", m.group(1))
        self.assertIn('local menu        = "wofi --show drun"', text)

    def test_hyprland_accepts_it(self):
        hypr = shutil.which("Hyprland")
        if not hypr:
            self.skipTest("Hyprland not installed")
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "t.lua")
            shutil.copy(TEMPLATE, p)
            env = {k: v for k, v in os.environ.items() if k not in ("HYPRLAND_INSTANCE_SIGNATURE", "WAYLAND_DISPLAY", "DISPLAY")}
            r = subprocess.run([hypr, "--verify-config", "-c", p], capture_output=True, text=True, timeout=60, env=env)
            self.assertIn("config ok", r.stdout + r.stderr)

    def test_the_migration_changes_only_that_line_and_only_once(self):
        old = open(TEMPLATE).read()
        old = old[:old.index("-- The shell's own launcher")] + 'hl.bind(mainMod .. " + R", hl.dsp.exec_cmd(menu))' + \
            old[old.index("\n", old.index("|| \" .. menu .. \"'\"))")):]
        self.assertIn(("launcher-bind", mig.MIGRATIONS[[m[0] for m in mig.MIGRATIONS].index("launcher-bind")][1]),
                      mig.pending(old))
        once = mig.migrate(old, {"launcher-bind"})
        self.assertIn("ipc call launcher toggle", once)
        self.assertEqual(mig.migrate(once, {"launcher-bind"}), once)
        self.assertEqual(once, open(TEMPLATE).read())

    def test_a_line_the_user_changed_is_left_alone(self):
        mine = open(TEMPLATE).read().replace("-- The shell's own launcher; wofi if the shell isn't running.\n", "")
        mine = re.sub(r'hl\.bind\(mainMod \.\. " \+ R".*?menu \.\. "\'"\)\)', 'hl.bind(mainMod .. " + R", hl.dsp.exec_cmd("rofi -show drun"))', mine, flags=re.S)
        self.assertEqual(mig.migrate(mine, {"launcher-bind"}), mine)


if __name__ == "__main__":
    unittest.main()
