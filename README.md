# DXrice

A Hyprland desktop environment built around a custom Quickshell shell (Dashboard, Media, Performance, Quick Settings, Taskbar, Calendar, a Theme/Nexus editor, and an optional Wayland-native lock screen), a wallpaper-driven color pipeline shared by every app in the stack, and matching SDDM login theme. Managed as one git checkout; your own colors, wallpaper, and shortcuts always live outside it.

---

## What DXrice is

DXrice is not a config file collection you drop into `~/.config` -- it's a small application layer on top of Hyprland:

- **A Quickshell shell** (`quickshell/`) providing the top bar, a bottom app dock, a Dashboard/Media/Performance panel, a Quick Settings-style control center, a Calendar, a Taskbar shortcut manager, a Theme editor ("Theme/Nexus"), and an optional real Wayland session lock screen -- all one persistent process, all sharing one design-token system.
- **A GTK4/libadwaita fallback** (`scripts/dxrice_*_gui.py`) for Theme, Taskbar, and Quick Settings, used automatically wherever Quickshell isn't installed. Same underlying config, same visual language, CSS transitions instead of Quickshell's GPU-composited ones.
- **A theming pipeline** (`scripts/dxrice_apply_theme.py` + `theme/*.template`) that renders one shared `theme.json` into waybar, wofi, mako, kitty, hyprlock, and the GTK apps' own stylesheet, and patches the relevant block of `hyprland.lua` in place.
- **A matching SDDM login theme** (`sddm/`), entirely opt-in, that pulls its colors/font/wallpaper from the same `theme.json`.
- **An installer/updater** (`install.sh`) that treats your own configuration as sacred: it initializes it once, never replaces it, and migrates it forward safely when this project adds new settings.

## Requirements

