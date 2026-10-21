# DXrice

DXrice is a Hyprland desktop: a Quickshell bar, dock and control panels, an
"infinite desktop" where floating windows arrange themselves in a spiral
(the Galaxy Spiral), a zoomed-out overview of every window, and one
`theme.json` that colours everything from the bar to kitty, mako and the
SDDM login screen.

It lives in one git checkout. Your theme, wallpaper and shortcuts live
outside it, in the usual XDG directories, so updating or re-cloning DXrice
never touches them.

## What you get

- **Bar, dock and panels** (Quickshell, `quickshell/`): workspaces and the
  focused window, a clock and calendar, a status area that opens Quick
  Settings (Wi-Fi, Bluetooth, Do Not Disturb, Keep Awake, audio, media
  controls, CPU/GPU/memory/disk/network, clipboard history), a dock with a
  shortcut manager, and a theme editor. One process, started with your
  session.
- **Window arrangement.** Three methods, one choice in Settings > Experience
  that decides both where a new window goes and what `SUPER+G` does:
  **Galaxy Spiral** (the default) keeps every window's size and grows an
  airy spiral outward across the infinite desktop; **Compact** packs the
  windows into a tight, balanced cluster and resizes them a little where
  that helps (never into a grid); **Expansion** keeps sizes and bursts the
  windows outward from the centre, each in its own direction, and new ones
  go to the most open side. Opening a window never moves the others.
  Pinned, fullscreen and hidden windows are never touched, and a dialog
  goes beside the window it belongs to. The overview (`SUPER+Tab`) has the
  same three as chips; picking one there changes the choice too. (theme.json
  `"window_layout"`; files from an earlier build with separate
  `layout_auto_place` / `layout_super_g` keep working, the first of those
  winning, until the next Apply replaces them.)
- **Desktop widgets.** Each one looks like what it is, under your windows:
  a clock in bare heavy type (or tty-clock style blocks), a now-playing card
  built around the album cover with a seekable bar, a terminal-style system
  readout (CPU, GPU, memory, disk, network, battery, temperatures and
  uptime from `/proc` and sysfs, with the last minute drawn in block
  characters), and the weather for a place you type in Settings (from
  Open-Meteo; nothing is shown until you set one). Switch each on or off and
  move it to another corner in Settings > Experience. Anything the machine
  can't measure is left out or says n/a, never shown as zero.
- **Audio visualizer.** A real spectrum of what's playing, from `cava`, along
  the bottom of the desktop. It only runs while music plays, as bars or as
  block characters.
- **Wallpaper browser.** Settings > Wallpaper shows thumbnails of the pictures
  in `~/Pictures/Wallpapers` (and the folder of the wallpaper in use); click
  one and Apply.
- **An infinite desktop.** `SUPER+ALT` and moving the mouse pans every
  window together. Dragging a window (`SUPER` + left mouse) into the screen
  edge pushes the others along.
- **Overview.** `SUPER+Tab` zooms the workspace out until every window fits,
  including the parts of the spiral past the screen edges. Click a window
  to focus it. Details: [docs/OVERVIEW.md](docs/OVERVIEW.md).
- **One theme for everything.** `scripts/dxrice_apply_theme.py` renders
  `theme.json` into waybar, wofi, mako, kitty, hyprlock and the GTK apps'
  stylesheet. It can also derive the colours from your wallpaper.
- **Fallbacks.** Without Quickshell you get waybar and GTK4 versions of the
  Theme, Taskbar and Quick Settings apps, driven by the same config.
- **Optional extras:** a matching SDDM theme and a Quickshell lock screen.
  Both are opt-in.

## Requirements

DXrice needs **Hyprland 0.55 or newer**, the first release that reads
`hyprland.lua`. An older Hyprland ignores the config completely, and the
installer warns about it.

