# DXrice engineering audit (2026-10-16)

Baseline: `main` = `4688761`. This file records what was found before any
change was made, and is updated at the end with what was done. Every claim
below says how it was established. "Measured" means a number came from a run
in this audit; "read" means it comes from reading the code.

## How the pieces fit

```
Hyprland (hyprland.lua, copy-once into ~/.config/hypr)
  ├─ autostart ─ systemctl --user restart dxrice-quickshell.service ─ qs -p quickshell/shell.qml
  │             systemctl --user restart dxrice-auto-place-window.service ─ scripts/dxrice_auto_place_window.py
  │             systemctl --user restart dxrice-infinite-desktop.service ─ scripts/dxrice_infinite_desktop_core.py
  │             swaybg, mako, nm-applet, blueman-applet, polkit agent, 2× wl-paste --watch cliphist
  └─ keybinds ─ python3 scripts/*.py per press (SUPER+G arrange, arrows, C close, D float/tile)
                qs ipc call <panel> toggle (SUPER+Tab overview, SUPER+SHIFT+A/T)

Quickshell process (one): TopBar + Dock + panels (lazy) + Overview (lazy) + OSD + LockScreen (opt-in)
auto-place daemon: event-driven on Hyprland's .socket2.sock (openwindow>>)
infinite-desktop daemon: evdev readers (input group) + two polling loops + device rescans
install.sh: deps → input group → copy-once deploy + hash-guarded renders → systemd user units
```

## Test baseline (measured, this container, before changes)

| Suite | Result | Note |
|---|---|---|
| 15 `scripts/dxrice_test_*.py` | 13 pass, 2 fail | both environmental, see below |
| 14 `tests/qml/test_*.py` (PySide6 offscreen) | 14 pass | after installing PySide6 + libEGL in the container |
| `dxrice_test_installer_lifecycle.sh`, `_launch.sh`, `_polkit_agent.sh` | pass | |
| `dxrice_test_install_cycle.sh` | fails as root (refuses root, by design); as a normal user fails 1 assertion | see C3 |
| `dxrice_test_legacy_rice_checkout.sh` | fails as root (`USER` unset); passes as a normal user | test fragility |
| `dxrice_test_launch_systemd.sh` | skips (no systemd user manager here) | |
| `bash -n`, `luac -p hypr/hyprland.lua`, `py_compile` | clean | |
| `shellcheck -S warning` | 6 warnings, all cosmetic (SC2088/SC2155) | |
| `ruff check` (default + extra rules) | 13 unused imports, 8 unused variables, rest stylistic | |

The two failing Python tests: `test_another_users_process_is_refused` fakes
"another user" as uid 0, which is the current user when tests run as root;
`dxrice_test_taskbar_shell_wrap.py` crashes on import when PyGObject is
broken instead of skipping.

## Findings, prioritized

### Critical (user-visible breakage)

- **C1. The overview ghosting fix never reaches installed desktops.** The
  double image during SUPER+Tab is Hyprland's `fadeLayersIn/Out` animation
  applied to the whole overlay surface (docs/OVERVIEW.md, established with a
  screen recording). The fix is two `hl.animation` lines in the *template*
  `hyprland.lua`, but the deployed copy is copy-once and nothing writes them
  into it; the drift checker only prints a notice. Any existing install keeps
  ghosting until the user edits the file by hand. (read)