- **Hyprland** (Wayland compositor) -- everything else assumes it.
- **Arch Linux** or **openSUSE**: fully supported, `install.sh` installs Hyprland itself too.
- **Fedora**: everything except Hyprland is officially packaged; Hyprland needs a third-party COPR (`install.sh` offers to enable one, with a clear "this can go stale" warning).
- **Ubuntu/Debian**: everything except Hyprland is officially packaged; Hyprland has no reliable package on point-release Ubuntu/Debian and is skipped with an explanation (see [wiki.hypr.land](https://wiki.hypr.land/Getting-Started/Installation/) if you want to build it yourself).
- **Quickshell** is optional everywhere -- packaged on Arch, a COPR on Fedora, no clean path yet on Ubuntu/Debian/openSUSE. Every keybind and click that would open a Quickshell panel falls straight back to the GTK app if `qs` isn't found, so skipping it never breaks anything.
- **SDDM** is entirely optional -- DXrice never installs or enables a display manager. If SDDM is already present, `install.sh` offers to theme it; if it isn't, that step is skipped with an explanation.

Run `./install.sh` and it detects your package manager (pacman/dnf/apt/zypper) and installs what it can; see `install.sh`'s own `GENERAL_*`/`HYPR_PACKAGES` arrays for the exact list per distro if you'd rather review or install by hand first.

## Architecture overview

```
Hyprland (compositor, keybinds via hyprland.lua)
  |
  +-- Quickshell (qs -p quickshell/shell.qml), one persistent process
  |     +-- TopBar.qml   -- clock/calendar island, status/Quick-Settings island
  |     +-- Dock.qml     -- app shortcuts + Taskbar manager island
  |     +-- LockScreen.qml -- real ext-session-lock-v1 lock, opt-in (see below)
  |     +-- ThemeEditor.qml (LazyLoader) -- "Theme/Nexus"
  |     +-- PanelManager.qml -- single source of truth for which panel is open
  |     +-- Theme.qml / ShellSurface.qml / Xdg.qml -- shared tokens + paths
  |
  +-- GTK4/libadwaita fallback (scripts/dxrice_*_gui.py) -- used only where
  |     Quickshell isn't installed; same config, same theme.json
  |
  +-- waybar / wofi / mako / kitty / hyprlock -- themed via rendered templates
  |
  +-- SDDM (optional) -- sddm/ theme, synced from the same theme.json
```

Every one of those pieces reads the *same* live config; nothing keeps a private copy of your colors.

## Configuration, data, state, and cache

DXrice follows the [XDG Base Directory specification](https://specifications.freedesktop.org/basedir-spec/latest/). Every path below respects the corresponding `$XDG_*` environment variable if you've set it; the right-hand column is only the fallback used when you haven't.

| Purpose | Variable | Default | Contents |
|---|---|---|---|
| **Config** | `$XDG_CONFIG_HOME` | `~/.config` | `dxrice/theme.json` (the live, hand-edited-by-you theme), `dxrice/presets/` (GTK Theme app's saved custom presets), `dxrice/gtk_style.css` (rendered) |
| **Data** | `$XDG_DATA_HOME` | `~/.local/share` | `dxrice/backups/<timestamp>/` (config-migration and SDDM-sync backups) |
| **State** | `$XDG_STATE_HOME` | `~/.local/state` | `dxrice/repo_path` (where your checkout lives), `dxrice/manifest.json` (the deploy hash-guard, see below) |
| **Cache** | `$XDG_CACHE_HOME` | `~/.cache` | reserved for future disposable/generated data; nothing writes here yet |

**The repository itself (wherever you cloned it) is never one of these.** It contains the program -- Quickshell source, Python scripts, shipped default templates, the SDDM theme source, this documentation, and the installer. Your live configuration, saved presets, and backups live in the table above, entirely outside the checkout. Reinstalling, updating, or even deleting and re-cloning the repository never touches them.

Third-party app configs this deploys into (waybar, wofi, hyprlock, `hyprland.lua`) live in their own usual spots under `$XDG_CONFIG_HOME/<app>/`, same as any other Linux app.

### The safety guarantee

**Updating DXrice does not overwrite your saved themes or configuration.** Concretely:

- `~/.config/dxrice/theme.json` (or wherever `$XDG_CONFIG_HOME` points) is seeded from the repo's shipped default *once*, the first time nothing exists there yet. After that, no install/update ever writes over it wholesale -- only individual keys get added when a newer version of DXrice introduces a new setting (see "Config migration" below), and your existing values are never touched by that process.
- `hyprland.lua`, and every `waybar/config*`/`wofi/config` file, are copied in once on a fresh install and then left completely alone by every later `install.sh update` -- they're yours to hand-edit (keybinds, shortcuts) and a hash-guarded manifest (`$XDG_STATE_HOME/dxrice/manifest.json`) makes sure a later deploy can tell "still what I last wrote" from "you've since changed this," and only ever touches the former.
- Backups happen automatically, but only for an actual migration or SDDM sync -- never on a normal shell restart, never for a no-op update. See "Backups" below.
- Uninstalling never deletes your config/data/state unless you explicitly pass `--purge`, and even then it tells you exactly what it's about to delete before doing it.

If you want to back these up yourself at any point, the whole guarantee reduces to one thing: copy `$XDG_CONFIG_HOME/dxrice/`, `$XDG_DATA_HOME/dxrice/`, and `$XDG_STATE_HOME/dxrice/` (or just their fallback paths `~/.config/dxrice`, `~/.local/share/dxrice`, `~/.local/state/dxrice` if you haven't overridden the XDG variables) -- that's the entirety of what DXrice keeps outside the repo.

## Installation

```bash
git clone https://github.com/dexovision/dxrice.git ~/dxrice
cd ~/dxrice
chmod +x install.sh
./install.sh
```

Install the whole repository this way, not just `install.sh` on its own (e.g. from a raw-file download) -- it needs the sibling `scripts/` and `theme/` directories and refuses to run with a clear error if they're missing.

What it does: asks where you want the checkout to live (and moves it there if you pick somewhere else), detects your package manager and installs missing dependencies, offers to add you to the `input` group (needed for the infinite-desktop workspace navigation), deploys app configs and `hyprland.lua` (only ever once -- see the safety guarantee above), auto-detects your monitor into a fresh `hyprland.lua`, renders the theme so everything comes up styled immediately, then verifies every file the keybinds depend on actually exists. If SDDM is already installed, it asks once (default: no) whether to also set up the matching login theme.

**A crucial gotcha the installer warns you about explicitly:** Hyprland decides whether to load `hyprland.conf` or `hyprland.lua` only *once*, at startup. If Hyprland was already running before `hyprland.lua` existed, your keybinds won't work until you fully log out and back in (or reboot) -- `hyprctl reload` does not pick this up.

### Preview without changing anything

```bash
./install.sh install --dry-run
```

Reports exactly what a real install would do -- which packages are missing, whether your config would be initialized or preserved, whether a schema migration would run, which app config files would be created vs. left alone, and whether SDDM would even be touched -- without installing a package, writing a file, or prompting for a password.

## Updating

```bash
cd ~/dxrice   # or wherever you installed it
./install.sh update
```

or, from anywhere, `dxrice-update` / `dx update` (shell functions `install.sh` adds to your `.bashrc`/`.zshrc`).

This pulls the latest commit (auto-stashing and restoring any uncommitted edits *inside the repo checkout itself* -- your theme and shortcuts live outside it, so this almost never has anything of yours to protect) and re-deploys. Re-run with `--dry-run` first if you want to see what it would do before it does it:

```bash
./install.sh update --dry-run
```

### Config migration

Your live `theme.json` carries a `schema_version`. When a DXrice update introduces a new setting, the *next* time anything touches your config (opening the Theme app, running `dxrice_apply_theme.py`, or `install.sh update`), it:

1. Backs up your current `theme.json` to `$XDG_DATA_HOME/dxrice/backups/<timestamp>/` -- **only when a migration is actually about to change something**, never on a normal load with nothing to do.
2. Adds whatever new keys the current schema expects, using their shipped defaults.
3. Never overwrites, renames away, or deletes a key you already have a value for -- your existing settings are the ones migration exists to protect, not what it operates on.
4. Stamps the file with the new `schema_version` and prints what it added.

Running this twice in a row is a no-op the second time (nothing left to migrate, so nothing gets backed up or rewritten) -- see `scripts/dxrice_config_migrate.py` for the exact contract and version history.

## Uninstallation

```bash
./install.sh uninstall
```

Removes DXrice's own integration: the `dx`/`dxrice-update` shell functions, the recorded repo-path state file, and (only if you confirm) the SDDM login theme. It does **not** touch your saved theme/config/data, and does **not** touch the app config files it deployed (`hyprland.lua`, `waybar/config*`, `wofi/config`) -- by the time you're uninstalling, those are indistinguishable from your own hand-edits, so removing them automatically would be guessing at what you want gone. It tells you exactly where everything it left behind lives.

To also permanently delete your saved configuration, data, and state:

```bash
./install.sh uninstall --purge
```

This is never the default. It names the exact three directories it's about to delete and asks for explicit confirmation before doing it.

## SDDM integration (login screen)

Entirely opt-in -- DXrice never installs, enables, or switches your display manager. If SDDM is already installed, `sddm/` is a matching login theme: your current wallpaper (blurred once into a static image, so the greeter has zero GPU shader dependency), your accent color, your font, all pulled from the same `theme.json` everything else reads.

Set up or refresh it any time:

```bash
./install.sh sddm-theme
# or directly:
sudo python3 scripts/dxrice_sync_sddm_theme.py
```

This needs root (it writes to `/usr/share/sddm/themes/` and `/etc/sddm.conf.d/`, both outside any normal user's access) -- which is exactly why it's a separate, explicit, occasionally-run command rather than something the Theme app's Apply button (which must stay unprivileged) does automatically on every change.

**Safety model** -- a broken login theme means a locked-out desktop, not a cosmetic bug, so this is deliberately conservative:

- Everything is rendered into a throwaway staging copy first, never directly into the live theme directory.
- The staging copy is verified two independent ways before anything live is touched: a static check that `metadata.desktop` declares `QtVersion=6` (without it, SDDM falls back to a Qt5 greeter binary that isn't guaranteed to work), and a real render check via `Item.grabToImage()` under Qt's offscreen platform (so it works identically whether or not a display session is reachable, e.g. under `sudo`).
- If either check fails, your **previously installed theme and SDDM configuration are left completely untouched** -- nothing is swapped in, `/etc/sddm.conf.d` isn't written.
- Only once verification passes: your current SDDM theme directory and `/etc/sddm.conf.d`'s contents are backed up to `$XDG_DATA_HOME/dxrice/backups/sddm-<timestamp>/` (owned by you, not root, even though the script itself runs as root), *then* the verified copy is swapped into place.
- A wallpaper that can't be found or blurred this run never blanks out a background a previous successful run already installed -- it's carried forward instead.
- Re-running is always safe and idempotent.

To preview without logging out: `sddm-greeter-qt6 --test-mode --theme /usr/share/sddm/themes/dxrice`. **Treat a clean test-mode load as a smoke check, not final proof** -- it cannot fully substitute for a real logout (different socket/PAM/session handling than a live preview window). Confirm with an actual logout when you're prepared to reach a TTY (`Ctrl+Alt+F3`/`F4`) if something's wrong.

To revert to SDDM's own default theme: `sudo rm /etc/sddm.conf.d/dxrice.conf`.

## Lock screen (Quickshell, opt-in)

`quickshell/LockScreen.qml` is a real Wayland session lock (`ext-session-lock-v1`), not a themed overlay -- your blurred wallpaper, a live clock, scattered real info (device/uptime, world clock, media controls), and a password prompt authenticated against the same PAM stack `hyprlock` already uses (`/etc/pam.d/hyprlock`).

Not bound to `SUPER+L` by default -- that keybind stays on the already-proven `hyprlock`. Try it deliberately:

```bash
dx lock
```

A Wayland session lock is fail-secure by design: if the locking client crashes while locked, a conformant compositor keeps the screen locked rather than exposing your session. If it ever won't accept a correct password, switch to another TTY, log in there, and restart the graphical session (`loginctl terminate-session`) -- the same recovery path as any Wayland lock client, hyprlock included.

## Wallpaper handling

Default location: `~/Pictures/Wallpapers/default.png`, set via `theme.json`'s `wallpaper` key (editable from the Theme app's Wallpaper category, which also shows a live preview). Static wallpapers are applied via `swaybg`; changing it and hitting Apply reloads it immediately.

The Theme app's Wallpaper category also has a "Generate colors from wallpaper" action (`scripts/dxrice_wallpaper_theme.py`) that samples the image for a background tone and accent color and writes them into your live `theme.json` -- review the result in the Colors category and Apply to keep it, or Revert to discard.

## The shell, panel by panel

- **Dashboard** -- connectivity (Wi-Fi/Bluetooth/DND/Keep Awake) toggles, a live clock, audio output/input control, a network list, and a world clock, opened from the status cluster in the top bar.
- **Media** -- native MPRIS playback controls (no polling), shown as one of Quick Settings' tabs; a framed empty state when nothing's playing rather than a bare icon.
- **Performance** -- live CPU/GPU/Memory/Storage/Network, plus clipboard history and quick actions (screenshot region/full-screen), another Quick Settings tab. GPU reads AMD sysfs or falls back to a one-shot `nvidia-smi` check; genuinely unavailable rather than fabricated on hardware neither supports.
- **Quick Settings** -- the parent surface hosting Dashboard/Media/Performance, opened by clicking the status cluster on the top bar's right side.
- **Taskbar** -- `SUPER+SHIFT+A` (or the dock's gear icon) opens the shortcut manager for the bottom dock: add any installed `.desktop` app, reorder by drag or arrow buttons, per-shortcut icon mode (auto/text/custom image), and edit the clock/volume/network/CPU module click actions.
- **Calendar** -- click the clock island in the top bar for month navigation with no backend/timers, pure view-state.
- **Theme / Nexus** (`SUPER+SHIFT+T`) -- the settings app, with seven categories: **Colors** (presets plus a live shell-material preview), **Transparency & Blur** (idle/active material comparison), **Layout** (corner-radius/gap previews plus grouped sliders), **Lock Screen** (a real miniature lock-screen preview reacting to every slider), **Fonts** (a live type specimen across heading/body/stat/UI roles), **Experience** (small live demos for animation speed/spacing density/shadow strength), and **Wallpaper** (a cinematic preview plus the generate-from-wallpaper action). Colors/wallpaper/font changes here are exactly what feeds the SDDM login theme when you next run `sddm-theme` -- one config, every surface.

Two front-ends exist for Theme, Taskbar, and Quick Settings: the Quickshell versions above (GPU-composited, native PipeWire/MPRIS bindings), and a GTK4/libadwaita fallback (`scripts/dxrice_*_gui.py`) used automatically wherever Quickshell isn't installed -- same `theme.json`, same feature set, CSS transitions instead of Quickshell's. One asymmetry worth knowing: the GTK Theme app supports saving/loading named custom presets (`$XDG_CONFIG_HOME/dxrice/presets/`) and has a "Sync Now" SDDM button (via `pkexec`); the Quickshell Theme/Nexus editor doesn't yet have either.

Essential keybinds (see `hypr/hyprland.lua` for the full set):

| Keybind | Action |
|---|---|
| `SUPER + Q` | Terminal (kitty) |
| `SUPER + R` | App launcher (wofi) |
| `SUPER + E` | File manager (Nautilus) |
| `SUPER + Shift + T` | Theme / Nexus |
| `SUPER + Shift + A` | Taskbar manager |
| `SUPER + D` | Floating/tiling toggle |
| `SUPER + Shift + S` | Region screenshot |
| `SUPER + L` | Lock (hyprlock) |

## Performance philosophy

Event-driven and lazy wherever possible: a panel's backends and timers are torn down within ~500ms of it closing and rebuilt fresh on next open (see `ShellIsland.qml`), never left ticking in the background. The two things that genuinely run all the time (a 1.5s active-window poll and a 1s clock tick, both in the always-visible top bar) are deliberately cheap and already measured as such. CPU/memory/disk/GPU/network sampling is scoped specifically to the Performance tab being the one currently selected, not just "the panel happens to be open" -- switching to Media or Dashboard stops it. No graph or visualizer continues rendering while its own tab isn't visible.

## Troubleshooting

- **Keybinds don't work after a fresh install** -- see the "crucial gotcha" under Installation: log out and back in once.
- **A theme change didn't apply** -- run `python3 scripts/dxrice_apply_theme.py` directly and read its output; it prints which files it skipped (and why) if any were hand-edited since the last deploy.
- **The login screen looks wrong / won't accept input** -- switch to a TTY (`Ctrl+Alt+F3` or `F4`), log in there, and run `sudo rm -f /etc/sddm.conf.d/dxrice.conf && sudo systemctl restart sddm` to fall back to SDDM's own default theme instantly. Then re-run `./install.sh sddm-theme` when you're ready to debug it properly -- it will refuse to switch the active theme again until it verifies cleanly.
- **Duplicate bars, or waybar and Quickshell both visible** -- `pkill -x waybar` once; `hyprland.lua`'s autostart only launches waybar when Quickshell isn't installed, so this should self-correct on the next graphical login.
- **Something in `~/.config` looks stale after an update** -- check the "Left alone (you edited this...)" section of `install.sh update`'s own output; that's the manifest telling you exactly what it declined to touch.

## Rollback and backups

Every backup DXrice creates lives at `$XDG_DATA_HOME/dxrice/backups/`, timestamped, and is *only* created before an actual config-schema migration or SDDM sync -- never on a normal restart or no-op update. The 10 most recent SDDM-sync backups are kept (older ones pruned automatically); config-migration backups are kept indefinitely since they're expected to be rare (one per schema bump you ever cross).

To roll back a config migration: copy the relevant `theme.json` back from its backup folder. To roll back an SDDM sync: `sudo rm /etc/sddm.conf.d/dxrice.conf` (or restore the backed-up theme directory from the same timestamped folder). Neither requires reinstalling anything.

## Development

Everything runs straight out of the checkout -- no build step, no install-to-`$HOME` for scripts. To iterate on the Quickshell shell:

```bash
qs -p quickshell/shell.qml -d -n     # run it directly, logs to stdout
qs -p quickshell/shell.qml ipc show  # list every registered IPC target
qs -p quickshell/shell.qml ipc call theme toggle
```

To iterate on the theming pipeline: edit `theme/*.template` or `scripts/dxrice_apply_theme.py`, then `python3 scripts/dxrice_apply_theme.py` to re-render and hot-reload everything. `theme/theme.json` is the shipped *default* (read to seed a fresh install, never written to after that) -- edit your live config at `$XDG_CONFIG_HOME/dxrice/theme.json` instead when testing values, exactly as the Theme app does.

Sanity checks used throughout this project rather than assumed: after any Quickshell change, confirm exactly one `qs` process, zero `waybar` processes (when Quickshell owns the bar), and zero QML errors in `$XDG_RUNTIME_DIR/quickshell/by-id/*/log.qslog`. Screenshot-based QA of QML uses `Item.grabToImage()` from inside the QML itself, never a screen/compositor-level capture.

### Contributing

Keep the separation this whole document describes: shipped defaults and templates go in the repo; nothing that represents a real user's personal choice (colors, wallpaper path, shortcuts) does. If you add a new `theme.json` key, add it to `theme/theme.json` (the shipped default) and bump `dxrice_config_migrate.CURRENT_SCHEMA_VERSION` with a new migration step -- don't assume every existing install already has it.

## Credits

- [sarodscommits/hyprland-infinitie-desktop-v2](https://github.com/sarodscommits/hyprland-infinitie-desktop-v2) -- the original infinite-canvas navigation scripts.
- @gentoolarp on TikTok -- reference for customization and looks.
