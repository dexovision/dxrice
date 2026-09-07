#!/usr/bin/env bash
set -e

# Visual formatting
BOLD="\033[1m"
GREEN="\033[0;32m"
YELLOW="\033[0;33m"
CYAN="\033[0;36m"
RED="\033[0;31m"
RESET="\033[0m"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo -e "${BOLD}${CYAN}===============================================${RESET}"
echo -e "${BOLD}${CYAN}    Hyprland Dotfiles & Rice Installer        ${RESET}"
echo -e "${BOLD}${CYAN}===============================================${RESET}\n"

# -------------------------------------------------------------
# 1. Dependency Check & Interactive Auto-Install
# -------------------------------------------------------------
echo -e "${BOLD}[1/5] Checking dependencies...${RESET}"
REQUIRED="hyprland hyprlock hypridle hyprpaper swaybg waybar wofi mako kitty nautilus grim slurp cliphist python-evdev"
MISSING=""

for pkg in $REQUIRED; do
    pacman -Qq "$pkg" &>/dev/null || MISSING="$MISSING $pkg"
done

if [ -n "$MISSING" ]; then
    echo -e "${YELLOW}Missing packages detected:${RESET}$MISSING"
    read -rp "Would you like to install missing dependencies with pacman now? [Y/n]: " INSTALL_PKG
    INSTALL_PKG=${INSTALL_PKG:-Y}
    if [[ "$INSTALL_PKG" =~ ^[Yy]$ ]]; then
        sudo pacman -S --needed $MISSING
    else
        echo -e "${RED}Aborting installer. Please install missing packages manually and re-run.${RESET}"
        exit 1
    fi
else
    echo -e "${GREEN}All required system packages are installed.${RESET}"
fi

# -------------------------------------------------------------
# 2. Wallpaper Configuration
# -------------------------------------------------------------
echo -e "\n${BOLD}[2/5] Wallpaper Setup${RESET}"
WP_DIR="$HOME/Pictures/Wallpapers"
mkdir -p "$WP_DIR"

echo -e "Default wallpaper path: ${CYAN}$WP_DIR/default.png${RESET}"
read -rp "Enter path to custom wallpaper image (press Enter for default): " USER_WP

if [ -n "$USER_WP" ]; then
    # Automatically expand ~ tilde to full $HOME path
    WP_PATH="${USER_WP/#\~/$HOME}"
else
    WP_PATH="$WP_DIR/default.png"
fi

if [ -f "$WP_PATH" ]; then
    echo -e "${GREEN}Found wallpaper at ${WP_PATH}${RESET}"
else
    echo -e "${YELLOW}No wallpaper found at ${WP_PATH}.${RESET}"
    if [ -f "$WP_DIR/wallpaper.png" ]; then
        cp "$WP_DIR/wallpaper.png" "$WP_DIR/default.png"
        WP_PATH="$WP_DIR/default.png"
        echo -e "${GREEN}Copied wallpaper.png -> default.png${RESET}"
    elif [ -f "$WP_DIR/hk_static.png" ]; then
        cp "$WP_DIR/hk_static.png" "$WP_DIR/default.png"
        WP_PATH="$WP_DIR/default.png"
        echo -e "${GREEN}Copied hk_static.png -> default.png${RESET}"
    else
        echo -e "Creating a placeholder image at ${CYAN}$WP_DIR/default.png${RESET}..."
        convert -size 1920x1080 canvas:black "$WP_DIR/default.png" 2>/dev/null || touch "$WP_DIR/default.png"
        WP_PATH="$WP_DIR/default.png"
    fi
fi

# -------------------------------------------------------------
# 3. Monitor Auto-Detection
# -------------------------------------------------------------
echo -e "\n${BOLD}[3/5] Monitor Setup${RESET}"
ACTIVE_MONITOR=""
if command -v hyprctl &>/dev/null; then
    ACTIVE_MONITOR=$(hyprctl monitors 2>/dev/null | grep "Monitor" | awk '{print $2}' | head -n 1 || true)
fi

if [ -n "$ACTIVE_MONITOR" ]; then
    echo -e "Detected active monitor: ${CYAN}${ACTIVE_MONITOR}${RESET}"
    sed -i "s/output = \".*\"/output = \"${ACTIVE_MONITOR}\"/" "$SCRIPT_DIR/hypr/hyprland.lua"
    echo -e "${GREEN}Configured hyprland.lua to use ${ACTIVE_MONITOR}${RESET}"
