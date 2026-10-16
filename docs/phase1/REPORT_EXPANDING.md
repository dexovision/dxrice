# Galaxy Spiral: an expanding spiral, not a ring

> **Refined in [REPORT_REFINE.md](REPORT_REFINE.md):** the gap now widens
> linearly and more gently (about 46 / 50 / 59 px at 0.5 / 1 / 2 turns, at
> most 2× the target). The geometry below is unchanged; its spacing numbers
> are the earlier, steeper curve.

Follows [REPORT_GEOMETRY.md](REPORT_GEOMETRY.md), whose fixed-gap geometry
this replaces. The acceptance criterion: the rendered output, without
arrows or labels, should read immediately as an airy spiral that winds
outward, with more breathing room on its outer turns.

Everything was tested offline: unit tests, an in-memory Hyprland, and renders
of the real `place_new_window` / SUPER+G output. Nothing touched the live
desktop.

## Why the previous geometry read as a ring

- **Constant clearance from the anchor's outline.** Each window was placed at
  a growing edge-to-edge clearance from the anchor's rectangle. The curves of
  constant clearance around a rectangle are rounded rectangles with long
  straight sides. Windows on those sides stacked into rows and columns, and
  the first turn hugged the anchor.
- **Small growth per turn.** One window's depth plus 42 px per turn is
  barely visible against the radius, so twelve windows read as a closed
  ring, with later windows looking appended.
- **One fixed 42 px gap everywhere.** That made a mechanical, uniform
  spacing.
- **Distance as the larger of the two axis gaps.** Diagonal neighbours sat
  visibly further apart than aligned ones at the same nominal gap.

## The new geometry

The model is in `scripts/dxrice_spiral.py`. Auto-placement (`join`) and
SUPER+G (`arrange`) both use it.

- **An Archimedean spiral of window centres** round the anchor's centre.
  - The radius grows continuously with the clockwise angle, by
    `SPIRAL_OPENING` = 1.8 typical window depths along that bearing, plus the
    gap, per turn. 1.0 would only just clear the turn inside; 1.8 is what
    reads as a spiral (opening 1.0, 1.4, 1.8 and 2.2 were compared by
    render).
  - The spiral is stretched along the anchor's longer side, by the anchor's
    aspect ratio to the power 0.75 (`SPIRAL_STRETCH`), at most 1.6:1. A wide
    anchor's ends are then wrapped instead of skipped, and the whole thing
    sits on a 16:9 screen without coming out taller than wide.
- **The curve is a guide, the footprint is what must clear.**
  - Each window's own rectangle must be the gap clear of every other window
    and fixed window.
  - Distance is the true distance between rectangles (`dist`): the gutter
    for facing neighbours, corner to corner for diagonal ones. It is the same
    rule in every direction.
- **Advance, never push.**
  - A window sits exactly on the curve.
  - If its spot conflicts, it advances along the same curve in 1° steps,
    then bisects to the first clear spot. It is never pushed off the curve,
    drawn inward, or put in a convenient hole.
  - Window 2 starts at the upper right (−55°), just clear of the anchor.
- **Spacing has two parts.**
  - The **minimum** (`window_spacing_min`, 32 px) is the hard floor.
  - The **target** grows with the window's radial progress p, in turns:
    target × (1 + p(1+p)/8), at most 2.5 × the target. The target is 42 px
    from the default 32–56 range.
  - Measured on uniform windows:

    | turn | gap range | median |
    |---|---|---|
    | inner | 43–56 px | 49 px |
    | middle | 54–80 px | 64 px |
    | outer | 77–90 px | 82 px |

    The brief's tuning ranges were inner 40–48, middle 56–72 and outer
    80–104 px.
  - **With realistic application windows the widening is modest.** On a
    1080p screen, 16 windows rarely get past the middle turn. Measured
    medians are 48 px on the inner turn (range 43–62) and 57 px on the
    middle one (51–65); the outer turn is barely reached. The breathing room
    grows visibly at reference proportions, and only by about 43 → 57 px
    with real apps. Two levers widen it:
    - `SPACING_GROWTH`: how fast the gap grows per turn;
    - `SPIRAL_OPENING`: how far apart the turns are.
  - It is one smooth curve, the same for every direction, independent of
    window size. Window size only enters through the footprint.

Unchanged:
- the anchor at the usable centre;
- auto-placement never moving an existing window;
- SUPER+G replaying creation order and keeping sizes, with a second press a
  no-op;
- closing never collapsing anything;
- no hole filling;
- fixed windows as obstacles;
- outer windows allowed off screen;
- the SUPER+C, popup and attached-dialog behaviour.

## Renders

All are real placement output, in `docs/phase1/spiral/expanding/`. They
use the clean style: windows only, no labels, arrows or gap marks.

