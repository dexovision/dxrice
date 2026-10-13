# Phase 2: visual modernization report

This work is on branch `phase1` in the worktree `/home/dexo/dxrice-phase1`, on top of `a255476`
(verified before starting: branch, tip, a clean tree, and the live checkout
`~/dxrice` still at `c959d2e`). Nothing was merged or pushed.

Commits are authored as `dexo <dexovisio@gmail.com>` with no AI attribution. The brief says
`dexovision`; you corrected that typo earlier.

## How this was validated: no live desktop

You were using the PC, so everything ran offscreen or in fakes:

* **Offscreen QML harness.** It loads the real shell QML with stubbed compositor types,
  points HOME/XDG dirs at a throwaway directory seeded from the repo, and replaces every
  shell subprocess with fixture output. I inspected it first: the only real subprocesses
  are the test files re-launching themselves per screen size.
* **Sandbox wrapper.** All Python, shell and QML suites ran through it. It unsets
  WAYLAND_DISPLAY, HYPRLAND_INSTANCE_SIGNATURE, DISPLAY and the session bus, and puts
  logging fakes for `hyprctl`, `qs`, `systemctl`, `sudo`, `pacman`, `grim` and similar
  first on PATH.
* **No nested Hyprland.** It runs as a window on your real desktop, and your real
  placement service would act on it.
* **Blur not verified.** Offscreen renders have no blur.
* **Design research.** Caelestia was studied through its public source on GitHub (read
  only).

## 1. Design system changes (`quickshell/Theme.qml` and the shared components)

**Typefaces.** There are three faces, one per job (see §3):

| Token | Used for |
|---|---|
| `fontFamily` | interface text |
| `fontMono` | fixed-width values: commands, hex codes |
| `iconFamily` | Nerd Font glyphs |

The type scale, weights and tabular figures (on clocks, values and the OSD) are applied
through these tokens.

**Surfaces.** Cards are tonal, with no outline on every group. Their titles are real
section headings (medium weight, secondary opacity) instead of 11px whispers. Preview
regions match.

**Sliders.** There is now one slider language. `FillSlider` (Theme editor, Taskbar) used
to be a full-height slab with its label baked in: a third grey layer inside every card,
and unlike Quick Settings' sliders. Now:

* the name and value sit on one line;
* a slim neutral track sits below;
* the accent appears only as the progress;
* the knob grows under the pointer and while held (not under reduce motion);
* the value glides when it jumps.

It has no wheel handler, so scrolling a settings page can't change a value. The API is
unchanged.

**Text fields.** There is one field: `InputField.qml` (soft fill, hover, an accent edge on
focus, optional leading glyph, compact size). It replaced:

* Add Shortcut's private copy;
* the Theme editor's hand-drawn search box;
* the Taskbar's underline-only command fields;
* the colour picker's hex box;
* the Wi-Fi dialog's box.

The lock screen's pill field is the one deliberate exception.

**States.**

* **Loading:** `LoadingDots` (phase 1).
* **Success:** Apply now shows a brief "✓ Applied", cleared by the next edit; before,
  success was silent.
* **Error:** red text, plus a red field edge on the lock screen.
* **Selected:** an accent edge and check on the current colour preset; before, nothing
  marked it.

**Motion.** The phase-1 grammar is kept (curves and durations already match Caelestia's
M3 model: decelerating enter, accelerating exit, short effects). The tokens from that pass
cover everything new: `durationMove`, `pressScale` and `contentShift` all honour reduce
motion. Under reduce motion the OSD's pop-in scale and the slider knob's growth are
skipped.

## 2. Surfaces

| Surface | Change |
|---|---|
| Quick Settings | Proportional type throughout. The hero clock is light weight with tabular figures; tiles, lists and cards read as one family. Scanning and empty states from phase 1 kept. |
| Theme editor | Settings-app look: unified sliders, tonal cards with real section titles, the shared search field, tonal preset chips that mark the current preset, round swatches, an even demo row on Experience ("Motion and spacing"), a new two-card **Fonts** page, the Apply success state. Apply / Revert / drafts / presets / migrations untouched. Automatic placement and Reduce motion stay on Experience. |
| Taskbar editor | Unified slider and fields; cards tonal; shortcut editing, modules and launching unchanged. |
| Dock | Tooltip and hover from phase 1, now in the interface face. No new pointer-driven compositor actions. |
| Top bar | Clock: the time bold, the date lighter after it ("11:26  Tue Oct 13") instead of one space-padded string. |
| OSD | A pill: icon, a thicker level bar, the value right-aligned in tabular figures, instead of a small card with a thin line. **It no longer takes input**: while visible it swallowed clicks on whatever was under it for 1.6s. |
| Lock screen | The clock is a step above Quick Settings' size, in light weight, with a larger date. The card is positioned from the clock's real height instead of a fixed offset. PAM handling untouched. |
| Wi-Fi password dialog | Network icon, name and "This network needs a password"; the shared field with a show/hide toggle; Cancel and Connect; sized to its content. |

**Evidence** (offscreen, no blur, 1920x1080; the full gallery was also rendered at
1366x768, 1280x720 and 1024x768, with no QML warnings in any of the 23 scenes x 4 sizes):

* `docs/phase1/phase2_before_after.png` compares `a255476` with now: Quick Settings,
  Theme editor Layout and Fonts, Taskbar, lock screen, OSD, top-bar clock.
* `docs/phase1/phase2_states.png` shows the Wi-Fi dialog, Wi-Fi scanning, a wrong lock
  password, and the Experience page.

## 3. The font decision

* **New key.** Interface text uses the new optional theme.json key `ui_font_family` (Theme
  editor › Fonts › *Interface font*).
