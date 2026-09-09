#!/usr/bin/env python3
"""Deploys the DXrice SDDM login theme so it matches your current theme.json.

Separate from dxrice_apply_theme.py on purpose: this writes to
/usr/share/sddm/themes/ and /etc/sddm.conf.d/, both outside any normal
user's write access, so it needs root -- and unlike the Theme GUI's Apply
(which must stay unprivileged, since it runs on every slider drag), this is
something you run occasionally by hand (or once via install.sh), whenever
you want the login screen to pick up a new wallpaper/color scheme.

The wallpaper is blurred once, here, into a static image (via ffmpeg, or
ImageMagick if that's what's installed) -- not blurred live by the greeter
-- so the greeter theme itself has zero GPU shader dependency.

Usage: sudo python3 dxrice_sync_sddm_theme.py
"""
import json
import os
import pwd
import shutil
import subprocess
import sys
from string import Template

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPTS_DIR)
import dxrice_apply_theme as apply_theme

REPO = os.path.dirname(SCRIPTS_DIR)
SDDM_SRC = os.path.join(REPO, "sddm")
SDDM_THEME_DIR = "/usr/share/sddm/themes/dxrice"
SDDM_CONF_D = "/etc/sddm.conf.d"
SDDM_DROPIN = os.path.join(SDDM_CONF_D, "dxrice.conf")


def real_user_home():
    """Resolves the invoking (pre-sudo) user's home directory -- os.path.
    expanduser("~") as root would resolve to /root, not the actual user's
    ~/.config/dxrice/theme.json this needs to read."""
    sudo_user = os.environ.get("SUDO_USER")
    if sudo_user:
        try:
            return pwd.getpwnam(sudo_user).pw_dir
        except KeyError:
            pass
    return os.path.expanduser("~")


def find_blur_tool():
    if shutil.which("ffmpeg"):
        return "ffmpeg"
    if shutil.which("magick"):
        return "magick"
    if shutil.which("convert"):
        return "convert"
    return None


def make_blurred_background(wallpaper_path, dst_path):
    """Best-effort: a missing blur tool or unreadable wallpaper just means
    no background image ships (the greeter falls back to a solid color
    from theme.conf's BackgroundColor) -- never a hard failure."""
    if not wallpaper_path or not os.path.isfile(wallpaper_path):
        print(f"  (no wallpaper found at {wallpaper_path!r} -- skipping background image)")
        return False

    tool = find_blur_tool()
    if not tool:
        print("  (no ffmpeg/ImageMagick found -- skipping blurred background image; "
              "install one of them and re-run to get one)")
        return False

    try:
        if tool == "ffmpeg":
            subprocess.run(
                ["ffmpeg", "-y", "-i", wallpaper_path, "-vf", "scale=1920:-1,gblur=sigma=30",
                 "-frames:v", "1", "-update", "1", dst_path],
                capture_output=True, timeout=30, check=True,
            )
        else:
            subprocess.run(
                [tool, wallpaper_path, "-resize", "1920x", "-blur", "0x16", dst_path],
                capture_output=True, timeout=30, check=True,
            )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        print(f"  (blur step failed: {e} -- skipping background image)")
        return False
    return True


def main():
    if os.geteuid() != 0:
        print("This needs root (it writes to /usr/share/sddm and /etc/sddm.conf.d).")
        print("Run it again as: sudo python3 scripts/dxrice_sync_sddm_theme.py")
        sys.exit(1)

    if not shutil.which("sddm") and not os.path.isdir("/usr/share/sddm"):
        print("SDDM doesn't appear to be installed -- nothing to sync.")
        print("This only sets up a theme for an SDDM you already have installed;")
        print("it never installs or switches your display manager for you.")
        sys.exit(1)

    home = real_user_home()
    live_theme_path = os.path.join(home, ".config", "dxrice", "theme.json")
    if not os.path.isfile(live_theme_path):
        print(f"No live theme found at {live_theme_path}.")
        print("Open the Theme app (or run dxrice_apply_theme.py) as your normal user first.")
        sys.exit(1)

    with open(live_theme_path) as f:
        theme = json.load(f)

    print(f"Deploying DXrice SDDM theme to {SDDM_THEME_DIR} ...")
    os.makedirs(SDDM_THEME_DIR, exist_ok=True)

    # Not os.path.expanduser() -- under sudo that resolves against root's
    # home, not the real user's, silently pointing at the wrong wallpaper.
    wallpaper = theme.get("wallpaper", "")
    if wallpaper.startswith("~"):
        wallpaper = wallpaper.replace("~", home, 1)
    background_dst = os.path.join(SDDM_THEME_DIR, "background.png")
    has_background = make_blurred_background(wallpaper, background_dst)

    tvars = apply_theme.build_vars(theme)
    tvars["SDDM_BACKGROUND_PATH"] = background_dst if has_background else ""
    with open(os.path.join(SDDM_SRC, "theme.conf.template")) as f:
        rendered = Template(f.read()).safe_substitute(tvars)
    with open(os.path.join(SDDM_THEME_DIR, "theme.conf"), "w") as f:
        f.write(rendered)

    shutil.copyfile(os.path.join(SDDM_SRC, "metadata.desktop"),
                     os.path.join(SDDM_THEME_DIR, "metadata.desktop"))
    shutil.copyfile(os.path.join(SDDM_SRC, "Main.qml"),
                     os.path.join(SDDM_THEME_DIR, "Main.qml"))

    # World-readable: the greeter runs as the unprivileged `sddm` system
    # user, which can't read anything more restrictive than that.
    for root, _dirs, files in os.walk(SDDM_THEME_DIR):
        os.chmod(root, 0o755)
        for name in files:
            os.chmod(os.path.join(root, name), 0o644)

    os.makedirs(SDDM_CONF_D, exist_ok=True)
    with open(SDDM_DROPIN, "w") as f:
        f.write("[Theme]\nCurrent=dxrice\n")
    os.chmod(SDDM_DROPIN, 0o644)

    print("Done.")
    print(f"  Theme files:  {SDDM_THEME_DIR}")
    print(f"  Config:       {SDDM_DROPIN}")
    print("Log out (or reboot) to see it on the login screen.")
    print(f"To revert to SDDM's default theme: sudo rm {SDDM_DROPIN}")
    print("To preview without logging out: "
          f"sddm-greeter-qt6 --test-mode --theme {SDDM_THEME_DIR}")


if __name__ == "__main__":
    main()
