# Desktop overview (SUPER+Tab)

Zoom the current workspace out until every window on it fits on screen,
including the whole Galaxy Spiral and the parts of it past the screen edges.
Zoom back in to exactly the desktop you left.

## Using it

| Do | Result |
|---|---|
| `SUPER + Tab` | Zoom out; press it again to zoom back in |
| Click a window | Focus that window and zoom back in, in one click |
| `Esc`, or a click on empty space | Zoom back in without changing anything |

SUPER+Tab is the overview's only key. It's the one
`hl.bind(mainMod .. " + Tab", overview("toggle"))` line in
`hypr/hyprland.lua`; change the key there to move it. From a terminal,
`dx overview` or `qs -p <repo>/quickshell/shell.qml ipc call overview
toggle` does the same.

## What happens

### Opening

| time after the keypress | what you see |
|---|---|
| about 30 ms | The keypress reaches the shell. On the next frame the screen starts to dim. The real desktop still shows through, so nothing stale is ever drawn. |
| about 6 ms later | Fresh window positions arrive (two parallel `hyprctl -j` reads). Each window's live picture is placed exactly over the real window, not yet drawn. |
| a frame or two later | **The handover.** Once every window that shows on screen has its live picture (at most 150 ms; a window still without one shows its card), the overview takes the screen over in one frame: wallpaper, dim and pictures, opaque, each picture exactly where its window is. That frame is the desktop you were looking at, so nothing visibly changes. |
| over the next 300 ms | One ease-in-out zoom (cubic-bezier 0.4, 0, 0.2, 1). Only the pictures move; the real windows are hidden under the opaque overview the whole time. |

At the end, every window is in the usable area (the screen minus the bar and
dock) with a 48 px margin, centred. They all scale and move by one
transform, so positions, sizes, spacing and the spiral's shape are kept.

If everything already fits, nothing zooms. The zoom stops at 8%; a
composition bigger than that is centred, and its outermost windows stay
partly off screen.

### Closing

The same 300 ms curve played back, with the dim fading out alongside it. The
overview stays opaque until the frame with every picture back on its window
and no dim left has actually been drawn; it lets go of the screen two frames
after the animation ends. So the last frame it shows is the desktop under
it, and there is no pop. No window has moved, unless a click panned the
desktop; then the pictures close onto the windows' new places.

The overview itself never crossfades with the real desktop. (An earlier
version faded its wallpaper in over the first sixth of the zoom and out over
the last, so the real windows showed through it; that is gone. It was not
the whole story: see "The double image" below.)

Toggling while it's still moving eases out of wherever it is, never
snapping.

When the click pans the desktop (below), Hyprland animates the real
windows to their new places with its own window-move animation (the
`windowsMove` leaf, else `windows`, else `global`). Its duration is taken
as the leaf's speed × 100 ms, Hyprland's unit for animation speed: 480 ms
for the template's `windows` speed of 4.79. That reading of `speed` is
inferred from Hyprland's documentation, not measured. The template's
`windows` leaf uses a spring curve, and whether a spring's duration follows
`speed` exactly can only be confirmed on a real desktop (manual check 3
below). The closing zoom then runs exactly that
long instead of 300 ms, so the pictures and the real windows land on the
same frame. Before this, the overlay let go about 340 ms after the click
(measured in the harness), while Hyprland's move was still running.
The real windows visibly slid the rest of the way into place where the
pictures had just been: the double image on selection. The duration is read from
`hyprctl -j animations` on the first open and after each config reload.

### Clicking a window

One click focuses exactly that window, by its Hyprland address, and the
overview closes.
- **Already in view:** if the window is entirely inside the usable area,
  nothing moves.
- **Partly or entirely off screen:** the whole desktop pans first, the way
  the SUPER+arrow keys move the infinite desktop.
  - Every floating window moves by the one shift that puts the clicked
    window's centre on the centre of the usable area (the monitor minus the
    bar and dock, in logical pixels, wherever the monitor sits in the
    layout). A window bigger than the screen is centred too, overhanging
    evenly.
  - The spiral keeps its shape. The overview then closes onto the windows in
    their new places.
  - Measured on the rendered harness: 0.0 px from the centre for targets
    left, right, above, below and diagonal, half off the edge, a 2400×1300
    window, a monitor at (1920, 120) with a bar and a side dock, and a
    1.5-scaled monitor. Rounding to whole pixels bounds it at 0.71 px. The
    previous version left the window 256–906 px off centre, just inside the
    edge it came from.
