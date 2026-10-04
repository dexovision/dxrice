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

Safety model (this is a real login screen -- a broken theme here is a
locked-out desktop, not a cosmetic bug):
  - Everything is rendered into a throwaway staging directory first, never
    directly into the live /usr/share/sddm/themes/dxrice.
  - The staging copy is verified with the real greeter binary
    (sddm-greeter-qt6 --test-mode) before anything live is touched. A
    verification failure leaves the previously-installed theme and
    /etc/sddm.conf.d completely untouched -- SDDM keeps using whatever it
    was already using.
  - Only once verification passes: the current live theme dir (if any) and
    /etc/sddm.conf.d's current contents are backed up to a timestamped
    folder under the real user's own data dir, THEN the staging copy is
    swapped into place and Current=dxrice is written.
  - A wallpaper that can't be found or blurred this run never blanks out a
    background that a previous successful run already installed -- it
    carries the old one forward instead.

Usage: sudo python3 dxrice_sync_sddm_theme.py
"""
import datetime
import json
import os
import pwd
import shutil
import subprocess
import sys
import tempfile
from string import Template

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPTS_DIR)
import dxrice_apply_theme as apply_theme
import dxrice_config_migrate
import dxrice_xdg

REPO = os.path.dirname(SCRIPTS_DIR)
SDDM_SRC = os.path.join(REPO, "sddm")
SDDM_THEME_DIR = "/usr/share/sddm/themes/dxrice"
SDDM_CONF_D = "/etc/sddm.conf.d"
SDDM_DROPIN = os.path.join(SDDM_CONF_D, "dxrice.conf")


def real_user_and_home():
    """The invoking (pre-sudo) user's name and home directory -- root's own
    identity under plain sudo is not who this needs to read theme.json for,
    or who should end up owning the backup this writes into their home."""
    sudo_user = os.environ.get("SUDO_USER")
    if sudo_user:
        try:
            pw = pwd.getpwnam(sudo_user)
            return sudo_user, pw.pw_dir, pw.pw_uid, pw.pw_gid
        except KeyError:
            pass
    pw = pwd.getpwuid(os.getuid())
    return pw.pw_name, pw.pw_dir, pw.pw_uid, pw.pw_gid


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
    no NEW background image is produced this run -- the caller carries the
    previous one forward if there was one. Never a hard failure."""
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


def render_staging(staging_dir, theme, home):
    os.makedirs(staging_dir, exist_ok=True)

    # Not os.path.expanduser() -- under sudo that resolves against root's
    # home, not the real user's, silently pointing at the wrong wallpaper.
    wallpaper = theme.get("wallpaper", "")
    if wallpaper.startswith("~"):
        wallpaper = wallpaper.replace("~", home, 1)
    background_dst = os.path.join(staging_dir, "background.png")
    has_background = make_blurred_background(wallpaper, background_dst)

    if not has_background:
        previous_bg = os.path.join(SDDM_THEME_DIR, "background.png")
        if os.path.isfile(previous_bg):
            shutil.copyfile(previous_bg, background_dst)
            has_background = True
            print("  (carrying forward the background image from the previously installed theme)")

    tvars = apply_theme.build_vars(theme)
    # The PNG bytes live at background_dst (inside staging_dir) for now --
    # verification reads from there -- but the STRING baked into theme.conf
    # must be the path the file will actually have once installed, not the
    # staging path. staging_dir is a tempfile.TemporaryDirectory() that gets
    # deleted the instant the caller's `with` block exits (before the script
    # even prints "Done."), so a theme.conf shipped with that path baked in
    # points at a location that's already gone by the time any greeter --
    # test-mode or, confirmed directly from the real sddm-greeter-qt6's own
    # journal output, the live daemon -- ever reads it.
    final_background_path = os.path.join(SDDM_THEME_DIR, "background.png")
    tvars["SDDM_BACKGROUND_PATH"] = final_background_path if has_background else ""
    with open(os.path.join(SDDM_SRC, "theme.conf.template")) as f:
        rendered = Template(f.read()).safe_substitute(tvars)
    with open(os.path.join(staging_dir, "theme.conf"), "w") as f:
        f.write(rendered)

    shutil.copyfile(os.path.join(SDDM_SRC, "metadata.desktop"),
                     os.path.join(staging_dir, "metadata.desktop"))
    shutil.copyfile(os.path.join(SDDM_SRC, "Main.qml"),
                     os.path.join(staging_dir, "Main.qml"))

    # World-readable: the greeter runs as the unprivileged `sddm` system
    # user, which can't read anything more restrictive than that.
    for root, _dirs, files in os.walk(staging_dir):
        os.chmod(root, 0o755)
        for name in files:
            os.chmod(os.path.join(root, name), 0o644)


