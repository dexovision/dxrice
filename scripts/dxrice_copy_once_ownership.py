#!/usr/bin/env python3
"""Ownership classifier for copy-once deployed files (hyprland.lua, the four
waybar configs).

Root cause this replaces: install.sh used to run three independent checks
over these files -- check_stale_hyprland_lua, check_stale_waybar_configs
(both marker-based, both correctly recognize a current-shaped dxrice file
and leave it alone), and check_foreign_copy_once_files (snapshot-absence-
based: "no snapshot => DXrice never deployed this => offer to replace it").
The third check ran independently of the first two's findings, so a file
the marker checks had just positively recognized as a genuine, current-
shaped DXrice deployment -- just one that predates the copy_once_snapshots
mechanism added after it was deployed -- still got treated as foreign
purely because it had no snapshot. Live incident: a real ~/.config/waybar/
config-dock with real custom taskbar shortcuts (Brave/Discord/Sober/Steam/
Prism Launcher/VirtualBox/VS Code) was backed up and overwritten with the
bare template on a completely ordinary `install.sh install` run.

This module is the single source of truth for "whose is this file", used
by install.sh in place of all three old checks. Hard safety invariant:

    IF OWNERSHIP CANNOT BE PROVEN, THE USER'S FILE IS PRESERVED.
    Uncertainty never results in an overwrite.

Only one state (LEGACY_DXRICE) is ever eligible for backup-and-replace, and
even then only through an explicit, declined-by-default-nothing-happens
confirmation in install.sh -- this module never deletes or overwrites
anything itself; it only classifies, and (for the one safe, no-content-
change case) backfills a missing snapshot.

States
------
MISSING                 -- nothing deployed at this path yet. Not this
                            module's concern; dxrice_deploy.py's normal
                            fresh-install path handles it.
DXRICE_OWNED_UNCHANGED   -- a snapshot exists and the live file still
                            matches it byte-for-byte.
DXRICE_OWNED_MODIFIED    -- a snapshot exists and the live file differs
                            (the user has customized it -- expected and
                            safe; copy-once files are supposed to be
                            hand-edited).
LEGACY_DXRICE            -- no snapshot, but the file can be POSITIVELY
                            identified as a DXrice deployment from before
                            the snapshot mechanism existed. Two shapes:
                              - current-shaped (still matches today's
                                marker) -> safe to silently backfill a
                                snapshot and otherwise leave completely
                                alone (detail="current-shaped")
                              - old-shaped (matches a legacy script-name
                                marker from a pre-Quickshell version of
                                this rice) -> eligible for an explicit,
                                opt-in backup-and-replace offer, the same
                                UX the old per-file checks already used
                                (detail="old-shaped")
FOREIGN                 -- no snapshot, no DXrice marker of any vintage,
                            AND positive evidence this belongs to
                            something else entirely (e.g. a waybar config
                            explicitly named for a different setup, or a
                            plain hyprland.conf-style file where DXrice
                            only ever deploys hyprland.lua). Preserved,
                            same as UNKNOWN -- the distinction is only
                            for a clearer message to the user, never a
                            difference in action.
UNKNOWN                 -- no snapshot, no marker, no positive foreign
                            evidence either -- genuinely can't tell.
                            Preserved.

Usage as a CLI (by install.sh):
    dxrice_copy_once_ownership.py classify <config_home> <state_dir> <repo_dir>
        Prints one line per copy-once slot that currently has a live file:
        "<rel>\t<STATE>\t<detail>"
    dxrice_copy_once_ownership.py claim-snapshot <rel> <config_home> <state_dir> <repo_dir>
        Backfills a missing snapshot for <rel> FROM THE REPO'S CURRENT
        TEMPLATE (never from the live file -- see _claim_snapshot's own
        docstring for why). Never touches the live file.
"""
import hashlib
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dxrice_xdg

MISSING = "MISSING"
DXRICE_OWNED_UNCHANGED = "DXRICE_OWNED_UNCHANGED"
DXRICE_OWNED_MODIFIED = "DXRICE_OWNED_MODIFIED"
LEGACY_DXRICE = "LEGACY_DXRICE"
FOREIGN = "FOREIGN"
UNKNOWN = "UNKNOWN"

# Script basenames from much older, pre-Quickshell versions of this rice --
# kept in sync with install.sh's own LEGACY_SCRIPT_NAMES (see that file's
# comment on why one shared list matters: a name added for one check must
# be recognized by every check that looks for an old deployment).
LEGACY_SCRIPT_NAMES = [
    "manage-taskbar.sh", "reorder-taskbar.sh", "infinite_desktop_core.py",
    "theme_gui.py", "floating_tile_toggle.py",
]


