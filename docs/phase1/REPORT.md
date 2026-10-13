# DXrice phase 1 — report

Branch `phase1`, worktree `/home/dexo/dxrice-phase1`, 17 commits on top of
`c959d2e` (your live `~/dxrice`, untouched). Nothing merged, nothing pushed.
Every commit is `dexo <dexovisio@gmail.com>` with no AI attribution (the
brief said `dexovision`; you corrected that typo earlier, so `dexovisio`
was kept).

## How this was validated

* **Offscreen**: the QML harness (real shell QML, stub compositor types) at
  1920x1080, 1366x768, 1280x720, 1024x768 (and 1024x600 for short-screen
  cases); `tests/qml/render_gallery.py` renders every surface for looking.
* **Real compositor, isolated**: a throwaway *nested* Hyprland (a
  compositor running in a window, its own config and its own copy of your
  theme.json) running this branch's shell. Screenshots were taken of that
  nested display only, panels were opened through that instance's own IPC
  (by pid), and SUPER+G / new-window placement ran against real kitty
  windows in it, with SUPER+G's resize memory in a private directory.
  Your real session, real Quickshell, real windows and real files were
  never touched. It still isn't your desktop: same machine, same GPU
  and fonts, but not your monitor setup or your apps.
* **Disposable homes and fakes** for everything that touches the system
  (installer, uninstall, SDDM, systemd), plus one isolated real-systemd
  test that uses only uniquely-named transient units and `sleep` copies.

## What changed

### Reliability and data safety
* `e648c8f` Apps opened from the dock/launcher/lock/screenshot/theme
  wallpaper get their own systemd scope: a shell crash or restart no
  longer kills them (proven against real systemd with stand-in units).
  Uninstall only stops the shell when nothing else lives in its cgroup.
* `2bdf277` SUPER+C force-quit: pidfd-pinned targets (no recycled pids),
  re-validated before acting, SIGTERM then SIGKILL after a grace period,
  never the compositor/shell/session/audio/portals/polkit, explains when
  a shared process can't be force-quit.
* `1a72856` Theme Apply rewrote `hyprland.lua` non-atomically on every
  Apply (a crash left it half-written — reproduced); now atomic, and no
  write at all when nothing changed.
* `3a2ef55` A failed SDDM theme install could leave the login screen with
  a half-copied theme (reproduced); now copied aside and swapped in.
* `0ce8caf` "Generate from wallpaper" wrote theme.json itself: the shell
  recoloured before Apply, Revert "restored" the generated colours, and
  drafts were discarded. Now draft-only; standalone writes are atomic;
  missing/hung ffmpeg gives a clear message instead of a traceback/hang.
* `7b61f1d` Revert didn't restore settings newer than your theme.json.

### SUPER+G (`f230d9e`)
Measured with `scripts/dxrice_arrange_report.py` (fixtures, dead-pocket /
fill / detached / stability metrics, rendered diagrams):
* The shape target was round, so on 16:9 screens clusters became crosses,
  T-shapes and tall columns (8 terminals: a 2x4 column 1748px tall). Now
  aimed at ~4:3 (1.0 = exact screen shape was tried and rejected — it broke
  clean 2x2 blocks into staircases).
* Stray windows were never pulled back (moving cost more than the
  bounding-box growth they caused): one benchmark layout in six kept a
  window 700–2400px away. Now detachment is costed.
* Results: fixture dead area 30464 → 0 px²; scattered windows on 200
  benchmark layouts 12 → 0; detached after press 1 34 → 6 (max 2450 →
  334px); layouts a second press still moved 11 → 4; 0/300 invariant
  violations before and after; runtime 180 → 147 ms/layout.
* On the real (nested) compositor with 6 real windows: old result a
  1890x1810 tower with 2 windows shrunk; new 2130x1630, 1 resize, the
  1100x720 anchor kept; presses 2 and 3 move nothing.
* Pictures: `docs/phase1/superg_*.png`.

### Panels, motion and look
* `ba7139d` Closing a panel shrank it around fully drawn text that then
  vanished in one frame (the cog-click bug). Content now fades first, the
  surface retracts empty on an accelerating curve; reversible mid-way; no
  input while closing; reduce_motion. Same fix for the accordion.
