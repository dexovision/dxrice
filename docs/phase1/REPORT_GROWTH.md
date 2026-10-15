# Galaxy Spiral growth, precise SUPER+C, transient UI

Follows [REPORT_SPIRAL.md](REPORT_SPIRAL.md). Everything was tested
offline: unit tests, an in-memory Hyprland, and renders of actual
algorithm output. Nothing touched the live desktop.

## Root causes

**Auto-placement didn't grow a spiral**
1. The first window on a workspace was never placed (`place_new_window`:
   "first window -- nothing to avoid"). It stayed wherever it mapped.
2. "The screen" was the raw monitor. Bars and docks (Hyprland's `reserved`,
   52 / 68 px here), scale and rotation were ignored, so the centre was
   off and windows could sit under the bar.
3. A new window joined at its size rank in a sweep anchored on the
   largest window, so the arm never extended from where it ended. And
   only on-screen windows were passed in: once the spiral grew past the
   screen edge, the next window lost track of the arm and restarted
   beside the anchor.

**An oversized SUPER+G layout cut off its anchor.** Recentring centred
the whole group's bounding box. Your live test (six 826×493 terminals)
put the anchor's top edge at y = −46.

**SUPER+C** was not pkill-based. It closes by window address first, and
force-kills only when the app ignores the close, and only if no other
window shares the process tree. The remaining flaw was in finding the
app's root process. It climbed parents "while the same executable", and
for interpreters and shared runtimes (python, java, node, a system
electron, shells) that climbs from the app into a different program that
launched it. The launcher and everything else it runs would then be
force-killed too. Proven by a test that fails on the old code.

**Transient UI.** Tooltips, menus and hover cards were already excluded
by both placers through one classifier. Two gaps remained:
- An XWayland surface the X server couldn't describe was treated as a
  popup when small, but by auto-placement only. SUPER+G laid it out as an
  ordinary window, a duplicated and conflicting filter.
- Dialogs with a parent (WM_TRANSIENT_FOR) were independent members of
  SUPER+G's spiral.

## What changed

One stateless model, shared by auto-placement and SUPER+G
(`scripts/dxrice_spiral.py`). There is no remembered state to go stale.

**The anchor** (`anchor_index`) is the window covering the usable area's
centre point. That's where auto-placement puts the first window and
SUPER+G its hub. If none covers it (you panned away), the most central
window is used.