def _legacy_names_regex():
    escaped = [re.escape(n) for n in LEGACY_SCRIPT_NAMES]
    return re.compile(r"(dxrice[-_])?(" + "|".join(escaped) + r")")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class WaybarRecognizer:
    """Recognizer for one of the four waybar copy-once configs."""

    def __init__(self, expected_name):
        self.expected_name = expected_name

    def _parsed(self, text):
        try:
            obj = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            return None
        return obj if isinstance(obj, dict) else None

    def is_current(self, text):
        obj = self._parsed(text)
        return bool(obj) and obj.get("name") == self.expected_name

    def is_legacy(self, text):
        # An old, pre-Quickshell waybar config of THIS rice referenced its
        # old script names directly in on-click commands -- true regardless
        # of whether the file happens to parse as JSON (a badly-hand-edited
        # legacy config might not).
        return bool(_legacy_names_regex().search(text))

    def is_foreign(self, text):
        # Positive evidence of a DIFFERENT, deliberately-named setup: valid
        # JSON, has a "name" field (DXrice's own naming convention for
        # telling its four bars apart), but it names something that isn't
        # one of DXrice's own four bars.
        obj = self._parsed(text)
        if not obj:
            return False
        name = obj.get("name")
        return isinstance(name, str) and name != "" and name != self.expected_name


class HyprlandLuaRecognizer:
    _CURRENT_MARKER = "dxrice_repo"
    # Plain hyprland.conf (the pre-hyprland.lua config format) syntax --
    # DXrice only ever deploys hyprland.lua, so a file at this exact path
    # written in the OLD native format is positive evidence of a setup
    # DXrice never put there (a hand-rolled or different-rice hyprland.conf
    # that happens to live at the .lua path, or was renamed into it).
    _NATIVE_CONF_RE = re.compile(r"^\s*(monitor|exec-once|bind)\s*=", re.MULTILINE)

    def is_current(self, text):
        return self._CURRENT_MARKER in text

    def is_legacy(self, text):
        return bool(_legacy_names_regex().search(text))

    def is_foreign(self, text):
        return bool(self._NATIVE_CONF_RE.search(text)) and "hl." not in text


# (repo-relative path, recognizer, expected waybar name for messages)
_SLOTS = [
    ("hypr/hyprland.lua", HyprlandLuaRecognizer()),
    ("waybar/config", WaybarRecognizer("waybar-top")),
    ("waybar/config-left", WaybarRecognizer("waybar-left")),
    ("waybar/config-right", WaybarRecognizer("waybar-right")),
    ("waybar/config-dock", WaybarRecognizer("waybar-dock")),
]


def _snapshot_path(state_dir: Path, rel: str) -> Path:
    return state_dir / "copy_once_snapshots" / rel.replace("/", "_")


def classify_one(rel: str, recognizer, config_home: Path, state_dir: Path):
    """Returns (state, detail). Pure -- reads files, writes nothing."""
    live = config_home / rel
    if not live.exists():
        return MISSING, None

    snap = _snapshot_path(state_dir, rel)
    if snap.exists():
        if _sha256(live.read_bytes()) == _sha256(snap.read_bytes()):
            return DXRICE_OWNED_UNCHANGED, None
        return DXRICE_OWNED_MODIFIED, None

    try:
        text = live.read_text(errors="replace")
    except OSError:
        return UNKNOWN, "could not read the file"

    if recognizer.is_current(text):
        return LEGACY_DXRICE, "current-shaped"
    if recognizer.is_legacy(text):
        return LEGACY_DXRICE, "old-shaped"
    if recognizer.is_foreign(text):
        return FOREIGN, "looks like it belongs to a different setup"
    return UNKNOWN, "no DXrice marker found, but nothing rules it out either"


def classify_all(config_home: Path, state_dir: Path):
    """Returns [(rel, state, detail), ...] for every slot with a live file."""
    out = []
    for rel, recognizer in _SLOTS:
        state, detail = classify_one(rel, recognizer, config_home, state_dir)
        if state != MISSING:
            out.append((rel, state, detail))
    return out


def claim_snapshot(rel: str, config_home: Path, state_dir: Path, repo_dir: Path):
    """Backfills a missing snapshot for a LEGACY_DXRICE/current-shaped file.

    Seeded from the REPO'S CURRENT TEMPLATE, never from the live file --
    same convention dxrice_check_hypr_drift.py already established for
    exactly this situation ("this can't retroactively know what the repo
    looked like when your copy was first made, so it honestly starts the
    clock from today instead of fabricating false-positive drift"). Never
    reads or writes the live file at all.
    """
    src = repo_dir / rel
    if not src.is_file():
        return False
    snap = _snapshot_path(state_dir, rel)
    snap.parent.mkdir(parents=True, exist_ok=True)
    snap.write_bytes(src.read_bytes())
    return True


def _main():
    if len(sys.argv) < 2:
        print("Usage: dxrice_copy_once_ownership.py classify|claim-snapshot ...", file=sys.stderr)
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "classify":
        config_home = Path(sys.argv[2])
        state_dir = Path(sys.argv[3])
        for rel, state, detail in classify_all(config_home, state_dir):
            print(f"{rel}\t{state}\t{detail or ''}")
    elif cmd == "claim-snapshot":
        rel = sys.argv[2]
        config_home = Path(sys.argv[3])
        state_dir = Path(sys.argv[4])
        repo_dir = Path(sys.argv[5])
        ok = claim_snapshot(rel, config_home, state_dir, repo_dir)
        sys.exit(0 if ok else 1)
    else:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    _main()