| | Arch | Gentoo | Fedora | openSUSE | Debian/Ubuntu |
|---|---|---|---|---|---|
| Hyprland ≥ 0.55 | official repos | hyproverlay overlay | third-party COPR | Tumbleweed repos² | not packaged (build it) |
| Quickshell | official repos | GURU overlay | third-party COPR | not packaged | not packaged |
| Everything else | official repos | main tree¹ | official repos¹ | official repos¹ | official repos¹ |
| Installer installs packages | yes, after asking | yes, `emerge --ask`, after asking | yes, after asking | yes, after asking | yes, after asking |
| Init system | systemd | OpenRC or systemd | systemd | systemd | systemd |

¹ cliphist (clipboard history) and nwg-look aren't packaged there. The
installer tells you where to get them, and DXrice works without them.
² Tumbleweed packages Hyprland, but whether it has reached 0.55 wasn't
checked; the installer warns if the installed version is too old.

Each package manager's exact list is in [`deps/`](deps/). The installer
reads those files and names no packages itself.

**What actually depends on what:**

- **Hyprland:** required. Everything is built on its IPC and config.
- **Quickshell:** optional but recommended. Without it you get waybar plus
  the GTK apps, and no overview.
- **Python 3 with python-evdev:** placement, SUPER+G, window movement keys,
  and the infinite desktop. The panning daemon reads input devices
  directly, so your user must be in the `input` group (the installer
  offers to add you).
- **PyGObject, GTK4, libadwaita, gtk4-layer-shell:** only the GTK fallback
  apps.
- **systemd:** not required. With a systemd user session, the bar and the two
  daemons run as user units that restart after a crash. Without one (for
  example OpenRC), `scripts/dxrice_session.sh` supervises them the same way.
  Reboot, power-off and Keep Awake use systemd's tools or elogind's,
  whichever is there.
- **SDDM:** only for the login theme. DXrice never installs or enables a
  display manager.

## Installing

```bash
git clone https://github.com/dexovision/dxrice.git ~/dxrice
cd ~/dxrice
./install.sh install --dry-run   # optional: see what it would do, change nothing
./install.sh
```

Clone the whole repository. The installer needs the `scripts/` and `theme/`
directories next to it. Keep the checkout at a path made of plain characters
(letters, digits, `. _ - / + @`): `hyprland.lua` runs scripts by that path
without quoting it, so the installer refuses one with spaces.

The installer:

1. Asks where the checkout should live, and moves it if you pick somewhere
   else.
2. Detects your distro, package manager and init system. It lists missing
   packages and installs them only after you say yes.
3. Offers to add you to the `input` group.
4. Copies `hyprland.lua`, the waybar and wofi configs, and the rest into
   `~/.config`. A file that already exists is never replaced.
5. Renders the theme and, on a fresh `hyprland.lua`, writes your monitor
   into it.
6. Sets up the systemd user units, when there is a systemd user manager.
7. Checks that every file the keybinds need is in place.

Anything that needs `sudo`, or that changes or moves files you already
have, is asked first. If no terminal is attached (for example in a
script), those questions are answered **no** unless you pass `--yes`.

> Hyprland decides between `hyprland.conf` and `hyprland.lua` when it starts.
> If it was already running when `hyprland.lua` was first created, log out and
> back in; `hyprctl reload` isn't enough.

### Gentoo

Hyprland 0.55+ and Quickshell come from overlays, and most of their
ebuilds are keyworded `~amd64`.

```bash
# 1. the overlays
sudo emerge --ask app-eselect/eselect-repository
sudo eselect repository enable hyproverlay guru
sudo emaint sync -r hyproverlay
sudo emaint sync -r guru

# 2. Hyprland and Quickshell; --autounmask proposes the keyword changes,
#    review them, then apply them with dispatch-conf and run it again
sudo emerge --ask --autounmask=y gui-wm/hyprland gui-apps/quickshell

# 3. DXrice: installs the rest (deps/emerge.list) with emerge --ask, after asking
git clone https://github.com/dexovision/dxrice.git ~/dxrice
cd ~/dxrice && ./install.sh
```

USE flags that matter:

