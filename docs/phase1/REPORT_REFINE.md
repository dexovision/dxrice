# Galaxy Spiral refinement: gentler outward spacing

A refinement of [REPORT_EXPANDING.md](REPORT_EXPANDING.md), not a redesign.
The geometry is unchanged: an Archimedean spiral of window centres,
clockwise from the upper right round the first window, with the true
rectangle distance and advancing along the curve on conflicts. Everything
was tested offline: unit tests, an in-memory Hyprland, and renders of the
real `place_new_window` / SUPER+G output. Nothing touched the live desktop,
and nothing was activated.

## The change

One curve in `scripts/dxrice_spiral.py` (`spacing_at`):

| | gap at progress p turns | cap |
|---|---|---|
| before (69cf9f9, live) | target × (1 + 0.125·p·(1+p)) | 2.5 × target |
| now | target × (1 + 0.2·p) | 2 × target |

The target is still 42 px from the default 32–56 range, so the inner turn
keeps its spacing: both curves give about 46 px half way round it. After
that the gap grows linearly instead of quadratically:

| progress p | 0.5 | 1 | 2 | 2.5 |
|---|---|---|---|---|
| before | 46 px | 53 px | 74 px | 88 px |
| now | 46 px | 50 px | 59 px | 63 px |

A turn's pitch includes the gap, so the outer turns also sit slightly
closer to the inner ones. `SPIRAL_OPENING`, the stretch and the start are
untouched.

## Measured before → after

Real `arrange` output, 200 random sets per kind (`turns.py`, same seeds):

| set | inner median | middle median | outer median |
|---|---|---|---|
| uniform (reference-like) | 49 → 48 px | 64 → 56 px | 82 → 61 px |
| mixed application sizes | 48 → 48 px | 55 → 52 px | not reached |
| very wide | 48 → 48 px | 55 → 52 px | not reached |
| very tall | 49 → 48 px | not reached | not reached |

The 16 mixed render windows' gaps went from 43…57 px to 44…53 px.

Invariants, before and after, for every kind:
- **Clearance:** no overlaps, and the smallest gap anywhere is 43 px.
- **Radius:** never steps inward along the spiral (0 of about 9,400 steps).
- **Angular advance:** unchanged, for example uniform p50 23 → 22° and p99
  57°, mixed p50 30° and p99 72°.

**SUPER+G bench** (291 desktops, 69cf9f9 → now):
- unchanged:
  - no overlaps;
  - nothing moved on the second or third press;
  - nothing resized;
  - clockwise arm 1.00;
  - spiral fit R² median 0.768 → 0.765;
  - erratic gap drops 1 → 1;
- gap by turn: inner 46 → 47 px, middle 55 → 52 px;
- nearest gaps inside 32–56 px: 98% → 100%;
- press-1 time unchanged (10–12 windows: p95 7 ms; fullscreen: p95 8 → 9 ms).

**Auto-placement report** (200 sequences, 1,002 opens): identical on every
count:
- no window moved by an open;
- no overlap;
- every new window at the spacing;
- SUPER+G accepts all 200 as is;
- 772 opened mostly off screen;
- 30 taller than wide;
- screen coverage 0.408.

Dead area went from 5,688 to 5,379 px².

## Wide and tall windows: tried, not changed

Twelve 1100–1700 px wide strips still pile into a shelf where the arm passes
the spiral's left side. Twelve tall windows still form a curved row along its
bottom. The cause is geometric: there, a window's long side points at the
anchor, so the arm only has to step forward by its short side plus the gap.

One rule was tried: consecutive centres at least half their mean long side
apart, so the window advances further along the same curve. It is still on
the spiral and still uses true footprints.
- **Unscoped:** wide strips stagger visibly instead of shelving. But a
  benchmark layout got a window 296 px from everything, and the smooth gap
  progression broke (a gap of 100 px followed by 50).
- **Scoped** to windows of aspect ≥ 3, never pushing past twice the gap: the
  shelf barely changes and the gap progression still jumps.

Un-shelving needs gaps between consecutive elongated windows larger than
the spiral's own gap. That conflicts with the smooth, attached spacing the
spiral keeps everywhere else, so the rule was dropped rather than traded
against those invariants. Ordinary and reference-proportion windows are
unaffected either way.

## Tests

All 14 Python suites (384 tests) and 6 shell suites pass, run sandboxed.
`launch_systemd` skips because there is no user manager in the sandbox.

The one test that changed is `test_gaps_widen_turn_by_turn`. Its per-turn
bands follow the requested gentler curve:
- before: 44–54 / 58–72 / 78–100 px;
- now: 44–52 / 52–60 / 57–66 px.

It also now asserts the medians strictly increase turn by turn, so the
spacing still widens.

## Renders

In `docs/phase1/spiral/refined/`, clean style, real placement output:

- **[before_after.png](spiral/refined/before_after.png):** 69cf9f9 (live) and
  this version side by side, each pair at one scale. It covers uniform and
  mixed sets at 6, 12 and 16 windows, and the 12 very wide and 12 very tall
  windows.
- [reference_vs_spiral.png](spiral/refined/reference_vs_spiral.png)
- [growth_uniform.png](spiral/refined/growth_uniform.png)
- [growth_mixed.png](spiral/refined/growth_mixed.png)
- [shapes.png](spiral/refined/shapes.png)
- [obstacles.png](spiral/refined/obstacles.png)
- [closing.png](spiral/refined/closing.png)
- [measures.png](spiral/refined/measures.png): the gap now rises gently
  (about 43 → 58 px over two turns of 32 windows), and the radius stays a
  straight line in angle.

## Activation (not done)

1. `git -C ~/dxrice merge --ff-only origin/claude/task-kcttpa`.
2. `systemctl --user restart dxrice-auto-place-window.service`.
