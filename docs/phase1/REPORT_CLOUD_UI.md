# Cloud auto-placement + UI pass — report

Branch `phase1`, worktree `/home/dexo/dxrice-phase1`, on top of the phase-1
tip `22a1c9e`. Your live `~/dxrice` is untouched (still `c959d2e`).
Nothing merged or pushed. Every commit is `dexo <dexovisio@gmail.com>`,
with no AI attribution. The brief said `dexovision`; you corrected that
typo earlier.

Validation had three parts:

* **Offscreen QML harness.** Real shell QML, stub compositor types, no
  blur.
* **In-memory Hyprland fakes.** For placement.
* **A throwaway nested Hyprland.** Its own config and its own copy of your
  theme.json, with real kitty windows, real GTK/X11 popups and this
  branch's shell. Only that nested display was captured.

Your real session, windows and files were never touched. That still isn't
your desktop.

## 1. Automatic placement: what triggers it

* **Trigger.** Exactly one event: Hyprland's `openwindow>>`, a window
  being mapped (`PlacementListener` in `scripts/dxrice_auto_place_window.py`).
* **Ignored events.** These never start a placement:
  * focus changes (with `follow_mouse` that's every time the pointer
    crosses a window);
  * title changes (a browser retitling itself as you hover links);
  * moves, including placement's own;
  * workspace and layer events;
  * anything else.
* **Once per window.** Each window is handled once per mapping. Repeated
  `openwindow>>` events for it are ignored until its `closewindow>>`.
* **Late joiners.** A window mapped fullscreen or tiled is retried when a
  fullscreen or floating-state change is reported. It is placed at most
  once, when it becomes an ordinary floating window.
* **Moved first.** If the user or the app moved the window between being
  read and being placed, it's left where it is (`user-moved`).
* **Bursts.** Windows are placed one at a time. Each placement waits until
  the compositor confirms the move, so the next window sees the true
  layout.

### The hover bug

**Cause.** In an XWayland app, hovering a link, a tab or anything with a
tooltip maps an *override-redirect popup*. Hyprland reports it exactly
like an application window: same event, same `hyprctl clients` fields.
Verified on the nested Hyprland with a real GTK popup: it and its app's
main window differ only in geometry.

**Impact.** The old placer moved every one. Over 300 simulated popups on
realistic desktops:
* all 300 popups were moved away from what they pointed at;
* in 50 cases, existing windows were moved or shrunk to make room for the
  popup.

**Fix.** `scripts/dxrice_window_class.py` asks the X server (libX11 via
ctypes; no new dependency). It uses one short-lived connection, and a
window that vanishes mid-query can't crash it.

| Surface | Treatment |
|---|---|
| Override-redirect windows; tooltip / menu / dropdown / popup / combo / notification / dnd types | Never placed, never part of anyone's layout |
| Splash screens | Left alone |
| DXrice's own Quickshell dialog (`org.quickshell`) | Left alone |
| Helper surfaces under 24px | Left alone |
| Dialogs | Go beside their `WM_TRANSIENT_FOR` parent |

* **Native Wayland.** Tooltips and menus with a parent are `xdg_popup`s,
  which Hyprland never reports as windows (verified on the nested
  compositor).
* **No X server.** A small XWayland window is left alone rather than
  guessed at.
* **SUPER+G.** It uses the same classification, so a popup that happens to
  be open during a press is neither arranged nor arranged around. Pinned
  windows are fixed obstacles for both.

**Live, nested compositor, new code:**
* real GTK override-redirect, tooltip-typed and menu-typed popups stayed
  exactly where the app put them;
* no existing window moved while they were open;
* 30 programmatic focus changes across the windows moved nothing.

On the same scenario, the old placer moved the popups and existing
windows.

### Where a window goes: the existing cloud algorithm

* **Dialogs.** A dialog of an open app goes beside the window it belongs
  to. That's either the X server's `WM_TRANSIENT_FOR` parent, or a window
  in the same process that is meaningfully larger.
* **Everything else joins the cloud** through
  `dxrice_auto_arrange.join_composition`. That is SUPER+G's own per-window
  step (`_find_best_position`): same edge-derived and organically
  staggered candidates, same screen-shaped composition cost, same
  compactness / detachment / dead-gap terms.
* **Nothing else changes.** Every existing window is held where it is. The
  new window keeps its size, lands exactly one gap from what it sits
  beside, and overlaps nothing.
* **What's in view.** It composes with the windows in view; a cloud panned
  off-screen doesn't drag new windows away. Everything is still an
  obstacle, so the infinite canvas is not clamped.
