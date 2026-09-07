# Hyprland Infinite Desktop Rice

A fully configured, Lua-based Hyprland environment optimized for performance, modularity, and an interactive "Infinite Desktop" workflow. Managed clean via Git.

---

## Package Dependencies (Arch Linux)

Install all system core, audio, font, and runtime dependencies before running the installer:

Official Packages (pacman):
sudo pacman -S --needed hyprland hyprlock hypridle hyprpaper swaybg xdg-desktop-portal-hyprland waybar wofi mako kitty nautilus grim slurp cliphist qt5ct qt6ct pipewire pipewire-pulse pipewire-alsa wireplumber pavucontrol networkmanager network-manager-applet bluez bluez-utils blueman ttf-font-awesome noto-fonts ttf-jetbrains-mono-nerd polkit-kde-agent python python-evdev jq brightnessctl playerctl

AUR Packages (yay / paru):
yay -S --needed nwg-look

---

## Quick Start Installation

Clone the repository and run the automated interactive installer:

git clone https://github.com/YOUR_USERNAME/dotfiles-rice.git ~/dotfiles-rice
cd ~/dotfiles-rice
chmod +x install.sh
./install.sh

What install.sh Does Automatically:
1. Dependency Verification: Prompts to auto-install missing packages via pacman.
2. Wallpaper Setup: Guides wallpaper setup and defaults to ~/Pictures/Wallpapers/default.png. Accepts custom paths with automatic ~ tilde expansion.
3. Monitor Auto-Detection: Uses hyprctl monitors to detect your active screen output and configures hyprland.lua dynamically.
4. Configuration Safety Backups: Automatically backs up existing ~/.config/hypr setups with timestamped folders.
5. Permissions Management: Checks and adds your user to the input group for Infinite Desktop core capabilities.

---

## Infinite Desktop Setup

The custom Infinite Desktop navigation engine is powered by Python scripts located in ~/scripts/ using python-evdev.

* Group Permissions Requirement: The installer automatically runs:
  sudo usermod -aG input $USER

* Reboot Required: You MUST reboot your computer after adding your user to the input group for raw input device access to take effect.

---

## Essential Keybindings

| Keybinding | Action |
| :--- | :--- |
| SUPER + Q | Launch Kitty Terminal |
| SUPER + R | Launch Application Launcher (Wofi) |
| SUPER + E | Open File Manager (Nautilus) |
| SUPER + C | Close Active Window |
| SUPER + V | Toggle Floating / Tiling Mode |
| SUPER + Arrow Keys | Move Focus Between Windows |
| SUPER + Shift + Arrows | Nudge Floating Window (90px) |
| SUPER + Ctrl + Arrows | Resize Floating Window |
| SUPER + Alt + F | Toggle Workspace Floating/Tiled Mode |
| SUPER + Shift + S | Capture Area Screenshot |

---

## Customization & Tweaks

### Wallpaper Management
* Default image location: ~/Pictures/Wallpapers/default.png
* To change wallpaper manually, update ~/.config/hypr/env_vars.conf:
  BG_WALLPAPER="/path/to/your/image.png"
* Apply changes anytime with: hyprctl reload

### Animated Wallpaper Engine (Optional)
Static wallpapers via swaybg are set by default. For animated wallpapers using Steam Wallpaper Engine:
yay -S linux-wallpaperengine-git

Replace the swaybg line in ~/.config/hypr/hyprland.lua under autostart:
exec_once = "linux-wallpaperengine --screen-root <YOUR_MONITOR> <WORKSHOP_ID>"
