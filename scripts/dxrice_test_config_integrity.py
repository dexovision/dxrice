#!/usr/bin/env python3
"""Static integrity checks between hyprland.lua, the QML shell, the repo and
install.sh's dependency lists.

hyprland.lua launched /usr/lib/polkit-kde-agent-1 from the very first
commit -- a path no package installs -- and nothing noticed, because nothing
checked what the config runs. This reads every command the config
launches (keybinds and autostart, including what runs inside `sh -c '...'`
and `$(...)`) and checks that:

  * repo scripts/QML it references exist (and are executable if run
    directly);
  * it never runs a hard-coded absolute program path -- those are
    machine-specific; resolve them at runtime in a repo helper instead
    (scripts/dxrice_polkit_agent.sh);
  * every program it runs is base system, installed by install.sh (its
    package arrays for EVERY package manager it supports, or
    install_quickshell), or explicitly listed below as an optional
    personal app -- and is a name the parser could actually resolve;
  * the systemd units it restarts are exactly the ones install.sh writes
    and uninstall removes;
  * scripts the QML shell runs, and install.sh's verify_deploy list, exist.

Pure file reading: nothing is executed.

    python3 scripts/dxrice_test_config_integrity.py
"""
import os
import re
import shlex
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LUA = os.path.join(REPO, "hypr", "hyprland.lua")
INSTALL = os.path.join(REPO, "install.sh")

# Programs every supported system has: the shell, coreutils/util-linux,
# systemd, procps -- not something install.sh could or should install.
BASE_SYSTEM = {"sh", "bash", "mkdir", "tee", "date", "setsid", "systemctl", "pgrep", "id", "true", "false"}

# Shell words that look like commands but aren't programs.
SHELL_WORDS = {"if", "then", "else", "elif", "fi", "for", "in", "do", "done", "while", "case", "esac",
               "command", "exec", "export", "cd", "echo", "test", "[", "]", "!", "{", "}", ">", ">>", "2>&1",
               ">/dev/null", "&"}

# Program -> the Arch package that provides it. The dnf/apt/zypper lists
# use the same name unless OTHER_DISTRO_NAMES says otherwise.
PROVIDED_BY = {
    "python3": "python",
    "kitty": "kitty",
    "nautilus": "nautilus",
    "wofi": "wofi",
    "waybar": "waybar",
    "swaybg": "swaybg",
    "mako": "mako",
    "nm-applet": "network-manager-applet",
    "nm-connection-editor": "network-manager-applet",
    "blueman-applet": "blueman",
    "blueman-manager": "blueman",
    "wl-paste": "wl-clipboard",
    "wl-copy": "wl-clipboard",
    "cliphist": "cliphist",
    "grim": "grim",
    "slurp": "slurp",
    "wpctl": "wireplumber",
    "brightnessctl": "brightnessctl",
    "pavucontrol": "pavucontrol",
    "qt6ct": "qt6ct",
    "nwg-look": "nwg-look",
    "hyprctl": "hyprland",
    "hyprlock": "hyprlock",
}

# Arch package -> its name in another package manager's list, where that
# differs. None: not packaged there -- install.sh must tell the user so
# (a `warn` naming it) instead.
OTHER_DISTRO_NAMES = {
    "python": {"dnf": "python3", "apt": "python3", "zypper": "python3"},
    "mako": {"apt": "mako-notifier"},
    "network-manager-applet": {"apt": "network-manager-gnome", "zypper": "NetworkManager-applet"},
    "cliphist": {"dnf": None, "apt": None, "zypper": None},
    "nwg-look": {"dnf": None, "apt": None, "zypper": None},
}

# Package manager -> install.sh's arrays it installs from. HYPR_PACKAGES is
# shared: install_hypr_ecosystem resolves it per distro.
MANAGER_ARRAYS = {
    "pacman": ("GENERAL_PACMAN", "HYPR_PACKAGES", "AUR_PACKAGES"),
    "dnf": ("GENERAL_DNF", "HYPR_PACKAGES"),
    "apt": ("GENERAL_APT", "HYPR_PACKAGES"),
    "zypper": ("GENERAL_ZYPPER", "HYPR_PACKAGES"),
}

# Placeholders a program may legitimately start with (see lua_commands).
# Any other <name> is a variable the parser couldn't resolve -- which used
# to be skipped, so a program behind it was never checked at all.
CHECKED_PLACEHOLDERS = ("<REPO>/",)

# Installed by a dedicated installer step rather than a package array.
INSTALLED_SEPARATELY = {"qs": "install_quickshell"}

# Personal apps bound to keys in the shipped config that install.sh does
# not (and should not have to) install -- the audit's P2-11 is to move these
# binds out of the shared config. Listed explicitly so a NEW unprovided
# program can't slip in unnoticed.
OPTIONAL_PERSONAL_APPS = {"firefox", "discord", "yazi", "cava"}


