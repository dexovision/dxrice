#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"

echo "==> Deploying hyprland-rice configs to ~/.config..."

mkdir -p ~/.config/{hypr,kitty,waybar,mako,wofi}
mkdir -p ~/scripts
mkdir -p ~/dotfiles-rice

[ -f "$REPO_DIR/hypr/hyprland.lua" ] && cp -v "$REPO_DIR/hypr/hyprland.lua" ~/.config/hypr/
[ -f "$REPO_DIR/hypr/hyprlock.conf" ] && cp -v "$REPO_DIR/hypr/hyprlock.conf" ~/.config/hypr/
[ -f "$REPO_DIR/kitty/kitty.conf" ] && cp -v "$REPO_DIR/kitty/kitty.conf" ~/.config/kitty/
[ -f "$REPO_DIR/waybar/config" ] && cp -v "$REPO_DIR/waybar/config" ~/.config/waybar/
[ -f "$REPO_DIR/waybar/style.css" ] && cp -v "$REPO_DIR/waybar/style.css" ~/.config/waybar/
[ -f "$REPO_DIR/mako/config" ] && cp -v "$REPO_DIR/mako/config" ~/.config/mako/
[ -f "$REPO_DIR/wofi/config" ] && cp -v "$REPO_DIR/wofi/config" ~/.config/wofi/
[ -f "$REPO_DIR/wofi/style.css" ] && cp -v "$REPO_DIR/wofi/style.css" ~/.config/wofi/

if [ -d "$REPO_DIR/scripts" ]; then
    cp -v "$REPO_DIR/scripts"/*.sh ~/scripts/ 2>/dev/null || true
    cp -v "$REPO_DIR/scripts"/*.py ~/scripts/ 2>/dev/null || true
    chmod +x ~/scripts/* 2>/dev/null || true
fi

echo "==> Deploying theme engine (theme.json + templates + presets)..."
if [ -d "$REPO_DIR/theme" ]; then
    rsync -a --exclude='.git' "$REPO_DIR/theme/" ~/dotfiles-rice/theme/ 2>/dev/null \
        || cp -rv "$REPO_DIR/theme" ~/dotfiles-rice/
fi

echo ""
echo "[OK] Configs successfully installed! Restart Hyprland or Waybar to apply changes."
