# Hyprland Infinite Desktop Rice

## Required packages (Arch)
sudo pacman -S --needed hyprland hyprlock hypridle hyprpaper swaybg xdg-desktop-portal-hyprland \
  waybar wofi mako kitty yazi nautilus grim slurp cliphist qt5ct qt6ct \
  pipewire pipewire-pulse pipewire-alsa wireplumber pavucontrol \
  networkmanager network-manager-applet bluez bluez-utils blueman \
  ttf-font-awesome noto-fonts ttf-jetbrains-mono-nerd polkit-kde-agent \
  python python-evdev jq brightnessctl playerctl

yay -S nwg-look

## Infinite Desktop feature
Uses https://github.com/sarodscommits/hyprland-infinitie-desktop-v2 (scripts/ folder).
Requires: `sudo usermod -aG input $USER` then REBOOT (not just re-login) for python-evdev
to get raw input device access.

## Install
./install.sh

## IMPORTANT: things you MUST change after installing
1. Monitor block in hypr/hyprland.lua — currently hardcoded to eDP-1 @ 1920x1080@144.03.
   Run `hyprctl monitors` and update output/mode/scale to match YOUR screen.
2. Wallpaper path — install.sh copies a placeholder; put your own image at
   ~/Pictures/Wallpapers/ and update the swaybg line if the filename differs.

## Wallpaper Engine (optional, NOT included)
Static wallpaper via swaybg is default. For the live animated version:
- Steam + Wallpaper Engine (paid, ~$4)
- yay -S linux-wallpaperengine-git
- Subscribe to a Workshop item on steamcommunity.com, grab the numeric ID from the URL
- Swap the swaybg line in hyprland.lua's autostart for:
  linux-wallpaperengine --screen-root <YOUR_MONITOR_NAME> <WORKSHOP_ID>
