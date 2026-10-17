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

Branch: `claude/dxrice-engineering-audit-uplvjy`, from `4688761`, since
rebased onto the rewritten `main` (`22a54da`, the same files).

### Finding by finding

| | Status | Commit |
|---|---|---|
| C1 layer-fade fix never reached installs | fixed: install/update offer the edit (backup, consent) | d4f785b |
| C1b overview let go while panned windows still moved | fixed: closing zoom runs as long as Hyprland's window move | 35884d4 |
| C2 no bar without systemd | fixed: `scripts/dxrice_session.sh` supervises without systemd | 307ab46 |
| C3 false "placement tests FAILED" | fixed: log in the state dir | d4f785b |
| C4 failed font download aborted the install | fixed | d4f785b |
| K1 `XDG_STATE_HOME` ignored | fixed in the template, the `dx` functions, and by migration | 307ab46, d4f785b |
| K2 re-exec dropped flags | fixed | d4f785b |
| K3 power actions systemd-only | fixed: `scripts/dxrice_power.sh` (systemd or elogind) | 307ab46 |
| K4 update/uninstall as root | refused, like install | d4f785b |
| K5 unquoted wallpaper path | fixed in the template | 307ab46 |
| P1 daemon busy-polling | fixed (measured below) | 273e663 |
| P2 top bar `hyprctl` poll | fixed (measured below) | 6abbdb1 |
| P3 python per focus change | not changed: event-driven, not idle cost | - |
| P4 clock every second | now once a minute | 6abbdb1 |
| M1 dead `_dev_` QML | removed | f10f05c |
| M2 duplicated install.sh Python | atomic-write and rc-strip copies replaced by helpers | d4f785b |
| M3 unused imports/variables | removed (ruff F clean) | f10f05c |
| M4 comment narration | trimmed only where code was rewritten | - |
| G1-G3 Gentoo, package lists | `deps/*.list`, emerge backend, docs | 4931edc |
| U1-U3 updater | fetch/preview/ask/fast-forward, refusals change nothing | 4931edc |
| D1-D2 README | rewritten; `dxrice_test_docs.py` checks it | 04ff6ae |
| Daemons outliving their Hyprland (found in review) | placement and panning daemons exit when their Hyprland instance is gone; the supervisor stops restarting | 8ab4d14 |
| Fixed `/tmp` paths (found during the work) | moved to `$XDG_RUNTIME_DIR/dxrice` | 776d527 |
| Unattended prompts defaulting to yes (found during the work) | privileged/file-changing prompts need a terminal or `--yes` | d4f785b |

