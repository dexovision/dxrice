# DXrice

A fully configured, Lua-based Hyprland environment optimized for performance, modularity, and an interactive "Infinite Desktop" workflow. Managed clean via Git.

---

## Package Dependencies (Arch Linux)

Install all system core, audio, font, and runtime dependencies before running the installer:

Official Packages (pacman):
```bash
sudo pacman -S --needed hyprland hyprlock hypridle hyprpaper swaybg xdg-desktop-portal-hyprland waybar wofi mako kitty nautilus grim slurp cliphist qt5ct qt6ct pipewire pipewire-pulse pipewire-alsa wireplumber pavucontrol networkmanager network-manager-applet bluez bluez-utils blueman ttf-font-awesome noto-fonts ttf-jetbrains-mono-nerd polkit-kde-agent python python-evdev jq brightnessctl playerctl python-gobject gtk4 libadwaita
```

AUR Packages (yay / paru):
```bash
yay -S --needed nwg-look
```

---

## Quick Start Installation

Clone the repository (it must land at `~/dxrice` -- the theme engine hardcodes that path) and run the installer:

```bash
git clone https://github.com/dexovision/dxrice.git ~/dxrice
cd ~/dxrice
chmod +x install.sh
./install.sh
```

What `./install.sh` does on a fresh machine:
1. **Dependency check:** checks every pacman package this rice needs (including `python-gobject`, `gtk4`, `libadwaita` for the theme GUI) and offers to install anything missing; lists AUR packages (`nwg-look`) separately since it won't assume you have an AUR helper.
2. **`input` group:** checks whether you're in it (required for the infinite-desktop's raw-input reader) and offers to add you if not -- you'll need to log out/in or reboot afterward for it to take effect.
3. **Monitor auto-detection:** the very first time `hyprland.lua` is deployed (i.e. it doesn't exist yet at `~/.config/hypr/hyprland.lua`), runs `hyprctl monitors -j` and writes your real output name/resolution/position into it. Skipped if Hyprland isn't running yet or the file already exists -- see "Updating" below for why it's never touched again after that.
4. **Deploys everything** (configs, scripts, theme engine) and renders the theme once so waybar/wofi/mako/kitty/hyprlock all come up themed immediately.

## Updating

```bash
cd ~/dxrice
./install.sh update
```

This pulls the latest commit (auto-stashing and restoring any uncommitted local changes in the repo, e.g. `theme.json` edits made through the GUI, around the pull so they aren't lost or blocked) and then re-deploys. The re-deploy is guarded by a small manifest at `~/.local/state/dxrice/manifest.json` that remembers the hash of every file it last wrote:

* If a live file (in `~/.config/...` or `~/scripts/`) still matches what was last deployed, it's safely updated to the new version.
* If you've hand-edited that file since -- it's **left alone** and reported as skipped, never silently overwritten. The output tells you exactly which files were skipped so you can diff and merge by hand if you want the new version.
* The very first deploy of a pre-existing, unmanaged file (e.g. running the installer on a machine that already had a `~/.config/waybar/config` from something else) backs the old one up under `~/.local/state/dxrice/backups/` before taking it over.
* `hyprland.lua` is a special case: it's the most hand-edited file in the whole rice (keybinds, autostart, monitor setup), so it is **only ever copied in once**, on a completely fresh install where no live copy exists yet. After that, `update` never touches it -- new theme colors/blur values still reach it through `dxrice_apply_theme.py`'s narrow, line-by-line patch (see Theming below), but nothing else about it is ever auto-changed. If a rice update adds new default keybinds, check the repo's `hypr/hyprland.lua` by hand and copy over what you want.

---

## Infinite Desktop & Taskbar Management

The custom Infinite Desktop navigation engine and taskbar management are powered by Python scripts located in `~/scripts/` using `python-evdev` and `hyprctl`.

* **Group Permissions Requirement:** The installer checks for and can add you to the `input` group:
  `sudo usermod -aG input $USER`
* **Reboot Required:** You **MUST** log out/in or reboot after being added to the `input` group for raw input device access to take effect.

---

## Essential Keybindings

| Keybinding | Action |
| :--- | :--- |
| `SUPER + Q` | Launch Kitty Terminal |
| `SUPER + R` | Launch Application Launcher (Wofi) |
| `SUPER + E` | Open File Manager (Nautilus) |
| `SUPER + C` | Close Active Window |
| `SUPER + V` | Toggle Floating / Tiling Mode |
| `SUPER + Arrow Keys` | Move Focus Between Windows / Workspace Navigation |
| `SUPER + Shift + Arrows` | Reorder Window Position / Nudge Floating Window (90px) |
| `SUPER + Ctrl + Arrows` | Resize Floating Window |
| `SUPER + Alt + F` | Toggle Workspace Floating/Tiled Mode |
| `SUPER + Shift + S` | Capture Area Screenshot |
| `SUPER + TAB` | Toggle Taskbar Manager / Window Overview |
| `SUPER + Shift + A` | Open Taskbar Manager (add/remove/reorder apps) |
| `SUPER + Shift + T` | Open Theme Settings (GUI) |

---

## Theming (GUI Settings App)

Everything visual — colors, transparency, blur, corner radius, gaps, window border gradient, lock screen blur, fonts, and wallpaper — is controlled from one place: `~/dxrice/theme/theme.json`. Press `SUPER + Shift + T` to open a native GTK4/Adwaita settings app (`~/scripts/dxrice_theme_gui.py`) instead of hand-editing CSS/config files across five different apps.

How it works:
* `theme/theme.json` is the single source of truth for every themeable value.
* `theme/*.template` files (waybar, wofi, mako, kitty, hyprlock) are plain configs with `${TOKEN}` placeholders.
* `~/scripts/dxrice_apply_theme.py` renders those templates into the real `~/.config/...` files, patches the color/decoration block of `hyprland.lua` in place (regex, so your keybinds and autostart are untouched), and hot-reloads waybar, mako, kitty, and Hyprland — no session restart needed.
* The GUI is just a front-end over that same script: tweak a color/slider, hit **Apply**, everything reloads live.
* **Presets:** four built-in looks (Glass Charcoal, Nord, Dracula, Sunset) plus save/load your own from the Presets section at the top of the settings window.

To theme by hand instead of via the GUI, edit `theme/theme.json` directly and run:
```bash
python3 ~/scripts/dxrice_apply_theme.py
```

---

## Customization & Tweaks

### Taskbar & Window Management
* `dxrice-manage-taskbar.sh` (`SUPER + Shift + A`) manages the waybar app shortcuts on the left side of the bar. It always syncs its changes back into `~/dxrice/waybar/config` so they survive an `install.sh update`.
* **Add app shortcut (browse installed apps):** scans `/usr/share/applications` and `~/.local/share/applications`, lets you search/pick by name, and pulls the real command straight from the `.desktop` file -- no typing exec paths by hand.
* **Icons, not text labels:** every shortcut shows a real Nerd Font glyph (via `~/scripts/dxrice_icons.py`, matched against the app's name/command) instead of a plain text button, with the app name shown on hover as a tooltip. Falls back to a generic window icon for anything unrecognized.
* **Fix icons on existing shortcuts:** a one-shot menu option that re-derives icons for shortcuts you already added under the old text-label behavior.
* Taskbar window switching and reordering work dynamically across tiled and floating workspace layouts.

### Wallpaper Management
* Default image location: `~/Pictures/Wallpapers/default.png`
* To change wallpaper manually, update `~/.config/hypr/env_vars.conf`:
  `BG_WALLPAPER="/path/to/your/image.png"`
* Apply changes anytime with: `hyprctl reload`

### Animated Wallpaper Engine (Optional)
Static wallpapers via `swaybg` are set by default. For animated wallpapers using Steam Wallpaper Engine:
```bash
yay -S linux-wallpaperengine-git
```

Replace the `swaybg` line in `~/.config/hypr/hyprland.lua` under autostart:
`exec_once = "linux-wallpaperengine --screen-root <YOUR_MONITOR> <WORKSHOP_ID>"`

### Credits
* https://github.com/sarodscommits/hyprland-infinitie-desktop-v2:
  Made the hyprland infinite-canvas scripts.

* @gentoolarp on tiktok:
  Gave reference for customization and looks.
