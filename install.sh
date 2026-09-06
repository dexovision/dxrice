#!/usr/bin/env bash
set -e

echo "Checking required packages..."
REQUIRED="hyprland hyprlock hypridle hyprpaper swaybg waybar wofi mako kitty nautilus grim slurp cliphist"
MISSING=""
for pkg in $REQUIRED; do
    pacman -Qq "$pkg" &>/dev/null || MISSING="$MISSING $pkg"
done

if [ -n "$MISSING" ]; then
    echo "Missing packages:$MISSING"
    echo "Install them first: sudo pacman -S --needed$MISSING"
    exit 1
fi

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

echo ""
echo "Done. Before restarting, you MUST:"
echo "  1. Edit ~/.config/hypr/hyprland.lua monitor block (run 'hyprctl monitors' to check yours)"
echo "  2. Put a wallpaper image at ~/Pictures/Wallpapers/ and check the swaybg line matches"
echo "  3. Run: sudo usermod -aG input \$USER   (then REBOOT, required for infinite desktop)"
echo ""
echo "Then restart Hyprland fully (log out/in) — NOT just hyprctl reload."
