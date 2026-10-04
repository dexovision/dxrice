#!/usr/bin/env python3
"""Regression suite for dxrice_copy_once_ownership.py's classification model.

Every fixture here is built in a disposable tmp directory standing in for
config_home/state_dir/repo_dir -- nothing here ever touches a real $HOME.
The central fixture (TestRealConfigDockIncident) reproduces the exact
real-world incident that motivated this module: a genuinely user-owned,
current-shaped ~/.config/waybar/config-dock, with real custom taskbar
shortcuts, that predates the copy_once_snapshots mechanism and was
previously misclassified as foreign and overwritten.
"""
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

import dxrice_copy_once_ownership as ownership


REAL_CONFIG_DOCK = {
    "layer": "bottom",
    "name": "waybar-dock",
    "modules-left": [
        "custom/brave", "custom/discord", "custom/sober", "custom/steam",
        "custom/prismlauncher", "custom/oraclevirtualbox", "custom/terminal",
        "custom/files", "custom/visualstudiocode",
    ],
    "dxrice_icon_size": 28,
    "dxrice_icons_enabled": True,
    "custom/brave": {"dxrice_label": "Brave", "dxrice_cmd": "brave", "dxrice_icon_mode": "auto",
                      "format": "", "on-click": "sh -c 'brave >/dev/null 2>&1 &'",
                      "tooltip": True, "tooltip-format": "Brave", "class": "app-icon"},
    "custom/discord": {"dxrice_label": "Discord", "dxrice_cmd": "discord", "dxrice_icon_mode": "auto",
                        "format": "", "on-click": "sh -c 'discord >/dev/null 2>&1 &'",
                        "tooltip": True, "tooltip-format": "Discord", "class": "app-icon"},
    "custom/sober": {"dxrice_label": "Sober", "dxrice_cmd": "flatpak run org.vinegarhq.Sober",
                      "dxrice_icon_mode": "auto", "format": "",
                      "on-click": "sh -c 'flatpak run org.vinegarhq.Sober >/dev/null 2>&1 &'",
                      "tooltip": True, "tooltip-format": "Sober", "class": "app-icon"},
    "custom/steam": {"dxrice_label": "Steam", "dxrice_cmd": "/usr/bin/steam", "dxrice_icon_mode": "auto",
                      "format": "", "on-click": "sh -c '/usr/bin/steam >/dev/null 2>&1 &'",
                      "tooltip": True, "tooltip-format": "Steam", "class": "app-icon"},
    "custom/prismlauncher": {"dxrice_label": "Prism Launcher", "dxrice_cmd": "prismlauncher",
                              "dxrice_icon_mode": "auto", "format": "",
                              "on-click": "sh -c 'prismlauncher >/dev/null 2>&1 &'",
                              "tooltip": True, "tooltip-format": "Prism Launcher", "class": "app-icon"},
    "custom/oraclevirtualbox": {"dxrice_label": "Oracle VirtualBox", "dxrice_cmd": "VirtualBox",
                                 "dxrice_icon_mode": "auto", "format": "",
                                 "on-click": "sh -c 'VirtualBox >/dev/null 2>&1 &'",
                                 "tooltip": True, "tooltip-format": "Oracle VirtualBox", "class": "app-icon"},
    "custom/terminal": {"dxrice_label": "Terminal", "dxrice_cmd": "kitty", "dxrice_icon_mode": "auto",
                         "format": "", "on-click": "sh -c 'kitty >/dev/null 2>&1 &'",
                         "tooltip": True, "tooltip-format": "Terminal", "class": "app-icon"},
    "custom/files": {"dxrice_label": "Files", "dxrice_cmd": "nautilus", "dxrice_icon_mode": "auto",
                      "format": "", "on-click": "sh -c 'nautilus >/dev/null 2>&1 &'",
                      "tooltip": True, "tooltip-format": "Files", "class": "app-icon"},
    "custom/visualstudiocode": {"dxrice_label": "Visual Studio Code", "dxrice_cmd": "code",
                                 "dxrice_icon_mode": "auto", "format": "",
                                 "on-click": "sh -c 'code >/dev/null 2>&1 &'",
                                 "tooltip": True, "tooltip-format": "Visual Studio Code", "class": "app-icon"},
}


class OwnershipTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="dxrice-ownership-test-"))
        self.config_home = self.tmp / "config"
        self.state_dir = self.tmp / "state"
        self.repo_dir = self.tmp / "repo"
        for d in (self.config_home / "waybar", self.config_home / "hypr",
                  self.state_dir / "copy_once_snapshots",
                  self.repo_dir / "waybar", self.repo_dir / "hypr"):
            d.mkdir(parents=True)
        # A plausible current repo template for each slot, used by the
        # claim-snapshot path and by any fixture that needs "what the repo
        # ships today" distinct from "what the user has live".
        (self.repo_dir / "waybar/config-dock").write_text(
            json.dumps({"name": "waybar-dock", "modules-left": ["custom/terminal", "custom/files"]}, indent=4))
        (self.repo_dir / "hypr/hyprland.lua").write_text(
            'local repo = os.getenv("DXRICE_REPO") or (home .. "/dxrice")\n'
            '-- dxrice_repo marker\nhl.bind(mainMod .. " + G", hl.dsp.exec_cmd("echo"))\n')

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write_live(self, rel, content):
        p = self.config_home / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, dict):
            p.write_text(json.dumps(content, indent=4))
        else:
            p.write_text(content)
        return p

    def write_snapshot(self, rel, content):
        p = ownership._snapshot_path(self.state_dir, rel)
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, dict):
            p.write_text(json.dumps(content, indent=4))
        else:
            p.write_text(content)
        return p

    def classify(self, rel):
        recognizer = dict(ownership._SLOTS)[rel]
        return ownership.classify_one(rel, recognizer, self.config_home, self.state_dir)


class TestMissingDestination(OwnershipTestBase):
    def test_no_live_file_is_missing(self):
        state, detail = self.classify("waybar/config-dock")
        self.assertEqual(state, ownership.MISSING)


class TestSnapshotPresentUnchanged(OwnershipTestBase):
    def test_live_matches_snapshot_exactly(self):
        content = {"name": "waybar-dock", "modules-left": ["custom/terminal"]}
        self.write_live("waybar/config-dock", content)
        self.write_snapshot("waybar/config-dock", content)
        state, detail = self.classify("waybar/config-dock")
        self.assertEqual(state, ownership.DXRICE_OWNED_UNCHANGED)


class TestSnapshotPresentModified(OwnershipTestBase):
    def test_user_customized_since_snapshot(self):
        self.write_snapshot("waybar/config-dock", {"name": "waybar-dock", "modules-left": ["custom/terminal"]})
        self.write_live("waybar/config-dock",
                         {"name": "waybar-dock", "modules-left": ["custom/terminal", "custom/brave"]})
        state, detail = self.classify("waybar/config-dock")
        self.assertEqual(state, ownership.DXRICE_OWNED_MODIFIED)

    def test_modified_state_is_never_touched_by_claim_snapshot(self):
        # claim_snapshot must never be invoked for an already-snapshotted
        # file by install.sh's own logic, but prove here that even if it
        # somehow were, the LIVE file is never read or written by it.
        self.write_snapshot("waybar/config-dock", {"name": "waybar-dock"})
        live = self.write_live("waybar/config-dock", {"name": "waybar-dock", "modules-left": ["custom/brave"]})
        before = live.read_bytes()
        ownership.claim_snapshot("waybar/config-dock", self.config_home, self.state_dir, self.repo_dir)
        self.assertEqual(live.read_bytes(), before)


class TestLegacyDxriceOldShaped(OwnershipTestBase):
    def test_old_pre_quickshell_waybar_config_is_legacy_old_shaped(self):
        # An ancient config referencing a pre-Quickshell script name directly,
        # no "name" field at all (that convention didn't exist yet).
        old = '{"modules-left": ["custom/taskbar"], "custom/taskbar": {"exec": "~/scripts/manage-taskbar.sh"}}'
        self.write_live("waybar/config-dock", old)
        state, detail = self.classify("waybar/config-dock")
        self.assertEqual(state, ownership.LEGACY_DXRICE)
        self.assertEqual(detail, "old-shaped")

    def test_old_hyprland_lua_referencing_legacy_script_is_legacy_old_shaped(self):
        old = 'hl.exec_cmd("python3 ~/scripts/infinite_desktop_core.py 1.6")\n'
        self.write_live("hypr/hyprland.lua", old)
        state, detail = self.classify("hypr/hyprland.lua")
        self.assertEqual(state, ownership.LEGACY_DXRICE)
        self.assertEqual(detail, "old-shaped")


