#!/usr/bin/env bash
# Installer / updater for the DXrice dotfiles.
#
#   ./install.sh            fresh install: deps, input group, monitor
#                            detection, deploy everything
#   ./install.sh update     git pull (auto-stashing local repo edits like
#                            theme.json tweaks), then re-deploy -- any file
#                            you've hand-edited in ~/.config or ~/scripts
#                            since the last deploy is left alone, not
#                            overwritten
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
MODE="${1:-install}"

PACMAN_PACKAGES=(hyprland hyprlock hypridle hyprpaper swaybg xdg-desktop-portal-hyprland
    waybar wofi mako kitty nautilus grim slurp cliphist qt5ct qt6ct
    pipewire pipewire-pulse pipewire-alsa wireplumber pavucontrol
    networkmanager network-manager-applet bluez bluez-utils blueman
    ttf-font-awesome noto-fonts ttf-jetbrains-mono-nerd polkit-kde-agent
    python python-evdev jq brightnessctl playerctl
    python-gobject gtk4 libadwaita)
AUR_PACKAGES=(nwg-look)

if [ "$REPO_DIR" != "$HOME/dxrice" ]; then
    echo "WARNING: this checkout is at $REPO_DIR, not ~/dxrice."
    echo "The theme engine (dxrice_apply_theme.py, dxrice_theme_gui.py) assumes ~/dxrice"
    echo "and will not find your templates/theme.json from anywhere else."
    echo ""
fi

check_dependencies() {
    echo "==> Checking pacman dependencies..."
    local missing=()
    for pkg in "${PACMAN_PACKAGES[@]}"; do
        pacman -Qi "$pkg" >/dev/null 2>&1 || missing+=("$pkg")
    done
    if [ "${#missing[@]}" -gt 0 ]; then
        echo "Missing: ${missing[*]}"
        read -rp "Install them now with pacman? [Y/n] " REPLY
        if [[ ! "$REPLY" =~ ^[Nn]$ ]]; then
            sudo pacman -S --needed "${missing[@]}" || echo "pacman install failed or was cancelled; continuing anyway."
        fi
    else
        echo "All pacman dependencies present."
    fi

    local missing_aur=()
    for pkg in "${AUR_PACKAGES[@]}"; do
        pacman -Qi "$pkg" >/dev/null 2>&1 || missing_aur+=("$pkg")
    done
    if [ "${#missing_aur[@]}" -gt 0 ]; then
        echo "AUR packages not installed, install manually with yay/paru: ${missing_aur[*]}"
    fi
}

check_input_group() {
    echo "==> Checking 'input' group membership (required for the infinite desktop)..."
    if id -nG "$USER" | grep -qw input; then
        echo "Already in the 'input' group."
    else
        read -rp "Add $USER to the 'input' group now? [Y/n] " REPLY
        if [[ ! "$REPLY" =~ ^[Nn]$ ]]; then
            sudo usermod -aG input "$USER" || echo "usermod failed; add yourself to 'input' manually."
            echo "Added. You must log out and back in (or reboot) for this to take effect."
        fi
    fi
}

detect_monitor() {
    local target="$HOME/.config/hypr/hyprland.lua"
    command -v hyprctl >/dev/null 2>&1 || { echo "hyprctl not found (Hyprland not running yet) -- skipping monitor auto-detect, edit hypr/hyprland.lua's eDP-1/resolution by hand."; return; }
    python3 - "$target" <<'PYEOF'
import json, re, subprocess, sys

target = sys.argv[1]
try:
    monitors = json.loads(subprocess.run(
        ["hyprctl", "monitors", "-j"], capture_output=True, text=True, timeout=2
    ).stdout)
except Exception:
    print("Could not query hyprctl monitors -- skipping auto-detect.")
    sys.exit(0)
if not monitors:
    sys.exit(0)

m = monitors[0]
name = m["name"]
mode = f'{m["width"]}x{m["height"]}@{m["refreshRate"]:.2f}'
pos = f'{m["x"]}x{m["y"]}'

with open(target) as f:
    content = f.read()
content = re.sub(r'output\s*=\s*"[^"]*"', f'output = "{name}"', content, count=1)
content = re.sub(r'mode\s*=\s*"[^"]*"', f'mode = "{mode}"', content, count=1)
content = re.sub(r'position\s*=\s*"[^"]*"', f'position = "{pos}"', content, count=1)
with open(target, "w") as f:
    f.write(content)
print(f"Detected monitor {name} ({mode} at {pos}) and wrote it into hyprland.lua")
PYEOF
}

do_deploy() {
    echo "==> Deploying configs (anything you've hand-edited is protected)..."
    mkdir -p ~/.config/{hypr,kitty,waybar,mako,wofi} ~/scripts
    python3 "$REPO_DIR/scripts/dxrice_deploy.py" "$REPO_DIR"

    echo ""
    echo "==> Rendering theme (waybar/wofi/mako/kitty/hyprlock from theme.json)..."
    python3 "$REPO_DIR/scripts/dxrice_apply_theme.py" "$REPO_DIR/theme/theme.json" || true
}

do_install() {
    check_dependencies
    check_input_group

    local hypr_existed=0
    [ -f "$HOME/.config/hypr/hyprland.lua" ] && hypr_existed=1

    do_deploy

    if [ "$hypr_existed" = "0" ]; then
        echo ""
        echo "==> Detecting your monitor for hyprland.lua..."
        detect_monitor
    fi

    echo ""
    echo "[OK] Fresh install complete."
    echo "If you were just added to the 'input' group, log out and back in (or reboot)."
    echo "Then log out/in once more so autostart (waybar, mako, swaybg, etc.) picks everything up."
}

do_update() {
    echo "==> Pulling latest from git..."
    cd "$REPO_DIR"
    if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
        echo "Not a git repository -- skipping git pull, deploying what's on disk."
    else
        local stashed=0
        if [ -n "$(git status --porcelain)" ]; then
            echo "Stashing your local repo changes (e.g. theme.json edits from the GUI) before pulling..."
            git stash push -m "rice-update-autostash" >/dev/null
            stashed=1
        fi
        git pull --ff-only || echo "git pull failed -- resolve manually (merge conflict, diverged branch?), then re-run './install.sh update'."
        if [ "$stashed" = "1" ]; then
            echo "Restoring your local repo changes..."
            git stash pop || echo "Could not auto-restore your stashed changes cleanly -- run 'git stash list' / 'git stash pop' by hand to recover them."
        fi
    fi

    do_deploy
    echo ""
    echo "[OK] Update complete. Anything hand-edited in ~/.config or ~/scripts was left alone -- see above."
}

case "$MODE" in
    install|"") do_install ;;
    update) do_update ;;
    *) echo "Usage: $0 [install|update]"; exit 1 ;;
esac
