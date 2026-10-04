#!/usr/bin/env python3
"""Regression suite for dxrice_manifest.deploy_file's ownership guard.

Central fixture (TestUnrecognizedFileIsNeverOverwritten) reproduces a real,
broadly-reachable invariant violation found during the installer ownership
audit: deploy_file's old "adopted" branch silently backed up and overwrote
ANY pre-existing file with no manifest record, no confirmation, every
single time -- the identical root cause as the config-dock incident, just
reachable through dxrice_apply_theme.py's TARGETS (waybar/style.css,
wofi/style.css, mako/config, kitty/kitty.conf, hyprlock.conf,
gtk_style.css) and dxrice_deploy.py's STATIC_FILES (wofi/config), all
files most Linux users already have hand-customized before ever installing
this rice. "No manifest record" is proof of nothing; it is never treated
as proof of DXrice ownership.
"""
import os
import shutil
import tempfile
import unittest
from pathlib import Path

import dxrice_manifest


class ManifestTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="dxrice-manifest-test-"))
        # Never touch the real machine's backup directory from a test --
        # redirect it into this test's own disposable tmp dir.
        self._real_backup_dir = dxrice_manifest.BACKUP_DIR
        dxrice_manifest.BACKUP_DIR = self.tmp / "backups"

    def tearDown(self):
        dxrice_manifest.BACKUP_DIR = self._real_backup_dir
        shutil.rmtree(self.tmp, ignore_errors=True)

    def live(self, name="config"):
        return self.tmp / name


class TestAtomicWriteBytes(ManifestTestBase):
    """Found during the installer ownership audit: every write to a path
    that may already hold real content used Path.write_bytes/write_text
    directly, which truncates the destination before writing the new
    data -- a process killed mid-write (crash, OOM, power loss) leaves a
    corrupted, partially-overwritten file instead of the original. Write-
    then-atomic-rename closes that window: a killed write leaves either
    the untouched original or the complete new content, never a mix."""

    def test_writes_new_content_to_a_fresh_path(self):
        target = self.live("new_file")
        dxrice_manifest.atomic_write_bytes(target, b"hello")
        self.assertEqual(target.read_bytes(), b"hello")

    def test_replaces_existing_content_completely(self):
        target = self.live("existing")
        target.write_bytes(b"old content, nice and long")
        dxrice_manifest.atomic_write_bytes(target, b"new")
        self.assertEqual(target.read_bytes(), b"new")

    def test_creates_missing_parent_directories(self):
        target = self.tmp / "a" / "b" / "c" / "file"
        dxrice_manifest.atomic_write_bytes(target, b"data")
        self.assertEqual(target.read_bytes(), b"data")

    def test_no_leftover_temp_file_after_a_successful_write(self):
        target = self.live("clean")
        dxrice_manifest.atomic_write_bytes(target, b"data")
        leftovers = [p for p in self.tmp.iterdir() if p.name != "clean"]
        self.assertEqual(leftovers, [])

    def test_failed_write_leaves_original_file_untouched(self):
        # Simulate a mid-write failure (e.g. disk full) by making the
        # write itself raise -- the original file must survive exactly as
        # it was, and no stray temp file should be left behind either.
        target = self.live("precious")
        original = b"the user's real, valuable content"
        target.write_bytes(original)

        import dxrice_manifest as m
        real_fdopen = os.fdopen

        def failing_fdopen(fd, mode):
            f = real_fdopen(fd, mode)
            f.write = lambda *a, **k: (_ for _ in ()).throw(OSError("simulated disk full"))
            return f

        os.fdopen = failing_fdopen
        try:
            with self.assertRaises(OSError):
                m.atomic_write_bytes(target, b"new content that will never land")
        finally:
            os.fdopen = real_fdopen

        self.assertEqual(target.read_bytes(), original, "original must survive an interrupted write")
        leftovers = [p for p in self.tmp.iterdir() if p.name != "precious"]
        self.assertEqual(leftovers, [], "no stray temp file should remain after a failed write")


class TestMissingDestination(ManifestTestBase):
    def test_fresh_install_writes_the_file(self):
        live = self.live()
        manifest = {"version": 1, "files": {}}
        result = dxrice_manifest.deploy_file(live, b"new content", manifest)
        self.assertEqual(result, "installed")
        self.assertEqual(live.read_bytes(), b"new content")