- **Pinned and fullscreen windows** belong to the screen, not the desktop.
  They never pan, and clicking them just focuses them.
- **Tiled windows** are always in view.
- **How focus is sent:**
  - In Lua syntax, because DXrice runs hyprland.lua.
  - Only after the overview has released the keyboard.
  - Once more after the overlay is gone. When an overlay unmaps, Hyprland
    refocuses whatever window is under the pointer, which was over the
    picture, not over the real window.
- **A window that closed since the overview opened** can't be focused, so
  the overview says so and stays open.

### Other cases

- **A fullscreen window** (a game, say) covers its workspace. The windows
  behind it can't be seen at first, exactly as on screen, and they fade in
  over it as the view zooms out. Its picture lies at the bottom of the
  overview's stack. What can be seen is what can be clicked: a window
  showing over the game's picture is that window, not the game.
- **Windows opening or closing while it's open.** The overview re-reads
  Hyprland on each window event, not on a timer. Only the affected window's
  tile is added or dropped; every other tile, and its live picture, carries
  on. While zoomed out, the tiles glide to their new places.
- **Which windows:** every mapped window of the focused monitor's active
  workspace (tiled, floating, maximized, fullscreen), windows pinned to that
  monitor, and a special workspace if one is showing.
- **Stacking order:** Hyprland's order (tiled below, floating above, the
  most recently focused highest), except that fullscreen goes to the bottom
  as above.
- **Monitors:** it opens on the focused monitor, fitted to that monitor's
  logical size (scale and rotation applied).

## The double image: what actually caused it

On the real desktop, every window showed twice while the overview opened
(and faintly while it closed). A screen recording of SUPER+Tab, taken after
the in-QML crossfade above had been removed, showed it plainly: the real
terminal at full size, fading out, beside a smaller, moving picture of it.
Two copies, so two things visible at once, so the overview was not opaque on
screen -- although `Overview.qml` paints it opaque.

**The cause is Hyprland, not the shell.** Hyprland fades every layer-shell
surface in when it maps and out when it unmaps (animation leaves
`fadeLayersIn` / `fadeLayersOut`, which inherit the `fade` setting: 3.03
with the `quick` bezier, here). It applies that to the *whole surface*,
however opaque the shell paints it, so the overview was composited at 0..100%
over the real windows for about 300 ms while its pictures moved. The recording
shows the top bar's clock fading out over 9 frames (125 ms) opening and 4
closing (55 ms); a one-frame handover would be 1. `hyprctl animations`
confirms `fadeLayersIn` / `fadeLayersOut` are not overridden.

A first version of this fix turned those two leaves off for *every* layer
surface, on the belief that Hyprland has no per-layer switch. That was wrong.
In Hyprland 0.56's source, the animation tick checks each layer's `no_anim`
rule for every animated value of that layer, alpha included
(`AnimationManager.cpp`), and finishes it on the first tick; on unmap a
`no_anim` layer takes no snapshot, and with no snapshot no fade-out is
created (`LayerSurface.cpp`, `LayerFadeout.cpp`). So the fix is scoped to
the overview, and the bar, dock, notifications and launchers keep their
fades.

A synthetic harness has no compositor, so nothing there could show it.
`PanelWindow.qml`'s test stub now fades a surface in on map the same way
(`layer_fade_ms`), flattened as a compositor does, which reproduces the
recording's frames: `overview_compositor_fade.png`.

**The fix has two parts:**

1. `hypr/hyprland.lua` stops the compositor animating the overview's
   surface, and only that one:

   ```lua
   hl.layer_rule({ name = "overview-no-anim", match = { namespace = "^dxrice-overview$" }, no_anim = true })
   ```

   Every other surface keeps Hyprland's fade. The deployed `hyprland.lua`
   is copy-once, so `install.sh update` offers this as the
   `overview-no-anim` edit (backup first, only with your consent). That edit
   also takes out the two global `fadeLayersIn` / `fadeLayersOut` lines an
   earlier version added -- only if they are exactly as DXrice wrote them.
   `dxrice_check_hypr_drift.py` reports the rule as missing until it's in.
   Hyprland reloads the file when it's saved.
