#!/usr/bin/env python3
"""scripts/dxrice_check_command.py: what it accepts and what it says."""
import os
import stat
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dxrice_check_command as c  # noqa: E402


class CheckCommand(unittest.TestCase):
    def test_ordinary_commands_pass(self):
        for cmd in ("sh", "sh -c 'echo hi'", "env FOO=1 sh -c true", "FOO=1 sh", "sh | cat && true",
                    "sh --title='My Cool App' arg2"):
            self.assertIsNone(c.problem(cmd), cmd)

    def test_empty_and_broken_ones_say_why(self):
        self.assertEqual(c.problem("   "), "Enter a command.")
        self.assertIn("quote", c.problem("sh -c 'oops"))
        self.assertIn("isn't installed", c.problem("definitely-not-a-program-xyz --flag"))
        self.assertIn("no program", c.problem("FOO=1"))

    def test_paths_with_spaces(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "my app")
            open(p, "w").write("#!/bin/sh\n")
            self.assertIn("isn't executable", c.problem(f"'{p}'"))
            os.chmod(p, os.stat(p).st_mode | stat.S_IXUSR)
            self.assertIsNone(c.problem(f"'{p}' --x 'a b'"))
            self.assertIn("doesn't exist", c.problem(f"'{d}/nope'"))

    def test_the_command_line_tool(self):
        import subprocess
        r = subprocess.run([sys.executable, c.__file__, "sh", "-c", "true"], capture_output=True, text=True)
        self.assertEqual((r.returncode, r.stdout), (0, ""))
        r = subprocess.run([sys.executable, c.__file__, "nope-xyz"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 1)
        self.assertIn("nope-xyz", r.stdout)


if __name__ == "__main__":
    unittest.main()