| sheet | what |
|---|---|
| [reference_vs_spiral.png](spiral/expanding/reference_vs_spiral.png) | The reference's diagram beside 12 and 16 windows at the same pixels per screen pixel. |
| [growth_uniform.png](spiral/expanding/growth_uniform.png) | 2, 4, 6, 8, 12 and 16 windows at reference proportions. |
| [growth_mixed.png](spiral/expanding/growth_mixed.png) | 2, 4, 6, 8, 12 and 16 mixed application windows. |
| [shapes.png](spiral/expanding/shapes.png) | Very wide and very tall windows. |
| [obstacles.png](spiral/expanding/obstacles.png) | A pinned window in the arm's way, a fullscreen window, a screen-sized anchor, and the six 826×493 terminals after SUPER+G. |
| [closing.png](spiral/expanding/closing.png) | The middle, the newest or the anchor closed, a new window opened (outlined), then SUPER+G. |
| [measures.png](spiral/expanding/measures.png) | Radius against angle (a straight line) and each window's gap, by turn. |
| [before_after.png](spiral/expanding/before_after.png) | The same windows through 957792b (top) and this version (bottom). |

Regenerate with:

    python3 scripts/dxrice_spiral_render.py --geometry scripts --reference IMAGE \
        --compare 957792b=OLD/scripts docs/phase1/spiral/expanding

What the renders show:
- With 12 windows, the arm ends at the upper left, short of window 2. With
  16, its second turn passes clearly outside window 2 at the top right.
- Gaps visibly widen outward.
- The before/after sheet shows the old tight ring and packed cloud next to
  the open spiral.
- Weak spots are listed under limitations.

## Measurements

Random window sets; the "spiral frame" is the model's own (`spiral_coords`).

| | realistic sizes | reference-like | extreme |
|---|---|---|---|
| clockwise advance per window, p50 / p90 / p99 / max | 31 / 54 / 75 / 116° | 32 / 52 / 64 / 89° | 31 / 60 / 97 / 151° |
| spiral radius steps inward | 0 / 2,335 | 0 / 2,406 | 0 / 2,386 |
| straight-line fit of radius against angle, R² median (p10) | 0.998 (0.993) | 0.999 (0.998) | 0.995 (0.984) |
| smallest gap anywhere | 43 px | 43 px | 43 px |

**Gap smoothness.** Unobstructed, a window's gap is never more than 0.2 px
narrower than the one before it (uniform windows), and never more than
8 px with mixed sizes (tested).

**Same rule in every direction.** The median nearest gap is within 4 px for
windows at axis bearings and at diagonal ones (tested; measured 51 vs 50).

**Obstacles.** One fixed window in the way:
- per-window advance p99 rises from 74° to 104°, max 150°;
- extra total winding: median 0°, p90 29°, max 71°;
- the spiral radius still never shrinks, and nothing comes closer to the
  obstacle than the gap.

With 300 random *large* fixed windows, up to a whole screen, the largest
single advance was 224° and the hard minimum held everywhere. The march's
eight-turn cap was never reached. If it ever were, the window now steps
straight outward until clear. The previous fallback returned an unchecked
spot, and a forced test showed it overlapping by 419 px.

**Time with fixed windows.** With a fullscreen window over the screen, 16
windows take at most 8 ms to arrange, and a single placement takes at most
2 ms. Bench buckets, p95 of press 1, 957792b → this:

| bucket | 957792b | this |
|---|---|---|
| obstacle | 3 ms | 4 ms |
| fullscreen | 3 ms | 5 ms |
| wide | 3 ms | 3 ms |
| tall | 3 ms | 2 ms |

### Benchmarks against 957792b

**SUPER+G** (`dxrice_spiral_bench.py`, 291 realistic desktops):

| | 957792b | this |
|---|---|---|
| spiral fit R², plain screen frame, median (p10) | 0.537 (0.084) | 0.768 (0.347) |
| gap by turn, inner / middle | 42 / 42 px (flat) | 46 / 55 px |
| erratic gap drops (> 8 px) | 11 | 1 |
| nearest gap, min / median | 42 / 42 px | 43 / 46 px |
| overlaps / moved on press 2 / resized | 0 / 0 / 0 | 0 / 0 / 0 |
| press 1, 10–12 windows, p95 | 8 ms | 5 ms |
| press 1, 13–20 windows, max | 16 ms | 7 ms |

The plain-screen R² is lower than in the spiral's own frame (0.998) for two
reasons: the deliberate stretch makes the plain screen radius dip slightly
from the long side to the short side, and most benchmark desktops have only
3–12 windows.

**Auto-placement** (`dxrice_autoplace_report.py`, 200 sequences, 1,002
opens):

| | 957792b | this |
|---|---|---|
| an open moved or resized an existing window | 0 | 0 |
| new window overlapping / not at the spacing | 0 / 0 | 0 / 0 |
| SUPER+G accepts the result as is | 200 / 200 | 200 / 200 |
| dead area, mean | 44,268 px² | 5,688 px² |
| screen covered, median | 0.49 | 0.41 |
| opened mostly off screen | 727 | 772 |
| taller than wide | 17 / 200 | 30 / 200 |

