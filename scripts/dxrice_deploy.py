#!/usr/bin/env python3
"""Deploys repo files into ~/.config, guarded by dxrice_manifest so a file
you've hand-edited since the last deploy is never clobbered.

Used by install.sh for both the first install and `install.sh update`.
hyprland.lua and waybar/config are excluded from the generic hash-guard
below and copied in only once, on a brand new install (when no live copy
exists yet), then left completely alone forever -- both are places you're
expected to make them your own (keybinds/autostart for one, taskbar app
shortcuts for the other), and a byte-hash guard doesn't fit that: dxrice_
taskbar_gui.py's own edits would otherwise look, to a hash comparison,
identical to "untouched since the last deploy" and a later structural
change to the repo's default (like a new default module) would silently
overwrite your shortcuts instead of being left for you to merge by hand --
which is exactly what already happens with hyprland.lua's keybinds if a
rice update adds new defaults (see the README). Theme colors still reach
hyprland.lua via dxrice_apply_theme.py's narrow, line-level patch, not
this script.

.py/.sh scripts are NOT copied anywhere -- they run straight out of the
repo checkout (see hyprland.lua's keybinds and dxrice_theme_gui.py), so
nothing gets scattered into $HOME besides real app config directories.

Usage: dxrice_deploy.py <repo_dir>
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dxrice_manifest

HOME = Path.home()

STATIC_FILES = [
    ("wofi/config", HOME / ".config/wofi/config"),
]

COPY_ONCE_FILES = [
    ("hypr/hyprland.lua", HOME / ".config/hypr/hyprland.lua"),
    ("waybar/config", HOME / ".config/waybar/config"),
]

LEGACY_SCRIPTS_DIR = HOME / "scripts"


def cleanup_legacy_scripts(manifest: dict, results: dict):
    """Older versions of this rice copied scripts into ~/scripts. Remove any
    leftover copy that still matches what we last put there -- same
    hand-edit guard as everything else, so a copy you actually changed is
    left alone and reported, not deleted out from under you."""
    if not LEGACY_SCRIPTS_DIR.is_dir():
        return
    for f in sorted(LEGACY_SCRIPTS_DIR.iterdir()):
        if not f.is_file() or not f.name.startswith("dxrice"):
            continue
        key = dxrice_manifest.rel_key(f)
        last_known = manifest["files"].get(key)
        if last_known is None:
            results[str(f)] = "left-alone (not something this rice put here)"
            continue
        if dxrice_manifest.file_hash(f) != last_known:
            results[str(f)] = "left-alone (you edited this legacy copy -- remove it yourself if unwanted)"
            continue
        f.unlink()
        del manifest["files"][key]
        results[str(f)] = "removed (legacy copy -- scripts now run from the repo checkout)"

    try:
        next(LEGACY_SCRIPTS_DIR.iterdir())
    except StopIteration:
        LEGACY_SCRIPTS_DIR.rmdir()
        results[str(LEGACY_SCRIPTS_DIR)] = "removed (now empty)"
    except FileNotFoundError:
        pass


def deploy_static(repo_dir: Path, manifest: dict, results: dict):
    for rel, dst in STATIC_FILES:
        src = repo_dir / rel
        if not src.is_file():
            continue
        result = dxrice_manifest.deploy_file(dst, src.read_bytes(), manifest)
        results[str(dst)] = result


_QS_MODULES = ["pulseaudio", "network", "cpu", "memory"]
_QS_OLD_DEFAULT_ON_CLICK = {"pulseaudio": "pavucontrol", "network": "nm-connection-editor"}
_QS_ON_CLICK = ('sh -c \'python3 "$(cat ~/.local/state/dxrice/repo_path 2>/dev/null '
                '|| echo ~/dxrice)/scripts/dxrice_quick_settings.py"\'')


def _migrate_waybar_quicksettings(dst: Path) -> bool:
    """A live waybar/config from before the Quick Settings panel existed
    has pulseaudio/network/cpu/memory as flat modules-right entries, never
    grouped, never wired to it -- and since this file is now copy-once
    like hyprland.lua (see module docstring), that config would otherwise
    never change on its own. Narrowly upgrades just that cluster in place:
    groups the four into group/quicksettings and points their clicks at
    the panel, leaving modules-left (your actual shortcuts) and everything
    else completely untouched. Only overwrites an on-click that's still
    the old untouched default (pavucontrol / nm-connection-editor) or
    unset -- a click action you deliberately customized since is left as
    you set it."""
    try:
        cfg = json.loads(dst.read_text())
    except (OSError, json.JSONDecodeError):
        return False
    right = cfg.get("modules-right", [])
    if "group/quicksettings" in cfg or "group/quicksettings" in right:
        return False
    if not all(m in right for m in _QS_MODULES):
        return False

    idx = right.index("pulseaudio")
    new_right = [m for m in right if m not in _QS_MODULES]
    new_right.insert(idx, "group/quicksettings")
    cfg["modules-right"] = new_right
    cfg["group/quicksettings"] = {"orientation": "horizontal", "modules": list(_QS_MODULES)}
    for m in _QS_MODULES:
        entry = cfg.setdefault(m, {})
        current = entry.get("on-click")
        if current is None or current == _QS_OLD_DEFAULT_ON_CLICK.get(m):
            entry["on-click"] = _QS_ON_CLICK
        entry.pop("on-click-right", None)

    dst.write_text(json.dumps(cfg, indent=4))
    return True


_COPY_ONCE_MIGRATIONS = {
    "config": [_migrate_waybar_quicksettings],
}


def deploy_copy_once(repo_dir: Path, manifest: dict, results: dict):
    for rel, dst in COPY_ONCE_FILES:
        src = repo_dir / rel
        if not src.is_file():
            continue
        if dst.exists():
            migrated = any(migrate(dst) for migrate in _COPY_ONCE_MIGRATIONS.get(dst.name, []))
            if migrated:
                results[str(dst)] = "migrated (Quick Settings cluster added, your shortcuts untouched)"
            else:
                results[str(dst)] = "left-alone (never auto-overwritten)"
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(src.read_bytes())
        dxrice_manifest.mark_deployed(dst, manifest)
        results[str(dst)] = "installed"


def print_summary(results: dict):
    by_result = {}
    for path, result in results.items():
        by_result.setdefault(result, []).append(path)

    order = ["installed", "adopted", "updated", "migrated (Quick Settings cluster added, your shortcuts untouched)",
             "left-alone (never auto-overwritten)",
             "unchanged", "skipped-modified", "removed (legacy copy -- scripts now run from the repo checkout)",
             "removed (now empty)", "left-alone (you edited this legacy copy -- remove it yourself if unwanted)",
             "left-alone (not something this rice put here)"]
    labels = {
        "installed": "Newly installed",
        "adopted": "Took over pre-existing file (old version backed up)",
        "updated": "Updated to latest",
        "migrated (Quick Settings cluster added, your shortcuts untouched)": "Upgraded in place (Quick Settings cluster added, your shortcuts untouched)",
        "left-alone (never auto-overwritten)": "Left alone (yours to edit)",
        "unchanged": "Already up to date",
        "skipped-modified": "SKIPPED -- you edited this since the last deploy",
        "removed (legacy copy -- scripts now run from the repo checkout)": "Cleaned up (old ~/scripts copy, no longer needed)",
        "removed (now empty)": "Cleaned up",
        "left-alone (you edited this legacy copy -- remove it yourself if unwanted)": "Left alone (you edited this old ~/scripts copy)",
        "left-alone (not something this rice put here)": "Left alone (unrecognized file in ~/scripts)",
    }
    for key in order:
        paths = by_result.get(key)
        if not paths:
            continue
        print(f"\n{labels[key]}:")
        for p in paths:
            print(f"  - {p}")

    if by_result.get("skipped-modified"):
        print("\nTo take the new version of a skipped file anyway, delete it and re-run,")
        print("or diff it against the repo copy and merge by hand.")


def main():
    if len(sys.argv) < 2:
        print("Usage: dxrice_deploy.py <repo_dir>", file=sys.stderr)
        sys.exit(1)
    repo_dir = Path(sys.argv[1]).expanduser().resolve()

    manifest = dxrice_manifest.load_manifest()
    results = {}

    deploy_copy_once(repo_dir, manifest, results)
    deploy_static(repo_dir, manifest, results)
    cleanup_legacy_scripts(manifest, results)

    dxrice_manifest.save_manifest(manifest)
    print_summary(results)


if __name__ == "__main__":
    main()
