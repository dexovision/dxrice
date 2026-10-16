#!/usr/bin/env python3
"""Brings an already-deployed hyprland.lua forward, one exact edit at a time.

hyprland.lua is copied into ~/.config/hypr once and is the user's file from
then on, so a fix to the repo's template never reaches it on its own. Each
migration below replaces only text an earlier DXrice template shipped,
character for character. A line the user has changed doesn't match and is
left alone (`plan` reports it). Every applied change is preceded by a backup
of the whole file, checked byte for byte, and written atomically.

  dxrice_hypr_migrate.py plan  FILE
      one line per pending migration: "<id>\\t<description>"; id "manual"
      marks a fix this file needs by hand
  dxrice_hypr_migrate.py apply FILE BACKUP_DIR [ID ...]
      backs FILE up into BACKUP_DIR, then applies the given migrations (all
      pending ones if none are named); prints the backup's path

Exit status: 0 on success (also when nothing was pending), 1 on error.
"""
import os
import re
import shutil
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dxrice_manifest import atomic_write_bytes


def _replace(old, new):
    def apply(text):
        return text.replace(old, new)
    return lambda text: old in text, apply


_OLD_AUTOSTART_QS = (
    '    hl.exec_cmd("sh -c \'if command -v qs >/dev/null 2>&1; then "\n'
    '        .. "systemctl --user restart dxrice-quickshell.service; else "\n'
    '        .. "for c in config config-left config-right config-dock; do "\n'
    '        .. "setsid waybar -c ~/.config/waybar/$c -s ~/.config/waybar/style.css >/dev/null 2>&1 & "\n'
    '        .. "done; fi\'")\n'
)
_OLD_AUTOSTART_DAEMONS = (
    'hl.exec_cmd("systemctl --user restart dxrice-infinite-desktop.service")',
    'hl.exec_cmd("systemctl --user restart dxrice-auto-place-window.service")',
)
_SESSION_LINE = '    hl.exec_cmd(repo .. "/scripts/dxrice_session.sh")\n'


def _session_applies(text):
    return (_OLD_AUTOSTART_QS in text and all(line in text for line in _OLD_AUTOSTART_DAEMONS)
            and "local repo = dxrice_repo()" in text)


def _session_apply(text):
    text = text.replace(_OLD_AUTOSTART_QS, _SESSION_LINE)
    out = []
    for line in text.splitlines(keepends=True):
        if line.strip() in _OLD_AUTOSTART_DAEMONS:
            # the template's comment block directly above it goes with it
            while out and out[-1].lstrip().startswith("--"):
                out.pop()
            continue
        out.append(line)
    text = "".join(out)
    # a blank line left before the end of the start block
    return text.replace(_SESSION_LINE.rstrip("\n") + "\n", _SESSION_LINE)


# The very first templates started everything directly; the step after that
# moved each to a systemd unit. session-script then takes that form over.
_DIRECT_QS = '"qs -p " .. repo .. "/quickshell/shell.qml -d -n; else "'
_DIRECT_DAEMONS = (
    (re.compile(r'hl\.exec_cmd\("python3 " \.\. repo \.\. "/scripts/dxrice_infinite_desktop_core\.py 1\.6[^"]*"\)'),
     'hl.exec_cmd("systemctl --user restart dxrice-infinite-desktop.service")'),
    (re.compile(r'hl\.exec_cmd\("python3 " \.\. repo \.\. "/scripts/dxrice_auto_place_window\.py[^"]*"\)'),
     'hl.exec_cmd("systemctl --user restart dxrice-auto-place-window.service")'),
)


def _units_applies(text):
    return _DIRECT_QS in text and "dxrice-quickshell.service" not in text


def _units_apply(text):
    text = text.replace(_DIRECT_QS, '"systemctl --user restart dxrice-quickshell.service; else "')
    for pattern, line in _DIRECT_DAEMONS:
        text = pattern.sub(line, text)
    return text


_LAYER_FADE_LINES = (
    'hl.animation({ leaf = "fadeLayersIn",  enabled = false })\n'
    'hl.animation({ leaf = "fadeLayersOut", enabled = false })\n'
)


def _layer_fade_applies(text):
    return "fadeLayersIn" not in text and "fadeLayersOut" not in text and "hl.animation(" in text