def _read(path):
    with open(path) as f:
        return f.read()


def _strip_lua_comments(src):
    """Drops `--[[ ... ]]` block comments and whole-line `--` comments."""
    src = re.sub(r"--\[(=*)\[.*?\]\1\]", "", src, flags=re.S)
    return "\n".join(line for line in src.splitlines() if not line.lstrip().startswith("--"))


# Every Lua string literal form: "double", 'single' and [[long]] / [==[long]==].
_LUA_STRING = r"""\"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|\[(?P<eq>=*)\[.*?\](?P=eq)\]"""
_LUA_TOKEN = re.compile(r"(?P<literal>" + _LUA_STRING + r")|(?P<name>[A-Za-z_][\w.]*)", re.S)


def _lua_literal(token):
    if token.startswith("["):
        return token[token.index("[", 1) + 1:token.rindex("]", 0, -1)]
    return re.sub(r"\\(.)", r"\1", token[1:-1])


def _lua_string_vars(src):
    """`local name = <literal>` and `local name = os.getenv(...) or <literal>`,
    in any string form, with or without a trailing comment."""
    out = {}
    pattern = (r"^\s*local\s+(\w+)\s*=\s*(?:os\.getenv\([^)]*\)\s*or\s*)?(" + _LUA_STRING
               + r")[ \t]*(?:--[^\n]*)?$")
    for m in re.finditer(pattern, src, re.M | re.S):
        out[m.group(1)] = _lua_literal(m.group(2))
    return out


def _call_args(src, func):
    """The raw argument text of every `<func>(...)` call (balanced parens,
    string-aware)."""
    args = []
    for m in re.finditer(re.escape(func) + r"\(", src):
        i, depth, quote = m.end(), 1, None
        start = i
        while i < len(src) and depth:
            c = src[i]
            if quote:
                if c == "\\":
                    i += 1
                elif c == quote:
                    quote = None
            elif c in "\"'":
                quote = c
            elif c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
            i += 1
        args.append(src[start:i - 1])
    return args


def _resolve_concat(expr, variables):
    """Evaluates a Lua `"a" .. var .. 'b' .. [[c]]` concatenation to one
    string; a variable it can't resolve becomes `<name>`."""
    out = []
    for m in _LUA_TOKEN.finditer(expr):
        literal, name = m.group("literal"), m.group("name")
        if literal:
            out.append(_lua_literal(literal))
        else:
            out.append(variables.get(name, "<" + name + ">"))
    return "".join(out)


def lua_commands(src=None):
    src = _strip_lua_comments(_read(LUA) if src is None else src)
    variables = _lua_string_vars(src)
    variables.update({"repo": "<REPO>", "home": "<HOME>", "bg_path": "<WALLPAPER>"})
    cmds = []
    for arg in _call_args(src, "exec_cmd"):
        cmds.append(_resolve_concat(arg, variables))
    return cmds


def _split_outside_quotes(script):
    """Splits a shell snippet on ; && || | & -- but only outside quotes, so
    a quoted `sh -c '...'` script stays one word."""
    pieces, buf, quote, i = [], [], None, 0
    while i < len(script):
        c = script[i]
        if quote:
            buf.append(c)
            if c == quote:
                quote = None
        elif c in "\"'":
            quote = c
            buf.append(c)
        elif script.startswith(("&&", "||"), i):
            pieces.append("".join(buf)); buf = []; i += 1
        elif c in ";|" or (c == "&" and not (buf and buf[-1] in ">0123456789") and not script.startswith("&>", i)):
            pieces.append("".join(buf)); buf = []
        else:
            buf.append(c)
        i += 1
    pieces.append("".join(buf))
    return pieces


def _simple_commands(script):
    """First words (and `-e` targets) of every simple command in a shell
    snippet, recursing into `sh -c '...'` and `$(...)`."""
    programs = []
    for inner in re.findall(r"\$\(([^()]*)\)", script):
        programs += _simple_commands(inner)
    script = re.sub(r"\$\([^()]*\)", "X", script)
    for piece in _split_outside_quotes(script):
        try:
            words = shlex.split(piece)
        except ValueError:
            words = piece.split()
        while words and (words[0] in SHELL_WORDS or re.match(r"^\w+=", words[0])):
            if words[0] == "for":
                words = []  # `for x in a b c` -- a loop header, not a program
                break
            if words[0] == "command" and words[1:2] == ["-v"]:
                words = words[2:]  # `command -v qs` checks for (depends on) qs
                break
            words = words[1:]
        if not words:
            continue
        prog = words[0]
        programs.append(prog)
        if prog == "setsid" and len(words) > 1:
            programs.append(words[1])
        if prog in ("sh", "bash") and "-c" in words and words.index("-c") + 1 < len(words):
            programs += _simple_commands(words[words.index("-c") + 1])
        if prog == "kitty" and "-e" in words and words.index("-e") + 1 < len(words):
            programs.append(words[words.index("-e") + 1])
    return programs