| Package | Flags | Why |
|---|---|---|
| `gui-libs/gtk4-layer-shell` | `introspection` | the GTK fallback apps load it through PyGObject |
| `media-video/pipewire` | `sound-server` | PipeWire as the audio server (the shell talks to PipeWire, volume keys use `wpctl`) |
| `gui-apps/waybar` | `network pulseaudio tray` | only for the waybar fallback; its shipped configs use those modules |

**On OpenRC** you need `sys-auth/elogind`. Gentoo's desktop profiles pull it
in, and it provides `XDG_RUNTIME_DIR`, seat access, `loginctl` and
`elogind-inhibit`. There are no systemd user units: Hyprland's autostart
runs `scripts/dxrice_session.sh`, which starts and supervises the bar and
both daemons. Its logs are in
`$XDG_RUNTIME_DIR/dxrice/<hyprland instance>/`.
`scripts/dxrice_session.sh status` shows what's running. Start Hyprland
from a TTY or from your display manager, as usual.

The atoms in `deps/emerge.list` were checked against packages.gentoo.org
on 2026-10-16. If one has moved, `eix <name>` finds its new home; the fix
is a one-line change in that file.

## Keybindings

| Keys | Action |
|---|---|
| `SUPER + Q` | terminal (`$TERMINAL`, else kitty) |
| `SUPER + R` | application launcher (type to search, arrows to move, Enter to launch) |
| `SUPER + E` | file manager (Nautilus) |
| `SUPER + SHIFT + E` | yazi in kitty |
| `SUPER + W` | Firefox |
| `SUPER + SHIFT + D` | Discord (native Wayland, so screen sharing works) |
| `SUPER + C` | close the window (in the overview: the one under the mouse); an app that only hides to the tray is force-quit |
| `SUPER + SHIFT + K` | `hyprctl kill` (click a window to kill it) |
| `SUPER + V` | toggle floating for the window |
| `SUPER + D` | toggle the whole workspace between floating and tiled |
| `SUPER + G` | arrange the workspace with the chosen method (Galaxy Spiral, Compact or Expansion) |
| `SUPER + Tab` | overview: zoom out / back in |
| `SUPER + F` / `SUPER + M` | fullscreen / maximize |
| `SUPER + P` / `SUPER + J` | pseudo-tile / toggle split (tiled layout) |
| `SUPER + arrows` | focus the nearest window in that direction |
| `SUPER + SHIFT + arrows` | move the window |
| `SUPER + CTRL + arrows` | resize the window |
| `SUPER + ALT` + mouse | pan the whole desktop |
| `SUPER` + left / right drag | move / resize a window |
| `SUPER + 1`…`0`, `SUPER + SHIFT + 1`…`0` | go to / send to workspace |
| `SUPER + Z` / `SUPER + X` | previous / next workspace (also `SUPER` + scroll) |
| `SUPER + SHIFT + Z` / `SUPER + SHIFT + X` | send window to previous / next workspace |
| `SUPER + SHIFT + T` | theme editor |
| `SUPER + SHIFT + A` | taskbar (dock) manager |
| `SUPER + SHIFT + V` | clipboard history |
| `SUPER + SHIFT + S`, `PRINT` | screenshot a region (saved to `~/Pictures/Screenshots`, copied) |
| `SUPER + PRINT` | screenshot the whole screen |
| `SUPER + L` | lock (hyprlock) |
| `SUPER + SHIFT + M` / `SUPER + SHIFT + B` / `SUPER + N` | volume mixer / Bluetooth / network connections |
| `SUPER + I` / `SUPER + U` | GTK / Qt appearance (nwg-look / qt6ct) |
| `SUPER + SHIFT + C` | cava in kitty |
| `SUPER + SHIFT + R` | reload Hyprland's config |
| media and brightness keys | volume, mute, brightness |

All of them are in `~/.config/hypr/hyprland.lua`, which is yours to edit.
Hyprland reloads it when you save.

The installer also adds a `dx` command to your `.bashrc`/`.zshrc`:
`dx update`, `dx theme`, `dx taskbar`, `dx settings`, `dx overview`,
`dx lock` (try the Quickshell lock screen) and `dx sddm-theme`.

