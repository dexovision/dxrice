#!/usr/bin/env python3
"""The README says only true things about the repository.

  - every keybind in hypr/hyprland.lua is in the README's table, and every
    key combination the table names is bound;
  - every repository path the README mentions exists;
  - every `./install.sh MODE` and `dx SUBCOMMAND` it shows is real;
  - the Gentoo atoms it names are in deps/emerge.list.

  python3 scripts/dxrice_test_docs.py
"""
import glob
import os
import re
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(rel):
    with open(os.path.join(REPO, rel)) as f:
        return f.read()


README = read("README.md")
LUA = read("hypr/hyprland.lua")
INSTALL = read("install.sh")

# Binds the table describes as a group rather than one row per key.
GROUPED = {
    "left": "SUPER + arrows", "right": "SUPER + arrows", "up": "SUPER + arrows", "down": "SUPER + arrows",
    "mouse_down": "SUPER` + scroll", "mouse_up": "SUPER` + scroll",
    "mouse:272": "left / right drag", "mouse:273": "left / right drag",
}


def lua_binds():
    """Every statically bound combination, as the README writes it."""
    out = set()
    for m in re.finditer(r'hl\.bind\(\s*(mainMod\s*\.\.\s*)?"([^"]+)"', LUA):
        keys = m.group(2).strip()
        if m.group(1):
            keys = "SUPER" + (keys if keys.startswith(" ") else " " + keys)
        keys = re.sub(r"\s+", " ", keys)
        if not keys.endswith("+"):  # `" + " .. key` in the workspace loop
            out.add(keys)
    return out


def readme_keys():
    table = README[README.index("## Keybindings"):]
    table = table[:table.index("\n## ", 1)]
    return set(re.findall(r"`((?:SUPER|PRINT)[^`]*)`", table)), table


class TestKeybindingTable(unittest.TestCase):
    def test_every_bind_is_documented(self):
        documented, table = readme_keys()
        missing = []
        for keys in sorted(lua_binds()):
            last = keys.split(" + ")[-1]
            if keys.startswith("XF86"):
                ok = "media and brightness keys" in table
            elif last in GROUPED:
                mods = keys.rsplit(" + ", 1)[0]
                ok = GROUPED[last] in table and (mods == "SUPER" or f"{mods} + arrows" in table)
            else:
                ok = keys in documented
            if not ok:
                missing.append(keys)
        self.assertEqual(missing, [], "bound in hyprland.lua but not in the README")

    def test_every_documented_combination_is_bound(self):
        documented, _ = readme_keys()
        binds = lua_binds()
        # the workspace binds come from a loop: SUPER + 0-9, SUPER + SHIFT + 0-9
        workspace = re.search(r'for i = 1, 10 do.*?mainMod \.\. " \+ " \.\. key.*?'
                              r'mainMod \.\. " \+ SHIFT \+ " \.\. key', LUA, re.S)
        self.assertIsNotNone(workspace, "the workspace bind loop changed shape")
        unbound = [k for k in sorted(documented)
                   if k not in binds and not k.startswith(("SUPER + 1", "SUPER + SHIFT + 1"))
                   and k not in ("SUPER + arrows", "SUPER + SHIFT + arrows", "SUPER + CTRL + arrows",
                                 "SUPER + ALT", "SUPER")]
        self.assertEqual(unbound, [], "in the README but not bound")


class TestReferences(unittest.TestCase):
    def test_paths_exist(self):
        paths = set(re.findall(r"(?<![\w/.~])((?:scripts|quickshell|docs|deps|theme|sddm|hypr)/[\w./-]*)", README))
        missing = [p for p in sorted(paths)
                   if not glob.glob(os.path.join(REPO, p.rstrip(".")) + ("*" if p.endswith("_") else ""))]
        self.assertEqual(missing, [])

    def test_install_modes_exist(self):
        modes = set(re.findall(r"install\.sh ([a-z][a-z-]*)", README))
        case = INSTALL[INSTALL.rindex('case "$MODE" in'):]
        for mode in modes:
            self.assertRegex(case, rf"\n\s*{re.escape(mode)}[|)]", f"install.sh has no '{mode}' mode")

    def test_dx_subcommands_exist(self):
        subs = set(re.findall(r"`dx ([a-z-]+)`", README))
        self.assertTrue(subs)
        block = INSTALL[INSTALL.index("dx() {"):INSTALL.index("# END dxrice shell functions")]
        for sub in subs:
            self.assertRegex(block, rf"\n\s*(?:[a-z|-]*\|)?{re.escape(sub)}(?:\|[a-z|-]*)?\)", f"dx has no '{sub}'")

    def test_gentoo_atoms_are_listed(self):
        gentoo = README[README.index("### Gentoo"):README.index("## Keybindings")]
        atoms = set(re.findall(r"`([a-z0-9-]+/[a-z0-9-]+)`", gentoo))
        listed = {line.split()[1] for line in read("deps/emerge.list").splitlines()
                  if line.strip() and not line.startswith("#")}
        extra = {"sys-auth/elogind"}  # an OpenRC system requirement, not a DXrice dependency
        self.assertEqual(sorted(atoms - listed - extra), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
