# Phase 1 progress (branch `phase1`, worktree `/home/dexo/dxrice-phase1`)

**Reports: [REPORT.md](REPORT.md) (phase 1), [REPORT_CLOUD_UI.md](REPORT_CLOUD_UI.md)
(cloud auto-placement + UI pass), [REPORT_PHASE2.md](REPORT_PHASE2.md) (visual
modernization).** This file is the running log.

Live checkout `~/dxrice` is untouched at `c959d2e`. Nothing pushed.
Validation is offscreen / sandboxed, plus a throwaway **nested Hyprland**
(a compositor running in a window, with its own config and its own copy of
theme.json) for real-compositor screenshots of this branch's shell. The
user's real session, real Quickshell and real files were never touched.

## Commits (on top of c959d2e)

| Commit | What |
|---|---|
| `e648c8f` | Apps launched from the shell get their own systemd scope (a shell crash/restart no longer kills them) |
| `2bdf277` | SUPER+C force-quit: pidfd-pinned, re-validated, graceful-then-SIGKILL, protected desktop processes |
| `ba7139d` | Panel close: content fades before the surface retracts; enter/exit motion tokens; reduce_motion |
| `f230d9e` | SUPER+G: screen-shaped composition target; stray windows pulled back into the cluster |
| `1a72856` | Theme Apply could leave hyprland.lua half-written (atomic, skip no-op writes) |
| `3a2ef55` | A failed SDDM theme install could leave the login screen half-installed (swap-in install) |
| `d04549d`, `d3df8f1` | Hover/fade animations ran linear; lock shake ignored reduce_motion |
| `0ce8caf` | "Generate from wallpaper" applied itself before Apply and broke Revert; ffmpeg errors/timeout |
| `b117a30` | Panels cut content off mid-row: Quick Settings/Taskbar/Theme editor size to content; no scrolling except Theme editor + Wi-Fi list |
| `4539457` | Primary buttons neutral (accent only marks small things); clearer Theme editor copy |
| `e12c252` | Offscreen gallery tool for every surface |
| `69836bc` | Lock screen clock 12h -> 24h like the rest of the shell |

## Galaxy Spiral growth, SUPER+C, transient UI (see REPORT_GROWTH.md)

- Auto-placement now grows the spiral from the first window: anchor at
  the usable centre, each window beside the arm's tip one angular width
  further round, outward once a turn closes, holes reused. It's read
  statelessly from geometry and creation order, and shares
  `place_next` with SUPER+G.
- SUPER+G keeps the anchor on screen when the group is bigger than it.
- SUPER+C no longer climbs from an interpreted app into its launcher.
- Attached dialogs move with their parent, and one rule now covers
  unknown XWayland popups.
- Opening-order sweep: 0.74 → 0.96. SUPER+G composition and timing are
  unchanged.
- The auto-placement service needs a restart to use it.

## SUPER+G and auto-placement: the airy spiral (see REPORT_SPIRAL.md)

The audit's Phase 4 (section D), implemented. One composer
(`scripts/dxrice_spiral.py`) is shared by SUPER+G and new-window placement:

- a composition spacing range (theme.json `window_spacing_min/max`,
  16/24) separate from `gaps_in`;
- a soft spiral objective around the most prominent window;
- a keep-or-rebuild gate so the second press is a no-op;
- one conservative resize per set of windows.

The packed solver is removed, and the tests that encoded it were
rewritten deliberately.

Benchmarked against 0af6538 on 291 layouts:

- rotational flow median 0.67 → 0.89 (random: 0.67);
- 100% of neighbour gaps within 16–24 px;
- 0 overlaps, 0 re-shrinks, 0 rigid results;
- p95 faster at every window count.

Renders of actual output are in `spiral/`. Waiting for your visual
sign-off.

This also settles the open question below: separate clusters and
standalone dialogs now join the one composition.

## SUPER+G on rigid layouts of MIXED sizes (branch fix/superg-mixed)

`c926539` only recognised grids of near-equal tiles, so mixed-size blocks --
two large windows over three terminals, a browser beside a column of
terminals, a browser/Discord/PrismLauncher/terminal 2x2 -- were still "0
moved, N already in place". Rigidity now also counts FULL-SPAN SEAMS
(a straight gutter across the whole composition, 4+ windows); a layout
that fails only on rigidity is rearranged positions-only; if the ordinary
rebuild reproduces the block, a second rebuild that charges for rigidity is
tried; either is kept only if less rigid with no new dead gap. Evidence:
`superg_mixed_rigid_before_after.png` (synthetic fixtures). Activate:
`git -C ~/dxrice merge --ff-only fix/superg-mixed` (scripts/ and docs/
only; SUPER+G uses it on the next press, nothing to restart).

