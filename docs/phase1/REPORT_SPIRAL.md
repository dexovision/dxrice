# SUPER+G and auto-placement as an airy spiral

Status: implemented, tested and benchmarked offline. **Waiting for your
visual sign-off** (acceptance criterion 7), which only you can give.
Nothing here was run against the live desktop.

## Where the design came from

- **Audit section D** (2026-10-12) said the gap between SUPER+G and the
  airy spiral "isn't a tuning problem". The objective had no notion of
  angular progression, and spacing was a hard equality.
- **Its Phase 4 plan**, in this order:
  1. metrics;
  2. a spacing range separate from `gaps_in`;
  3. candidates at spacing offsets;
  4. a spiral-flow term;
  5. recalibrated dead-gap and notch scoring;
  6. new-window placement using the same range.
- **Your brief** settled decision I-1. The spiral replaces the flush 5 px
  look and the earlier "no spiral" instruction. The range is a separate
  setting and applies to new windows too.

No concept images exist on this machine or in the session logs. The
Soft / Tight / Loose Cloud Spiral direction survives only as text, so the
references were the audit's words and your briefs.

## What it does

`scripts/dxrice_spiral.py` is one composer, shared by SUPER+G
(`dxrice_auto_arrange.auto_arrange`) and new-window placement
(`join_composition`).

### Spacing

- The spacing is a range: `window_spacing_min` / `window_spacing_max` in
  theme.json, default 16 / 24.
- Each pair of neighbours gets a value inside the range by size: small
  windows sit closer, big ones get more room.
- Hyprland's `gaps_in` is not used for composition any more.
- Candidate positions are generated beside already-placed windows at that
  spacing, sliding along each side, plus the point where the preferred
  bearing crosses that side.

### The spiral, a soft preference

- The most prominent (largest) window is the hub.
- The others, in prominence order, share one sweep around it. The sweep
  is 0.9–1.75 turns, more turns for more windows, and each window's slice
  is proportional to its size.
- Each window prefers:
  - its bearing on the sweep;
  - not being closer to the hub than the window before it;
  - touching that previous window.
- These preferences are weighed against:
  - contact and nestling into the cloud;
  - slits (facing windows 25–60 px apart, which read as mistakes; further
    apart is open space and is fine);
  - collinear edges (rows, columns, grids);
  - the cluster's shape (the screen's aspect to the power 0.5) and its
    balance;
  - a small pull toward where the window already is.
- There is no fixed direction. Both turning directions from four start
  bearings are built, and a whole-composition score picks one.

### Convergence

- The current layout is kept (recentred) unless a rebuild beats it by a
  margin, so the second press is a no-op.
- A kept layout already near the screen centre isn't shifted.
- A partial recentre beside a fixed window skips the last few pixels. It
  used to creep 1 px per press.

### Resizing

- Sizes are kept.
- One window per set may shrink: the most oversized one, by one bounded
  step, only for a real whole-composition gain.
- Never once any window of the set is DXrice-resized (resize memory), or
  when the layout was kept.

### New windows

- New windows use the same candidates, spacing and spiral preference. The
  preferred bearing continues the sweep at the window's prominence rank.
- Existing windows never move.
- The composition stays about the screen centre, and the new window is
  placed where it is visible.
- Dialogs sit beside their parent at the pair's composition spacing.

### What stays and what's removed

- **Kept unchanged:** `main()`, batched dispatch, re-planning against the
  sizes clients actually took, resize memory, fullscreen windows as fixed
  obstacles, popup classification, the Settings switch.
- **Removed:** the packed solver (incremental build, notch refinement,
  rigidity gate, settle passes, about 1,900 lines). It is in git history.
- **Kept as a diagnostic:** grid and block detection, as
  `dxrice_spiral.cross_junctions` / `full_span_seams` / `rigidity`. It is
  used in tests and the benchmark, not as the objective.

## Acceptance (scripts/dxrice_spiral_bench.py)

Baseline is 0af6538, spiral is this branch. Both ran on the same 291
deterministic layouts, interleaved in one run so background load hit
both. Full output: `spiral/benchmark.txt`.

| # | Target | Baseline | Spiral | Met? |
|---|---|---|---|---|
| 1 | Rotational flow clearly above random (random angles, same counts: 0.67), target ≥ 0.85 | median 0.67, mean 0.74 | **median 0.89, mean 0.88** | Overall yes. Per bucket: 1.00 / 0.95 / **0.83** / **0.77** at 3–4 / 5–6 / 7–9 / 10–12 windows. See caveats. |
| 2 | ≥ 80% of neighbour spacing within 16–24 px | 0% (98% exactly 5 px) | **100%** | yes |
| 3 | Zero overlaps | 0 | **0** | yes |
| 4 | Stable by press 2–3 | 4 / 0 of 291 move on press 2 / 3 | **4 / 0** | yes |
| 5 | No window shrunk again across presses | 2 re-shrunk | **0** | yes |
| 6 | p95 at ≤ 12 windows no worse than baseline | 10 / 47 / 108 / 258 ms | **6 / 36 / 73 / 114 ms** | yes, every window-count bucket |
| 7 | Your visual approval | | | **pending** |

### Other measurements

- **Size→centrality** (Spearman, +1 = big windows central): median 0.43
  baseline → 0.71 spiral.
- **Fill:** 0.72 → 0.51. That is negative space by design. The arrange
  report still finds 0 enclosed holes, 0 slits and 0 stranded windows.
- **Bounding-box aspect:** 1.32 → 1.31.
- **Still a grid or block after press 1:** 77 → 0 layouts.
- **Resized on press 1:** 377 → 53 windows.
- **Median movement on press 1** (centroid-aligned): 678 → 1106 px. A
  real rearrangement moves more than a re-pack.