## Updating

```bash
dx update          # or: ~/dxrice/install.sh update
```

The update:

1. Fetches, and lists the commits it would bring in.
2. Asks before applying them.
3. Fast-forwards and redeploys.

It refuses, and changes nothing, in two cases:

- **You have commits of your own on the branch.** It suggests
  `git pull --rebase`.
- **You've edited files in the checkout that the update also changes.**
  It names them and shows how to set your edits aside.

Edits to other files stay exactly as they are. It never resets, stashes
or discards anything. If the network is down, nothing changes. At the
end it prints the old and new commit and the command to go back. Every
update is also recorded in `~/.local/state/dxrice/update-history`.

Nothing is restarted for you. The running bar and daemons switch to the
new code at your next login.

Your `hyprland.lua` is never replaced. When DXrice fixes something in the
template, the update lists the exact edits it would make to your copy and
asks first. Each edit only replaces text an earlier DXrice template
shipped, so a line you've changed is left alone. Before writing, it
backs the file up to `~/.local/state/dxrice/backups/`.

## Uninstalling

```bash
./install.sh uninstall            # remove DXrice's services, shell functions, SDDM theme (asks)
./install.sh uninstall --purge    # also delete your DXrice config, data and state (asks, names each)
```

`uninstall` keeps your theme, presets and backups, and every config file
in `~/.config` (`hyprland.lua`, waybar, wofi). Delete those yourself if you
want them gone. Hyprland's autostart line stays too, but does nothing
once DXrice is uninstalled.

## Where things live

All paths follow your `XDG_*` variables when set.

| Path | What |
|---|---|
| `~/.config/dxrice/theme.json` | your theme: colours, fonts, wallpaper, spacing, animation speed |
| `~/.config/dxrice/presets/` | saved theme presets |
| `~/.config/hypr/hyprland.lua`, `~/.config/waybar/`, `~/.config/wofi/` | copied once at install, then yours |
| `~/.local/share/dxrice/backups/` | backups made before a theme migration or an SDDM sync |
| `~/.local/state/dxrice/` | checkout location (`repo_path`), deploy manifest, `hyprland.lua` backups, update history |
| `$XDG_RUNTIME_DIR/dxrice/` | pid files; without systemd, the session supervisor's logs in `<hyprland instance>/` |

