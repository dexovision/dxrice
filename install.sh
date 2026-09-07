#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"

echo "==> Deploying hyprland-rice configs to ~/.config..."

mkdir -p ~/.config/{hypr,kitty,waybar,mako}
mkdir -p ~/scripts

[ -f "$REPO_DIR/hypr/hyprland.lua" ] && cp -v "$REPO_DIR/hypr/hyprland.lua" ~/.config/hypr/
[ -f "$REPO_DIR/kitty/kitty.conf" ] && cp -v "$REPO_DIR/kitty/kitty.conf" ~/.config/kitty/
[ -f "$REPO_DIR/waybar/config" ] && cp -v "$REPO_DIR/waybar/config" ~/.config/waybar/
[ -f "$REPO_DIR/waybar/style.css" ] && cp -v "$REPO_DIR/waybar/style.css" ~/.config/waybar/
[ -f "$REPO_DIR/mako/config" ] && cp -v "$REPO_DIR/mako/config" ~/.config/mako/

if [ -d "$REPO_DIR/scripts" ]; then
    cp -v "$REPO_DIR/scripts"/*.sh ~/scripts/ 2>/dev/null || true
    cp -v "$REPO_DIR/scripts"/*.py ~/scripts/ 2>/dev/null || true
    chmod +x ~/scripts/* 2>/dev/null || true
fi

echo ""
echo "[OK] Configs successfully installed! Restart Hyprland or Waybar to apply changes."