def check_qt_version_key(staging_dir) -> tuple[bool, str]:
    """A missing QtVersion=6 in metadata.desktop is exactly the bug that
    caused a real lockout once already on this machine: without it, SDDM's
    daemon launches the Qt5 `sddm-greeter` binary, which is broken here
    (missing libQt5Quick.so.5, exits 127) -- and sddm-greeter-qt6
    --test-mode can NEVER catch this, because invoking that binary by name
    on the command line bypasses SDDM's own greeter-binary-selection logic
    entirely. This static check is what actually catches that failure
    mode; the render check below only proves the QML itself is valid."""
    meta_path = os.path.join(staging_dir, "metadata.desktop")
    if not os.path.isfile(meta_path):
        return False, "metadata.desktop is missing from the staged theme"
    with open(meta_path) as f:
        content = f.read()
    if not any(line.strip().replace(" ", "") == "QtVersion=6" for line in content.splitlines()):
        return False, "metadata.desktop is missing 'QtVersion=6' -- SDDM would fall back to the Qt5 greeter binary"
    return True, ""


def check_renders(staging_dir) -> tuple[bool, str]:
    """Proves the QML actually renders, via the one method already proven
    reliable in this exact environment: Item.grabToImage() producing a real
    image file. Plain stdout/stderr capture from a killed sddm-greeter-qt6
    process is NOT reliable here -- confirmed empirically (came back
    completely empty across multiple capture strategies, including direct
    file-descriptor redirection, even though the process demonstrably ran
    and rendered) -- so this never relies on that text output to decide
    pass/fail, only on whether a real screenshot file was produced."""
    if not shutil.which("sddm-greeter-qt6") and not shutil.which("sddm-greeter"):
        return True, "(no sddm-greeter binary found to test with -- skipping the render check)"
    greeter = "sddm-greeter-qt6" if shutil.which("sddm-greeter-qt6") else "sddm-greeter"

    with tempfile.TemporaryDirectory(prefix="dxrice-sddm-verify-") as verify_dir:
        screenshot_path = os.path.join(verify_dir, "render.png")
        selftest_qml = os.path.join(verify_dir, "Main.qml")
        with open(os.path.join(staging_dir, "Main.qml")) as f:
            main_qml = f.read()
        # Inserted as a child, just before the root object's own closing
        # brace -- appending it AFTER that brace would leave two root-level
        # objects in the file, which is a QML syntax error, not a sibling.
        main_qml = main_qml.rstrip()
        assert main_qml.endswith("}"), "Main.qml did not end with the root object's closing brace"
        selftest_snippet = f"""
    Timer {{
        interval: 800
        running: true
        onTriggered: root.grabToImage(function(result) {{ result.saveToFile("{screenshot_path}"); }})
    }}
"""
        main_qml = main_qml[:-1] + selftest_snippet + "}\n"
        with open(selftest_qml, "w") as f:
            f.write(main_qml)
        # A throwaway copy of the theme with everything else the same, just
        # this one file swapped -- background/theme.conf/metadata are still
        # read from the real staging_dir's own copies via a symlinked dir.
        selftest_theme_dir = os.path.join(verify_dir, "theme")
        os.makedirs(selftest_theme_dir)
        for name in os.listdir(staging_dir):
            if name == "Main.qml":
                continue
            src = os.path.join(staging_dir, name)
            dst = os.path.join(selftest_theme_dir, name)
            (shutil.copytree if os.path.isdir(src) else shutil.copyfile)(src, dst)
        shutil.copyfile(selftest_qml, os.path.join(selftest_theme_dir, "Main.qml"))

        # Forces Qt's offscreen platform plugin -- this runs under sudo,
        # which resets the environment by default, so DISPLAY/
        # WAYLAND_DISPLAY/XDG_RUNTIME_DIR are almost certainly gone
        # regardless of what the invoking user's own session has (confirmed
        # empirically: the real-display path failed here specifically
        # because of this). grabToImage() renders to an in-memory buffer
        # either way, so it never needed a real display connection to begin
        # with -- offscreen mode makes that explicit and reliable instead
        # of accidentally depending on env vars sudo may or may not pass
        # through.
        env = dict(os.environ)
        env["QT_QPA_PLATFORM"] = "offscreen"
        proc = subprocess.Popen(
            [greeter, "--test-mode", "--theme", selftest_theme_dir],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env,
        )
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=2)

        if not os.path.isfile(screenshot_path) or os.path.getsize(screenshot_path) < 1024:
            return False, "sddm-greeter did not produce a render (grabToImage never wrote a screenshot) -- the QML likely failed to load"
        return True, ""


def verify_staging(staging_dir) -> tuple[bool, str]:
    ok, msg = check_qt_version_key(staging_dir)
    if not ok:
        return False, msg
    return check_renders(staging_dir)


def chown_tree_to_user(root_path, uid, gid):
    """Fixes ownership of root_path itself plus everything inside it --
    os.walk()'s own top-level directory is never one of the entries it
    yields, so a plain walk-and-chown loop over a path's contents always
    misses that path itself (and any parent this same run happened to
    create along the way, e.g. data_dir() not existing yet). Used any time
    this (root-running) script creates something under the real user's own
    $XDG_DATA_HOME, so nothing it leaves behind ends up root-owned inside
    the user's own home."""
    try:
        os.chown(root_path, uid, gid)
    except OSError:
        pass
    for dirpath, dirnames, filenames in os.walk(root_path):
        for name in dirnames + filenames:
            try:
                os.chown(os.path.join(dirpath, name), uid, gid)
            except OSError:
                pass