**Runtime of `arrange`:** 4 windows 0.7 ms, 8 windows 1.6 ms, 16 windows
4.6 ms, 24 windows 7.1 ms.

## Tests

All 14 Python suites (384 tests) and 6 shell suites pass, run sandboxed.
`launch_systemd` skips because there is no user manager in the sandbox.

New in `dxrice_test_spiral_growth.py` (27 → 33 tests):
- `test_it_is_an_archimedean_spiral`: the radius grows with the angle, and
  a straight line fits (median R² > 0.99, p10 > 0.97). A ring or appended
  windows would fail.
- `test_gaps_widen_turn_by_turn`: median gap per turn in 44–54 / 58–72 /
  78–100 px.
- `test_gap_progression_is_smooth`: no gap more than 8 px narrower than the
  previous one.
- `test_the_same_distance_rule_in_every_direction`: axis-bearing and
  diagonal-bearing gaps agree within 4 px.
- `test_obstacles_are_gone_round_along_the_spiral`: a bounded detour, the
  radius never shrinks, and the gap to the obstacle is kept.
- `test_past_the_march_cap_the_gap_is_still_kept`: forces the fallback.
  It fails on the previous fallback.

Changed tests, with the reason in each docstring:
- **Spacing helpers.** `spacing_violations`, `assert_composed`, the cloud
  `_sep` / `_in_band`, and the "within reach of a neighbour" bounds now
  measure with `dist` and allow up to `widest_gap` (105 px by default),
  because the gap widens outward by design. The minimum is still checked
  for every pair, including diagonal pairs.
- **Bounded advance.** It now asserts the spiral radius never shrinks.
  Edge clearance from the anchor isn't monotone: a bigger window's edges
  come closer at the same radius.
- **`test_4`** uses 16 windows, because the roomier first turn holds more
  than 12.
- **`test_8d` (anchor closed)** no longer requires the new window to be
  within reach of a neighbour. See limitations. SUPER+G afterwards must
  compose everything.
- **The vertical-stack test.** Axial concentration scores the spiral's
  opening arc (windows 2–4, upper right to lower right, as in the
  reference) about like a stack. It now asserts the stack itself is gone:
  - no shared column;
  - no grid seam;
  - the arm winds clockwise.

## Limitations

- **A relaxed test and a regression: closing the anchor.**
  `test_8d` no longer requires the next window to land within reach of a
  neighbour, because with this geometry it may not. The arm was wound round
  the closed anchor, and continuing it round the earliest survivor can land
  the next window in open space: legal (no overlap, the minimum kept) but
  detached. 957792b's fixed-gap model kept it attached. The next SUPER+G
  re-winds everything, and the test asserts that. The model only sees
  rectangles, so it can't tell a closed anchor from a moved one.
- **Extreme aspect ratios.** Twelve 1300–1700 px wide strips pile into a
  five-high stack where the arm passes the left side. Twelve narrow tall
  windows form a curved row along the bottom. It is still the spiral, but at
  those proportions the arc holds many windows side by side (`shapes.png`).
- **Short columns on the sides.** Where the arm passes the far left and far
  right, two consecutive windows can line up vertically, as windows 8 and 9
  do in the reference.
- **A fullscreen window over the whole screen.** Windows can only sit where
  the spiral passes outside it, so they form a sparse cross round it
  (`obstacles.png`).
- **Plain screen distance.** It dips slightly as the arm goes from the
  stretched long side to the short side. Along the spiral itself it never
  does.
- **The reference's inner turn is airier.** The reference leaves more room
  between the anchor and its first ring than the 42–56 px inner gaps here.
  `window_spacing_min/max` in theme.json scales *every* gap
  proportionally: 64/112 would double them, so the outer turns would reach
  about 210 px. That is no longer the "match the picture" setting
  REPORT_GEOMETRY.md suggested.
- **Screen coverage.** Coverage is lower and more windows open partly off
  screen, as the expanding gaps intend. The anchor stays visible.

## Compatibility and activation

- `dxrice_auto_place_window.py` is unchanged. The running placement daemon
  imports `dxrice_spiral` / `dxrice_auto_arrange` lazily, and its 39bddfa
  code with the new modules passes all 39 of its own placement tests.
- **Nothing was activated.** The live checkout `~/dxrice` is still at
  39bddfa; the previous geometry wasn't activated either. To activate:
  1. `git -C ~/dxrice merge --ff-only origin/claude/task-kcttpa`. After that,
     SUPER+G and SUPER+C use the new code on their next press.
  2. `systemctl --user restart dxrice-auto-place-window.service` for
     auto-placement. Otherwise the daemon picks the new code up on its first
     import of the module.
