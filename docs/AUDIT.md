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

## Results (end of the audit)

Branch: `claude/dxrice-engineering-audit-uplvjy`, from `4688761`.

### Finding by finding

| | Status | Commit |
|---|---|---|
| C1 layer-fade fix never reached installs | fixed: install/update offer the edit (backup, consent) | 311982b |
| C1b overview let go while panned windows still moved | fixed: closing zoom runs as long as Hyprland's window move | 8770d2f |
| C2 no bar without systemd | fixed: `scripts/dxrice_session.sh` supervises without systemd | 770d0d7 |
| C3 false "placement tests FAILED" | fixed: log in the state dir | 311982b |
| C4 failed font download aborted the install | fixed | 311982b |
| K1 `XDG_STATE_HOME` ignored | fixed in the template, the `dx` functions, and by migration | 770d0d7, 311982b |
| K2 re-exec dropped flags | fixed | 311982b |
| K3 power actions systemd-only | fixed: `scripts/dxrice_power.sh` (systemd or elogind) | 770d0d7 |
| K4 update/uninstall as root | refused, like install | 311982b |
| K5 unquoted wallpaper path | fixed in the template | 770d0d7 |
| P1 daemon busy-polling | fixed (measured below) | e9c8d66 |
| P2 top bar `hyprctl` poll | fixed (measured below) | fe65fee |
| P3 python per focus change | not changed: event-driven, not idle cost | - |
| P4 clock every second | now once a minute | fe65fee |
| M1 dead `_dev_` QML | removed | 97a967b |
| M2 duplicated install.sh Python | atomic-write and rc-strip copies replaced by helpers | 311982b |
| M3 unused imports/variables | removed (ruff F clean) | 97a967b |
| M4 comment narration | trimmed only where code was rewritten | - |
| G1-G3 Gentoo, package lists | `deps/*.list`, emerge backend, docs | e6fbbcc |
| U1-U3 updater | fetch/preview/ask/fast-forward, refusals change nothing | e6fbbcc |
| D1-D2 README | rewritten; `dxrice_test_docs.py` checks it | 7f6db89 |
| Daemons outliving their Hyprland (found in review) | placement and panning daemons exit when their Hyprland instance is gone; the supervisor stops restarting | see below |
| Fixed `/tmp` paths (found during the work) | moved to `$XDG_RUNTIME_DIR/dxrice` | b22dc20 |
| Unattended prompts defaulting to yes (found during the work) | privileged/file-changing prompts need a terminal or `--yes` | 311982b |

(e6fbbcc carries both the Gentoo work and the updater rewrite: install.sh
went into that commit whole. ba71fc6 adds the updater's test.)

### Measurements

All taken in this audit's container: no Hyprland, no input devices, no
display. They measure the code paths that run while the desktop is idle.
They do not measure the whole desktop.

| What | How | Before | After |
|---|---|---|---|
| infinite-desktop daemon, idle | `scripts/dxrice_idle_probe.py 60`, 25 s warm-up, 2 runs each | 119.8 / 119.9 wakeups/s, 0.38 % CPU, 18.3–18.6 MiB PSS | 0.3 / 0.3 wakeups/s, 0.00–0.02 % CPU, 18.4–18.6 MiB PSS |
| top bar processes spawned while idle | QML harness, 5 s idle, count of `hyprctl activewindow` runs | 3 (≈ 2,400/hour) | 0 |
| overview release after a panning click | QML harness, wall clock from click to the overlay letting go | 340 ms | 520 ms (the 480 ms move + 2 frames) |

The 480 ms is Hyprland's window move as the template configures it,
derived from the `windows` leaf's speed (4.79 × 100 ms). It was not
measured: that leaf is a spring, and whether `speed` sets a spring's
duration exactly is unconfirmed. The parser also assumes the
`hyprctl -j animations` output format. docs/OVERVIEW.md's manual check 3
confirms both on a real desktop. The message of commit 8770d2f states the
480 ms as fact; this paragraph is the correction.

**Not measured** (needs the real desktop):
- Hyprland's and Quickshell's own memory and CPU;
- the daemon's per-3 s device rescans with real devices;
- the whole-session idle total.

To get them, run `python3 scripts/dxrice_idle_probe.py 60` on the desktop
before and after updating. Leave it idle, with the same windows open. It
reports Hyprland, Quickshell, the DXrice daemons and everything else
separately.

### Not done, on purpose

- **SUPER+G's resize branch** in `dxrice_auto_arrange.py`. It is dead
  (sizes are always kept; 2,000 random layouts produced no size change),
  but a dozen placement tests are built around its API. Removing it is a
  test rewrite with no behaviour change.
- **Overview focus timers** (`focusSoon` 30 ms, `focusAgain` after
  release). They compensate for Hyprland refocusing the window under the
  pointer when the overlay unmaps. Changing them needs a live compositor
  to verify, so they're unchanged.
- **Animation retuning** beyond the overview close. Curves, durations and
  springs are the visual identity, and judging them needs the real
  screen. docs/OVERVIEW.md lists the manual checks.
- **History rewrite** for commit `0d3352e`'s co-author trailer: see the
  proposal above.
