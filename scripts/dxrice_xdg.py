#!/usr/bin/env python3
"""XDG Base Directory resolution, shared by every dxrice script.

https://specifications.freedesktop.org/basedir-spec/latest/ -- four
directories, each with an env var override and a fixed fallback:

    CONFIG  $XDG_CONFIG_HOME   ~/.config        user-editable settings
    DATA    $XDG_DATA_HOME     ~/.local/share   themes/resources, backups
    STATE   $XDG_STATE_HOME    ~/.local/state   manifest, repo_path, history
    CACHE   $XDG_CACHE_HOME    ~/.cache         disposable generated data

Every dxrice_*.py script imports this instead of hardcoding "~/.config" (or
worse, "/home/<user>") directly -- a user who sets one of these env vars
gets it honored, and a script run under sudo (dxrice_sync_sddm_theme.py)
still resolves against the invoking user's home, never root's.

The REPO itself (wherever this checkout lives) is never one of these four --
see the module docstring on dxrice_apply_theme.py for that separation.
"""
import os
import pwd


def real_home():
    """The invoking user's home directory, even under sudo.

    os.path.expanduser("~") as root resolves to /root, not the actual
    user's home -- every script that might run privileged (currently just
    dxrice_sync_sddm_theme.py) needs this instead, so it reads/writes
    ~/.config/dxrice/theme.json for the real user, not root's.
    """
    sudo_user = os.environ.get("SUDO_USER")
    if sudo_user:
        try:
            return pwd.getpwnam(sudo_user).pw_dir
        except KeyError:
            pass
    return os.path.expanduser("~")


def _base(env_var, fallback_parts):
    # sudo resets most environment variables by default (no env_keep for
    # XDG_*), so this will usually fall through to the fallback path under
    # sudo anyway -- which is correct: real_home() below is what actually
    # matters there, not a stale root-session XDG override.
    override = os.environ.get(env_var)
    if override:
        return override
    return os.path.join(real_home(), *fallback_parts)


def config_home():
    return _base("XDG_CONFIG_HOME", (".config",))


def data_home():
    return _base("XDG_DATA_HOME", (".local", "share"))


def state_home():
    return _base("XDG_STATE_HOME", (".local", "state"))


def cache_home():
    return _base("XDG_CACHE_HOME", (".cache",))


def config_dir():
    """User configuration: theme.json, config.json, saved theme presets.
    Never the repo -- see dxrice_apply_theme.py."""
    return os.path.join(config_home(), "dxrice")


def data_dir():
    """User data: saved/imported theme presets (if treated as data rather
    than config), generated wallpaper assets, migration backups."""
    return os.path.join(data_home(), "dxrice")


def state_dir():
    """Persistent-but-not-config state: the deploy manifest, repo_path,
    window/recent history."""
    return os.path.join(state_home(), "dxrice")


def cache_dir():
    """Disposable generated data: thumbnails, anything safe to delete and
    regenerate."""
    return os.path.join(cache_home(), "dxrice")
