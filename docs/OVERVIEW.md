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
| about 6 ms later | Fresh window positions arrive (two parallel `hyprctl -j` reads). Each window's live picture is placed exactly over the real window. |
| over the next 300 ms | One ease-in-out zoom (cubic-bezier 0.4, 0, 0.2, 1). The wallpaper fades in over the first sixth, covering the real windows while their pictures have barely left them. |

At the end, every window is in the usable area (the screen minus the bar and
dock) with a 48 px margin, centred. They all scale and move by one
transform, so positions, sizes, spacing and the spiral's shape are kept.

If everything already fits, nothing zooms. The zoom stops at 8%; a
composition bigger than that is centred, and its outermost windows stay
partly off screen.

### Closing

The same 300 ms curve played back, with the dim fading out alongside it. The
last frames are the real desktop, so there is no jump, and no window has
moved.

Toggling while it's still moving eases out of wherever it is, never
snapping.

### Clicking a window

One click focuses exactly that window, by its Hyprland address, and the
overview closes.
- **Already in view:** if the window is entirely inside the usable area,
  nothing moves.
- **Partly or entirely off screen:** the whole desktop pans first, the way
  the SUPER+arrow keys move the infinite desktop.
  - Every floating window moves by the same, smallest shift that brings the
    clicked one fully into view, 24 px inside the edge.
  - A window bigger than the screen is centred instead.
  - The spiral keeps its shape. The overview then closes onto the windows in
    their new places.
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
| close | 360 ms, then a separate 120 ms fade | 300 ms, the fade alongside |

`overview_timing.png` plots both. The remaining 30 ms before the shell even
hears the key is the `qs ipc call` client process. Hyprland's
global-shortcut dispatcher (`hl.dsp.global(...)`) would remove it, but
whether Quickshell receives it can only be checked live. If it didn't, the
key would silently do nothing, so the proven path is kept.

## Limitations

- **The look of the live captures** can only be judged on the real desktop.
  - The tests use stand-in pictures.
  - It's unconfirmed whether Hyprland exports windows that are off screen.
    A window that can't be captured shows a card with its title, once the
    zoom is a sixth under way. Before that the real window shows through.
- **Window decorations.** The pictures are the windows' own contents.
  Hyprland's borders, rounded corners and shadows aren't part of them.
- **Bar and dock.** They are dimmed at first, then covered once the
  wallpaper is in, and come back as the overview closes. While zoomed out
  the overlay must cover them: the bar is separate islands, and windows
  reaching under them would otherwise show through.
- **Infinite-desktop panning.** SUPER-drag panning reads input devices
  directly, so it still moves your real windows while the overview is open.
  The overview follows as it re-reads.
- **One monitor at a time.** Only the focused monitor zooms out.

## Testing

- `scripts/dxrice_test_overview.py` (26 tests, no compositor). It covers:
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
    - the bind calls a function that exists.
- `tests/qml/test_overview.py` (18 tests, offscreen harness, the real
  shell). It covers:
  - opening and closing back exactly;
  - the first and last frames on the real windows;
  - repeated and reversed toggles that never jump, judged against the
    zoom's own curve and the time actually elapsed;
  - Esc and empty-space clicks change nothing;
  - **one click on every thumbnail** focuses that exact window. Windows not
    in view pan the desktop by one shared delta, sent before the focus;
    windows in view move nothing;
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
  - `overview_timeline.png`: opening and closing at 0 to 300 ms;
  - `overview_one_click.png`: one click on an off-screen window;
  - `overview_timing.png`: before and after, plotted;
  - before/after sheets for one window up to 32, very wide, very tall,
    fullscreen and pinned windows, and a 1440p monitor;
  - the zoom frames.

## Activation

1. `git -C ~/dxrice merge --ff-only origin/claude/task-kcttpa`, then
   `systemctl --user restart dxrice-quickshell.service`. The restart makes
   the bar and dock blink once.
2. In `~/.config/hypr/hyprland.lua`, the overview block after SUPER+G keeps
   only:

   ```lua
   hl.bind(mainMod .. " + Tab", overview("toggle"))
   ```

   Delete the five `overview("zoomOut")` / `overview("zoomIn")` lines.
   Hyprland reloads the file when it's saved.