* `b117a30`, `e5903fe` Panels were cut off mid-row behind fixed caps
  (Quick Settings 420px, Taskbar 360px, Theme editor 640px). They now size
  to their content, bounded by the bar and the dock, and **don't scroll**
  — scrolling is left only in the Theme editor and the Wi-Fi list, as you
  asked (plus a last-resort scroll on a screen physically too short).
  The Quick Settings clipboard card shows the entries that fit.
* `4539457` Primary buttons were accent-filled slabs; now neutral pills
  (your rule: accent only marks small things). Apply shows a small dot
  for unapplied edits instead of "Apply*". Truncated/outdated editor copy
  fixed.
* `d04549d`, `d3df8f1` 21 linear hover/fade animations now share the
  standard curve; the lock shake respects reduce_motion.
* `69836bc` Lock-screen clock was 12-hour while everything else is 24-hour.

### Customization (`7b61f1d`)
* New **Shell text size** (Fonts) — the shell's whole type scale; before,
  the Fonts page only reached Waybar/wofi/mako.
* **Corner roundness** now actually changes the shell's panels.
* "Spacing inside panels" (was "Settings app spacing").
* Quick Settings tiles keep their icons aligned and fit their labels at
  larger text sizes.

## Tests

See the table at the end (final run at the branch tip). New suites this
pass: `test_panel_motion`, `test_panel_fit`, `test_customization`,
`test_app_launch` (QML); `dxrice_test_launch`, `dxrice_test_launch_systemd`,
`dxrice_test_install_cycle`, `dxrice_test_polkit_agent` (shell);
`dxrice_test_wallpaper_theme`, `dxrice_test_sddm_install`,
`dxrice_test_apply_theme_launch` (Python), plus new cases in the placement,
force-close, theme-draft and lifecycle suites. Where practical each new
test was run against the previous code and failed there.

## Performance

* SUPER+G: 180 → 147 ms per benchmark layout (300 layouts, same seed).
* Shell, nested Hyprland, this branch: 0.10% CPU idle and with Quick
  Settings open (20 s samples); RSS 455 MB at start — identical to
  `c959d2e` (455.7 MB) — of which ~292 MB is shared libraries (Qt, Mesa)
  and ~126 MB private; no growth across repeated open/close cycles.

## Left for you / known limits

* **Needs your real desktop**: blur/opacity on your monitor, the dock
  launching your apps in their scopes, SUPER+C on real tray apps, SUPER+G
  on your real window mix, the lock screen with PAM.
* Apps already running when you merge stay in the old shell's cgroup
  until you log out; only apps launched after the merge get scopes.
* Your deployed `~/.config/hypr/hyprland.lua` line 49 still has the old
  polkit path (from before phase 0) — run the installer's update, or edit
  it to `hl.exec_cmd(repo .. "/scripts/dxrice_polkit_agent.sh")`.
* Design question, unchanged: SUPER+G keeps a window 1–2x its own size
  away from the rest as a "deliberate standalone dialog".
* ffmpeg (only for "Generate from wallpaper") isn't installed by
  install.sh; Fedora/openSUSE package names unverified, so it's optional
  with a clear message.
* Every install/update runs the SDDM theme sync as root; uninstall with no
  terminal removes the SDDM theme by default. Both pre-existing, reported
  not changed.

## Review and merge

```sh
git -C ~/dxrice log --oneline c959d2e..phase1
git -C ~/dxrice diff --stat c959d2e..phase1
# save your work first: the merge hot-reloads the running shell
git -C ~/dxrice merge --ff-only phase1
```

## Final test run (branch tip, sandboxed: blocked system commands are logged)

| Suite | Result |
|---|---|
| Python (12 suites) | 296 tests, all pass — placement 171, force-close 27, copy-once 22, manifest 15, integrity 14, hypr-ipc 13, taskbar-wrap 12, migrate 7, wallpaper-theme 6, apply-theme 5, sddm-install 3, reconnect 1 |
| Shell (6 suites) | install-cycle 22, installer-lifecycle 43, launch 9, legacy 8, polkit 10 assertions pass; launch-systemd skips in the sandbox by design and passes outside it (8 assertions, isolated transient units only) |
| QML (11 suites) | 100 test cases pass — add-shortcut 10 (x3 sizes), input-regions 10 (x4 sizes), theme-palette 18 (x3 sizes), top-bar 4 (x5 sizes; 1 skip that applies only at 1920 wide), panel-motion 20, theme-draft 11, panel-fit 9, branch-geometry 9, customization 5, app-launch 2, level-bar 2 |

No failures. The only blocked-command log entry is the systemd probe of
the skipped launch-systemd test.
