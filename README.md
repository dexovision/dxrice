# Hyprland Infinite Desktop Rice

## Required packages (Arch)
sudo pacman -S --needed hyprland hyprlock hypridle hyprpaper xdg-desktop-portal-hyprland \
  waybar wofi mako kitty yazi nautilus grim slurp cliphist qt5ct qt6ct \
  pipewire pipewire-pulse pipewire-alsa wireplumber pavucontrol \
  networkmanager network-manager-applet bluez bluez-utils blueman \
  ttf-font-awesome noto-fonts ttf-jetbrains-mono-nerd polkit-kde-agent \
  python python-evdev jq

## Infinite Desktop feature
Uses https://github.com/sarodscommits/hyprland-infinitie-desktop-v2 (scripts/ folder).
Requires: `sudo usermod -aG input $USER` then reboot, for python-evdev to read raw input.

## Install
./install.sh

## IMPORTANT: edit the monitor line
In hypr/hyprland.lua, the `hl.monitor({...})` block has MY exact monitor name/resolution
hardcoded (eDP-1, 1920x1080@144.03). Run `hyprctl monitors` on your own machine and change
that block to match, or you'll get the wrong resolution/scale.

## Wallpaper Engine (optional)
Static wallpaper via swaybg is default. For the live animated version you need:
- Steam + Wallpaper Engine (paid, ~$4)
- yay -S linux-wallpaperengine-git
- Subscribe to a Workshop item, get its ID from the URL, swap the swaybg line in
  hyprland.lua's autostart for: linux-wallpaperengine --screen-root <YOUR_MONITOR> <ID>
