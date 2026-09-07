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

Clone the repository -- it can go anywhere, under any folder name, and `install.sh` will offer to move it wherever you actually want it to live before doing anything else -- then run the installer:

```bash
git clone https://github.com/dexovision/dxrice.git ~/dxrice
cd ~/dxrice
chmod +x install.sh
./install.sh
```

Important: install the whole repository this way, not just `install.sh` by itself (e.g. from a raw-file download link) -- the installer needs the sibling `scripts/` and `theme/` directories to exist next to it, and will refuse to run with a clear error if they're missing.

DXrice keeps everything -- scripts, the theme engine, its own state -- inside that one folder; scripts run straight out of it instead of being copied loose into `$HOME`. The only things that land outside it are the real app config files each app expects in its own `~/.config/<app>` spot (waybar, wofi, mako, kitty, hyprlock) and `~/.config/hypr/hyprland.lua` itself.

What `./install.sh` does on a fresh machine:
1. **Asks where you want it installed** (default: wherever you cloned it) and moves the checkout there if you pick somewhere else, then records that location in `~/.local/state/dxrice/repo_path` so `hyprland.lua`'s keybinds -- a plain dotfile deployed to a fixed path -- can always find it later.
2. **Dependency check:** checks every pacman package this rice needs (including `python-gobject`, `gtk4`, `libadwaita` for the theme GUI) and offers to install anything missing; lists AUR packages (`nwg-look`) separately since it won't assume you have an AUR helper. Skipped gracefully on non-Arch systems (no `pacman`).
3. **`input` group:** checks whether you're in it (required for the infinite-desktop's raw-input reader) and offers to add you if not -- you'll need to log out/in or reboot afterward for it to take effect.
4. **Monitor auto-detection:** the very first time `hyprland.lua` is deployed (i.e. it doesn't exist yet at `~/.config/hypr/hyprland.lua`), runs `hyprctl monitors -j` and writes your real output name/resolution/position into it. Skipped if Hyprland isn't running yet or the file already exists -- see "Updating" below for why it's never touched again after that.
5. **Deploys everything** (app configs, `hyprland.lua`, theme engine) and renders the theme once so waybar/wofi/mako/kitty/hyprlock all come up themed immediately, then verifies every file the keybinds depend on actually exists before declaring success.

**A crucial gotcha on first install:** Hyprland decides whether to load `hyprland.conf` or `hyprland.lua` only *once*, at startup. If Hyprland was already running before `hyprland.lua` existed (e.g. it booted off a bare default config), your keybinds and the infinite desktop won't work until you fully log out and back in (or reboot) -- a `hyprctl reload` does not pick up the switch. `install.sh` detects this case and warns you explicitly.

## Updating

```bash
cd ~/dxrice   # or wherever you installed it
./install.sh update
```

This pulls the latest commit (auto-stashing and restoring any uncommitted local changes in the repo, e.g. `theme.json` edits made through the GUI, around the pull so they aren't lost or blocked) and then re-deploys. The re-deploy is guarded by a small manifest at `~/.local/state/dxrice/manifest.json` that remembers the hash of every file it last wrote:

* If a live file in `~/.config/...` still matches what was last deployed, it's safely updated to the new version.
* If you've hand-edited that file since -- it's **left alone** and reported as skipped, never silently overwritten. The output tells you exactly which files were skipped so you can diff and merge by hand if you want the new version.
* The very first deploy of a pre-existing, unmanaged file (e.g. running the installer on a machine that already had a `~/.config/waybar/config` from something else) backs the old one up under `~/.local/state/dxrice/backups/` before taking it over.
* `hyprland.lua` is a special case: it's the most hand-edited file in the whole rice (keybinds, autostart, monitor setup), so it is **only ever copied in once**, on a completely fresh install where no live copy exists yet. After that, `update` never touches it -- new theme colors/blur values still reach it through `dxrice_apply_theme.py`'s narrow, line-by-line patch (see Theming below), but nothing else about it is ever auto-changed. If a rice update adds new default keybinds, check the repo's `hypr/hyprland.lua` by hand and copy over what you want.
* An older version of this rice used to copy scripts into `~/scripts`. If you're updating from one of those, `install.sh` automatically removes any leftover copy there that you never hand-edited (and removes the folder entirely once it's empty), since scripts now run straight out of the repo checkout instead.

---

## Infinite Desktop & Taskbar Management

The custom Infinite Desktop navigation engine and taskbar management are powered by Python scripts that run straight out of `<repo>/scripts/` (never copied into `$HOME`), using `python-evdev` and `hyprctl`.

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

Everything visual — colors, transparency, blur, corner radius, gaps, window border gradient, lock screen blur, fonts, and wallpaper — is controlled from one place: `<repo>/theme/theme.json` (`<repo>` being wherever you cloned this, as recorded by `install.sh`). Press `SUPER + Shift + T` to open a native GTK4/Adwaita settings app (`<repo>/scripts/dxrice_theme_gui.py`) instead of hand-editing CSS/config files across five different apps.

How it works:
* `theme/theme.json` is the single source of truth for every themeable value.
* `theme/*.template` files (waybar, wofi, mako, kitty, hyprlock) are plain configs with `${TOKEN}` placeholders.
* `<repo>/scripts/dxrice_apply_theme.py` renders those templates into the real `~/.config/...` files, patches the color/decoration block of `hyprland.lua` in place (regex, so your keybinds and autostart are untouched), and hot-reloads waybar, mako, kitty, and Hyprland — no session restart needed.
* The GUI is just a front-end over that same script: tweak a color/slider, hit **Apply**, everything reloads live.
* **Presets:** four built-in looks (Glass Charcoal, Nord, Dracula, Sunset) plus save/load your own from the Presets section at the top of the settings window.

To theme by hand instead of via the GUI, edit `theme/theme.json` directly and run:
```bash
python3 <repo>/scripts/dxrice_apply_theme.py
```

---

## Customization & Tweaks

### Taskbar & Window Management
* `dxrice_taskbar_gui.py` (`SUPER + Shift + A`) is a native GTK4/Adwaita settings window -- the same style as the theme GUI below -- for managing the waybar app shortcuts on the left side of the bar. Every change (add, remove, reorder, the icons toggle) applies and restarts waybar immediately, and is synced back into `<repo>/waybar/config` so it survives an `install.sh update`.
* **Add shortcut:** the `+` button opens a searchable list of every installed `.desktop` app (scanned from `/usr/share/applications` and `~/.local/share/applications`) -- click one to add it, with the real command pulled straight from the `.desktop` file. There's also a plain name + command field underneath for anything not in that list.
* **Show icons toggle:** an Options switch at the top of the window. On, every shortcut shows a real Nerd Font glyph (via `<repo>/scripts/dxrice_icons.py`, matched against the app's name/command), falling back to a generic glyph for anything unrecognized. Off, every shortcut shows its plain name as text instead -- flipping it re-derives every existing shortcut immediately, no need to re-add them.
* Reorder shortcuts with the up/down arrows on each row, or remove one with the trash icon. The app launcher shortcut itself is pinned and can't be reordered or removed.
* **Per-shortcut icon mode:** expand any shortcut's row for a dropdown -- Automatic (follows the global switch above), Text label (always plain text), or Custom image. Custom image renders as a real waybar `image#` picture module (waybar's text-based shortcuts can't show pictures), copied into `~/.config/waybar/icons/` so it survives the original file moving.
* **System Modules section:** edit left/right-click commands on the clock/volume/network/CPU/RAM modules directly.
* Taskbar window switching and reordering work dynamically across tiled and floating workspace layouts.

### Quick Settings Panel

Clicking the volume/wifi/CPU/RAM cluster on the right side of the bar (grouped into one pill) opens `dxrice_quick_settings.py` -- a control-center-style panel docked under the top-right corner via `gtk4-layer-shell` (an extra dependency `install.sh` installs) instead of a normal window. Clicking the cluster again closes it instead of opening a duplicate. Its look -- colors, opacity, corner radius -- comes from `theme/quick_settings_style.css.template`, the same theme.json tokens as everything else, so it stays in sync with whatever you set in the theme GUI.

Sections: media controls (play/pause/skip, only shown while something is actually playing, via `playerctl`), quick toggles for Wi-Fi/Bluetooth/Keep Awake/Do Not Disturb, output volume + mute + device picker, microphone volume + mute + device picker, screen brightness (only shown if a backlight actually exists), Wi-Fi network list (click to connect -- prompts for a password only for a network with no saved connection yet), Bluetooth paired device list (connect/disconnect), clipboard history (via `cliphist` -- click an entry to copy it), screenshot buttons (region or full screen, via `grim`/`slurp` -- saved to `~/Pictures/Screenshots/` and copied to the clipboard), live CPU/RAM/disk usage, and power actions (lock, logout, reboot, shutdown -- the last three ask for confirmation first). Do Not Disturb only appears if `mako` is actually running. Keep Awake holds a `systemd-inhibit` idle/sleep lock for as long as it's on.

Wi-Fi and Bluetooth device lists load in the background instead of blocking the panel from opening -- listing paired Bluetooth devices runs a separate `bluetoothctl` command per device, which adds up fast with several devices paired.

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