`theme.json` is seeded from `theme/theme.json` once. After that, an update
only adds settings that didn't exist yet, after backing the file up. It
never changes a value you've set. Rendered files you've edited by hand
(waybar's stylesheet, say) are recognised from the deploy manifest and
left alone.

If you keep these files in a dotfiles repository and symlink them into
`~/.config` (stow, a bare repo), DXrice writes through the links: the file in
your dotfiles tree is updated and the link stays a link. The same goes for
`~/.bashrc` and `~/.zshrc`.

## Troubleshooting

- **No keybinds after installing.** Log out and back in (see the note
  under Installing). Run `Hyprland --version`; it needs 0.55 or newer.
  `./install.sh update` warns if the checkout's path has spaces in it,
  which breaks every keybind; move it (e.g. to `~/dxrice`).
- **No bar.** Check `scripts/dxrice_session.sh status`. Under systemd, also
  run `journalctl --user -u dxrice-quickshell`; without systemd, see
  `$XDG_RUNTIME_DIR/dxrice/<hyprland instance>/quickshell.log`. After 5
  crashes in 30 s a part stops being restarted until the next login.
- **Windows show twice while the overview zooms.** Your `hyprland.lua`
  predates the fix. Run `./install.sh update` and accept the
  "stop Hyprland fading the SUPER+Tab overview" edit, or add this line
  yourself, after the other `hl.layer_rule` lines:
  `hl.layer_rule({ name = "overview-no-anim", match = { namespace = "^dxrice-overview$" }, no_anim = true })`.
- **A new window landed in a strange place.** Every placement is logged
  (class, size, where it was, where it went; no window titles):
  `journalctl --user -u dxrice-auto-place-window`. Without systemd the log is
  in `$XDG_RUNTIME_DIR/dxrice/<hyprland instance>/auto-place-window.log`.
- **Panning doesn't work.** You need to be in the `input` group
  (`id -nG`), and that only takes effect after logging in again.
- **A theme change didn't apply.** Run `python3 scripts/dxrice_apply_theme.py`.
  It lists any file it skipped because you'd edited it.
- **Waybar and the Quickshell bar both visible.** Run `pkill -x waybar`.
  Waybar only starts when Quickshell isn't installed.
- **An install or update stopped half-way.** Every file write is atomic,
  so run the same command again. `--dry-run` shows what's left to do.
- **The login screen is broken.** Switch to a TTY (`Ctrl+Alt+F3`), log in,
  and run `sudo rm -f /etc/sddm.conf.d/dxrice.conf`, then restart SDDM
  (`sudo systemctl restart sddm`, or `sudo rc-service display-manager
  restart` on OpenRC). SDDM is back on its own theme.
- **Undo a `hyprland.lua` migration.** Copy the backup the installer named
  from `~/.local/state/dxrice/backups/` over `~/.config/hypr/hyprland.lua`.

## SDDM login theme

```bash
./install.sh sddm-theme
```

This renders `sddm/` with your wallpaper (blurred once into a static image),
accent colour and font into `/usr/share/sddm/themes/dxrice`, and points
`/etc/sddm.conf.d/dxrice.conf` at it. It needs `sudo`. It checks the
rendered theme in a staging copy first, both statically and with an
offscreen render. Only if both checks pass does it back up your current
SDDM theme and config to `~/.local/share/dxrice/backups/` and swap the new
one in. If anything fails, your current login screen is left untouched.

You can preview it with `sddm-greeter-qt6 --test-mode --theme
/usr/share/sddm/themes/dxrice`. To go back to SDDM's own theme, run
`sudo rm /etc/sddm.conf.d/dxrice.conf`.

## Lock screen

`SUPER+L` runs hyprlock. DXrice also has a Quickshell lock screen
(`quickshell/LockScreen.qml`), a real `ext-session-lock-v1` lock that
authenticates through `/etc/pam.d/hyprlock`. Try it with `dx lock`. If it
ever won't take your password, switch to a TTY and end the session with
`loginctl terminate-session <id>`, as with any Wayland locker.

## Development

Everything runs from the checkout; there's no build step.

```bash
qs -p quickshell/shell.qml -d -n              # run the shell in the foreground
qs -p quickshell/shell.qml ipc call theme toggle
python3 scripts/dxrice_apply_theme.py         # re-render the theme
python3 scripts/dxrice_idle_probe.py 60       # idle CPU, wakeups, memory, spawned processes
```

**Tests.** None of them need Hyprland or a display. The QML suites run the
real shell offscreen against stubs (`pip install PySide6-Essentials`).
The shell suites run the real installer in a sandbox, with fakes for
`sudo`, the package managers and `systemctl`; run them as a normal user.

```bash
for t in scripts/dxrice_test_*.py; do python3 "$t"; done
for t in scripts/dxrice_test_*.sh; do bash "$t"; done
for t in tests/qml/test_*.py; do python3 "$t"; done
```

**Adding a setting.** If you add a `theme.json` key, also add it to
`theme/theme.json` and add a migration step in
`scripts/dxrice_config_migrate.py`, bumping `CURRENT_SCHEMA_VERSION`.

**Changing `hyprland.lua`.** Template changes never reach existing
installs on their own. If an existing install needs the change, add an
exact-text migration to `scripts/dxrice_hypr_migrate.py`.

[docs/AUDIT.md](docs/AUDIT.md) records the October 2026 engineering audit:
what was found, what changed, and what was measured.

## Credits

- [sarodscommits/hyprland-infinitie-desktop-v2](https://github.com/sarodscommits/hyprland-infinitie-desktop-v2):
  the original infinite-canvas navigation scripts.
- @gentoolarp on TikTok: reference for customization and looks.
