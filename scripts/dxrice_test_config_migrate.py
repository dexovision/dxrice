#!/usr/bin/env python3
"""dxrice_config_migrate.migrate_file(): only migrates (and only backs up)
when a file actually needs it, and never leaves theme.json half-written.

Every path is a temporary directory; XDG_DATA_HOME is pointed into it so
migration backups land there too, never in the real data directory.

    python3 scripts/dxrice_test_config_migrate.py
"""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dxrice_config_migrate as migrate  # noqa: E402


class MigrateFileTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = self._tmp.name
        self._env = mock.patch.dict(os.environ, {"XDG_DATA_HOME": os.path.join(self.dir, "data")})
        self._env.start()
        self.path = os.path.join(self.dir, "theme.json")

    def tearDown(self):
        self._env.stop()
        self._tmp.cleanup()

    def write(self, data, mode=0o600):
        with open(self.path, "w") as f:
            json.dump(data, f)
        os.chmod(self.path, mode)

    def backups(self):
        root = os.path.join(self.dir, "data", "dxrice", "backups")
        return sorted(os.listdir(root)) if os.path.isdir(root) else []

    def test_current_file_is_left_alone_with_no_backup(self):
        """A file the Theme editor saves keeps schema_version -- it must be
        a no-op here, not a fresh migration and backup per Apply."""
        self.write({"schema_version": migrate.CURRENT_SCHEMA_VERSION, "accent": "123456"})
        before = open(self.path).read()
        self.assertEqual(migrate.migrate_file(self.path), [])
        self.assertEqual(open(self.path).read(), before)
        self.assertEqual(self.backups(), [])

    def test_unversioned_file_is_migrated_once(self):
        self.write({"accent": "123456"})
        notes = migrate.migrate_file(self.path)
        self.assertTrue(notes)
        data = json.load(open(self.path))
        self.assertEqual(data["schema_version"], migrate.CURRENT_SCHEMA_VERSION)
        self.assertEqual(data["accent"], "123456", "migration changed an existing setting")
        self.assertEqual(len(self.backups()), 1)
        self.assertEqual(migrate.migrate_file(self.path), [], "a migrated file was migrated again")
        self.assertEqual(len(self.backups()), 1)

    def test_failed_write_leaves_the_original_intact(self):
        """open(path, "w") truncated the live file before writing it: a
        failure mid-write (crash, full disk) left an empty or partial
        theme.json."""
        original = {"accent": "123456", "glass_bg": "101010"}
        self.write(original)
        before = open(self.path).read()

        # the disk fills up while the new file is being written
        with mock.patch("os.fsync", side_effect=OSError(28, "No space left on device")):
            with self.assertRaises(OSError):
                migrate.migrate_file(self.path)
        self.assertEqual(open(self.path).read(), before, "theme.json was damaged by a failed migration write")
        self.assertEqual([n for n in os.listdir(self.dir) if n.endswith(".tmp")], [], "temp file left behind")

    def test_permissions_are_kept(self):
        self.write({"accent": "123456"}, mode=0o640)
        migrate.migrate_file(self.path)
        self.assertEqual(os.stat(self.path).st_mode & 0o777, 0o640)


    def make_backup_dirs(self, names):
        root = os.path.join(self.dir, "data", "dxrice", "backups")
        for name in names:
            os.makedirs(os.path.join(root, name, "marker"))

    def test_sddm_backups_cannot_evict_a_fresh_theme_backup(self):
        """dxrice_sync_sddm_theme.py writes sddm-<timestamp> backups into
        the same directory. Rotation counted them toward the 10 kept but,
        sorting after every timestamp, never removed them -- so with ten or
        more of them the theme backup just made was deleted straight away,
        before the migration overwrote theme.json."""
        sddm = [f"sddm-2026-09-{d:02d}_120000" for d in range(1, 13)]
        self.make_backup_dirs(sddm)
        self.write({"accent": "123456"})
        notes = migrate.migrate_file(self.path)
        theme_backups = [b for b in self.backups() if not b.startswith("sddm-")]
        self.assertEqual(len(theme_backups), 1, "the pre-migration backup was pruned as soon as it was made")
        saved = json.load(open(os.path.join(self.dir, "data", "dxrice", "backups", theme_backups[0], "theme.json")))
        self.assertEqual(saved, {"accent": "123456"})
        self.assertIn(theme_backups[0], notes[0])
        self.assertEqual(sorted(b for b in self.backups() if b.startswith("sddm-")), sddm,
                         "theme rotation removed SDDM backups")

    def test_rotation_keeps_the_newest_ten_theme_backups(self):
        old = [f"2026-01-{d:02d}_120000" for d in range(1, 13)]
        self.make_backup_dirs(old + ["sddm-2026-09-17_192237", "sddm-2026-09-17_200239"])
        self.write({"accent": "123456"})
        migrate.migrate_file(self.path)
        theme_backups = [b for b in self.backups() if not b.startswith("sddm-")]
        self.assertEqual(len(theme_backups), migrate.MAX_BACKUPS)
        self.assertEqual(theme_backups[:-1], old[-(migrate.MAX_BACKUPS - 1):], "an older backup outlived a newer one")
        self.assertEqual(len(self.backups()), migrate.MAX_BACKUPS + 2, "SDDM backups were touched")

    def test_existing_state_loses_nothing(self):
        """The state found on a real install (8 theme + 2 SDDM backups):
        one more theme backup must not prune anything."""
        existing = [f"2026-10-12_1404{n:02d}" for n in range(8)] + ["sddm-2026-09-17_192237", "sddm-2026-09-17_200239"]
        self.make_backup_dirs(existing)
        self.write({"accent": "123456"})
        migrate.migrate_file(self.path)
        self.assertTrue(set(existing) <= set(self.backups()))
        self.assertEqual(len(self.backups()), 11)


if __name__ == "__main__":
    unittest.main(verbosity=2)
