#!/usr/bin/env python3
"""Deploys repo files into ~/.config and ~/scripts, guarded by dxrice_manifest
so a file you've hand-edited since the last deploy is never clobbered.

Used by install.sh for both the first install and `install.sh update`.
hyprland.lua is intentionally excluded from the generic guard below: it's
the most hand-edited file in the rice (keybinds, autostart, monitor setup),
so it is only ever copied in on a brand new install (when no live copy
exists yet) and otherwise left completely alone. Theme colors still reach
it via dxrice_apply_theme.py's narrow, line-level patch -- not this script.

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


def deploy_scripts(repo_dir: Path, manifest: dict, results: dict):
    src_dir = repo_dir / "scripts"
    dst_dir = HOME / "scripts"
    dst_dir.mkdir(parents=True, exist_ok=True)
    if not src_dir.is_dir():
        return
    for src in sorted(src_dir.iterdir()):
        if src.suffix not in (".py", ".sh"):
            continue
        dst = dst_dir / src.name
        result = dxrice_manifest.deploy_file(dst, src.read_bytes(), manifest)
        results[str(dst)] = result
        if result != "skipped-modified":
            dst.chmod(0o755)


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
             "unchanged", "skipped-modified"]
    labels = {
        "installed": "Newly installed",
        "adopted": "Took over pre-existing file (old version backed up)",
        "updated": "Updated to latest",
        "left-alone (never auto-overwritten)": "Left alone (yours to edit)",
        "unchanged": "Already up to date",
        "skipped-modified": "SKIPPED -- you edited this since the last deploy",
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
    deploy_scripts(repo_dir, manifest, results)

    dxrice_manifest.save_manifest(manifest)
    print_summary(results)


if __name__ == "__main__":
    main()