* **The old Stage 2/3** ("move or trim existing windows to make room") is
  off the live path. The code is kept for comparison.

`scripts/dxrice_autoplace_report.py` runs the real `place_new_window` over
200 realistic opening sequences (1002 opens), old vs new:

| | old (`22a1c9e`) | new |
|---|---|---|
| opens that moved or resized an existing window | 426 | **0** |
| overlaps / new window not exactly one gap from a neighbour | 0 / 0 | 0 / 0 |
| median shape, width:height (screen is 16:9) | 1.04 | **1.30** |
| finished layouts taller than wide | 80 | **33** |
| mean dead-pocket area | 5868 px² | **1878 px²** |
| layouts SUPER+G's own "already good" test accepts | 188 | **198** |
| composition centre to screen centre, median | **243 px** | 294 px |
| screen covered, median | **0.788** | 0.773 |

**Trade-off.** The last two rows are the honest cost of never moving
existing windows: the cloud grows from wherever it is, so it sits a little
further off-centre. SUPER+G recentres it. Weighting visibility or centring
into the join step was tried and moved those numbers only marginally
(278–303 px), so it was not added.

**Same-process rule.** Two windows of one class from *different processes*
are no longer treated as a window and its dialog. On the nested
compositor, kittys of different sizes anchored to each other and walked
the whole cloud off one side of the screen.

**Pictures:** `autoplace_old_vs_new.png` (the same sequences, old and new)
and `autoplace_nested_live.png` (real kittys on the nested compositor).
Live gaps measured exactly 5px.

## 2. The setting

**Theme editor → Experience → "Windows and motion" → *Automatic window
placement*.** The description reads: "Newly opened windows join the
arrangement on their own, next to what's already open. Nothing else moves.
SUPER+G still rearranges everything."

* **Storage.** theme.json `auto_place_windows`, saved through the editor's
  normal draft / Apply / Revert. Apply preserves unknown keys and
  `schema_version` as before.
* **When it applies.** The daemon re-reads the setting on every window
  open, using an mtime check. Apply takes effect on the next window, and
  turning it back on needs no restart. Verified live on the nested
  compositor: off left a new kitty where it mapped; back on, the next one
  joined the cloud at exactly 5px.
* **Off.** Nothing at all happens when a window opens. SUPER+G is a
  separate script and keeps working (tested).
* **Default: on.** Placement has always been on. A theme.json without the
  key reads as on, so no schema bump is needed. The shipped default
  theme.json lists the key for new installs.
* **Behaviour, not theme.** Colour presets and "Generate from wallpaper"
  carry colour keys only and leave it alone (tested).
* **Same page: *Reduce motion*.** The key already existed and was honoured
  by the shell, but only by hand-editing theme.json.

## 3. UI changes by surface

**Before/after:**
* `ui_before_after.png` covers Theme editor sliders, Taskbar editor, lock
  screen, Quick Settings and Theme editor › Experience;
* `ui_dock_tooltip.png` shows the new dock tooltip.

All are offscreen renders, which have no blur. On the nested compositor
with real blur, panels read near-opaque and legible.

**Shared language** (`Theme.qml`, used everywhere instead of per-widget
numbers):
* **Press feedback.** One press-scale for every pressable control, and no
  movement under reduce motion.
* **State layer.** Named hover/press amounts.
* **Moving things.** `durationMove` covers the tab indicator, workspace
  pill, OSD level, scroll glides and slider handles. These ignored reduce
  motion before; now they don't move under it.
* **Content shift.** `contentShift` for swapped-in content.
* **LoadingDots.** One "working" indicator: opacity only, animating only
  while visible.

**Theme editor:**
* **Sliders.** They were accent-tinted slabs, a dozen coloured bars per
  page against your "accent marks small things" rule. They are now a
  neutral step of the surface with a 2px accent value line under the fill,
  so the text is never struck through. Added:
  * a hover state;
  * a glide on click / Revert / preset;
  * units on decimal values;
  * tabular figures.
* **Busy buttons.** Apply and Generate show LoadingDots in place of the
  label instead of swapping to "Applying…" / "Sampling…", so the header no
  longer jumps and nothing can be clicked twice.
* **Category switches.** The new page fades up into place and starts at
  its top.
* **New switches.** Two switches with wrapped (never elided) descriptions.
  No truncated text anywhere in the editor at 1920 or 1024 wide (checked).

**Quick Settings:**
* Tabs fade *and* rise into place.
* The Wi-Fi and Bluetooth lists' "Scanning…" was one muted line at the top
  of an empty card. It is now a centred state: a glyph and a sentence, or
  LoadingDots while the first scan runs. On the nested compositor the
  first `nmcli` scan takes a few seconds; this is what you see meanwhile.

