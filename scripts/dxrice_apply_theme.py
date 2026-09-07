#!/usr/bin/env python3
"""Renders theme.json into every app's real config and hot-reloads them.

Single source of truth: <repo>/theme/theme.json
Templates:              <repo>/theme/*.template  (string.Template ${TOKENS})
<repo> is this script's own parent-of-parent directory -- it runs straight
out of the git checkout (never copied elsewhere), so it always finds its
own theme/ folder no matter where that checkout lives.
Usage: dxrice_apply_theme.py [path/to/theme.json]
"""
import json
import os
import re
import subprocess
import sys
from string import Template

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPTS_DIR)
import dxrice_manifest

HOME = os.path.expanduser("~")
REPO = os.path.dirname(SCRIPTS_DIR)
THEME_DIR = os.path.join(REPO, "theme")
THEME_JSON = os.path.join(THEME_DIR, "theme.json")

TARGETS = {
    "waybar_style.css.template": os.path.join(HOME, ".config/waybar/style.css"),
    "wofi_style.css.template": os.path.join(HOME, ".config/wofi/style.css"),
    "mako_config.template": os.path.join(HOME, ".config/mako/config"),
    "kitty.conf.template": os.path.join(HOME, ".config/kitty/kitty.conf"),
    "hyprlock.conf.template": os.path.join(HOME, ".config/hypr/hyprlock.conf"),
}


def hex_to_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def opacity_to_hex(o):
    return format(round(max(0.0, min(1.0, o)) * 255), "02x")


def build_vars(theme):
    bg_r, bg_g, bg_b = hex_to_rgb(theme["glass_bg"])
    active_r, active_g, active_b = hex_to_rgb(theme["glass_bg_active"])
    border_r, border_g, border_b = hex_to_rgb(theme["glass_border"])
    accent_r, accent_g, accent_b = hex_to_rgb(theme["accent"])
    text_r, text_g, text_b = hex_to_rgb(theme["glass_text"])
    text_active_r, text_active_g, text_active_b = hex_to_rgb(theme["glass_text_active"])

    return {
        "FONT_FAMILY": theme["font_family"],
        "FONT_SIZE_WAYBAR": theme["font_size_waybar"],
        "FONT_SIZE_WAYBAR_ICONS": theme["font_size_waybar_icons"],
        "FONT_SIZE_WOFI": theme["font_size_wofi"],
        "FONT_SIZE_MAKO": theme["font_size_mako"],

        "BG_R": bg_r, "BG_G": bg_g, "BG_B": bg_b, "BG_HEX": theme["glass_bg"],
        "ACTIVE_R": active_r, "ACTIVE_G": active_g, "ACTIVE_B": active_b,
        "ACTIVE_HEX": theme["glass_bg_active"],
        "BORDER_R": border_r, "BORDER_G": border_g, "BORDER_B": border_b,
        "BORDER_HEX": theme["glass_border"],
        "ACCENT_R": accent_r, "ACCENT_G": accent_g, "ACCENT_B": accent_b,
        "ACCENT_HEX": theme["accent"],
        "TEXT_R": text_r, "TEXT_G": text_g, "TEXT_B": text_b,
        "TEXT_COLOR": "#" + theme["glass_text"], "TEXT_HEX": theme["glass_text"],
        "TEXT_ACTIVE_R": text_active_r, "TEXT_ACTIVE_G": text_active_g,
        "TEXT_ACTIVE_B": text_active_b,
        "TEXT_ACTIVE_COLOR": "#" + theme["glass_text_active"],
        "TEXT_ACTIVE_HEX": theme["glass_text_active"],

        "OPACITY_IDLE": theme["opacity_idle"],
        "OPACITY_ACTIVE": theme["opacity_active"],
        "BORDER_OPACITY_IDLE": theme["border_opacity_idle"],
        "BORDER_OPACITY_ACTIVE": theme["border_opacity_active"],
        "BG_ALPHA_HEX": opacity_to_hex(theme["opacity_active"]),
        "BORDER_ALPHA_HEX": opacity_to_hex(theme["border_opacity_active"]),

        "RADIUS": theme["radius"],
        "ENTRY_RADIUS": max(0, theme["radius"] - 2),

        "KITTY_OPACITY": theme["kitty_opacity"],

        "HYPR_BLUR_SIZE": theme["hypr_blur_size"],
        "HYPR_BLUR_PASSES": theme["hypr_blur_passes"],
        "HYPR_BLUR_VIBRANCY": theme["hypr_blur_vibrancy"],

        "LOCK_BLUR_PASSES": theme["lock_blur_passes"],
        "LOCK_BLUR_SIZE": theme["lock_blur_size"],
        "LOCK_BLUR_VIBRANCY": theme["lock_blur_vibrancy"],
        "LOCK_BG_OPACITY": theme["lock_bg_opacity"],
    }


def render_templates(theme):
    tvars = build_vars(theme)
    manifest = dxrice_manifest.load_manifest()
    results = {}
    for template_name, target_path in TARGETS.items():
        src = os.path.join(THEME_DIR, template_name)
        with open(src) as f:
            rendered = Template(f.read()).safe_substitute(tvars)
        result = dxrice_manifest.deploy_file(target_path, rendered.encode(), manifest)
        results[target_path] = result
    dxrice_manifest.save_manifest(manifest)

    skipped = [p for p, r in results.items() if r == "skipped-modified"]
    if skipped:
        print("Skipped (hand-edited since last Apply, left untouched):")
        for p in skipped:
            print(f"  - {p}")
    return results