class TestForeign(OwnershipTestBase):
    def test_waybar_config_named_for_a_different_setup_is_foreign(self):
        other = {"name": "some-other-rice-top-bar", "modules-left": ["clock"]}
        self.write_live("waybar/config", other)
        state, detail = self.classify("waybar/config")
        self.assertEqual(state, ownership.FOREIGN)

    def test_native_hyprland_conf_at_the_lua_path_is_foreign(self):
        native = "monitor=,preferred,auto,1\nexec-once=waybar\nbind=SUPER,Q,exec,kitty\n"
        self.write_live("hypr/hyprland.lua", native)
        state, detail = self.classify("hypr/hyprland.lua")
        self.assertEqual(state, ownership.FOREIGN)


class TestUnknown(OwnershipTestBase):
    def test_waybar_config_with_no_name_field_and_no_markers_is_unknown(self):
        ambiguous = {"modules-left": ["clock"], "clock": {"format": "{:%H:%M}"}}
        self.write_live("waybar/config", ambiguous)
        state, detail = self.classify("waybar/config")
        self.assertEqual(state, ownership.UNKNOWN)

    def test_invalid_json_with_no_markers_is_unknown_not_foreign(self):
        self.write_live("waybar/config", "{not even valid json")
        state, detail = self.classify("waybar/config")
        self.assertEqual(state, ownership.UNKNOWN)

    def test_generic_lua_with_no_markers_is_unknown(self):
        self.write_live("hypr/hyprland.lua", "-- just some personal lua notes\nprint('hi')\n")
        state, detail = self.classify("hypr/hyprland.lua")
        self.assertEqual(state, ownership.UNKNOWN)

    def test_unknown_file_is_never_touched_by_classification_alone(self):
        p = self.write_live("waybar/config", "{not even valid json")
        before = p.read_bytes()
        self.classify("waybar/config")
        self.assertEqual(p.read_bytes(), before, "classify_one must be read-only")


class TestRealConfigDockIncident(OwnershipTestBase):
    """The exact real-world fixture: a genuinely user-owned, current-shaped
    config-dock with real custom shortcuts, no snapshot (predates the
    mechanism) -- must classify as LEGACY_DXRICE/current-shaped, and the
    fix (claim_snapshot) must leave the live file byte-for-byte untouched."""

    def test_classifies_as_legacy_dxrice_current_shaped_not_foreign(self):
        self.write_live("waybar/config-dock", REAL_CONFIG_DOCK)
        state, detail = self.classify("waybar/config-dock")
        self.assertEqual(state, ownership.LEGACY_DXRICE,
                          "a genuine current-shaped DXrice file must never classify as FOREIGN "
                          "or UNKNOWN just because it predates the snapshot mechanism")
        self.assertEqual(detail, "current-shaped")

    def test_claim_snapshot_leaves_live_file_byte_for_byte_identical(self):
        live = self.write_live("waybar/config-dock", REAL_CONFIG_DOCK)
        before = live.read_bytes()
        before_mtime = live.stat().st_mtime_ns

        ok = ownership.claim_snapshot("waybar/config-dock", self.config_home, self.state_dir, self.repo_dir)
        self.assertTrue(ok)

        after = live.read_bytes()
        self.assertEqual(before, after, "claim_snapshot must never modify the live file")
        self.assertEqual(live.stat().st_mtime_ns, before_mtime, "claim_snapshot must not even rewrite the file")

        # Every real shortcut must still be there, verbatim.
        restored = json.loads(after)
        for app in ("custom/brave", "custom/discord", "custom/sober", "custom/steam",
                    "custom/prismlauncher", "custom/oraclevirtualbox", "custom/visualstudiocode"):
            self.assertIn(app, restored)
            self.assertIn("dxrice_label", restored[app])
            self.assertIn("dxrice_cmd", restored[app])

    def test_after_claiming_snapshot_file_reclassifies_as_owned_modified(self):
        # The snapshot is seeded from the bare repo template (see the next
        # test), which legitimately differs from the user's real
        # customized content -- so MODIFIED, not UNCHANGED, is the
        # correct, accurate classification from this point on. Either way
        # it is now a definitively-owned, never-replaced state.
        self.write_live("waybar/config-dock", REAL_CONFIG_DOCK)
        ownership.claim_snapshot("waybar/config-dock", self.config_home, self.state_dir, self.repo_dir)
        state, detail = self.classify("waybar/config-dock")
        self.assertEqual(state, ownership.DXRICE_OWNED_MODIFIED)

    def test_snapshot_is_seeded_from_repo_template_not_live_file(self):
        # The live file has the user's real customizations; the repo
        # template (set up in setUp) is the bare default. The backfilled
        # snapshot must match the REPO template, not the user's live
        # content -- matching dxrice_check_hypr_drift.py's own established
        # convention for exactly this "no prior snapshot" situation.
        self.write_live("waybar/config-dock", REAL_CONFIG_DOCK)
        ownership.claim_snapshot("waybar/config-dock", self.config_home, self.state_dir, self.repo_dir)
        snap = ownership._snapshot_path(self.state_dir, "waybar/config-dock")
        self.assertEqual(snap.read_bytes(), (self.repo_dir / "waybar/config-dock").read_bytes())


