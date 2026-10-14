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