class TestUnchanged(ManifestTestBase):
    def test_live_already_matches_new_content(self):
        live = self.live()
        live.write_bytes(b"same content")
        manifest = {"version": 1, "files": {}}
        before_mtime = live.stat().st_mtime_ns
        result = dxrice_manifest.deploy_file(live, b"same content", manifest)
        self.assertEqual(result, "unchanged")
        self.assertEqual(live.stat().st_mtime_ns, before_mtime, "must not rewrite an already-matching file")


class TestUnrecognizedFileIsNeverOverwritten(ManifestTestBase):
    """The exact bug: no manifest record + differs from template used to
    mean silent backup-and-overwrite ("adopted"). Now it must mean
    preserve, unconditionally, with no backup needed because nothing is
    touched."""

    def test_no_record_and_differs_from_template_is_preserved(self):
        live = self.live("kitty.conf")
        live.write_text("# my own kitty config from years before this rice existed\nfont_size 14\n")
        before = live.read_bytes()
        manifest = {"version": 1, "files": {}}  # no record at all -- exactly the real scenario

        result = dxrice_manifest.deploy_file(live, b"# dxrice's own kitty template\nfont_size 11\n", manifest)

        self.assertEqual(result, "unrecognized")
        self.assertEqual(live.read_bytes(), before, "a file with no manifest record must never be overwritten")

    def test_unrecognized_file_gets_no_backup_and_no_manifest_entry(self):
        # Nothing is done to it at all -- it was never DXrice's to begin
        # with, so there is nothing to "take over" and nothing to record.
        live = self.live("mako_config")
        live.write_text("# hand-written mako config\n")
        manifest = {"version": 1, "files": {}}
        backups_before = (set(dxrice_manifest.BACKUP_DIR.iterdir())
                           if dxrice_manifest.BACKUP_DIR.exists() else set())

        dxrice_manifest.deploy_file(live, b"# dxrice mako template\n", manifest)

        self.assertNotIn(dxrice_manifest.rel_key(live), manifest["files"])
        backups_after = (set(dxrice_manifest.BACKUP_DIR.iterdir())
                          if dxrice_manifest.BACKUP_DIR.exists() else set())
        self.assertEqual(backups_before, backups_after, "must not create any new backup file")

    def test_byte_for_byte_across_repeated_deploys(self):
        # Simulates install -> install -> update: an unrecognized file must
        # survive every single subsequent run identically, not just the
        # first one.
        live = self.live("hyprlock.conf")
        live.write_text("# my own hyprlock config\nbackground { path = ~/wall.png }\n")
        before = live.read_bytes()
        manifest = {"version": 1, "files": {}}

        for _ in range(3):
            result = dxrice_manifest.deploy_file(live, b"# dxrice hyprlock template\n", manifest)
            self.assertEqual(result, "unrecognized")
            self.assertEqual(live.read_bytes(), before)


class TestSkippedModified(ManifestTestBase):
    def test_tracked_file_hand_edited_since_last_deploy_is_preserved(self):
        live = self.live()
        live.write_text("user's hand-edited version")
        before = live.read_bytes()
        # Manifest DOES have a record, but it doesn't match the live
        # content -- proof DXrice deployed this once, and the user has
        # since changed it.
        manifest = {"version": 1, "files": {dxrice_manifest.rel_key(live): "some-other-hash-not-matching-live"}}

        result = dxrice_manifest.deploy_file(live, b"new template content", manifest)

        self.assertEqual(result, "skipped-modified")
        self.assertEqual(live.read_bytes(), before)


class TestUpdated(ManifestTestBase):
    def test_tracked_unmodified_file_is_updated_to_new_template(self):
        live = self.live()
        old_content = b"old template content"
        live.write_bytes(old_content)
        manifest = {"version": 1, "files": {dxrice_manifest.rel_key(live): dxrice_manifest._sha256(old_content)}}

        result = dxrice_manifest.deploy_file(live, b"new template content", manifest)

        self.assertEqual(result, "updated")
        self.assertEqual(live.read_bytes(), b"new template content")


if __name__ == "__main__":
    unittest.main(verbosity=2)
