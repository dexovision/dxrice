# Desktop overview (zoom out)

Zoom the current workspace out until every window on it fits on screen,
including the whole Galaxy Spiral and the parts of it past the screen edges.
Zoom back in to exactly the desktop you left.

## Keybinds

| Keybind | Action |
|---|---|
| `SUPER + Tab` | Toggle: zoom out, or back in |
| `SUPER + minus` | Zoom out only (does nothing if already out) |
| `SUPER + equal` | Zoom back in only |
| `Esc`, or a click on empty space | Zoom back in, focus unchanged |
| Click a window | Focus that window and zoom back in |

All three keys were unbound before. They are defined on three lines in
`hypr/hyprland.lua`, next to SUPER+G; change the key there to move them.
From a terminal, `dx overview` toggles it; so does
`qs -p <repo>/quickshell/shell.qml ipc call overview toggle|show|hide`.

## What it does

- **Opening.**
  1. The overlay fades in over about 150 ms, with each window's picture
     lying exactly on top of the real window.
  2. The whole composition then zooms out over about 420 ms (the theme's
     animation speed). All windows scale and move by one transform, so their
     relative positions, sizes, spacing and the spiral's shape are kept.
  3. The result is centred in the usable area (the screen minus the bar and
     dock) with a 48 px margin.
- **No unnecessary zoom.** If every window is already fully on screen,
  nothing moves at all.
- **Minimum scale.** The zoom stops at 8%. A composition bigger than that
  (more than about 12 screens across) is centred, and its outermost windows
  stay partly off screen.
- **Closing** plays the same motion back. The last frame before the overlay
  disappears is the real desktop, so there is no jump. Toggling while it is
  still moving reverses from wherever it is.
- **Nothing is changed.** No window is moved, resized, refocused, retiled or
  sent to another workspace when the overview opens or closes. The workspace
  doesn't change. Coming back is exact because nothing was touched.
- **Which windows:** every mapped window of the focused monitor's active
  workspace:
  - tiled, floating and maximized windows;
  - fullscreen windows;
  - windows pinned to that monitor;
  - a special workspace if one is showing.
- **Stacking order.** Windows keep Hyprland's order:
  - tiled at the bottom;
  - floating and pinned above them;
  - fullscreen on top;
  - within each group, the most recently focused window is higher.
- **Fullscreen windows** (a game, say) stay at their real size and place.
  As the view zooms out they turn half transparent, so the windows behind
  them on that workspace can be seen too. The game itself is untouched and
  keeps running.
- **Windows opening or closing while it's open.** The overview re-reads
  Hyprland on each window event, not on a timer, and re-fits. Switching
  workspace while it's open shows the new workspace.
- **Monitors.** It opens on the focused monitor and shows that monitor's
  workspace, fitted to that monitor's logical size (scale and rotation
  applied).

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
- **Geometry.** `scripts/dxrice_overview.py` reads `hyprctl clients` /
  `monitors` once on open and computes where each picture goes. It only
  reads; it has no code that sends anything to Hyprland.
- **Focus.** The only thing the overview ever tells Hyprland is to focus the
  window you click.

No background service, timer or new dependency is involved. A closed
overview holds no surface, no window pictures and no capture sessions.

## Limitations

- **Not yet seen on your real desktop.** Everything was validated offscreen,
  in the QML harness, with stand-in window pictures; see Testing. Two things
  only a live session shows:
  - whether Hyprland exports windows that are off screen as readily as
    visible ones;
  - how the live captures look.

  A window that can't be captured shows a card with its title instead of a
  hole.
- **Window decorations.** The pictures are the windows' own contents.
  Hyprland's borders, rounded corners and shadows aren't part of them, so a
  thin edge changes as the zoom starts.
- **Bar and dock.** They fade out with the opening fade and back in with the
  closing one. The overlay must cover them: the bar is separate islands, and
  windows reaching under them would otherwise show through around the
  overview.
- **Infinite-desktop panning.** SUPER-drag panning reads input devices
  directly, so it still moves your real windows while the overview is open.
  The overview follows as it re-reads, but it's best not to pan while zoomed
  out.
- **Opening delay.** There is about 70 ms between the keypress and the
  animation starting: the time to start Python and read Hyprland's window
  list.
- **Off-screen windows.** Clicking a window that sits off screen in the
  spiral focuses it but doesn't bring it on screen. Nothing is ever moved.
- **One monitor at a time.** Only the focused monitor zooms out.

## Testing

- `scripts/dxrice_test_overview.py` (17 tests, no compositor). It covers:
  - which windows count, and their stacking order;
  - no zoom when everything fits;
  - centring and the margin;
  - one transform for every window, so the shape is kept;
  - spirals of 2 to 32 windows, mixed sizes, and very wide and very tall
    windows;
  - windows far off screen, and the minimum scale;
  - fullscreen and pinned windows;
  - three monitors, including a scaled 1440p one and a rotated one;
  - windows opening and closing while open;
  - that the entry point never dispatches anything;
  - speed.
- `tests/qml/test_overview.py` (12 tests, offscreen harness, the real
  shell). It covers:
  - opening to the fitted view and closing back;
  - the first and last frames lying exactly on the real windows;
  - repeated toggles, fast and slow;
  - reversing mid-zoom without a jump;
  - Esc and clicks on empty space;
  - clicking a window to focus it, in both Lua and classic dispatch syntax;
  - windows opening and closing while open;
  - an open panel closing when the overview opens;
  - the placeholder for an uncapturable window;
  - no compositor answer;
  - a 2560×1440 monitor;
  - that a closed overview holds no tiles.
- **Renders:** `python3 tests/qml/render_overview.py OUT_DIR` writes the
  before/after sheets in `docs/overview/`:
  - one window;
  - 6 windows;
  - 16 windows (reference proportions);
  - 16 mixed windows;
  - 32 windows;
  - very wide windows;
  - very tall windows;
  - fullscreen and pinned windows;
  - a 1440p monitor;
  - the zoom at 0, 25, 50, 75 and 100%.

**Performance:**

| | time |
|---|---|
| Python start, import and read on each open | about 70 ms |
| layout, 16 windows | about 0.1 ms |
| layout, 200 windows | about 1 ms |

## Activation

Not activated. When you're ready:

1. `git -C ~/dxrice merge --ff-only origin/claude/task-kcttpa`. Quickshell
   watches its files, so this **reloads the shell immediately**: the bar and
   dock blink once. Do it when you're not mid-game.
2. Add the overview binds to `~/.config/hypr/hyprland.lua`. DXrice never
   overwrites your copy of that file. Copy the block after SUPER+G from the
   repo's `hypr/hyprland.lua`:

   ```lua
   local function overview(action)
       return hl.dsp.exec_cmd("sh -c 'qs -p " .. repo .. "/quickshell/shell.qml ipc call overview "
           .. action .. " 2>/dev/null'")
   end
   hl.bind(mainMod .. " + Tab", overview("toggle"))    -- zoom out / back in
   hl.bind(mainMod .. " + minus", overview("show"))    -- zoom out
   hl.bind(mainMod .. " + equal", overview("hide"))    -- zoom back in
   ```

   Hyprland reloads its config on save. `install.sh update`'s drift check
   lists these three binds as new if they're missing.

Fresh installs get both: the keybinds in the template, and the overview in
the shell.