(4931edc carries both the Gentoo work and the updater rewrite: install.sh
went into that commit whole. 63ae867 adds the updater's test.)

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
confirms both on a real desktop. The message of commit 35884d4 (8770d2f before the rebase) states the
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
- **History rewrite** for commit `0d3352e`'s co-author trailer: not part
  of the audit. Done afterwards at the maintainer's request: `main` was
  rewritten to `22a54da` (`0d3352e` became `3432ed1`, identical apart from
  the removed trailer) and pushed with `--force-with-lease`.

## Second pass (bug hunt), 2026-10-16

An independent pass over the code as it stood after the first one. "Old code
fails" means the new regression test was also run against the code before the
fix, and failed there.

### Fixed

| Severity | Where | Finding and evidence | Commit |
|---|---|---|---|
| medium | `dxrice_navigate_windows.py`, `dxrice_move_window.py`, `dxrice_infinite_desktop_core.py` | monitor measured in mode pixels, not layout coordinates: on a 2880×1620 panel at 1.5×, "centre" was (1440, 810) and the right edge 960 px too far; the bar and dock were ignored, unlike SUPER+G and the overview. Old code fails the new tests | 3ec9c88 |
| medium | same three | pans moved pinned (e.g. picture-in-picture) and fullscreen windows, which the overview's own pan leaves alone. Old code fails | 3ec9c88 |
| low | `dxrice_infinite_desktop_core.py` | the active workspace was cached for 2 s, so a pan right after switching workspace moved the old workspace's windows. Old code fails | 3ec9c88 |
| medium | `dxrice_auto_place_window.place_new_window` | a window opened on another monitor was placed in the focused monitor's area. The old code put the test window at (560, 282) on the wrong screen | 07026d9 |
| medium | `dxrice_floating_tile_toggle.py` | SUPER+D restore moved, then resized, and the resize is centre-anchored, so windows came back offset by half their size change (old: (170, 390) instead of (100, 120)) | 315e992 |
| medium (suspected) | `TopBar.qml` workspace pills | clicks went through Quickshell's `activate()`, whose dispatch syntax this Lua-config Hyprland may refuse; now sends `hl.dsp.focus({ workspace = N })` like every other DXrice dispatch. Not confirmed live | b1df545 |
| low | `TopBar.qml` | special workspaces (negative ids) were shown as ordinary pills | b1df545 |
| medium | `install.sh` | a checkout path with a space installed "successfully" with every keybind broken (`hyprland.lua` splices the path unquoted). Now refused. Old installer: rc 0 | 56302e4 |
| low | `install.sh` | update failed for a branch tracking a local branch (`git fetch main`). Old updater: rc 1 | 56302e4 |
| low | `install.sh` `verify_deploy` | didn't check `dxrice_session.sh` and the other new helpers, or the executable bit of the two scripts `hyprland.lua` runs directly | 56302e4 |
| medium | every atomic writer of user files | `os.replace` replaced a dotfiles symlink with a plain file (`hyprland.lua`, `theme.json`, dock config, `.bashrc`/`.zshrc`). Reproduced; old code fails the new tests. Five duplicate writers consolidated | 96c5ddb |
| medium (security) | `WifiBackend.qml` `connectWithPassword`, `dxrice_quick_settings.connect_wifi` | the Wi-Fi password was an `nmcli` argument (`device wifi connect SSID password SECRET`), readable by any local user in `ps`/`/proc/PID/cmdline` while nmcli ran. Now `scripts/dxrice_wifi_connect.py` takes it on stdin, creates the profile without a secret, and activates it with nmcli's documented `passwd-file` (a 0600 file in `$XDG_RUNTIME_DIR/dxrice`, removed when nmcli exits). `--ask` wasn't used: nmcli documents it as an interactive prompt, and a piped password is reported not to work with it. Test: a fake nmcli scans every `/proc/PID/cmdline` for a throwaway secret during activation (a negative control proves the scan catches an argv leak); the QML harness test fails on the old code | 183ba34 |
| low | `dxrice_navigate_windows.py` | `--to`/`pan_to` was dead code (the overview pans in QML), and its docstring said otherwise | ee00926 |

### Found, not fixed

| Severity | Where | Finding | Why not, and the fix |
|---|---|---|---|
| low (suspected) | `Overview.qml` `refresh()` | restarting a running `hyprctl` process could, if Quickshell still delivers the killed run's `streamFinished`, count one reply twice and close a just-reopened overview | depends on Quickshell's process semantics, which the harness can't model; only reachable when reopening within ~5 ms. Fix if seen: don't restart a running read, re-read once it finishes |
| low | `dxrice_apply_theme.patch_hyprland_lua` | each regex patches the first match in the file, a commented-out line included | the shipped template has no such comments; a user adding one before the real setting would see Apply edit the comment |
| low | `dxrice_quick_settings.py` screenshots | `shell=True` with the screenshot path interpolated | the path is built from `$HOME` and a timestamp; only a home path containing `"` or `$` could break it |
| low | `dxrice_auto_arrange.py` | the resize branch and resize memory are dead (sizes are always kept) | removal means rewriting a dozen placement tests; no behaviour change |

### Stress testing (exercised, not inferred)

`scripts/dxrice_test_spiral_stress.py` drives the real placement and the real
SUPER+G entry point through the in-memory Hyprland: seeded sequences of opens
(ordinary, 2400×260, 300×1600, larger than the screen, tiny), closes, pinned
and fullscreen windows, and SUPER+G presses, each followed by a second press.
Over 500 seeds: 7,963 placements and 5,924 presses with no invariant broken
(nothing moved or resized by an open, no overlaps, SUPER+G never resizes or
moves a pinned/fullscreen window, a second press moves nothing). The suite
runs 40 seeds (about 3 s).

Not exercised: real multi-monitor layouts beyond the unit tests' fixtures,
real compositor timing under a burst of opens, and Hyprland's own animations.

### Keypress latency (measured, no change)

Each keybind starts a Python process. Best of 7 runs here, up to the first
Hyprland call: SUPER+G 48 ms, arrows 28-32 ms, SUPER+C 43 ms, against 14 ms
for a bare `python3`. `-X importtime` puts most of the difference in the
standard library's `json` (8-10 ms, via `re` and `enum`), which every script
needs to parse Hyprland's replies. The remainder is a few milliseconds and
wasn't worth a change.

Commit hashes above are those of `claude/dxrice-engineering-audit-uplvjy`
after it was rebased onto the rewritten `main` (2026-10-16); commit messages
written before the rebase still cite the earlier hashes.

## Third pass (interaction lifecycle, input, motion, visuals), 2026-10-16

Independent pass on `78c008a`, aimed at what happy-path tests miss:
interrupted transitions, input that outlives what is drawn, overlapping
refreshes, ugly data. Every fix below has a regression test that was also
run against the code before the fix and failed there.

### Fixed

| Severity | Where | Finding and evidence | Commit |
|---|---|---|---|
| high (input) | `Overview.qml` | no input mask: the overlay stays mapped through its closing zoom (300 ms, or the compositor's window move -- 480 ms -- after a panning click) and the release frames, and took the pointer over the whole monitor all that time. A click on the app underneath right after Esc / a click on empty space / SUPER+Tab was swallowed. Harness: owner `overview` at 30/120/250 ms into a close. Now input only while `open`. Old code fails `test_input_regions` test_10 | 138504a |
| medium (motion) | `AddShortcutBranch.qml` | closing the taskbar with Add Shortcut open: the branch kept re-placing itself against the collapsing panel; as the centred panel narrowed, right/left tied and it flipped sides mid-fold (rendered: left side at 110 ms, a detached pill at 180 ms). Its fold (420 ms) also outlived the parent (300 ms) and the TaskbarManager it reads. Now geometry freezes when a close starts, and when the parent is leaving the branch dissolves in place on the parent's own content-fade curve. Old code fails `test_closing_the_taskbar_dissolves_the_branch_in_place` | 929fab0 |
| medium | `WifiBackend.qml`, `dxrice_quick_settings.py` | `nmcli -t` escapes `:` and `\` in values; every line was split on every `:`, so "Cafe: Free" became "Cafe\", its signal was misread, Connect asked for a network that doesn't exist, and saved-profile matching (also escaped) failed. Old code fails `WifiTerseParsing` | 3279327 |
| medium | `BluetoothBackend.qml` | one chained process reads every device; a refresh mid-chain re-pointed it while a `bluetoothctl info` was running, so that reply was filed under the next device (reproduced: headset shown disconnected with another device's 10% battery). A bluetoothctl that can't start left the list on "Looking for devices..." forever. Refreshes are serialized; failed starts end the chain. Old code fails all 3 tests in `test_bluetooth.py` | 03fdc7f |
| low (visual) | `ThemeEditor.qml` | previews inset 16 px, the settings cards beside them 24 px: labels in one column started 8 px apart | cd41483 |
| test | `test_overview.py` | the pan-close ghosting test sampled ~350 ms of a 480 ms close: it failed every time it ran alone and passed in the full suite only because frame grabs were slower there | 7588ab7 |

Harness fidelity, same commits: the Process stub now produces the output
of the command as started (not as `command` reads at exit) and models a
binary that cannot start (`__FAIL__`).

### Investigated, left alone

| Where | Finding | Why |
|---|---|---|
| `TopBar.qml` `refreshActiveIcon` | restarting a running lookup can briefly show a stale/empty glyph before the right one | transient, self-correcting; same class as the Overview note above |
| `WifiBackend.savedCheckProc` | two Connect clicks within one `nmcli` call (~10 ms) drop the first | both runs read the same list; nothing misattributed |
| Dashboard Audio card | on a machine without a backlight it stretches to match Networks and keeps ~40 px empty under two sliders | keeping both columns' bottom edges aligned was judged the better trade; brightness fills it on laptops |
| Calendar -> Quick Settings switch at 1366 px | QS grows over the retracting calendar for ~2 frames | rendered frame by frame: the covered island fades on the panel's live edge as designed |
| `tests/qml/test_overview.py` | one test failed once in 16 runs of the final commit (inside the full-suite run); 15 runs since, 3 of them concurrent, all 38/38. The baseline under load also showed 2 failures, one of them the pan-close test fixed above | name unknown: the runner kept counts, not logs. It should keep per-suite logs; until then this is an open intermittent, not a clean suite |
| Lifecycle fuzz | 240 seeded random interleavings of open/close/toggle/tab switch/branch/overview/Escape at 0-400 ms intervals, each settled and checked (input mask back to idle, every island at rest, branch and overview released, Theme unloaded, no QML warnings) | 0 failures; a negative control (skipping the final close) is caught by every check |

### Measurements (harness, software renderer, this container)

| What | How | 78c008a | after |
|---|---|---|---|
| CPU per frame during open/close | process CPU / frames swapped, 4 cycles x 2 runs | QS 3.4 ms, taskbar 2.7-2.8, branch 1.4-1.5, tabs 2.9 | QS 3.5-3.7, taskbar 2.8-3.0, branch 1.7-1.8, tabs 2.5-2.6 |
| idle frames, Dashboard open | frames swapped in 3.6 s | 0 | 0 |
| object growth | items in every shell surface after 150 full cycles (all panels, tabs, branch, Theme, overview) | 168 -> 168 | 168 -> 168 |
| RSS growth over the same 150 cycles | VmRSS of the harness process | 111 -> 123 MiB | 111 -> 123 MiB |

The RSS creep is identical before and after and the item count is flat, so
it is not something this pass introduced; it can't be attributed further
without a live Quickshell (allocator, JS heap and image caches all live in
the same harness process). Not measured: GPU frame pacing, real 144 Hz,
compositor blur, live Quickshell memory.

### Manual checks on the real desktop

1. Overview: SUPER+Tab, then Esc, then click a window *immediately*; it
   must take the click. Repeat with a click on a window off screen (the
   desktop pans): click another app during the slide.
2. `hyprctl layers` with nothing open: only `dxrice-bar-top`,
   `dxrice-bar-dock` and the OSD; `pgrep -af "qs -p"`: one shell.
3. Taskbar -> Add -> close the taskbar (click outside): the branch fades
   with the panel's contents and never jumps sides.
4. A network whose name contains `:` connects and shows Forget once saved.
5. Bluetooth: toggle the radio off/on quickly with two devices paired;
   each row keeps its own state and battery.
6. Overview focus after the input change (unverified): the overlay now
   stops taking the pointer at `hide()`, not at unmap, so with
   focus-follows-mouse Hyprland may focus the window under the pointer
   during the close. Click an off-screen window (the desktop pans), keep
   the mouse still and type: the keys must reach the clicked window.
   Repeat while moving the mouse across another window during the slide.
   If focus lands wrong, the `focusAgain` retry is the place to look.

## Fourth pass (placement, overview fade, consolidation), 2026-10-16

Baseline: `main` = `f20ced5`. The live desktop ran the pre-rewrite `4688761`
(same files as the rewritten history up to it; every one of its 148 local
commits has a patch-equivalent in `main`, checked with `git cherry`).

### Fixed

| Severity | Where | Finding and evidence | Commit |
|---|---|---|---|
| high (reported) | `dxrice_auto_place_window.py` | "three windows placed right, the fourth far lower, SUPER+G puts it back". A new window joins the spiral one step after the newest window that exists when it maps. When an app's launcher/updater/splash window is still up as its real window maps, the real window is placed after the launcher; when the launcher then closes, the window keeps a place reckoned from a window that no longer exists, while SUPER+G replays the spiral without it. Reproduced through the real listener and placement: the fourth window at (746, 1521) instead of (1733, 1093), and SUPER+G moves it. In the ideal model (every window maps at its final size, nothing closes) incremental placement and SUPER+G agree exactly: 62 sequences, 0 px. Fix: when the window a new window was placed directly after (its tip) had been placed less than 60 s before it and closes within 4 s of it, the new window -- and any placed right after it the same way -- is placed again from the windows created before it, if it is still exactly where it was put and on the same workspace. Closing any other window, or an older one, moves nothing (an earlier version of this fix moved the new window when *any* window it followed closed; caught in review, see the tests for unrelated and older windows). Old code fails the three hand-off tests on the layout itself | ea63ca5, 34fbda7, see below |
| medium (visual) | `hypr/hyprland.lua`, `dxrice_hypr_migrate.py` | the overview's double-image fix turned Hyprland's layer fade off for every layer surface (launchers, notifications, the theme window lost theirs), on the belief that no per-layer switch existed. Wrong: in Hyprland 0.56.2's source the animation tick checks each layer's `no_anim` for every animated value, alpha included (`AnimationManager.cpp`), and a `no_anim` layer's unmap takes no snapshot, so no fade-out is created (`LayerSurface.cpp`, `LayerFadeout.cpp`). Now one layer rule for `^dxrice-overview$`; the migration removes the global lines only in the forms DXrice wrote | 3f625d8 |
| test | `dxrice_test_session.sh` | the "no Quickshell" case put `/usr/bin` on PATH, so wherever Quickshell is installed it found `/usr/bin/qs`: 2 failures here, a pass only in a container without Quickshell | 683f45f |
| test | `dxrice_test_gentoo.sh` | same class: it fakes `emerge` but ran the installer with `/usr/bin` on PATH, and the installer takes the first package manager it finds (pacman before emerge), so on Arch every emerge assertion failed (10 here); Quickshell, Hyprland or cliphist being installed hid the "not installed" paths. Earlier sweeps reported it as passing because the runner printed `$?` after a command substitution | 2a2492c |
| test | `tests/qml/test_overview.py` | **the open intermittent above, named**: `TestUnderTheCompositorFade.test_control_the_recorded_double_image_is_reproduced`. It sampled the emulated 303 ms fade in real time; under load each frame grab took so long that the fade was over before the zoom moved anything, so it saw no second copy. 6 failures in 12 runs, 4 concurrent, and no other test failed. Now holds the zoom and the surface alpha at fixed values | 602e7b0 |
| test | `tests/qml/test_overview.py` | a second one, found by the next 12 runs: `test_the_surface_draws_nothing_in_its_last_frames` compared closing frames with a desktop grabbed seconds earlier; 4 runs that crossed the same minute saw the bar's clock change. Reproduced by starting it at second 58 (only the clock's digits differ); now compares with the desktop right after the unmap | 602e7b0 |

After both fixes: 16 runs of `test_overview.py`, 4 at a time and alongside
the full QML and Python sweeps, all 38/38. Every suite now keeps its own log
(`<suite>.log`), and the runner reports each suite's real exit status.

### Evidence not available, and what would settle it

The fourth-window report happened before this pass, and nothing recorded
it: the placement daemon logged nothing, and Hyprland's log at its default
level has no window events (checked: 7,151 lines, none about windows). The
mechanism above produces exactly the reported symptom and is fixed, but
which app's launcher it was can't be shown. Placement now writes one
journal line per decision (class, size, from/to, the arm window it
followed; no titles). If it recurs: `journalctl --user -u
dxrice-auto-place-window --since "10 min ago"` from just before it happened.

### Checked, nothing to change

- Overview input mask: input only while `open`, so the closing zoom and the
  two empty frames before the unmap take no clicks.
- Wi-Fi secret: stdin only, cleared once written. If the helper can't start
  at all, the string stays in that QML property until the next attempt
  (never logged, never in argv).
- Visual pass over the gallery at 1920x1080 and 1024x768: no inconsistency
  worth a change. The taskbar manager scrolls at 768 px height (the
  "screens physically too short" exception) and fits at 1080.
- Static: ruff (F, E9), shellcheck `-S warning`, `luac -p`, `py_compile`,
  `bash -n`, qmllint errors: all clean.

## Fifth pass (the ghost after picking another window), 2026-10-16

| Severity | Where | Finding and evidence | Commit |
|---|---|---|---|
| high (reported) | `Overview.qml` | "picking a different window in the overview, a ghost slides in from the side a moment after it closes; picking the window I was on, never". A different window is usually off screen, so picking it pans the desktop, and Hyprland animated the real windows' moves with the `windows` leaf -- a spring in the template. C1b's fix (above) kept the overlay up for that leaf's `speed` x 100 ms = 480 ms, but hyprutils 0.14.2 runs springs on their own physics and ignores `speed` (`AnimatedVariable.cpp`, `Spring.cpp`): the template's `easy` spring finishes after ~1 s and is 4-6 % short at 480 ms. The original recording, measured frame to frame after each close: 180 px of sliding over 306 ms after one close, none after a close without a pan. `hyprctl clients` reports a window's destination, not its animated position, so the overview can't watch the move. Fix: the pan moves each window with `no_anim` set first, in the same request, so it lands under the overlay at once; `no_anim` is unset once the overview has let go; the close is the usual 300 ms. `windowMoveMs` and the `hyprctl -j animations` read are gone. Old code fails the new tests (no `set_prop`, a 513 ms close after a pan) | see git log |
| medium (reported) | `Overview.qml` | "SUPER+Tab is delayed, and the zoom is rough". The overview decoded the wallpaper on every open, synchronously, at full size, on the GUI thread that runs the zoom (`asynchronous: false`, `cache: false`, source set only while showing). The user's wallpaper is a 3840x2160 PNG of 16.6 MB: measured 402-414 ms per decode with Qt's reader on this machine. The user's recording shows the zoom's first frames stalling (frames with no motion between moving ones, recorder frames evenly spaced). Now decoded once in the background at the screen's width and kept; the handover also waits for it if it is still loading. The zoom's curve, an ease-in-out that barely moved for its first ~60 ms, is now decelerating (0.2, 0, 0, 1). Old code fails the new tests (show() blocked ~the decode's length; no decoded wallpaper while closed) | see git log |
| test tool | `dxrice_overview_probe.py` | a window or a pan sliding over the bar's clock read as an overview transition (and its slide as "the ghost"); the slide measure also ran into a following reopen. Now a transition during which the whole picture shifts is reported as a slide and not judged, and the measure stops at the next transition | see git log |
