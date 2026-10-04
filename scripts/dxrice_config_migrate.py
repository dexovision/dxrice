#!/usr/bin/env python3
"""Schema versioning and safe migration for the live theme.json.

The live file at $XDG_CONFIG_HOME/dxrice/theme.json is the user's sacred,
hand-tuned configuration -- an update to this repo must never overwrite it
wholesale (see dxrice_apply_theme.py's ensure_live_theme(), which only ever
seeds it once, on a machine that has none yet). But the repo's own shipped
default (<repo>/theme/theme.json) does sometimes gain new keys as features
are added -- this module is how an EXISTING live file safely picks up those
new keys without losing anything the user already set.

The rule for every migration step, always: ADD what's missing, using the
shipped default's value. NEVER overwrite, rename away, or delete a key the
user already has a value for, even if that value looks stale -- if a
migration genuinely can't tell what the user intended for a renamed/
restructured key, it leaves the old key in place untouched and reports it
(see migrate()'s return value) rather than guessing.

schema_version history:
  (missing)  Pre-versioning. Any live file with no "schema_version" key at
             all is treated as version 0.
  1          First versioned schema. Backfills any key present in the
             current shipped default but missing from the live file
             (concretely, this is how an existing install picks up
             "shadow_intensity", added to theme/theme.json after some
             already-live installs had gone through the Theme editor
             without it) -- a plain, generic "add what's missing" step,
             not a value transformation, since nothing has been renamed or
             restructured yet.

Future migrations that DO rename/restructure a key get their own numbered
step function below, each one runs in sequence via CURRENT_SCHEMA_VERSION,
and each is independently safe to run against a file already at that
version (a no-op) so re-running migrate() is always idempotent.
"""
import datetime
import json
import os
import shutil
import sys

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPTS_DIR)
import dxrice_xdg

REPO = os.path.dirname(SCRIPTS_DIR)
DEFAULT_THEME_JSON = os.path.join(REPO, "theme", "theme.json")

CURRENT_SCHEMA_VERSION = 1

# Keep this many timestamped backups under data_dir()/backups/ before
# pruning the oldest -- a migration backup is a safety net for the
# migration that just ran, not a permanent version history.
MAX_BACKUPS = 10


def _load_default():
    with open(DEFAULT_THEME_JSON) as f:
        return json.load(f)


def _migrate_to_1(theme: dict, notes: list) -> dict:
    default = _load_default()
    for key, value in default.items():
        if key == "schema_version":
            continue
        if key not in theme:
            theme[key] = value
            notes.append(f"added new setting '{key}' (default: {value!r}) -- your existing settings were not changed")
    theme["schema_version"] = 1
    return theme


# Ordered (from_version -> step function). A live file's version determines
# where in this list it enters; every later step still runs on top of it.
_STEPS = [
    (0, _migrate_to_1),
]


def needs_migration(theme: dict) -> bool:
    return theme.get("schema_version", 0) < CURRENT_SCHEMA_VERSION


def backup_dir_for_run():
    ts = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    return os.path.join(dxrice_xdg.data_dir(), "backups", ts)


def _prune_old_backups():
    root = os.path.join(dxrice_xdg.data_dir(), "backups")
    if not os.path.isdir(root):
        return
    entries = sorted(
        (e for e in os.listdir(root) if os.path.isdir(os.path.join(root, e))),
    )
    excess = len(entries) - MAX_BACKUPS
    for name in entries[:max(0, excess)]:
        shutil.rmtree(os.path.join(root, name), ignore_errors=True)


def backup_live_config(live_theme_path: str) -> str:
    """Timestamped copy of the live theme.json before a migration touches
    it. Only called from migrate_file() when a migration is actually about
    to run -- never on a plain, no-op load (see that function)."""
    dst_dir = backup_dir_for_run()
    os.makedirs(dst_dir, exist_ok=True)
    if os.path.isfile(live_theme_path):
        shutil.copy2(live_theme_path, os.path.join(dst_dir, os.path.basename(live_theme_path)))
    _prune_old_backups()
    return dst_dir


def migrate(theme: dict) -> tuple[dict, list, bool]:
    """Runs every step from the file's current version up to
    CURRENT_SCHEMA_VERSION. Returns (migrated_theme, human-readable notes,
    changed). Pure function -- does not touch disk or create a backup;
    see migrate_file() for the version that does, guarded correctly."""
    notes = []
    version = theme.get("schema_version", 0)
    if version >= CURRENT_SCHEMA_VERSION:
        return theme, notes, False

    for from_version, step in _STEPS:
        if version <= from_version:
            theme = step(theme, notes)
    return theme, notes, True


def migrate_file(live_theme_path: str) -> list:
    """Loads, migrates if needed, and writes back the live theme.json --
    backing it up first, but ONLY when a migration is actually going to
    change something. A file already at CURRENT_SCHEMA_VERSION is read and
    left alone: this must be cheap and side-effect-free to call on every
    normal Apply/startup, not just for an explicit update -- 'do not create
    backups on every normal shell restart' means this exact function has
    to be a no-op in the common case, not just backed off to a separate
    'migrate-only' code path.

    Returns a list of human-readable notes describing what was added (empty
    if nothing needed to change).
    """
    if not os.path.isfile(live_theme_path):
        return []
    try:
        with open(live_theme_path) as f:
            theme = json.load(f)
    except (OSError, json.JSONDecodeError):
        # Corrupt live config is dxrice_apply_theme.py's problem to report,
        # not this module's to guess at -- leave it untouched.
        return []

    if not needs_migration(theme):
        return []

    backup_dir = backup_live_config(live_theme_path)
    migrated, notes, changed = migrate(theme)
    if not changed:
        return []

    with open(live_theme_path, "w") as f:
        json.dump(migrated, f, indent=4)
        f.write("\n")

    notes.insert(0, f"Backed up your previous configuration to {backup_dir} before migrating.")
    return notes


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(dxrice_xdg.config_dir(), "theme.json")
    for note in migrate_file(path):
        print(note)
