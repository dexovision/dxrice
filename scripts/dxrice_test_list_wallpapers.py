#!/usr/bin/env python3
"""dxrice_list_wallpapers.py: which files are offered as wallpapers."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dxrice_list_wallpapers import LIMIT, list_wallpapers  # noqa: E402


def touch(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"x")


class TestListWallpapers(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_lists_only_images_sorted_by_name(self):
        for n in ("b.png", "A.jpg", "c.webp", "notes.txt", "d.png.bak"):
            touch(os.path.join(self.home, "Pictures", "Wallpapers", n))
        got = [w["name"] for w in list_wallpapers(home=self.home)]
        self.assertEqual(got, ["A", "b", "c"])

    def test_no_folder_means_an_empty_list_not_an_error(self):
        self.assertEqual(list_wallpapers(home=self.home), [])

    def test_the_folder_of_the_current_wallpaper_is_included_once(self):
        cur = os.path.join(self.home, "elsewhere", "mine.png")
        touch(cur)
        touch(os.path.join(self.home, "Pictures", "Wallpapers", "x.png"))
        got = list_wallpapers(cur, home=self.home)
        self.assertEqual([w["name"] for w in got], ["mine", "x"])
        self.assertEqual(len(list_wallpapers(os.path.join(self.home, "Pictures", "Wallpapers", "x.png"), home=self.home)), 1)

    def test_a_symlink_to_the_same_file_is_not_listed_twice(self):
        real = os.path.join(self.home, "Pictures", "Wallpapers", "a.png")
        touch(real)
        os.symlink(real, os.path.join(self.home, "Pictures", "Wallpapers", "b.png"))
        self.assertEqual([w["name"] for w in list_wallpapers(home=self.home)], ["a"])

    def test_a_directory_named_like_an_image_is_skipped(self):
        os.makedirs(os.path.join(self.home, "Pictures", "Wallpapers", "trap.png"))
        self.assertEqual(list_wallpapers(home=self.home), [])

    def test_the_list_is_capped(self):
        for i in range(LIMIT + 10):
            touch(os.path.join(self.home, "Pictures", "Wallpapers", f"w{i:03}.png"))
        self.assertEqual(len(list_wallpapers(home=self.home)), LIMIT)


if __name__ == "__main__":
    unittest.main()