def installer_packages(install_src, manager):
    pkgs = set()
    for name in MANAGER_ARRAYS[manager]:
        m = re.search(r"^" + name + r"=\(([^)]*)\)", install_src, re.M)
        assert m, f"install.sh has no {name} array"
        pkgs |= set(m.group(1).split())
    return pkgs


def absolute_path_problems(commands):
    return [f"hyprland.lua runs a hard-coded absolute path {prog!r} ({cmd!r}) -- "
            "machine-specific; probe for it in a repo helper instead"
            for cmd in commands for prog in _simple_commands(cmd) if prog.startswith("/")]


def program_problems(commands, install_src):
    """Every program the commands run that isn't accounted for, on any of
    install.sh's package managers."""
    installed = {mgr: installer_packages(install_src, mgr) for mgr in MANAGER_ARRAYS}
    problems = []
    for cmd in commands:
        for prog in _simple_commands(cmd):
            if prog.startswith("<"):
                if not prog.startswith(CHECKED_PLACEHOLDERS):
                    problems.append(f"{prog}: runs something the check can't resolve (an unknown variable, "
                                    f"or a path under the user's home) -- {cmd!r}")
                continue
            if prog in BASE_SYSTEM or prog in OPTIONAL_PERSONAL_APPS:
                continue
            if prog in INSTALLED_SEPARATELY:
                if not re.search(r"^" + INSTALLED_SEPARATELY[prog] + r"\(\)", install_src, re.M):
                    problems.append(f"{prog}: install.sh has no {INSTALLED_SEPARATELY[prog]}()")
                continue
            if prog not in PROVIDED_BY:
                problems.append(f"{prog}: unknown program -- add it to PROVIDED_BY (and install.sh) "
                                f"or OPTIONAL_PERSONAL_APPS ({cmd!r})")
                continue
            arch_pkg = PROVIDED_BY[prog]
            for mgr, pkgs in installed.items():
                pkg = arch_pkg if mgr == "pacman" else OTHER_DISTRO_NAMES.get(arch_pkg, {}).get(mgr, arch_pkg)
                if pkg is None:
                    if not re.search(r'warn "[^"\n]*' + re.escape(arch_pkg), install_src):
                        problems.append(f"{prog}: not packaged for {mgr}, and install.sh never tells the user")
                elif pkg not in pkgs:
                    problems.append(f"{prog}: needs package {pkg!r}, which install.sh's {mgr} list doesn't install")
    return sorted(set(problems))


class HyprlandConfigIntegrityTest(unittest.TestCase):
    def setUp(self):
        self.commands = lua_commands()
        self.assertGreater(len(self.commands), 20, "parsed suspiciously few commands from hyprland.lua")

    def test_repo_files_it_runs_exist(self):
        for cmd in self.commands:
            for rel in re.findall(r"<REPO>/([\w./-]+)", cmd):
                path = os.path.join(REPO, rel)
                self.assertTrue(os.path.isfile(path), f"hyprland.lua runs {rel}, which is not in the repo: {cmd!r}")
                if cmd.strip().startswith("<REPO>/" + rel):
                    self.assertTrue(os.access(path, os.X_OK), f"{rel} is run directly but is not executable")

    def test_no_hard_coded_absolute_program_paths(self):
        self.assertEqual(absolute_path_problems(self.commands), [])

    def test_every_program_it_runs_is_provided(self):
        self.assertEqual(program_problems(self.commands, _read(INSTALL)), [])

    def test_systemd_units_agree(self):
        # hyprland.lua starts them through dxrice_session.sh, which restarts
        # the units under systemd
        self.assertTrue(any("<REPO>/scripts/dxrice_session.sh" in c for c in self.commands),
                        "hyprland.lua's autostart doesn't run dxrice_session.sh")
        session = _read(os.path.join(REPO, "scripts", "dxrice_session.sh"))
        lua_units = set(re.findall(r"dxrice-[a-z-]+\.service", session))
        install_src = _read(INSTALL)
        m = re.search(r"DXRICE_UNITS=\(([^)]*)\)", install_src)
        self.assertIsNotNone(m, "install.sh has no DXRICE_UNITS list")
        removed = set(m.group(1).split())
        written = set(re.findall(r'\$unit_dir/(dxrice-[a-z-]+\.service)', install_src))
        self.assertTrue(lua_units, "no DXrice units found in dxrice_session.sh")
        self.assertEqual(lua_units, written, "units dxrice_session.sh restarts != units install.sh writes")
        self.assertEqual(written, removed, "units install.sh writes != units uninstall removes")