2. `Overview.qml` no longer unmaps from a drawn frame. Hyprland fades a
   surface out from a snapshot of its last frame, so the overview now commits
   two frames of nothing (the surface mapped, drawing nothing) before it
   unmaps. That makes the closing clean even without the layer rule. The
   opening can't be fixed from the shell: whatever alpha the compositor has the
   surface at, only the config removes it. Without the rule the overview
   still looks correct at the handover (the first covered frame is the
   desktop, so any alpha over it is invisible) but doubles while it zooms.

To check a real recording, `python3 scripts/dxrice_overview_probe.py
RECORDING.mp4` measures how many frames the bar's clock takes to go: 1 or 2 is
a clean handover, 3 or more is a compositor fade.

What that number means: the probe correlates the clock's box in every frame
with the first frame (a uniform dim doesn't change a correlation), and counts
the frames between "the clock is there" and "the clock is covered" (and back).
The compositor's alpha applies to the whole overview surface at once, so the
clock is a fair sample of it: a surface that goes from 0 to fully opaque in
one compositor frame covers the clock between two recorded frames, and one
extra frame is allowed for an encoder or recorder frame that straddles the
change. It says nothing about the windows' own pictures (their alignment is
what the harness tests check), and it can't judge a transition in which
something covers the clock -- a window over it reads as a slow transition.
On the recording that found the bug it read 9 frames opening and 4 closing.

To record one: with the bar's clock visible and nothing over it,
`wf-recorder -f ~/Videos/overview.mp4`, then SUPER+Tab, wait, SUPER+Tab,
Ctrl+C in the terminal, and
`python3 ~/dxrice/scripts/dxrice_overview_probe.py ~/Videos/overview.mp4`.

## How it works, and why not a "real" zoom

Hyprland has no way to zoom the desktop out:
- `cursor:zoom_factor` is a magnifier: it only zooms in, around the cursor.
- Lowering the monitor's scale makes every app re-render at a new scale, and
  reflows fullscreen games and the bar. It also scales from the screen's
  top-left, so windows at negative coordinates (half the spiral) would never
  come into view.
- The overview plugins (hyprexpo, Hyprspace) show a grid of workspaces, not
  one workspace zoomed out. They also have to be rebuilt for every Hyprland
  release.

So the overview is a **view**: an overlay drawn by Quickshell
(`quickshell/Overview.qml`) on top of everything.
- **Window pictures.** It shows a live picture of each window, captured
  through Hyprland's toplevel-export protocol (Quickshell's
  `ScreencopyView`).
- **Backdrop.** Your wallpaper, drawn the way hyprpaper draws it.
- **Geometry.** `quickshell/OverviewGeometry.js` computes it, a line-for-line
  mirror of `scripts/dxrice_overview.py`, which is the reference and CLI.
  A test keeps the two identical on 300 random workspaces.
- **What it sends Hyprland.** Opening and closing never move, resize or
  refocus anything. The only things the overview ever sends are the focus
  for the window you click, and the pan when that window wasn't in view.

No background service, timer or dependency is involved. A closed overview
holds no surface, no window pictures, no capture sessions and no decoded
wallpaper.

## Measured latency

Measured on this machine; the window data is read live, read-only.

| stage | before | now |
|---|---|---|
| keypress → the shell (`qs ipc call`, every DXrice panel key uses it) | 26–32 ms | 26–32 ms |
| first visible feedback after that | the next frame | the next frame |
| window data | 1st version: `python3 dxrice_overview.py`, 50–52 ms; then 2 × `hyprctl -j`, 5–7 ms | 2 × `hyprctl -j` in parallel, 5–7 ms |
| geometry | 0.07 ms (16 windows), 1.1 ms (200) | the same |
| zoom | 420 ms decelerating | 300 ms ease-in-out |
| close | 360 ms, then a separate 120 ms fade | 300 ms, the fade alongside; after a click that pans the desktop, as long as Hyprland's window move (480 ms with the template) |

