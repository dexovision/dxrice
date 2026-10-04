#!/usr/bin/env python3
"""Surfaces the exact failure mode that cost a whole debugging session on
this rice: hypr/hyprland.lua (and waybar/config*) are deployed ONCE, then
left completely alone forever so they stay yours to hand-edit (see
dxrice_deploy.py's own docstring) -- but that also means when a later
`git pull` adds a new default keybind or a new required autostart line to
the REPO's copy, your already-deployed copy has no way to ever pick it up,
and nothing ever told you it existed. That's exactly what happened to
dxrice_auto_place_window.py's autostart line: added to the repo, silently
absent from the live config, for hours, with zero indication anything was
wrong short of noticing the feature just never ran.

This never auto-merges anything into your hand-edited file -- that would
be exactly the "silently overwrite your customization" failure the
copy-once design exists to prevent. It only ever tells you, in plain
terms, what the repo's template has gained since your copy was seeded that
your live file doesn't seem to reference anywhere, so you can decide for
yourself whether to add it by hand.

Heuristic, not a full Lua parse: identifies two kinds of line the repo
template's hyprland.start block and top-level bind table actually contain
today --
  - hl.exec_cmd("...scripts/dxrice_X.py...")  (an autostart entry)
  - hl.bind(mods .. " + KEY", ...)            (a keybind)
-- by their referenced script basename / key combo, and reports any such
identity that's new in the repo template since the snapshot taken at your
original install but doesn't appear ANYWHERE (verbatim substring) in your
live file. A script referenced with different formatting, or wired up a
different way entirely, can produce a false positive here -- this is a
"go take a look" signal, never an authority overriding your own read of
the diff.

Run: python3 scripts/dxrice_check_hypr_drift.py [--fix-baseline]
Exit code: 0 = no drift found (or nothing to compare against yet),
           1 = drift found -- printed to stdout for a human to review.
"""
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dxrice_manifest
import dxrice_xdg

REPO = Path(os.path.dirname(os.path.abspath(__file__))).parent
CONFIG_HOME = Path(dxrice_xdg.config_home())
STATE_DIR = Path(dxrice_xdg.state_dir())
SNAPSHOT_DIR = STATE_DIR / "copy_once_snapshots"

# (repo-relative path, live deployed path, snapshot filename)
TRACKED = [
    ("hypr/hyprland.lua", CONFIG_HOME / "hypr/hyprland.lua", "hypr_hyprland.lua"),
]

_EXEC_RE = re.compile(r'hl\.exec_cmd\([^)]*?scripts/([\w.\-]+\.py)')
_BIND_RE = re.compile(r'hl\.bind\(\s*\w+\s*\.\.\s*"([^"]+)"')


def _identities(text: str):
    """Returns {"autostart:dxrice_foo.py", "bind: + G", ...} -- a stable,
    order-independent identity for each autostart entry and keybind found."""
    ids = set()
    for m in _EXEC_RE.finditer(text):
        ids.add(f"autostart:{m.group(1)}")
    for m in _BIND_RE.finditer(text):
        ids.add(f"bind:{m.group(1)}")
    return ids


def check_one(repo_rel, live_path, snapshot_name, fix_baseline=False):
    repo_path = REPO / repo_rel
    snapshot_path = SNAPSHOT_DIR / snapshot_name

    if not repo_path.is_file():
        return None  # nothing to compare -- not this rice's file
    if not live_path.exists():
        return None  # never deployed yet -- a fresh install will just copy the current template

    current_repo_text = repo_path.read_text(errors="replace")

    if not snapshot_path.exists():
        # Either a pre-existing install from before this checker existed,
        # or dxrice_deploy.py's own snapshot step hasn't run yet. Seed a
        # baseline NOW rather than guessing -- this can't retroactively
        # know what the repo looked like when your copy was first made, so
        # it honestly starts the clock from today instead of fabricating
        # false-positive drift against content you may have always had.
        SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
        dxrice_manifest.atomic_write_bytes(snapshot_path, current_repo_text.encode())
        return {
            "path": str(live_path),
            "status": "baseline-established",
            "detail": f"No prior snapshot existed for {repo_rel} -- established one now from the "
                      f"current repo template. Drift will be detectable starting from your next update.",
        }

    snapshot_text = snapshot_path.read_text(errors="replace")
    live_text = live_path.read_text(errors="replace")

    old_ids = _identities(snapshot_text)
    new_ids = _identities(current_repo_text)
    added = new_ids - old_ids

    missing = []
    for identity in sorted(added):
        kind, _, name = identity.partition(":")
        needle = name if kind == "autostart" else f'"{name}"'
        if needle not in live_text:
            missing.append(identity)

    if fix_baseline:
        dxrice_manifest.atomic_write_bytes(snapshot_path, current_repo_text.encode())

    if not missing:
        return {"path": str(live_path), "status": "clean", "detail": None}

    return {"path": str(live_path), "status": "drift", "detail": missing}


def main():
    fix_baseline = "--fix-baseline" in sys.argv
    any_drift = False
    for repo_rel, live_path, snapshot_name in TRACKED:
        result = check_one(repo_rel, live_path, snapshot_name, fix_baseline)
        if result is None:
            continue
        if result["status"] == "baseline-established":
            print(f"[baseline] {result['path']}: {result['detail']}")
        elif result["status"] == "clean":
            print(f"[ok] {result['path']}: matches everything the repo template currently ships.")
        elif result["status"] == "drift":
            any_drift = True
            print(f"[DRIFT] {result['path']} is missing content the repo's template has gained since "
                  f"it was first deployed:")
            for identity in result["detail"]:
                kind, _, name = identity.partition(":")
                if kind == "autostart":
                    print(f"    - autostart entry for scripts/{name} (not found anywhere in your live file)")
                else:
                    print(f"    - keybind \"{name}\" (not found anywhere in your live file)")
            print(f"  This file is copy-once and yours to hand-edit (see the README), so nothing here "
                  f"was changed automatically -- open {result['path']} and the repo's own "
                  f"{TRACKED[0][0]} side by side and add whatever of the above you actually want.")
            print(f"  Once you've reviewed it, re-run with --fix-baseline to silence this check "
                  f"until the repo template changes again.")
    if any_drift:
        sys.exit(1)


if __name__ == "__main__":
    main()