class ShellAndInstallerIntegrityTest(unittest.TestCase):
    def test_scripts_run_by_the_qml_shell_exist(self):
        qml_dir = os.path.join(REPO, "quickshell")
        for name in sorted(os.listdir(qml_dir)):
            if not name.endswith(".qml"):
                continue
            for rel in re.findall(r'"/(?:\.\./)?scripts/([\w.-]+)"', _read(os.path.join(qml_dir, name))):
                self.assertTrue(os.path.isfile(os.path.join(REPO, "scripts", rel)), f"{name} runs scripts/{rel}, which is missing")

    def test_verify_deploy_list_exists_in_repo(self):
        body = re.search(r"verify_deploy\(\) \{(.*?)\n\}", _read(INSTALL), re.S).group(1)
        for rel in re.findall(r'"\$REPO_DIR/([^"]+)"', body):
            self.assertTrue(os.path.exists(os.path.join(REPO, rel)), f"verify_deploy requires {rel}, which is missing")

    def test_polkit_helper_probes_the_real_arch_agent(self):
        src = _read(os.path.join(REPO, "scripts", "dxrice_polkit_agent.sh"))
        self.assertIn("/usr/lib/polkit-kde-authentication-agent-1", src)
        self.assertTrue(os.access(os.path.join(REPO, "scripts", "dxrice_polkit_agent.sh"), os.X_OK))


class CheckerSelfTest(unittest.TestCase):
    """The checks above must fail on a broken config, not just pass on the
    current one. Each case is a way the first version of this test passed a
    config that was broken."""

    BASE = 'local repo = dxrice_repo()\nlocal home = os.getenv("HOME")\n'

    def commands(self, lua):
        return lua_commands(self.BASE + lua)

    def test_absolute_path_in_any_lua_string_form_is_caught(self):
        # The original bug (/usr/lib/polkit-kde-agent-1), quoted the other
        # two ways Lua allows: both used to resolve to nothing checkable.
        for lua in ("hl.exec_cmd('/usr/lib/polkit-kde-agent-1')\n",
                    "hl.exec_cmd([[/usr/lib/polkit-kde-agent-1]])\n",
                    "hl.exec_cmd([==[/usr/lib/polkit-kde-agent-1]==])\n",
                    "local agent = '/usr/lib/polkit-kde-agent-1'\nhl.exec_cmd(agent)\n"):
            with self.subTest(lua=lua):
                self.assertEqual(self.commands(lua), ["/usr/lib/polkit-kde-agent-1"])
                self.assertTrue(absolute_path_problems(self.commands(lua)))

    def test_variable_with_trailing_comment_is_resolved(self):
        cmds = self.commands('local browser = "nonexistent-app" -- my browser\nhl.exec_cmd(browser)\n')
        self.assertEqual(cmds, ["nonexistent-app"])
        self.assertTrue(any("nonexistent-app: unknown program" in p for p in program_problems(cmds, _read(INSTALL))))

    def test_a_commented_variable_does_not_hide_the_ones_after_it(self):
        # [[long]] strings need DOTALL, under which a trailing `-- .*`
        # comment ran on to the end of the file and swallowed every
        # later `local`.
        cmds = self.commands('local a = "x" -- c\nlocal b = "mako"\nhl.exec_cmd(b)\n')
        self.assertEqual(cmds, ["mako"])

    def test_unresolvable_program_is_a_problem_not_skipped(self):
        for lua in ("hl.exec_cmd(some_function())\n", 'hl.exec_cmd(home .. "/.local/bin/tool")\n'):
            with self.subTest(lua=lua):
                self.assertTrue(program_problems(self.commands(lua), _read(INSTALL)))

    def test_repo_program_is_left_to_the_repo_file_check(self):
        cmds = self.commands('hl.exec_cmd(repo .. "/scripts/dxrice_polkit_agent.sh")\n')
        self.assertEqual(program_problems(cmds, _read(INSTALL)), [])

    def test_package_missing_from_another_distro_is_caught(self):
        src = _read(INSTALL)
        broken = re.sub(r"^(GENERAL_DNF=\([^)]*?) wl-clipboard", r"\1", src, flags=re.M)
        self.assertNotEqual(broken, src, "fixture: wl-clipboard not found in GENERAL_DNF")
        cmds = self.commands('hl.exec_cmd("wl-paste --watch cliphist store")\n')
        self.assertEqual(program_problems(cmds, src), [])
        self.assertEqual(program_problems(cmds, broken),
                         ["wl-paste: needs package 'wl-clipboard', which install.sh's dnf list doesn't install"])

    def test_block_comment_is_ignored(self):
        self.assertEqual(self.commands('--[[\nhl.exec_cmd("/usr/lib/old")\n]]\nhl.exec_cmd("mako")\n'), ["mako"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