**Lock screen** (PAM handling unchanged):
* an initial avatar and a centred greeting;
* a pill field with a submit button that shows LoadingDots while PAM
  checks;
* on a wrong password, a red field edge and message, which clear when you
  type again;
* an "Enter to unlock" hint;
* clock and card settle in when the lock comes up;
* the shake still respects reduce motion.

**Top bar.** The clock and status islands took hover but showed none. They
now lighten by the shared state amount under the pointer and while
pressed.

**Dock.** Icon-only tiles now name themselves:
* the name appears above the dock after the pointer rests 450ms;
* it then follows the pointer from icon to icon at once;
* pressing hides it;
* it sits outside the window's input mask, so it can't take clicks
  (tested).

**Taskbar editor.** "System modules" was a heading and rows loose on the
panel in a different style from its two sibling cards. It is now the third
card of the same family.

**Shared controls:**
* `GlassButton` gains a `danger` variant for irreversible actions and
  `busy`;
* `SliderRow`'s handle grows on hover;
* the Experience page's speed demo stops under reduce motion and when
  hidden.

**Corner roundness.**
* Still effective: panels, cards, sliders and chips derive from the
  `rounding*` tokens it scales.
* Exempt by design: pills (buttons, the lock field, the tooltip) are
  `height/2` at any setting.

**Not changed, deliberately:**
* the panel material and opacity — with real blur it's legible;
* the overall layouts — they were already composed;
* the font (see §6).

## 4. Tests

New:

| File | Tests | What it covers |
|---|---|---|
| `scripts/dxrice_test_auto_place_cloud.py` | 33 | transient surfaces never placed (override-redirect, popup/tooltip/menu/dnd/combo/notification/splash types, no-X fallback, tiny and shell surfaces); a tooltip is neither obstacle nor layout, including for SUPER+G; X11 classification and partition; dialogs beside their `WM_TRANSIENT_FOR` parent and never moving others; placement uses SUPER+G's step; 200 sequences with exact gaps, sizes kept and no existing window touched; SUPER+G accepts the result; fullscreen/pinned obstacles; off-screen cluster; closed-before-placement; late geometry; self-resizing client; user-moved window; event noise (focus, titles, moves, workspace, garbage) never places; once per window; rapid opens; deferred fullscreen; failing placement; switch off/on live; torn or missing theme.json; SUPER+G works when switched off; a real listener burst |
| `tests/qml/test_behavior_settings.py` | 5 | the switch's display, click, Apply, Revert, presets, reduce motion, wrapping |
| `tests/qml/test_interaction.py` | 8 | reduce-motion tokens, neutral slider fill, busy Apply, the scanning state, lock card states, category transition, dock tooltip (including input passthrough), island hover |

Updated:
* the obsolete Stage-3 tests in the placement suite became "opening never
  changes an existing window";
* the family-anchor tests now require the same process.

How the old code fares:
* **The old placement behaviour is shown failing by measurement.** That
  means the popups it moved, the existing windows it shoved, and its
  shape: the 300-popup run and the 200-sequence report above, both run
  against `22a1c9e`.
* **`dxrice_test_auto_place_cloud.py` doesn't prove that.** Run against
  `22a1c9e` (with the new classifier module copied in), 29 of its 33 tests
  *error* in setup, because the new seams don't exist; that is not a
  behavioural failure. The 4 classifier unit tests pass, since they test
  the new module itself. The event-noise test is a regression guard the
  old listener would also pass.
* **QML tests.** `test_interaction.py` (8) and `test_behavior_settings.py`
  (5) each fail or error on `22a1c9e` in every case. The features didn't
  exist there.

Final run at the branch tip: see the table at the end.

## 5. Performance

* **CPU.** Nested shell, this branch, fresh start: 0.10% CPU idle over
  20s.
* **Memory.** RSS 449 MB at start, which matches phase 1's measurement
  (455 MB); 480 MB after the first 5 Quick Settings + Theme open/close
  cycles (first-load warm-up); 478 → 477 MB over 10 more. No growth.
* **Placement work.** Placement subscribes to nothing new and still reacts
  to one event type. It asks the X server only when an XWayland window is
  involved. The one extra `hyprctl clients` read before dispatch is the
  user-moved check.

## 6. Left for you

* **Font.** The shell is set in your `font_family` (JetBrains Mono, also
  used by Waybar/wofi/mako). A proportional UI face such as Noto Sans,
  already installed by the installer, would be the single largest
  "modern" change. It overrides your choice, so it wasn't made.
