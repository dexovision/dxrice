# Galaxy Spiral geometry: one deterministic model

> **Superseded by [REPORT_EXPANDING.md](REPORT_EXPANDING.md).** The geometry
> is now an expanding Archimedean spiral with gaps that widen outward. The
> fixed 42 px gap and the 64/112 spacing suggestion below no longer apply.

Follows [REPORT_GROWTH.md](REPORT_GROWTH.md). The acceptance criterion was
the visual reference ("Galaxy Spiral Window Layout — Target Behavior for
DXrice"). Everything was tested offline: unit tests, an in-memory Hyprland,
and renders of the real `place_new_window` / SUPER+G output. Nothing
touched the live desktop.

## What changed

`scripts/dxrice_spiral.py` is now one small deterministic geometry model.
New-window placement and SUPER+G both use it:

- **Anchor.** The first window created is the anchor. It is centred on the
  usable area, which excludes the bar and dock. If a fixed window
  (fullscreen, pinned) is within the gap of that spot, the anchor is pushed
  clear of it.
- **The step.** `next_rect` places each new window from three things only:
  the anchor, the previous window (the tip), and what it must clear.
  - It starts at the tip's bearing round the anchor and turns clockwise.
    Window 2 starts at the upper right, −55°.
  - Clearance from the anchor grows smoothly: one pitch per turn, where the
    pitch is the median window short side plus the gap. The window's own
    width and height are accounted for at every bearing.
  - A window may be pushed outward past an earlier turn, by up to half a
    pitch.
  - If it can't sit there, it advances along the spiral to the first clear
    bearing, to a fraction of a degree. It never looks for vacancies or
    back-fills to be compact.
- **Spacing is a hard constraint.** Every window is at least the target gap
  (42 px, from the 32–56 band) from every other window and every fixed
  window. Every window is exactly the target gap from its nearest window
  or fixed window, so nothing touches and nothing floats.
  - Across the 291 benchmark desktops, 99% of windows have another window
    in the band as their nearest neighbour.
  - The remaining 1% sit beside a fixed window only.
- **Fixed windows.** The arm goes round a fixed window when a detour of up
  to 45° clears it. Otherwise the window is pushed past it, as with a
  fullscreen window over the whole screen. Pushing outward every time would
  inflate every later window's radius. Detouring every time would strand
  windows on the far side of a large obstacle. Both happened in testing.
- **SUPER+G (`arrange`)** replays the same step for every window in creation
  order (Hyprland's `stableId`, else the client list order). Sizes are
  always kept.
- **Auto-placement (`join`)** is that step for one new window, with every
  existing window held where it is. Replay and incremental growth are
  bit-identical; this is tested over 200 random mixed sets, with and without
  obstacles. So after undisturbed auto-placement, SUPER+G moves nothing.

The removed composer (`compose`, `anchor_index`, `sweep_state`, vacancy
scoring, SUPER+G resizing) is about 1,000 lines. `dxrice_auto_arrange.py`'s
`auto_arrange` is now a sort plus `arrange`.

Kept unchanged:
- the SUPER+C process-tree fix;
- attached dialogs moving with their parent;
- the transient and unknown-popup rule;
- the usable-area handling.

## Against the reference

Measured on the reference image, scaled to a 1920-wide screen, and on the
model with the same proportions. The anchor is 381×225 and the ring
windows 262×125.

| | reference | model, 32–56 (default) | model, 64–112 |
|---|---|---|---|
| window 2 | upper right, −53° | upper right, −55° | upper right, −55° |
| direction | clockwise | clockwise | clockwise |
| windows in the first turn | 11 | 10 | 10 |
| clearance from anchor, w2 → w12 | 84 → 309 px | 42 → 222 px | 84 → 310 px |
| gaps between windows | ~40–135 px, uneven | 42 px | 84 px |

Structurally the model is the reference: anchor centred, clockwise from the
upper right, one ring for the first ten or eleven windows, then outward.

The difference is airiness. The illustration is drawn at about twice the
gap its own text asks for ("32–56 px, target ~40–44"). With the default
band the ring reads noticeably tighter than the picture. With
`window_spacing_min/max` = 64/112 in theme.json it matches the picture's
clearances almost exactly (84 → 310 against 84 → 309). The default stays
at the spec's numbers. **Which one is right is your call**, and switching
is a theme.json edit, no code. See
[spacing_default_vs_airy.png](spiral/geometry/spacing_default_vs_airy.png).

## Behaviour changes to sign off

- **Anchor.** The anchor is the first-created window, not the largest one.
- **Fixed start and direction.** Window 2 always starts upper right, and
  the arm always turns clockwise.
- **SUPER+G rebuilds from creation order** and ignores current positions.
  - A hand-made layout is rebuilt on the first press. Every later press is
    a no-op.
  - A layout you panned away from comes back bit-identical, anchor at the
    centre.
- **SUPER+G after a close tidies up.** Closing a window moves nothing, and
  the arm carries on from its tip. A later SUPER+G press replays without
  the closed window, so the windows created after it close up the arm. The
  ones created before it don't move. This is deliberate: an explicit press
  tidies, a close never collapses. Tested in
  `test_super_g_after_a_close_rebuilds_only_what_came_after`.
- **Hole reuse.** A hole in the middle of the arm is not back-filled. The
  tip's own hole is, since that keeps the progression: the next window of
  that size retakes the spot. If the anchor closes, the earliest survivor
  is the anchor from then on.
- **Spacing default** is now 32–56 px (target 42), up from 16–24.
- **No resizing.** SUPER+G never resizes. Its resize-memory plumbing in
  `main()` is now inert: it records nothing, because nothing resizes.

## Renders (real place_new_window / SUPER+G output)

All six are in `docs/phase1/spiral/geometry/`:

- [reference_vs_model.png](spiral/geometry/reference_vs_model.png): the
  reference beside 12 windows at reference proportions and 12 mixed
  application windows.
- [spacing_default_vs_airy.png](spiral/geometry/spacing_default_vs_airy.png):
  the reference, then the default band and 64/112.
- [growth_reference.png](spiral/geometry/growth_reference.png) and
  [growth_mixed.png](spiral/geometry/growth_mixed.png): 1, 2, 3, 4, 6, 8
  and 12 windows opened one by one, then SUPER+G (unchanged).
- [closing.png](spiral/geometry/closing.png): the middle, the tip or the
  anchor closed, a window opened, then SUPER+G.
- [special_cases.png](spiral/geometry/special_cases.png):
  - your live test's six 826×493 terminals, before and after SUPER+G;
  - a pinned window in the arm's way;
  - a fullscreen window over the screen;
  - an anchor as big as the screen.

Regenerate with:

    python3 scripts/dxrice_spiral_render.py --geometry scripts --reference IMAGE docs/phase1/spiral/geometry

## Tests

All 14 Python suites (378 tests) and 6 shell suites pass, run sandboxed.
`launch_systemd` skips because there is no user manager in the sandbox.

`dxrice_test_spiral_growth.py` went from 20 to 27 tests.
- New `TestGeometryModel`:
  - replay equals incremental, bit-identical;
  - spacing is a hard constraint, with nearest gap = target;
  - window 2 starts upper right and the arm turns clockwise;
  - bounded advance with never-shrinking clearance.
- New closing cases:
  - a closed tip is retaken;
  - a closed anchor is handed to the earliest survivor;
  - SUPER+G after a close moves only later windows.
- "One press at most" became "the first press moves nothing".

Rewritten tests in `dxrice_test_placement.py`. Each docstring says why:
- Determinism now uses `stableId` and still asserts input-order
  independence.
- Recentring now asserts SUPER+G's own result is a fixed point and that a
  far-away layout comes home bit-identical.
- The five resize tests now assert sizes are kept, nothing resize-related is
  dispatched or recorded, and results don't depend on earlier calls.
- The hand-made staircase now settles in one press.

Two real bugs were found and fixed on the way:
- The anchor could touch a fullscreen window (gap 0).
- A fixed window in the arm's way inflated the radius of every window after
  it, by up to 2× in one case.

## Benchmarks (against 39bddfa)

**SUPER+G** (`dxrice_spiral_bench.py`, 291 realistic desktops):

| | 39bddfa | this |
|---|---|---|
| press 1, 10–12 windows, p95 | 119 ms | 5 ms |
| press 1, 13–20 windows, max | 287 ms | 11 ms |
| nearest gap: min / median | 16 / 20 px | 42 / 42 px |
| arm clockwise (creation order) | 0.52 | 1.00 |
| moved on press 2 | 4 / 291 | 0 / 291 |
| resized | 53 | 0 |
| overlaps | 0 | 0 |
| fill (median) | 0.51 | 0.55 |

The old "sweep / rotation / centrality" metrics measure the old objective:
prominence order round the largest window. They drop as expected
(sweep 0.86 → 0.63, centrality 0.71 → −0.43), because the anchor is now the
first window, not the largest.

**Auto-placement** (`dxrice_autoplace_report.py`, 200 sequences, 1,002
opens):

| | 39bddfa | this |
|---|---|---|
| an open moved or resized an existing window | 0 | 0 |
| new window overlapping | 0 | 0 |
| SUPER+G accepts the result as is | 106 / 200 | 200 / 200 |
| opening-order sweep | 0.96 | 1.00 |
| screen covered (median) | 0.65 | 0.49 |
| opened mostly off screen | 673 | 727 |

Off-screen placement is allowed by the spec, and the anchor stays visible.
The wider gaps make realistic application windows on 1080p spill off screen
sooner.

## Limitations

- **Long advances with unusual shapes.** With extreme shapes, such as a
  1700×240 strip or one window much bigger than the rest, a step can
  advance up to about 180° round the anchor, and clearance can jump by up
  to about 500 px.
  - Realistic sizes: p99 is about 80° and nothing exceeded 150° (6,000
    steps).
  - Extreme sizes: 4 steps in about 4,000 exceeded 150°.
- **Creation order** comes from Hyprland's `stableId`. A client without one
  falls back to list order, which Hyprland keeps in creation order.
- **Ring tightness.** With large application windows on a 1080p screen, the
  default 42 px gap makes the ring read tightly. See the spacing decision
  above.

## Compatibility with the running daemon, and activation

- `dxrice_auto_place_window.py` changed only by a comment.
- The running placement daemon imports `dxrice_spiral` / `dxrice_auto_arrange`
  lazily. Its 39bddfa code already passes the composition in creation
  order, which is what `join` reads.
  - Checked: 39bddfa's auto-placement with the new modules passes all 39 of
    its tests.
  - The mixed case, old `dxrice_spiral` cached and new `dxrice_auto_arrange`,
    only calls `join`, which kept its signature.
- **Not yet live.** The commits are pushed to origin (`main`,
  `claude/task-kcttpa`). The live checkout `~/dxrice` was deliberately
  left at 39bddfa, because SUPER+G and SUPER+C run straight from it.
  Activation is yours:
  - `git -C ~/dxrice merge --ff-only origin/claude/task-kcttpa`. After
    that, SUPER+G and SUPER+C use the new code on their next press.
- **Auto-placement** (after that fast-forward) uses it once the daemon
  imports the module for the first time, or after `systemctl --user restart
  dxrice-auto-place-window.service`. That restart is yours to run; it was
  not done.