`overview_timing.png` plots both. The remaining 30 ms before the shell even
hears the key is the `qs ipc call` client process. Hyprland's
global-shortcut dispatcher (`hl.dsp.global(...)`) would remove it, but
whether Quickshell receives it can only be checked live. If it didn't, the
key would silently do nothing, so the proven path is kept.

## Limitations

- **The look of the live captures** can only be judged on the real desktop.
  - The tests use stand-in pictures.
  - It's unconfirmed whether Hyprland exports windows that are off screen.
    A window that can't be captured within 150 ms of the data arriving
    shows a card with its title; the handover waits that long for it.
- **Window decorations.** The pictures are the windows' own contents.
  Hyprland's borders, rounded corners and shadows aren't part of them.
- **Bar and dock.** They are dimmed at first, then covered at the handover,
  in one frame, and come back in one frame when the overview lets go. That
  is the one remaining hard cut, chosen over a crossfade: while zoomed out
  the overlay must cover them (the bar is separate islands, and windows
  reaching under them would otherwise show through), and fading them would
  bring back the double image.
- **What the handover can't hide.** The handover frame matches the desktop
  pixel for pixel in the harness. On the real desktop it can only match as
  well as the captures do, so borders, rounded corners and shadows appear
  and disappear at the handover.
- **Infinite-desktop panning.** SUPER-drag panning reads input devices
  directly, so it still moves your real windows while the overview is open.
  The overview follows as it re-reads.
- **One monitor at a time.** Only the focused monitor zooms out.

## Testing

- `scripts/dxrice_test_overview.py` (32 tests, no compositor). It covers:
  - which windows count, and their stacking order;
  - no zoom when everything fits;
  - centring and the margin;
  - one transform for every window, so the shape is kept;
  - spirals of 2 to 32 windows, mixed sizes, very wide and very tall
    windows, windows far off screen, and the minimum scale;
  - fullscreen and pinned windows;
  - three monitors, including a scaled 1440p one and a rotated one;
  - windows opening and closing while open;
  - that the geometry never dispatches anything;
  - speed;
  - **keys:**
    - SUPER+Tab is the only overview bind, and the old zoom keys are
      absent from the template and from your live `hyprland.lua`;
    - Hyprland's own parser (`--verify-config`, which starts nothing)
      accepts the template, with a bogus key name as a control;
    - the drift checker sees the bind;
    - no IpcHandler function is named after a `qs ipc` subcommand
      (`qs ipc call overview show` used to run `qs ipc show` instead);
    - the bind calls a function that exists;
  - **the compositor layer fade:** the template's layer rule matches the
    overview's namespace (read from `Overview.qml`) and no other DXrice
    surface, no global layer-fade setting is left, Hyprland's parser accepts
    `no_anim` (and refuses a made-up field), and an install that predates the
    rule is told by the drift checker;
  - **the migration** (`TestLayerRuleMigration`): both forms of the old
    global lines DXrice wrote are replaced by the rule and nothing else
    changes; a global line the user edited stays; a second run changes
    nothing; Hyprland accepts the migrated file;
  - **the recording probe**, on synthetic recordings: one frame is clean even
    while the overview darkens, a fade is flagged, one noisy frame doesn't
    split a transition.
