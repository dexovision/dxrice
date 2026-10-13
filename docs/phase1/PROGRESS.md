# Phase 1 progress (branch `phase1`, worktree `/home/dexo/dxrice-phase1`)

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

## In progress

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