## SUPER+G on rigid grids (branch fix/superg-grid)

Report: six windows in a grid, SUPER+G -> "Arranged 6 window(s); 0 moved,
0 resized, 6 already in place." Root cause: `_shape_is_coherent`
(scripts/dxrice_auto_arrange.py) accepted any overlap-free, connected,
not-too-elongated layout as finished, so a rigid grid never reached the
rebuild -- which, given the grid, does produce a staggered composition. A
grid is now recognised by its cross junctions (four similar-size windows
meeting at one gutter intersection) and rebuilt; a rebuild that isn't less
rigid is discarded (layout kept, recentred only), and one press settles
the result so the next press moves nothing. Evidence:
`superg_rigid_grid_before_after.png` (constructed fixtures, not your
desktop). Activate: `git -C ~/dxrice merge --ff-only fix/superg-grid` (only
scripts/ and docs/ change; Quickshell does not reload) -- SUPER+G uses it on
the next press, nothing to restart.

## Finalization (2026-10-14)

| Commit | What |
|---|---|
| `e5fceca` | Popup detection under fractional scaling: X11 windows matched by size at each monitor's scale when exact geometry fails; ambiguous matches treated as popups (left alone) |
| `9ce0908` | OSD and Wi-Fi dialog use a near-opaque material (neither gets blur) |

All Python, shell and QML suites pass, run in the sandbox (no compositor,
no session bus, logging fakes for system commands). launch-systemd is
skipped: outside the sandbox it creates units on the real user systemd.

**Activating.**

* Run `~/dxrice/install.sh update`.
  * It fast-forwards the checkout from its upstream, and Quickshell hot-reloads the
    shell as soon as its files change.
  * It redeploys the configs, keeping hand edits, and fixes the old polkit line in
    `hyprland.lua`.
  * It may ask about the SDDM theme.
  * It restarts no service.
* Then run `systemctl --user restart dxrice-auto-place-window.service`: the placement
  daemon is a long-running Python process still holding the old code.
* SUPER+G picks up the new code on its next press.

**Still needs your desktop:** blur on your monitor, real XWayland apps' tooltips
(probes were GTK), real PAM on the lock screen, the dock's launch scopes.
Also: WifiBackend passes the Wi-Fi password to nmcli on its command line
(readable in the process list while nmcli runs); fixing it needs a real
network to verify.

## Phase 2: visual modernization (see REPORT_PHASE2.md)

| Commit | What |
|---|---|
| `04002d6` | Proportional interface type (Noto Sans default, font_family kept for terminal/bar/icons); one slider, field and card language; Wi-Fi dialog |
| `a32c88b` | OSD as a click-through pill; lock clock |
| `49e6247` | Presets mark the current one, round swatches, two-tone clock, hex field |

## Cloud auto-placement + UI pass (see REPORT_CLOUD_UI.md)

| Commit | What |
|---|---|
| `4dedd4a` | New windows join the cloud (SUPER+G's own step, nothing else moves); XWayland tooltips/menus/hover cards never placed |
| `853bd70` | Settings > Experience: "Automatic window placement" (default on) and "Reduce motion" switches |
| `70a0f7a` | Shared interaction tokens; neutral sliders; busy/empty/error states; lock card; content transitions |
| `645c563` | Dock tooltips; bar island hover; Taskbar "System modules" card |
| `c56b3eb` | Slider value line no longer strikes through its label |

## Done since (see REPORT.md)

- Customization that reaches the shell: Shell text size (`text_scale`),
  Corner roundness honoured by the islands, Revert restoring settings
  theme.json doesn't have yet, toggle tiles that fit at larger text.
- Installer lifecycle test in a disposable home (install, update x2,
  user-edit preservation, uninstall, purge, reinstall).

## Open design questions (left for you)

- `_shape_is_coherent` keeps a window 1-2x its own short side away from
  the rest as a "deliberate standalone dialog" and does not rebuild. That
  contradicts "one composed cluster" for small desktops; it was an earlier
  deliberate decision with its own test, so it was not changed silently.
- ffmpeg (needed only by "Generate from wallpaper") is not in the
  installer's package lists; it is handled as optional with a clear
  message. Package names were not verified for Fedora/openSUSE.
