#!/usr/bin/env python3
"""Shared deploy-guard used by install.sh (via dxrice_deploy.py) and dxrice_apply_theme.py.

Tracks a sha256 of every file this rice has deployed into ~/.config in a
small manifest. On a later deploy/update we only ever overwrite a live file
if its current content still matches the hash we last wrote there -- if the
user hand-edited it since, we skip it and say so instead of clobbering their
change. Older versions of this rice also deployed .py/.sh scripts into
~/scripts; the manifest's records of those are now only used to clean up
those legacy copies (see dxrice_deploy.cleanup_legacy_scripts), since
scripts now run straight out of the git checkout instead.

deploy_file used to have a fifth outcome, "adopted": a file with no
manifest record (i.e. one this exact mechanism has no memory of ever
deploying) that differs from the current template got silently backed up
and overwritten, no confirmation, every time. That is the identical
invariant violation that motivated dxrice_copy_once_ownership.py's whole
ownership model, just reachable through a second, independent mechanism --
and a more dangerous one in practice, since every TARGETS entry in
dxrice_apply_theme.py (waybar/style.css, wofi/style.css, mako/config,
kitty/kitty.conf, hyprlock.conf, gtk_style.css) and dxrice_deploy.py's
STATIC_FILES (wofi/config) are exactly the kind of file most Linux users
already have hand-customized from some entirely unrelated, pre-dxrice
setup. "No record of deploying this" is proof of nothing -- it is
identical to the config-dock incident's root cause, applied here with no
confirmation prompt at all. A file in this state is now left completely
alone (reported as "unrecognized") instead of ever being adopted.
"""
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dxrice_xdg


def atomic_write_bytes(path, data: bytes):
    """Writes data to path via a temp file + atomic rename, so a process
    killed mid-write (crash, OOM, power loss) leaves the ORIGINAL file
    exactly as it was rather than truncated or half-written -- never a
    corrupted mix of old and new content. Used anywhere this rice writes
    to a path that may already hold real content (a tracked template
    update, an in-place structural migration of a user's live, customized
    config) rather than a brand-new file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise

HOME = Path(dxrice_xdg.real_home())
STATE_DIR = Path(dxrice_xdg.state_dir())
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
    'unrecognized' (pre-existing file, no manifest record, differs from the
    template -- ownership unproven, left completely untouched; see the
    module docstring for why this is never auto-adopted),
    'skipped-modified' (left untouched -- user changed it since last deploy).
    """
    live_path = Path(live_path).expanduser()
    key = rel_key(live_path)
    new_hash = _sha256(new_content)

    if not live_path.exists():
        atomic_write_bytes(live_path, new_content)
        manifest["files"][key] = new_hash
        return "installed"

    current_hash = file_hash(live_path)
    last_known = manifest["files"].get(key)

    if current_hash == new_hash:
        manifest["files"][key] = new_hash
        return "unchanged"

    if last_known is None:
        # No manifest record is not evidence this is ours -- it is
        # evidence of nothing. The hard invariant: if ownership cannot be
        # proven, the file is preserved. Never written, never backed up
        # (there is nothing safe to do with it, so nothing is done).
        return "unrecognized"

    if current_hash != last_known:
        return "skipped-modified"

    atomic_write_bytes(live_path, new_content)
    manifest["files"][key] = new_hash
    return "updated"


def mark_deployed(live_path, manifest: dict):
    """Record a file as deployed without necessarily rewriting it (used
    right after a plain first-time copy performed outside deploy_file)."""
    live_path = Path(live_path).expanduser()
    h = file_hash(live_path)
    if h is not None:
        manifest["files"][rel_key(live_path)] = h
