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

        def half_write_then_fail(obj, f, **kw):
            f.write('{"accent": "12')
            raise OSError(28, "No space left on device")

        with mock.patch.object(migrate.json, "dump", side_effect=half_write_then_fail):
            with self.assertRaises(OSError):
                migrate.migrate_file(self.path)
        self.assertEqual(open(self.path).read(), before, "theme.json was damaged by a failed migration write")
        self.assertEqual([n for n in os.listdir(self.dir) if n.endswith(".tmp")], [], "temp file left behind")

    def test_permissions_are_kept(self):
        self.write({"accent": "123456"}, mode=0o640)
        migrate.migrate_file(self.path)
        self.assertEqual(os.stat(self.path).st_mode & 0o777, 0o640)


if __name__ == "__main__":
    unittest.main(verbosity=2)