* **Settings timing.** The switch follows the editor's draft/Apply model,
  like every other setting. It is not an instant toggle.
* **Startup sizing.** It still enlarges a main window that maps in the
  "too big for a dialog, too small to be deliberate" band (existing
  behaviour; never a dialog or a second window of an open app). That is
  the one exception to "new windows keep their size".
* **Centring.** With nothing else moving, the cloud drifts slightly
  off-centre as it grows (median 294px against 243px); SUPER+G recentres.
  Moving the whole cloud on every open was rejected as disruptive.
* **Dead code.** Stage 2/3 (`try_make_room`, `try_resize_room`) is unused
  by the live placer, but kept with its tests. Delete it if you're happy
  with the new behaviour.
* **No X server.** X11 classification needs `DISPLAY` in the placement
  service's environment. Hyprland exports it to the systemd user
  environment (checked on this machine). Without it, small XWayland
  windows are left unplaced rather than risk moving a popup.
* **Monitor geometry.** The X11 lookup matches X windows to Hyprland
  windows by exact geometry. That was verified on one monitor at scale 1,
  which is what your config uses. With fractional scaling plus
  `xwayland:force_zero_scaling`, or Xwayland coordinates offset on a
  multi-monitor layout, matches would fail. Every XWayland window would
  then count as "unknown":
  * small ones left alone;
  * a large override-redirect menu (over 5% of the screen) placed again.
* **Not reviewed.**
  * The Wi-Fi password dialog (`WifiPasswordDialog.qml`, a separate
    Quickshell window) was not rendered or redesigned in this pass.
  * `GlassButton`'s new `danger` variant exists but has no caller yet; the
    shell's destructive actions are icon buttons, which already had a
    hover-only red tint.
* **Parentless Wayland popups.** A Wayland app that makes a *parentless*
  popup as a toplevel would still be placed. Hyprland exposes no parent or
  type for Wayland toplevels; real tooltips and menus are `xdg_popup`s.
* **Unchanged from phase 1:** the `_shape_is_coherent` standalone-dialog
  allowance, and ffmpeg as an optional dependency.
* **Needs your real desktop:**
  * real Chromium/Electron/Steam tooltips (the probes were GTK);
  * your monitor's blur;
  * your app mix;
  * the lock screen with real PAM.

## Commits (on top of `22a1c9e`)

| Commit | What |
|---|---|
| `4dedd4a` | New windows join the cloud; tooltips and hover cards are never placed |
| `853bd70` | "Automatic window placement" and "Reduce motion" switches in Settings |
| `70a0f7a` | One interaction language: press, busy, empty, error, transitions |
| `645c563` | Dock icons name themselves; bar islands answer the pointer; Taskbar's third group is a card |
| `c56b3eb` | Slider value mark struck through its label at small values |
| `c7272d8` | Experience category subtitle no longer truncated; report and evidence images |

## Final test run (branch tip)

Python and shell suites run sandboxed: no compositor, no session bus, and
system commands replaced by fakes that log and refuse. The only refused
calls in the log came from the launch-systemd test's own probe.

| Suite | Result |
|---|---|
| Python (13 suites) | **329 tests, all pass**: placement 171, auto-place-cloud 33, force-close 27, copy-once 22, manifest 15, integrity 14, hypr-ipc 13, taskbar-wrap 12, migrate 7, wallpaper-theme 6, apply-theme 5, sddm-install 3, reconnect 1 |
| Shell (6 suites) | install-cycle, installer-lifecycle, launch, legacy, polkit: all assertions pass. launch-systemd skips in the sandbox by design; run outside it (isolated transient units only), all assertions pass |
| QML (13 suites) | **113 test cases pass**: add-shortcut 10 (x3 sizes), app-launch 2, behavior-settings 5, branch-geometry 9, customization 5, input-regions 10 (x4 sizes), interaction 8, level-bar 2, panel-fit 9, panel-motion 20, theme-draft 11, theme-palette 18 (x3 sizes), top-bar 4 (x5 sizes; 1 skip that applies only at 1920 wide) |
| Gallery | 19 scenes x 4 sizes render with no QML warnings |

## Review and merge

```sh
git -C ~/dxrice log --oneline c959d2e..phase1
# save your work first: the merge hot-reloads the running shell, and the
# placement service picks up the new code when it restarts
# note: ~/dxrice is currently on branch claude/task-kcttpa (at c959d2e),
# not main -- the merge lands on whichever branch it is on
git -C ~/dxrice merge --ff-only phase1
systemctl --user restart dxrice-auto-place-window.service
```