- `tests/qml/test_overview.py` (38 tests, offscreen harness, the real
  shell). It covers:
  - opening and closing back exactly;
  - the first and last frames on the real windows;
  - repeated and reversed toggles that never jump, judged against the
    zoom's own curve and the time actually elapsed;
  - Esc and empty-space clicks change nothing;
  - **one click on every thumbnail** focuses that exact window. Windows not
    in view pan the desktop by one shared delta, sent before the focus;
    windows in view move nothing;
  - **centring** (`TestSelectionCentring`): targets in every direction, half
    off, bigger than the screen, on a monitor away from the origin with a bar
    and a side dock, and on a scaled monitor. In each case the window lands
    within 2 px of the usable area's centre, one delta moves every movable
    window, pinned and fullscreen windows stay put, and the closing
    animation's last frame is exactly the panned desktop;
  - **no ghosting** (`TestNoGhosting`, judged on rendered frames, with one
    real window and its picture painted a colour nothing else has):
    - every zoom frame, stepped from 0 to 100%, has no second copy of it
      (the previous version fails at 2–12%);
    - the real-time opening, and closing after a pan, never show two;
    - before the handover nothing but the uniform dim is drawn;
    - the handover frame is the desktop, pixel for pixel;
    - the last frame drawn on closing is the desktop (letting go one frame
      early fails this by 242/255);
    - the handover waits for the pictures, at most 150 ms;
    - the surface draws nothing in its last frames before it unmaps;
    - **under the emulated compositor fade** (`TestUnderTheCompositorFade`):
      a control that reproduces the recorded double image, and that the
      overlay equals the desktop until it moves;
    - pressing again before the handover, or during the release frames,
      backs out or resumes cleanly;
  - **closing in step with the compositor** (`TestCloseFollowsTheCompositor`):
    reading `hyprctl -j animations`, and that the overlay lets go only after
    the compositor's window move when the click panned the desktop, and at
    the zoom's own length otherwise;
  - focus always in Lua syntax;
  - fullscreen, pinned and tiled windows focus without a pan;
  - a window that just closed says so;
  - windows opening or closing mid-animation, with existing tiles updated
    rather than rebuilt;
  - the first frame's feedback before any data;
  - JS geometry identical to the Python reference;
  - the placeholder card;
  - a 1440p monitor.
- **Renders:** `python3 tests/qml/render_overview.py OUT_DIR` writes
  `docs/overview/`:
  - `overview_timeline.png`: opening and closing at 0 to 300 ms, including
    the frame pairs on either side of the handover and of the release;
  - `overview_ghost_check.png`: those two pairs as actual frames, with their
    pixel difference (both 0/255);
  - `overview_compositor_fade.png`: the same opening with the compositor fade
    on (the recording's double image) and off (the template's two lines);
  - `overview_one_click.png`: one click on an off-screen window, ending
    with it centred (screen centre marked);
  - `overview_timing.png`: before and after, plotted;
  - before/after sheets for one window up to 32, very wide, very tall,
    fullscreen and pinned windows, and a 1440p monitor;
  - the zoom frames.

`overview_ghost_before_after.png` was rendered once, from both the 7de7718
version and 0be89f9: the zoom at 3, 8 and 14%. It shows the in-QML
crossfade only; the compositor's is `overview_compositor_fade.png`.

## Activation

`./install.sh update` (or `dx update`) brings in the new shell code and
offers the edits an existing `~/.config/hypr/hyprland.lua` needs. That
includes the `overview-no-anim` layer rule (and taking out the earlier global
`fadeLayersIn` / `fadeLayersOut` lines), after a backup and only if you
accept. The running bar picks up the new `Overview.qml` at your
next login. Nothing restarts it for you.

## Manual check on a real desktop

The harness has no compositor, so check these on the real desktop. They
need no special setup.

1. **Opening.** Put a terminal and a browser on a workspace and press
   SUPER+Tab. The screen dims at once, then the windows shrink toward the
   centre in one movement. Watch any window's edges: there must never be a
   second, fading copy of a window at its old size.
2. **Selecting a window in view.** Click a window that is fully on screen.
   It zooms back to exactly where it was, with keyboard focus (type into
   it). Nothing else moves.
3. **Selecting a window off screen** (the case that ghosted). Press SUPER+G
   with five or more windows so the spiral runs past the screen edge, then
   SUPER+Tab and click an outer window. The view zooms back in while the
   desktop pans so that window ends centred. When the overview disappears,
   the windows must already be in their final places, with no slide
   afterwards. That window has focus.
4. **Interrupting.** Press SUPER+Tab twice quickly, and again mid-zoom. It
   reverses from wherever it is, with no jump.
5. **Esc / empty space** close it without changing focus or moving
   anything.

If step 1 still shows a double image, your `hyprland.lua` lacks the
`overview-no-anim` layer rule (`hyprctl layers` names the overview's
namespace while it's open; `grep overview-no-anim ~/.config/hypr/hyprland.lua`
shows the rule). If step 3 shows a slide after the overview disappears, report
your `windows` / `windowsMove` animation settings. The overview reads them
from `hyprctl -j animations` to time that close.