**The arm** (`sweep_state`) is read from geometry, in one of two orders:
- creation order (Hyprland's `stableId`, otherwise the client list order)
  for a spiral auto-placement grew;
- prominence order for one SUPER+G built.

Whichever order turns most consistently round the anchor is the arm. Its
last window is the tip, and a closed window simply drops out.

**The step** (`Composer.place_next`) is shared by SUPER+G's build and
auto-placement's join.

**Auto-placement** (`join`, via `place_new_window`):
- The first window becomes the anchor at the usable centre, clear of
  fullscreen and pinned windows.
- Each later window sits beside the tip, one angular width further round.
  Once a turn closes, the arm continues further out.
- It considers every window of the composition, including those past the
  screen edge. It starts a new anchor only when none of the composition
  is on screen.
- A hole a closed window leaves inside the ring (an enclosed spot touching
  three windows) is reused by the next window that fits. An open gap is
  left, and the arm carries on.
- It avoids slits and spots that would be mostly hidden. The latter is
  only a tie-breaker, because beside a screen-filling anchor every next
  spot is mostly off-screen.
- Existing windows never move.

**SUPER+G** recentres as nearly to the box centre as the anchor allows.
The anchor keeps covering the centre point, and stays at least 32 px
inside the usable area where it fits. In the live-test case its top edge
is now at y = 47 instead of −46.

**The usable area** (`usable_bounds`) is the monitor's logical size
(scale, rotation) minus the reserved space. Both placers use it.

**SUPER+C**: a shared runtime counts as the same program only when it
runs the same script or module. Multiple instances, an instance launched
from another, and a missing or unreadable process all behave safely. Two
cases to know:
- **A main window**, the only window of its app: SUPER+C asks it to close.
  If it ignores that (it hides to the tray), its own process tree is
  terminated: TERM, a grace period, then KILL.
- **A secondary window**, or one whose process also runs other windows:
  SUPER+C asks only that window to close. It never force-kills; if the
  window ignores the request, a notification says why.

**Transients**: one rule for both placers. A small XWayland surface the X
server couldn't describe is treated as a popup (`settle_unknown`).
Dialogs with WM_TRANSIENT_FOR are attached to their parent
(`attached_children`): SUPER+G moves them with it, and they don't count
as members of the composition a new window joins. Legitimate small
windows (a 320×260 calculator) are still placed.

## Tests

All 14 Python suites pass. All shell suites pass; `launch_systemd` is
skipped because the sandbox has no systemd.

- `dxrice_test_spiral_growth.py` (20 new tests): one window centred; two
  joining; six mixed with no rigidity; twelve wrapping round and moving
  out; nothing moving on opens; closing (hole reused / arm continues);
  fullscreen and pinned obstacles; SUPER+G after scattering; convergence;
  an oversized layout keeping its anchor visible; no overlap or repeated
  shrink; tooltip, menu, hover card, unknown surface, attached dialog,
  small real app; usable area (reserved space, scale, rotation).
- `dxrice_test_force_close_window.py` (4 new): two instances, an instance
  started from another, a Python app started by another Python program
  (fails on the old code), runtime detection.
- Updated deliberately: the first-window test (now moved to the centre, no
  move when it's already there), and recentring (centred as nearly as the
  anchor allows).
- An old placement daemon still running with these files on disk keeps
  working. Simulated for both the 0af6538 and the released code.

## Benchmarks (same fixtures, interleaved)

**SUPER+G** (291 layouts, released 55f58f8 vs this change): identical
composition. Sweep 0.86, rotation 0.89, 100% of gaps 16–24 px, 0
overlaps, 0 rigid, 0 re-shrunk. p95 timing is within 1 ms per bucket
(5 / 37 / 75 / 115 ms at 3–4 / 5–6 / 7–9 / 10–12 windows). The recentring
change only moves the group as a whole.

**Auto-placement** (200 opening sequences, 1002 windows):

| | Released | This change |
|---|---|---|
| Opening-order sweep (random ≈ 0.69) | 0.74 | **0.96** |
| A SUPER+G press keeps it as it is | 90 | **106** |
| Existing windows moved / overlaps / off the spacing | 0 / 0 / 0 | 0 / 0 / 0 |
| Rigid after opening | 0 | 0 |
| Median aspect / taller than wide | 1.29 / 24 | 1.27 / 30 |
| Group centre to screen centre (median) | 281 px | 345 px |
| Screen covered (median) | 0.71 | 0.65 |
| New window opened mostly (>50%) off screen | 580 of 1002 | **673 of 1002** |

Join time, including the hole search: median 2.3 / 4.6 / 9 / 15 ms with
6 / 12 / 20 / 30 windows open (worst 22 ms). Bursts don't stall.

**Costs, stated plainly:**
- With these app sizes on a 1080p screen, most new windows already opened
  more than half off-screen. Growing outward round a fixed, often large,
  central anchor makes that more common (58% → 67%).
- Weighting visibility more strongly is exactly what broke the sweep
  (windows jumped to whichever side had room). Visibility is kept as a
  tie-breaker, and the infinite desktop pans to the window.
- The group also sits further from the screen centre, because the anchor
  stays put instead of the group being re-centred at every step.

## Renders (actual output, `spiral/growth/`)

| File | What it shows |
|---|---|
| `growth_1_2_6_12.png` | 1, 2, 6 and 12 windows: one turn round the anchor, then a wider second turn |
| `growth_mixed_8.png`, `growth_mixed_12.png` | mixed sizes, frame by frame, flow line in opening order |
| `close_and_reuse.png` | a window closes, nothing moves, the next window takes its hole |
| `oversized_anchor_visible.png` | your live test's six terminals: released vs this change |

## Also worth knowing

- **SUPER+G on a single window** now centres it in the usable area (it
  used to do nothing with fewer than two windows). With one window open,
  the next press moves it to the centre.
- **One test,** `test_opening_after_super_g_continues_super_gs_own_arm`,
  pins the shared model. After SUPER+G, a new window reads SUPER+G's arm
  (prominence order) and continues its sweep without moving anything.
- **One live-checkout edit, reverted:** at the start, one refactor
  (byte-identical output on all 291 benchmark layouts) was written into
  the live `~/dxrice/scripts/dxrice_spiral.py`. It was reverted with
  `git checkout` within a minute, before any work continued in the
  worktree. Nothing else touched the live checkout until the final
  fast-forward.
- **Commit email:** commits use `dexovisio@gmail.com`, your earlier
  correction of the `dexovision` in briefs. Tell me if this one is meant
  differently.

## Remaining limitations

- Native Wayland dialogs: Hyprland doesn't report their parent, so they
  can't be attached. Auto-placement still puts a same-app dialog beside
  its window.
- Hole reuse is only for enclosed holes. A window closed on the airy
  outside leaves its gap, and the arm continues.
- If you move windows by hand, the arm is re-read from the new geometry;
  creation or prominence order, whichever is consistent.
- The new-window spawn-then-jump still needs Hyprland window rules (a
  config reload). Not part of this change.
- Not validated on the live desktop. Measured offline only.

## Activation (deferred, nothing was restarted)

- **SUPER+G, SUPER+C:** their scripts run fresh on every press. They use
  this the moment `~/dxrice` has it. Nothing to restart.
- **Auto-placement** (first window centred, growth, attached dialogs,
  shared transient rule): the long-running service keeps the code it
  started with. When you're ready:
  `systemctl --user restart dxrice-auto-place-window.service`
- No QML, Hyprland config or theme changes. Quickshell doesn't reload.
