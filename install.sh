#!/usr/bin/env bash
set -e
echo "Installing rice..."
mkdir -p ~/.config/hypr ~/.config/kitty ~/.config/waybar ~/.config/mako ~/scripts
cp hypr/hyprland.lua ~/.config/hypr/
cp hypr/hyprpaper.conf ~/.config/hypr/ 2>/dev/null || true
cp kitty/kitty.conf ~/.config/kitty/
cp waybar/config ~/.config/waybar/
cp waybar/style.css ~/.config/waybar/
cp mako/config ~/.config/mako/ 2>/dev/null || true
cp scripts/*.py scripts/*.sh ~/scripts/ 2>/dev/null || true
chmod +x ~/scripts/*.py ~/scripts/*.sh 2>/dev/null || true
echo "Done. Restart Hyprland (log out/in) to apply."
echo "Note: your friend needs eDP-1/1920x1080@144.03 hardcoded in hyprland.lua monitor block —"
echo "they should update that line to match THEIR monitor (run 'hyprctl monitors' to check)."