def _sub(content, pattern, replacement_fn, flags=0):
    return re.sub(pattern, lambda m: replacement_fn(m), content, count=1, flags=flags)


def patch_hyprland_lua(theme):
    path = os.path.join(HOME, ".config/hypr/hyprland.lua")
    if not os.path.exists(path):
        return
    with open(path) as f:
        content = f.read()

    # [\d.]+ rather than \d+ on the whole-number fields below: a theme.json
    # value that was ever stored as e.g. 12.0 (see dxrice_theme_gui.py) would
    # otherwise only have its "12" replaced, leaving a stray ".0" that then
    # compounds into an invalid Lua literal ("14.0.0") on the next Apply.
    # Matching the whole numeral -- however malformed a previous run left it
    # -- and always writing back a clean int string self-heals that.
    content = _sub(content, r"(gaps_in\s*=\s*)[\d.]+",
                    lambda m: m.group(1) + str(theme["hypr_gaps_in"]))
    content = _sub(content, r"(gaps_out\s*=\s*)[\d.]+",
                    lambda m: m.group(1) + str(theme["hypr_gaps_out"]))
    content = _sub(content, r"(border_size\s*=\s*)[\d.]+",
                    lambda m: m.group(1) + str(theme["hypr_border_size"]))
    content = _sub(
        content,
        r'(active_border\s*=\s*\{\s*colors\s*=\s*\{)"rgba\([0-9a-fA-F]+\)",\s*"rgba\([0-9a-fA-F]+\)"(\}\s*,\s*angle\s*=\s*)[\d.]+',
        lambda m: (m.group(1)
                   + f'"rgba({theme["hypr_active_border_1"]}ee)", "rgba({theme["hypr_active_border_2"]}ee)"'
                   + m.group(2) + str(theme["hypr_active_border_angle"]))
    )
    content = _sub(
        content, r'(inactive_border\s*=\s*)"rgba\([0-9a-fA-F]+\)"',
        lambda m: m.group(1) + f'"rgba({theme["hypr_inactive_border"]}aa)"'
    )
    content = _sub(content, r"(decoration\s*=\s*\{[^}]*?rounding\s*=\s*)[\d.]+",
                    lambda m: m.group(1) + str(theme["hypr_rounding"]), flags=re.DOTALL)
    content = _sub(content, r"(active_opacity\s*=\s*)[\d.]+",
                    lambda m: m.group(1) + str(theme["hypr_active_opacity"]))
    content = _sub(content, r"(inactive_opacity\s*=\s*)[\d.]+",
                    lambda m: m.group(1) + str(theme["hypr_inactive_opacity"]))
    content = _sub(content, r"(blur\s*=\s*\{[^}]*?size\s*=\s*)[\d.]+",
                    lambda m: m.group(1) + str(theme["hypr_blur_size"]), flags=re.DOTALL)
    content = _sub(content, r"(blur\s*=\s*\{[^}]*?passes\s*=\s*)[\d.]+",
                    lambda m: m.group(1) + str(theme["hypr_blur_passes"]), flags=re.DOTALL)
    content = _sub(content, r"(blur\s*=\s*\{[^}]*?vibrancy\s*=\s*)[\d.]+",
                    lambda m: m.group(1) + str(theme["hypr_blur_vibrancy"]), flags=re.DOTALL)

    with open(path, "w") as f:
        f.write(content)


def _run_guarded(args, timeout=3):
    """Run a reload command with a hard timeout so one hung/contended
    command (e.g. hyprctl under IPC load) can never freeze the whole
    Apply -- each reload step is independent and best-effort."""
    try:
        subprocess.run(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=timeout)
    except (subprocess.TimeoutExpired, OSError):
        pass


def reload_apps(reload_wallpaper):
    _run_guarded(["pkill", "-x", "waybar"])
    subprocess.Popen(["setsid", "waybar"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                      stdin=subprocess.DEVNULL, start_new_session=True)

    _run_guarded(["makoctl", "reload"])
    _run_guarded(["pkill", "-SIGUSR1", "-x", "kitty"])
    _run_guarded(["hyprctl", "reload"])

    if reload_wallpaper:
        wallpaper = os.path.expanduser(theme_data.get("wallpaper", ""))
        if wallpaper and os.path.exists(wallpaper):
            _run_guarded(["pkill", "-x", "swaybg"])
            subprocess.Popen(["setsid", "swaybg", "-i", wallpaper, "-m", "fill"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


def main():
    global theme_data
    theme_path = sys.argv[1] if len(sys.argv) > 1 else THEME_JSON
    try:
        with open(theme_path) as f:
            theme_data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"Could not read {theme_path}: {e}", file=sys.stderr)
        print("Fix or restore it (theme_gui.py writes atomically and self-heals a corrupt "
              "theme.json, so opening the GUI once will also fix this) before re-running.",
              file=sys.stderr)
        sys.exit(1)

    render_templates(theme_data)
    patch_hyprland_lua(theme_data)
    reload_apps(reload_wallpaper=True)
    print("Theme applied.")


if __name__ == "__main__":
    main()