* **When the key is unset** (true of every existing config), nothing is written to your
  file:
  * if `font_family` is still the shipped JetBrains Mono, the interface uses **Noto
    Sans**;
  * if you had changed `font_family`, the interface keeps using your font, so a choice
    made before the split is preserved.
* **`font_family` keeps its role.** It is still the Waybar / wofi / mako / kitty font, and
  the shell's face for fixed-width values and icons (*Terminal and bar font* on the same
  page).
* **Why Noto Sans.** It is a proportional face the installer already ships:
  * Arch `noto-fonts`;
  * Debian `fonts-noto`;
  * openSUSE `noto-sans-fonts`;
  * Fedora's list had only the metadata package `google-noto-fonts-common`, so
    `google-noto-sans-fonts` was added (package name not verified on a Fedora system).
* **If it's missing anyway,** fontconfig substitutes another sans.
* **Icons.** Nerd Font glyphs inside interface strings render through Qt's font fallback
  (checked offscreen); glyph-only text names the Nerd Font explicitly.
* **Tested:** default, a kept custom font, explicit, blank.

## 4. Tests

* **Python:** sandboxed, all pass.
* **Shell:** sandboxed, all pass.
  * `dxrice_test_launch_systemd.sh` **skipped**: outside the sandbox it creates transient
    units on your real user systemd, which this brief rules out.
* **QML:** 14 suites, all pass.

New suite `tests/qml/test_design_system.py` (6 tests):

* typeface resolution across five configurations;
* interface font through Apply (unknown keys kept, terminal font untouched) and Revert;
* cards unoutlined;
* the OSD never taking input;
* the Wi-Fi dialog: Connect disabled when empty, reveal, submit, and the password not in
  any log output;
* Apply's success state appearing and clearing.

Updated tests:

* `test_interaction.py`: the accent test now checks the new slider (neutral track, thin
  accent progress).
* `test_theme_draft.py`: a successful Apply may now show "✓ Applied" (still no error and
  no draft notice).

| Suite | Result |
|---|---|
| Python (13) | 329 tests pass: placement 171, auto-place-cloud 33, force-close 27, copy-once 22, manifest 15, integrity 14, hypr-ipc 13, taskbar-wrap 12, migrate 7, wallpaper-theme 6, apply-theme 5, sddm-install 3, reconnect 1 |
| Shell (6) | install-cycle, installer-lifecycle, launch, legacy, polkit pass; launch-systemd skipped (see above) |
| QML (14) | add-shortcut 10 (x3 sizes), app-launch 2, behavior-settings 5, branch-geometry 9, customization 5, design-system 6, input-regions 10 (x4 sizes), interaction 8, level-bar 2, panel-fit 9, panel-motion 20, theme-draft 11, theme-palette 18 (x3 sizes), top-bar 4 (x5 sizes, 1 skip that applies only at 1920 wide) |

**Placement untouched.** Placement, SUPER+G, popup classification and the
auto-placement switch were not modified in this phase. Their 204 Python tests
(placement 171, auto-place-cloud 33) pass unchanged.

**Performance.**

* No new continuous animations. LoadingDots runs only while visible; the Experience speed
  demo stops when hidden and under reduce motion.
* No new subprocesses or dependencies. Noto Sans was already installed by the installer
  everywhere except, possibly, Fedora.
* Live CPU and RSS were **not** re-measured: that needs a running shell, which means the
  nested compositor.

## 5. Remaining limits and open issues

* **Blur and the real compositor.** Not verified this phase; offscreen only (see above).
  Panels with blur were checked in phase 1.
* **Pre-existing security issue, found by the new dialog test.** `WifiBackend.qml` passes
  the Wi-Fi password to `nmcli` as a command-line argument (`... password <pw>`), which
  any local user can read in the process list while `nmcli` runs. The fix is to feed it
  on stdin with `nmcli --ask`. It needs a real network connection to verify, so it wasn't
  changed blind. The dialog itself never logs the password (tested).
* **Fedora package name.** `google-noto-sans-fonts` is unverified on Fedora.
* **Lock screen with real PAM.** Not exercised.
* **Theme editor at 1024x768.** It still scrolls (allowed: it's one of the two surfaces
  you said may scroll).
* **Carried over.** Placement-related open questions from `REPORT_CLOUD_UI.md` §6 are
  unchanged (old Stage 2/3 code kept, startup sizing, X11 geometry assumption).

## 6. No live interaction

Verified from this session's actions and logs, not assumed:

* **Real processes not restarted.** The live Quickshell (pid 1088,
  `/home/dexo/dxrice/quickshell`) and placement service (pid 1095) both still show
  `started Mon Oct 12 11:25:33`. Neither was reloaded, restarted, signalled or queried
  (no `qs ipc`).
* **No live compositor calls.** No `hyprctl` and no `systemctl --user` against the live
  session. The only `systemctl` attempts in the sandbox's refusal log are the
  launch-systemd test's own probe (`--user show-environment`), refused by the fake.
* **No live screenshots or nested session.** No screenshots of the real desktop; no
  nested compositor this phase.
* **No config or install changes.** No changes under `~/.config`; nothing installed. The
  only system queries were read-only (`fc-list`, `fc-match`, `pacman -Q noto-fonts`).
* **Live checkout untouched.** `~/dxrice` is unchanged at `c959d2e`; worktrees are the
  same two as at the start.

## Commits (on top of `a255476`)

| Commit | What |
|---|---|
| `04002d6` | Proportional interface type; one slider, field and card language |
| `a32c88b` | OSD as a click-through pill; lock clock carries the screen |
| `49e6247` | Refinement pass: presets, swatches, clock, last hand-drawn field |
| `b989685` | Report, evidence, theme-draft test updated for the success state |