def _layer_fade_apply(text):
    # After the last animation line, so it overrides the `fade` leaf the two
    # layer leaves would otherwise inherit.
    lines = text.splitlines(keepends=True)
    last = max(i for i, line in enumerate(lines) if line.lstrip().startswith("hl.animation("))
    if not lines[last].endswith("\n"):
        lines[last] += "\n"
    lines.insert(last + 1, _LAYER_FADE_LINES)
    return "".join(lines)


MIGRATIONS = [
    ("taskbar-gui",
     "SUPER+SHIFT+A opens the taskbar manager GUI instead of the old terminal script",
     *_replace('hl.dsp.exec_cmd("kitty -e " .. repo .. "/scripts/dxrice-manage-taskbar.sh")',
               'hl.dsp.exec_cmd("python3 " .. repo .. "/scripts/dxrice_taskbar_gui.py")')),
    ("systemd-units",
     "Quickshell and the two daemons start supervised (restarted after a crash)",
     _units_applies, _units_apply),
    ("polkit-agent",
     "start whichever polkit agent is installed (the old path didn't exist)",
     *_replace('hl.exec_cmd("/usr/lib/polkit-kde-agent-1")',
               'hl.exec_cmd(repo .. "/scripts/dxrice_polkit_agent.sh")')),
    ("session-script",
     "start the shell and daemons through scripts/dxrice_session.sh (works with or without systemd)",
     _session_applies, _session_apply),
    ("layer-fade-off",
     "turn off Hyprland's layer fade, which showed every window twice in the SUPER+Tab overview",
     _layer_fade_applies, _layer_fade_apply),
    ("xdg-state-home",
     "find the checkout through $XDG_STATE_HOME when it's set",
     *_replace('    local f = io.open(home .. "/.local/state/dxrice/repo_path", "r")',
               '    local f = io.open((os.getenv("XDG_STATE_HOME") or (home .. "/.local/state"))'
               ' .. "/dxrice/repo_path", "r")')),
]

# polkit-agent's and the old taskbar line's replacements need the template's
# `repo` variable; a file without it is reported instead of edited.
_NEEDS_REPO = {"taskbar-gui", "polkit-agent", "session-script"}


def pending(text):
    """[(id, description)] of the migrations that would change `text`, in
    the order they apply. Each is checked against the result of the ones
    before it, as `apply` runs them. A fix that can't be applied to this
    file (it lacks the template's `repo` variable) comes back as
    ("manual", what to change by hand)."""
    out = []
    has_repo = "local repo = dxrice_repo()" in text
    for mid, desc, applies, apply in MIGRATIONS:
        if mid in _NEEDS_REPO and not has_repo:
            if mid == "polkit-agent" and applies(text):
                out.append(("manual", 'replace hl.exec_cmd("/usr/lib/polkit-kde-agent-1") with a line that runs '
                                      '<your DXrice checkout>/scripts/dxrice_polkit_agent.sh'))
            continue
        if applies(text):
            out.append((mid, desc))
            text = apply(text)
    return out


def migrate(text, ids=None):
    has_repo = "local repo = dxrice_repo()" in text
    for mid, _desc, applies, apply in MIGRATIONS:
        if ids is not None and mid not in ids:
            continue
        if mid in _NEEDS_REPO and not has_repo:
            continue
        if applies(text):
            text = apply(text)
    return text


def backup(path, backup_dir):
    os.makedirs(backup_dir, exist_ok=True)
    dest = os.path.join(backup_dir, f"hyprland.lua.{time.strftime('%Y%m%d-%H%M%S')}.{os.getpid()}.bak")
    shutil.copy2(path, dest)
    with open(path, "rb") as a, open(dest, "rb") as b:
        if a.read() != b.read():
            raise OSError(f"backup {dest} does not match {path}")
    return dest


def main(argv):
    if len(argv) < 3 or argv[1] not in ("plan", "apply") or (argv[1] == "apply" and len(argv) < 4):
        print(__doc__, file=sys.stderr)
        return 1
    path = argv[2]
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError as e:
        print(f"can't read {path}: {e}", file=sys.stderr)
        return 1

    if argv[1] == "plan":
        for mid, desc in pending(text):
            print(f"{mid}\t{desc}")
        return 0

    ids = set(argv[4:]) or None
    new = migrate(text, ids)
    if new == text:
        return 0
    try:
        dest = backup(path, argv[3])
        atomic_write_bytes(path, new.encode("utf-8"))
    except OSError as e:
        print(f"left {path} unchanged: {e}", file=sys.stderr)
        return 1
    print(dest)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
