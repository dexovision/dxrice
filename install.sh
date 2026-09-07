#!/usr/bin/env bash
set -e

BOLD="\033[1m"
GREEN="\033[0;32m"
YELLOW="\033[0;33m"
CYAN="\033[0;36m"
RED="\033[0;31m"
RESET="\033[0m"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo -e "${BOLD}${CYAN}=== Hyprland Dotfiles & Rice Installer ===${RESET}\n"

# 1. Dependency Check
echo -e "${BOLD}[1/5] Checking dependencies...${RESET}"
REQUIRED="hyprland hyprlock hypridle hyprpaper swaybg waybar wofi mako kitty nautilus grim slurp cliphist python-evdev"
MISSING=""

for pkg in $REQUIRED; do
    pacman -Qq "$pkg" &>/dev/null || MISSING="$MISSING $pkg"
done

if [ -n "$MISSING" ]; then
    echo -e "${RED}Missing required packages:${RESET}$MISSING"
    echo -e "Please install them first with: ${YELLOW}sudo pacman -S --needed$MISSING${RESET}"
    exit 1
else
    echo -e "${GREEN}All required system packages are installed.${RESET}"
fi

# 2. Wallpaper Setup
echo -e "\n${BOLD}[2/5] Wallpaper Setup${RESET}"
WP_DIR="$HOME/Pictures/Wallpapers"
WP_PATH="$WP_DIR/wallpaper.png"
mkdir -p "$WP_DIR"

echo -e "Wallpapers are expected at: ${CYAN}$WP_PATH${RESET}"

if [ -f "$WP_PATH" ]; then
    echo -e "${GREEN}Found wallpaper image at $WP_PATH!${RESET}"
else
    echo -e "${YELLOW}No image found at $WP_PATH.${RESET}"
    echo -e "${BOLD}Please place your desired wallpaper image at:${RESET} ${CYAN}$WP_PATH${RESET}"
    
    # Check if hk_static.png or any fallback exists to copy over temporarily
    if [ -f "$WP_DIR/hk_static.png" ]; then
        cp "$WP_DIR/hk_static.png" "$WP_PATH"
        echo -e "${GREEN}Copied hk_static.png to wallpaper.png as default.${RESET}"
    elif [ -f "$WP_DIR/default.png" ]; then
        cp "$WP_DIR/default.png" "$WP_PATH"
        echo -e "${GREEN}Copied default.png to wallpaper.png as default.${RESET}"
    else
        echo -e "Creating black placeholder image at ${CYAN}$WP_PATH${RESET}..."
        convert -size 1920x1080 canvas:black "$WP_PATH" 2>/dev/null || touch "$WP_PATH"
    fi
fi

# 3. Monitor Setup
echo -e "\n${BOLD}[3/5] Monitor Setup${RESET}"
ACTIVE_MONITOR=""
if command -v hyprctl &>/dev/null; then
    ACTIVE_MONITOR=$(hyprctl monitors 2>/dev/null | grep "Monitor" | awk '{print $2}' | head -n 1 || true)
fi

if [ -n "$ACTIVE_MONITOR" ]; then
    echo -e "Detected active monitor output: ${CYAN}${ACTIVE_MONITOR}${RESET}"
    sed -i "s/output = \".*\"/output = \"${ACTIVE_MONITOR}\"/" "$SCRIPT_DIR/hypr/hyprland.lua"
    echo -e "${GREEN}Updated monitor in hyprland.lua to ${ACTIVE_MONITOR}${RESET}"
fi

# 4. Deploy Configuration Files
echo -e "\n${BOLD}[4/5] Deploying configuration files...${RESET}"
mkdir -p ~/.config/{hypr,kitty,waybar,mako} ~/scripts

cp -r "$SCRIPT_DIR/hypr/"* ~/.config/hypr/
cp -r "$SCRIPT_DIR/kitty/"* ~/.config/kitty/
cp -r "$SCRIPT_DIR/waybar/"* ~/.config/waybar/
cp -r "$SCRIPT_DIR/mako/"* ~/.config/mako/ 2>/dev/null || true
cp -r "$SCRIPT_DIR/scripts/"* ~/scripts/ 2>/dev/null || true
chmod +x ~/scripts/*.py ~/scripts/*.sh 2>/dev/null || true

# Update wallpaper environment variable
ENV_FILE="$HOME/.config/hypr/env_vars.conf"
echo "BG_WALLPAPER=\"$WP_PATH\"" > "$ENV_FILE"

# 5. User Group Permissions
echo -e "\n${BOLD}[5/5] Checking User Group Permissions${RESET}"
if groups "$USER" | grep &>/dev/null '\binput\b'; then
    echo -e "${GREEN}User is already in the 'input' group.${RESET}"
else
    echo -e "${YELLOW}User '$USER' is not in the 'input' group (required for Infinite Desktop).${RESET}"
    sudo usermod -aG input "$USER"
    echo -e "${GREEN}Added $USER to the 'input' group.${RESET}"
fi

# Completion Summary
echo -e "\n${BOLD}${GREEN}=== Setup Complete! ===${RESET}"
echo -e "Summary of actions:"
echo -e "  • Config files copied to ${CYAN}~/.config/${RESET}"
echo -e "  • Scripts installed to ${CYAN}~/scripts/${RESET}"
echo -e "  • Wallpaper path set to: ${CYAN}$WP_PATH${RESET}"
echo -e "\n${YELLOW}NOTE:${RESET} Place your wallpaper image at ${CYAN}~/Pictures/Wallpapers/wallpaper.png${RESET}"
echo -e "Then reload Hyprland using: ${BOLD}hyprctl reload${RESET}"