- **Clearance to fixed and fullscreen windows:** at least 17 px
  (baseline 5).
- **13–20 windows (stress):** p95 757 → 218 ms.
- **Wide (3440×1440) and tall (1080×1920) monitors:** only 6 layouts
  each. p95 there was 62 and 79 ms against the baseline's 45 and 48 ms.
  That's within the range of the 7–9-window bucket, but slower on those
  samples.
- **Invariant benchmark** (`dxrice_placement_benchmark.py`, 300 layouts ×
  6 presses): 0 violations.

### Auto-placement

`dxrice_autoplace_report.py`: 200 sequences, 1002 windows opened one by
one through the real `place_new_window`.

| | Baseline | Spiral |
|---|---|---|
| Existing windows moved or resized by an open | 0 | 0 |
| New window overlapping, or off the spacing | 0 | 0 |
| Taller than wide | 33 | 24 |
| Composition centre to screen centre (median) | 294 px | 281 px |
| A SUPER+G press keeps it as it is | 154 | **90** |
| Join time with 3 / 12 / 20 windows open | | 0.5 / 1.8 / 2.4 ms |

### Caveats: where a metric misleads

- **Rotation at 7+ windows.** The audit's rotation metric orders windows
  by distance from the unweighted mean centre. A one-sided arm trailing
  away from the hub scores higher than a ring wound around it. Six start
  bearings instead of four raised 7–9 / 10–12 to 0.89 / 0.83. But it did
  so by pushing the hub to one edge (size→centrality 0.93 → 0.38 on one
  fixture) and cost the 5–6-window timing.
  `spiral/rotation_metric_caveat.png` shows it; the four-start results
  are the galaxies. So 0.83 / 0.77 at 7–12 windows stands.
- **Rotation at 3–4 windows** has only two steps (n = 4) or none (n = 3),
  so it reads 1.00 almost by definition.
- **Fill.** Lower is the point here, but fill alone doesn't separate
  negative space from holes. Holes, slits and strands are measured
  separately, and all three are 0.
- **SUPER+G re-winds about 40% of auto-placed sets.** Placement composes
  in opening order and never moves an existing window. SUPER+G orders the
  whole set by prominence. Raising the keep-margin hardly changed this,
  because those sets genuinely score worse as a whole.

## Renders: actual algorithm output

All in `spiral/`. Each panel shows the window labels and boundaries. The
white line joins window centres in prominence order (the flow; the dot is
the hub). Gutters are coloured green for 16–24 px, amber for 25–60 px
and red under 16 px.

| File | What it shows |
|---|---|
| `superg_3-6_windows.png` | 3–6 windows, mixed sizes, packed inputs, your reported six (sizes and positions only) |
| `superg_7-12_windows.png` | 7–12 windows |
| `superg_asymmetric_wide_tall.png` | one huge window plus dialogs; 3440×1440 and 1080×1920 monitors |
| `superg_obstacles_fullscreen.png` | a manually placed fixed window; a fullscreen window |
| `autoplace_baseline_vs_spiral.png` | real `place_new_window` sequences, then one SUPER+G press |
| `rotation_metric_caveat.png` | four vs six start bearings (see caveats) |

Regenerate with `scripts/dxrice_spiral_bench.py --json` and
`scripts/dxrice_spiral_render.py` (Pillow).

## Tests

All Python suites pass: 183 placement and 38 cloud tests, plus the other
11 suites. All shell suites pass; `launch_systemd` is skipped because the
sandbox has no systemd.

Tests that encoded the packed design were rewritten deliberately. Each
one now asserts the guarantee it protected, with the reason in its
docstring:

- **Exact 5 px gaps** became the spacing range plus no dead strip
  (`spacing_violations`, `assert_composed`).
- **"A 5 px-flush L / T / asymmetric shape is finished"** became:
  rebuilt at most once, and the second press touches nothing.
- **Two separate clusters, or a far-off dialog, left alone** became
  "joined into one composition". This settles the open question in
  PROGRESS.md.
- **Notch-repair sizes** (e.g. 1614×1186, 855×675) became "bounded,
  stable, never a typical window, clean".
- **Two windows resized in one press** became one per set. That is a
  deliberate, more conservative policy.
- **Resize-memory fixtures that re-shrank without memory** now assert
  that no window is resized twice even without memory. That is stronger.
- **New:** your reported six-window block, through `auto_arrange` and
  through `main()`.

## Activation

- **SUPER+G:** the bind runs `python3 ~/dxrice/scripts/dxrice_auto_arrange.py`
  fresh on every press, so the next press after `~/dxrice` updates uses
  this. Nothing to restart.
- **Auto-placement:** `dxrice-auto-place-window.service` is long-lived and
  holds the code it started with. It picks this up after
  `systemctl --user restart dxrice-auto-place-window.service`. That
  restart was not done, because you're gaming.
- **Spacing:** add `"window_spacing_min": 16, "window_spacing_max": 24` to
  `~/.config/dxrice/theme.json` to change it. Both SUPER+G and new windows
  read it on every use. There's no Settings slider yet, because that's a
  QML change and would reload Quickshell.
- **Spawn-then-jump** (new windows appearing, then moving) is not fixed
  here. A reliable fix needs Hyprland window rules, and changing the
  config reloads the compositor. It is left for a session when you're not
  playing.

## Remaining limitations

- No live-desktop validation; everything was measured offline.
- Rotation at 7–12 windows is below 0.85 (see caveats).
- SUPER+G re-winds about 40% of auto-placed layouts.
- The packed solver is gone. Tag `backup/live-before-spiral` (0af6538)
  restores it in one command.