- **C2. Without a systemd user manager the shell never starts.** The
  autostart lines call `systemctl --user restart dxrice-*.service`
  unconditionally. On OpenRC (Gentoo's default) there is no user manager, so
  Quickshell and both daemons never start, and the waybar fallback does not
  run either because `qs` exists: no bar at all. (read)
- **C3. Installer reports false test failures.** Placement tests log to the
  fixed path `/tmp/dxrice-verify-tests.log`; once that file belongs to another
  user, every install prints "Window placement/arrangement tests FAILED".
  Reproduced here as a second user. A fixed, predictable `/tmp` path is also a
  symlink hazard. (measured)
- **C4. A failed Nerd Font download aborts the whole install.** `curl -f`
  runs unguarded under `set -e`, so the "Download failed" branch can never
  run; a network error kills the installer mid-way. (read)

### Correctness

- **K1. `XDG_STATE_HOME` is ignored at runtime.** install.sh writes
  `repo_path` under `$XDG_STATE_HOME/dxrice`, but `hyprland.lua` and the `dx`
  shell functions read the hard-coded `~/.local/state/dxrice/repo_path`.
  With a custom `XDG_STATE_HOME`, every keybind falls back to `~/dxrice`. (read)
- **K2. Moving the checkout drops flags.** `choose_install_location` re-execs
  with only `$MODE`. (read)
- **K3. Power buttons assume systemd.** Reboot/power-off call `systemctl`;
  `loginctl` works with both systemd-logind and elogind. (read)
- **K4. `do_update` and `do_uninstall` don't refuse root** (install does).
  (read)
- **K5. swaybg wallpaper path is unquoted** in the autostart (`swaybg -i
  path`), so a path with spaces breaks. (read)

### Performance / idle cost

- **P1. Infinite-desktop daemon busy-polls while idle.** Two threads wake
  every 16.7 ms forever (`IDLE_POLL_INTERVAL = 1/60`): about 120 wakeups/s with
  no input. The device manager opens and queries *every* `/dev/input` device
  every 3 s. (read; to be measured)
- **P2. The top bar spawns `hyprctl` every 1.5 s forever** (2,400
  processes/hour) to learn the focused window. Quickshell already holds
  Hyprland's event socket (`Hyprland.rawEvent`), which delivers
  `activewindow>>class,title` on every focus change. (read)
- **P3. A Python process per focus change** (`dxrice_icons.py`) to pick the
  bar's app glyph. Lower priority: event-driven, not idle. (read)
- **P4. The clock timer fires every second** to display `HH:mm`. Small. (read)

### Maintainability

- **M1. Dead files shipped in the runtime shell directory:**
  `quickshell/_dev_MaterialHarness.qml`, `_dev_QuickSettingsSnapshot.qml`
  (never loaded). (read)
- **M2. Duplicated inline Python in install.sh:** four copies of the same
  atomic-write block and two copies of the rc-file stripper. (read)
- **M3. Unused imports/variables** reported by ruff (13 + 8). (measured)
- **M4. Comment narration.** Many comments retell incident history ("confirmed
  live", "this exact bug shipped once") rather than explaining the code. Trim
  where it is pure narration; keep the why. Not a rewrite.

### Portability (Gentoo first)

- **G1. No Gentoo path.** Package detection knows pacman/dnf/apt/zypper
  only; on Gentoo the installer can only skip dependencies. Needs an `emerge`
  backend, correct atoms, and a GURU note for Hyprland/Quickshell
  availability. Packages must never be installed without consent.
- **G2. Service supervision is systemd-only** (C2). Needs a fallback that
  supervises the same three processes without systemd.
- **G3. Distribution package lists live inline in install.sh.** Split them
  into one data file per distro family so core logic doesn't change when a
  package name does.

### Installer / updater reliability

- **U1. `update` pulls without showing what it will pull.** It should fetch,
  show the incoming commits and any conflict with local edits, ask, then
  fast-forward. It should never reset.
- **U2. No version report.** There's no before/after commit, and nothing
  says the running shell/daemons need a restart to pick up new code (no
  restart is done, which is correct).
- **U3. Network failure handling** is limited to `git pull` failing; a fetch
  failure should leave the stash and checkout untouched with clear recovery
  steps.

### Polish / docs

- **D1. README** is long and repeats the safety guarantee in several places;
  no Gentoo section, no compatibility matrix, no troubleshooting index.
- **D2. Keybinding table** must be regenerated from `hyprland.lua` rather
  than maintained by hand.

### Git history and attribution (read, via git and the GitHub API)

- All 228 commits on `main` are authored and committed as
  `dexo <dexovisio@gmail.com>` (one merge by GitHub's web UI).
- Exactly one commit, `0d3352e` (2026-09-17, "feat: build cohesive dxrice
  shell dashboard"), carries `Co-Authored-By: Claude Sonnet 5
  <noreply@anthropic.com>` and a `Claude-Session:` trailer. GitHub attributes
  co-author trailers to the account that owns that email. The repository's
  only collaborator is `dexovision`, so that trailer is almost certainly why
  Claude shows up in the contributor list. Removing it requires rewriting
  every commit from `0d3352e` to the tip of `main` and force-pushing. That is
  not done here; see "History cleanup proposal" below.
- The container's git identity defaults to `Claude <noreply@anthropic.com>`.
  Commits from this audit are made as the project's author identity, with no
  co-author trailers, per the maintainer's instruction.

## Plan (order of work)

1. **Critical correctness:** C1 (installer migrates the two layer-fade lines
   into the deployed `hyprland.lua` with a backup and consent, and the overview
   checks the live setting and warns), C3, C4, K1, K2, K4, K5, and the two
   environment-fragile tests.
2. **Idle cost:** P1 (event-gated loops, rescan only when `/dev/input`
   changes), P2 (event-driven focused window with a one-shot read at start),
   P4. Measured before and after.
3. **Cleanup:** M1–M3, plus deduplicating install.sh's inline Python into one
   helper.
4. **Portability:** G1–G3 and K3: `emerge` backend, per-distro package files,
   a non-systemd supervisor for the three services.
5. **Installer/updater hardening:** U1–U3 plus new isolated tests (fake
   remote, network failure, conflicting local edit, no-systemd path).
6. **Docs:** README rewrite with Gentoo path, matrix, troubleshooting,
   generated keybinding table.
7. **Final pass:** full test run, results recorded here.

Out of scope without approval: history rewrite, force-push, anything touching
a live desktop session.

## History cleanup proposal (not executed)

Only one commit is affected. Options, from least to most invasive:

1. **Leave history alone (recommended).** The trailer is accurate: that
   commit was co-written with Claude. New commits carry no co-author trailer,
   so nothing further gets added to the contributor list.
2. **Strip the trailer by rewriting `main`.** For example, with
   `git filter-repo --message-callback` removing the two trailer lines, run
   from `0d3352e^`. Effects:
   - every commit from `0d3352e` onward gets a new SHA (roughly 130 commits);
   - `main` must be force-pushed;
   - the `claude/*` branches must be rebased or deleted;
   - any clone (including your own `~/dxrice`) must be re-cloned or
     hard-reset, and `install.sh update`'s `--ff-only` pull will refuse until
     it is;
   - GitHub caches contributor stats, so the list may take a while to update.
3. **`.mailmap` doesn't help.** It changes how `git log`/`shortlog` print
   names, but GitHub's contributor graph ignores it.

Nothing here is done without your explicit go-ahead.