def backup_current_state(home, uid, gid):
    ts = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    backup_root = os.path.join(dxrice_xdg.data_dir(), "backups", f"sddm-{ts}")
    os.makedirs(backup_root, exist_ok=True)

    if os.path.isdir(SDDM_THEME_DIR):
        shutil.copytree(SDDM_THEME_DIR, os.path.join(backup_root, "theme_dir"))
    if os.path.isdir(SDDM_CONF_D) and os.listdir(SDDM_CONF_D):
        shutil.copytree(SDDM_CONF_D, os.path.join(backup_root, "sddm.conf.d"))
    else:
        with open(os.path.join(backup_root, "sddm.conf.d.was-empty"), "w"):
            pass

    # Give the real user ownership of the whole dxrice data tree, not just
    # this new backup -- this ran as root, but it's living inside their
    # $XDG_DATA_HOME, not root's, and an earlier step (config migration)
    # may have created data_dir() itself as root-owned before this ever ran.
    chown_tree_to_user(dxrice_xdg.data_dir(), uid, gid)

    return backup_root


def main():
    if os.geteuid() != 0:
        print("This needs root (it writes to /usr/share/sddm and /etc/sddm.conf.d).")
        print("Run it again as: sudo python3 scripts/dxrice_sync_sddm_theme.py")
        sys.exit(1)

    if not shutil.which("sddm") and not os.path.isdir("/usr/share/sddm"):
        print("SDDM doesn't appear to be installed -- nothing to sync.")
        print("This only sets up a theme for an SDDM you already have installed;")
        print("it never installs or switches your display manager for you.")
        sys.exit(0)

    user, home, uid, gid = real_user_and_home()
    live_theme_path = os.path.join(dxrice_xdg.config_dir(), "theme.json")
    if not os.path.isfile(live_theme_path):
        print(f"No live theme found at {live_theme_path}.")
        print("Open the Theme app (or run dxrice_apply_theme.py) as your normal user first.")
        sys.exit(1)

    # Same migration dxrice_apply_theme.py runs on every unprivileged Apply
    # -- almost always a no-op by the time this is invoked (Apply already
    # migrated it), but this script can be run on its own, so build_vars()
    # below still needs a complete theme dict either way. Running under
    # sudo means any directory this creates along the way (data_dir()
    # itself, if it didn't already exist) is root-owned unless fixed up --
    # chown_tree_to_user() below covers the path ITSELF, not just its
    # contents (os.walk()'s own top-level dir is never one of the entries
    # it yields, which is what left ~/.local/share/dxrice and its backups/
    # subdirectory root-owned the first time this ran).
    for note in dxrice_config_migrate.migrate_file(live_theme_path):
        print(note)
    chown_tree_to_user(dxrice_xdg.data_dir(), uid, gid)

    with open(live_theme_path) as f:
        theme = json.load(f)

    with tempfile.TemporaryDirectory(prefix="dxrice-sddm-staging-") as staging_dir:
        print("Rendering the theme into a staging copy...")
        render_staging(staging_dir, theme, home)

        print("Verifying the staged theme with the real greeter (sddm-greeter --test-mode)...")
        ok, output = verify_staging(staging_dir)
        if not ok:
            print("!! The staged theme failed to load cleanly -- NOT touching the live theme "
                  "or SDDM's configuration. Your previous login screen is unaffected.", file=sys.stderr)
            print(output, file=sys.stderr)
            sys.exit(1)
        print("  Verified.")

        print("Backing up the current SDDM theme/configuration (safety fallback)...")
        backup_root = backup_current_state(home, uid, gid)
        print(f"  Backed up to {backup_root}")

        print(f"Installing the verified theme to {SDDM_THEME_DIR} ...")
        if os.path.isdir(SDDM_THEME_DIR):
            shutil.rmtree(SDDM_THEME_DIR)
        shutil.copytree(staging_dir, SDDM_THEME_DIR)

    os.makedirs(SDDM_CONF_D, exist_ok=True)
    with open(SDDM_DROPIN, "w") as f:
        f.write("[Theme]\nCurrent=dxrice\n")
    os.chmod(SDDM_DROPIN, 0o644)

    print("Done.")
    print(f"  Theme files:  {SDDM_THEME_DIR}")
    print(f"  Config:       {SDDM_DROPIN}")
    print(f"  Backup:       {backup_root}")
    print("Log out (or reboot) to see it on the login screen.")
    print(f"To revert to SDDM's default theme: sudo rm {SDDM_DROPIN}")
    print("To preview without logging out: "
          f"sddm-greeter-qt6 --test-mode --theme {SDDM_THEME_DIR}")
    print("")
    print("This has been verified with the real greeter binary, but only from a preview")
    print("window -- test-mode cannot fully substitute for a real logout (different socket/")
    print("PAM/session handling). Log out for real to confirm before relying on this, and")
    print("know how to reach a TTY (e.g. Ctrl+Alt+F3/F4) to run the revert command above")
    print("if anything looks wrong.")


if __name__ == "__main__":
    main()