else
    echo -e "${YELLOW}Hyprland not currently running; keeping default monitor settings.${RESET}"
fi

# -------------------------------------------------------------
# 4. Safe Configuration Deployment (with Backups)
# -------------------------------------------------------------
echo -e "\n${BOLD}[4/5] Deploying configuration files...${RESET}"

# Create backup of existing config if present
BACKUP_DIR="$HOME/.config/hypr_backup_$(date +%Y%m%d_%H%M%S)"
if [ -d "$HOME/.config/hypr" ]; then
    echo -e "Creating safety backup at ${CYAN}${BACKUP_DIR}${RESET}"
    mkdir -p "$BACKUP_DIR"
    cp -r ~/.config/hypr ~/.config/kitty ~/.config/waybar ~/.config/mako "$BACKUP_DIR/" 2>/dev/null || true
fi

mkdir -p ~/.config/{hypr,kitty,waybar,mako} ~/scripts

cp -r "$SCRIPT_DIR/hypr/"* ~/.config/hypr/
cp -r "$SCRIPT_DIR/kitty/"* ~/.config/kitty/
cp -r "$SCRIPT_DIR/waybar/"* ~/.config/waybar/
cp -r "$SCRIPT_DIR/mako/"* ~/.config/mako/ 2>/dev/null || true
cp -r "$SCRIPT_DIR/scripts/"* ~/scripts/ 2>/dev/null || true
chmod +x ~/scripts/*.py ~/scripts/*.sh 2>/dev/null || true

# Set wallpaper environment variable
ENV_FILE="$HOME/.config/hypr/env_vars.conf"
echo "BG_WALLPAPER=\"$WP_PATH\"" > "$ENV_FILE"

# -------------------------------------------------------------
# 5. User Group Permissions
# -------------------------------------------------------------
echo -e "\n${BOLD}[5/5] Checking User Group Permissions${RESET}"
if groups "$USER" | grep &>/dev/null '\binput\b'; then
    echo -e "${GREEN}User '$USER' is in the 'input' group.${RESET}"
else
    echo -e "${YELLOW}Adding '$USER' to the 'input' group (required for Infinite Desktop)...${RESET}"
    sudo usermod -aG input "$USER"
    echo -e "${GREEN}Successfully added $USER to 'input' group.${RESET}"
fi

# -------------------------------------------------------------
# Summary & User Help Reference
# -------------------------------------------------------------
echo -e "\n${BOLD}${GREEN}===============================================${RESET}"
echo -e "${BOLD}${GREEN}          Installation Complete!              ${RESET}"
echo -e "${BOLD}${GREEN}===============================================${RESET}"

echo -e "\n${BOLD}${CYAN}--- Installed Directories ---${RESET}"
echo -e "  • Configs : ${CYAN}~/.config/{hypr, kitty, waybar, mako}${RESET}"
echo -e "  • Helpers : ${CYAN}~/scripts/${RESET}"
echo -e "  • Wallpaper: ${CYAN}${WP_PATH}${RESET}"

echo -e "\n${BOLD}${CYAN}--- Essential Keybindings Cheat Sheet ---${RESET}"
echo -e "  • ${BOLD}SUPER + Q${RESET}              : Open Kitty Terminal"
echo -e "  • ${BOLD}SUPER + R${RESET}              : App Launcher (Wofi)"
echo -e "  • ${BOLD}SUPER + E${RESET}              : File Manager (Nautilus)"
echo -e "  • ${BOLD}SUPER + C${RESET}              : Close Active Window"
echo -e "  • ${BOLD}SUPER + V${RESET}              : Toggle Floating Mode"
echo -e "  • ${BOLD}SUPER + Arrow Keys${RESET}     : Move Window Focus"
echo -e "  • ${BOLD}SUPER + Shift + Arrows${RESET} : Move Floating Window (90px)"
echo -e "  • ${BOLD}SUPER + Ctrl + Arrows${RESET}  : Resize Floating Window"
echo -e "  • ${BOLD}SUPER + Shift + S${RESET}      : Area Screenshot"

echo -e "\n${YELLOW}NOTE:${RESET} Default wallpaper is expected at ${CYAN}~/Pictures/Wallpapers/default.png${RESET}"
echo -e "${YELLOW}NEXT STEPS:${RESET}"
echo -e "  1. Reload Hyprland to apply changes: ${BOLD}hyprctl reload${RESET}"
echo -e "  2. If group permissions changed, ${YELLOW}log out and back in${RESET} for Infinite Desktop.\n"