class TestAdversarialRobustness(OwnershipTestBase):
    """Found during the installer ownership audit: classify_one must never
    crash on a hostile or damaged filesystem state, and must never let
    that damage become a write path."""

    def test_unreadable_live_file_with_existing_snapshot_does_not_crash(self):
        live = self.write_live("waybar/config-dock", {"name": "waybar-dock"})
        self.write_snapshot("waybar/config-dock", {"name": "waybar-dock"})
        os.chmod(live, 0o000)
        try:
            state, detail = self.classify("waybar/config-dock")
        finally:
            os.chmod(live, 0o644)
        # Must not crash, and must land on a state that can never trigger
        # a write -- MODIFIED and UNCHANGED are the only two options here,
        # both always safe.
        self.assertIn(state, (ownership.DXRICE_OWNED_MODIFIED, ownership.DXRICE_OWNED_UNCHANGED))

    def test_directory_where_a_file_is_expected_does_not_crash(self):
        live = self.config_home / "waybar" / "config-dock"
        live.mkdir(parents=True)
        state, detail = self.classify("waybar/config-dock")
        self.assertEqual(state, ownership.UNKNOWN)

    def test_directory_at_snapshot_path_does_not_crash(self):
        live = self.write_live("waybar/config-dock", {"name": "waybar-dock"})
        snap = ownership._snapshot_path(self.state_dir, "waybar/config-dock")
        snap.mkdir(parents=True)
        state, detail = self.classify("waybar/config-dock")
        # A snapshot "existing" as a directory still counts as present --
        # the state must be one that never triggers a write.
        self.assertIn(state, (ownership.DXRICE_OWNED_MODIFIED, ownership.DXRICE_OWNED_UNCHANGED))

    def test_corrupted_snapshot_can_never_cause_an_overwrite_eligible_state(self):
        # A snapshot that exists but is garbage (truncated, bit-rotted,
        # whatever) must never cause classification to fall through to
        # LEGACY_DXRICE/FOREIGN/UNKNOWN -- its mere presence is what keeps
        # this file out of every overwrite-eligible branch, regardless of
        # its content.
        self.write_live("waybar/config-dock", REAL_CONFIG_DOCK)
        snap = ownership._snapshot_path(self.state_dir, "waybar/config-dock")
        snap.parent.mkdir(parents=True, exist_ok=True)
        snap.write_bytes(b"\x00\x01\x02 not even close to valid JSON \xff\xfe")
        state, detail = self.classify("waybar/config-dock")
        self.assertIn(state, (ownership.DXRICE_OWNED_MODIFIED, ownership.DXRICE_OWNED_UNCHANGED))
        # And the live file must obviously still be untouched.
        live_text = json.loads((self.config_home / "waybar/config-dock").read_text())
        self.assertIn("custom/discord", live_text)

    def test_stale_snapshot_from_an_older_repo_template_is_still_safe(self):
        # The repo's template for this file can change between DXrice
        # versions -- a snapshot seeded long ago, from an older template,
        # must still only ever land on a no-write state, never cause a
        # reclassification into something replaceable.
        self.write_live("waybar/config-dock", REAL_CONFIG_DOCK)
        self.write_snapshot("waybar/config-dock", {"name": "waybar-dock", "modules-left": []})  # old, bare template
        state, detail = self.classify("waybar/config-dock")
        self.assertEqual(state, ownership.DXRICE_OWNED_MODIFIED)


class TestClassifyAll(OwnershipTestBase):
    def test_reports_every_slot_with_a_live_file_and_skips_missing_ones(self):
        self.write_live("waybar/config-dock", REAL_CONFIG_DOCK)
        self.write_live("waybar/config", {"name": "waybar-top"})
        results = ownership.classify_all(self.config_home, self.state_dir)
        rels = {rel for rel, _, _ in results}
        self.assertIn("waybar/config-dock", rels)
        self.assertIn("waybar/config", rels)
        self.assertNotIn("waybar/config-left", rels)
        self.assertNotIn("hypr/hyprland.lua", rels)


if __name__ == "__main__":
    unittest.main(verbosity=2)
