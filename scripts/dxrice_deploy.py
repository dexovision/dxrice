#!/usr/bin/env python3
"""Deploys repo files into ~/.config, guarded by dxrice_manifest so a file
you've hand-edited since the last deploy is never clobbered.

Used by install.sh for both the first install and `install.sh update`.
hyprland.lua is intentionally excluded from the generic guard below: it's
the most hand-edited file in the rice (keybinds, autostart, monitor setup),
so it is only ever copied in on a brand new install (when no live copy
exists yet) and otherwise left completely alone. Theme colors still reach
it via dxrice_apply_theme.py's narrow, line-level patch -- not this script.

.py/.sh scripts are NOT copied anywhere -- they run straight out of the
repo checkout (see hyprland.lua's keybinds and dxrice_theme_gui.py), so
nothing gets scattered into $HOME besides real app config directories.

Usage: dxrice_deploy.py <repo_dir>
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dxrice_manifest

HOME = Path.home()

STATIC_FILES = [
    ("waybar/config", HOME / ".config/waybar/config"),
    ("wofi/config", HOME / ".config/wofi/config"),
]

HYPRLAND_LUA = ("hypr/hyprland.lua", HOME / ".config/hypr/hyprland.lua")

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


def deploy_hyprland_lua(repo_dir: Path, manifest: dict, results: dict):
    rel, dst = HYPRLAND_LUA
    src = repo_dir / rel
    if not src.is_file():
        return
    if dst.exists():
        results[str(dst)] = "left-alone (never auto-overwritten)"
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(src.read_bytes())
    dxrice_manifest.mark_deployed(dst, manifest)
    results[str(dst)] = "installed"


def print_summary(results: dict):
    by_result = {}
    for path, result in results.items():
        by_result.setdefault(result, []).append(path)

    order = ["installed", "adopted", "updated", "left-alone (never auto-overwritten)",
             "unchanged", "skipped-modified", "removed (legacy copy -- scripts now run from the repo checkout)",
             "removed (now empty)", "left-alone (you edited this legacy copy -- remove it yourself if unwanted)",
             "left-alone (not something this rice put here)"]
    labels = {
        "installed": "Newly installed",
        "adopted": "Took over pre-existing file (old version backed up)",
        "updated": "Updated to latest",
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

    deploy_hyprland_lua(repo_dir, manifest, results)
    deploy_static(repo_dir, manifest, results)
    cleanup_legacy_scripts(manifest, results)

    dxrice_manifest.save_manifest(manifest)
    print_summary(results)


if __name__ == "__main__":
    main()
