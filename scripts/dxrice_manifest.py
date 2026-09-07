#!/usr/bin/env python3
"""Shared deploy-guard used by install.sh (via dxrice_deploy.py) and dxrice_apply_theme.py.

Tracks a sha256 of every file this rice has deployed into ~/.config (and
~/scripts) in a small manifest. On a later deploy/update we only ever
overwrite a live file if its current content still matches the hash we
last wrote there -- if the user hand-edited it since, we skip it and say
so instead of clobbering their change.
"""
import hashlib
import json
import os
from pathlib import Path

HOME = Path.home()
STATE_DIR = HOME / ".local" / "state" / "dxrice"
MANIFEST_PATH = STATE_DIR / "manifest.json"
BACKUP_DIR = STATE_DIR / "backups"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_hash(path: Path):
    path = Path(path)
    if not path.exists():
        return None
    return _sha256(path.read_bytes())


def rel_key(path: Path) -> str:
    path = Path(path).expanduser().resolve()
    try:
        return str(path.relative_to(HOME))
    except ValueError:
        return str(path)


def load_manifest() -> dict:
    if MANIFEST_PATH.exists():
        try:
            return json.loads(MANIFEST_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {"version": 1, "files": {}}


def save_manifest(manifest: dict):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2))


def deploy_file(live_path, new_content: bytes, manifest: dict) -> str:
    """Write new_content to live_path, guarded by the manifest.

    Returns one of: 'installed', 'updated', 'unchanged',
    'adopted' (pre-existing file backed up then taken over),
    'skipped-modified' (left untouched -- user changed it since last deploy).
    """
    live_path = Path(live_path).expanduser()
    key = rel_key(live_path)
    new_hash = _sha256(new_content)

    if not live_path.exists():
        live_path.parent.mkdir(parents=True, exist_ok=True)
        live_path.write_bytes(new_content)
        manifest["files"][key] = new_hash
        return "installed"

    current_hash = file_hash(live_path)
    last_known = manifest["files"].get(key)

    if current_hash == new_hash:
        manifest["files"][key] = new_hash
        return "unchanged"

    if last_known is None:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        backup_path = BACKUP_DIR / (key.replace("/", "_") + ".bak")
        backup_path.write_bytes(live_path.read_bytes())
        live_path.write_bytes(new_content)
        manifest["files"][key] = new_hash
        return "adopted"

    if current_hash != last_known:
        return "skipped-modified"

    live_path.write_bytes(new_content)
    manifest["files"][key] = new_hash
    return "updated"


def mark_deployed(live_path, manifest: dict):
    """Record a file as deployed without necessarily rewriting it (used
    right after a plain first-time copy performed outside deploy_file)."""
    live_path = Path(live_path).expanduser()
    h = file_hash(live_path)
    if h is not None:
        manifest["files"][rel_key(live_path)] = h
