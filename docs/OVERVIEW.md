# Desktop overview (zoom out)

Zoom the current workspace out until every window on it fits on screen,
including the whole Galaxy Spiral and the parts of it past the screen edges.
Zoom back in to exactly the desktop you left.

## Keybinds

| Keybind | Action |
|---|---|
| `SUPER + Tab` | Toggle: zoom out, or back in |
| `SUPER + -` (the minus key), or `SUPER + keypad -` | Zoom out only |
| `SUPER + +` (that is, `SUPER + Shift + =`), `SUPER + =`, or `SUPER + keypad +` | Zoom back in only |
| `Esc`, or a click on empty space | Zoom back in, focus unchanged |
| Click a window | Focus that window and zoom back in |

**Key names.** These are for a US layout. In `hypr/hyprland.lua` they are
`Tab`, `minus`, `KP_Subtract`, `SHIFT + equal`, `equal` and `KP_Add`.
- On a US keyboard, `+` is Shift and `=`. Hyprland matches
  `SUPER + SHIFT + equal` when you hold Shift, the same way the
  SUPER+SHIFT+1 workspace keys work.
- `equal` alone is bound too, so it zooms in with or without Shift.
- All were unbound before.

`scripts/dxrice_test_overview.py` runs Hyprland's own config parser
(`Hyprland --verify-config`, which starts nothing) over the template. That
proves every key name is accepted, and the drift checker reports any of them
missing from your live file.

To move the keys, change them on these lines next to SUPER+G.
From a terminal, `dx overview` toggles it; so does
`qs -p <repo>/quickshell/shell.qml ipc call overview toggle|zoomOut|zoomIn`.

## What it does

- **Opening.**
  1. The keypress dims the screen on the next frame, with the real desktop
     showing through. This happens before any window data is read, so
     nothing stale is ever drawn.
  2. About 5 ms later, fresh window data from two parallel `hyprctl -j`
     reads puts each window's picture exactly over the real window.
  3. The whole composition zooms out over about 420 ms (the theme's
     animation speed). The wallpaper fades in under it over the first
     third, covering the real windows. All windows scale and move by one
     transform, so their relative positions, sizes, spacing and the spiral's
     shape are kept.
  4. The result is centred in the usable area (the screen minus the bar and
     dock) with a 48 px margin.
- **No unnecessary zoom.** If every window is already fully on screen,
  nothing moves at all.
- **Minimum scale.** The zoom stops at 8%. A composition bigger than that
  (more than about 12 screens across) is centred, and its outermost windows
  stay partly off screen.
- **Closing** plays the same motion back. The last frames before the overlay
  disappears are the real desktop, so there is no jump. Toggling while it is
  still moving reverses from wherever it is.
- **Clicking a window.**
  - It focuses that exact window by its Hyprland address, then closes.
  - Focus is sent in Lua syntax, because DXrice runs hyprland.lua.
  - It is sent only after the overview releases the keyboard, and again
    after the overlay is gone. Otherwise Hyprland would refocus whatever
    real window happens to be under the pointer.
- **A window entirely off screen** can't be shown without moving windows, so
  it is never focused silently: typing would go to a window you can't see.
  - The first click says so.
  - A second click on the same window pans the desktop there, moving every
    window together the same way SUPER+arrow keys do
    (`dxrice_navigate_windows.py --to`). The overview then closes onto the
    windows in their new places, and the window is focused.
  - A window that is partly on screen is focused straight away.
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
- **Geometry.** The shell computes it itself, in `quickshell/OverviewGeometry.js`.
  That file mirrors `scripts/dxrice_overview.py` line for line. The Python
  module is the reference and CLI, and a test keeps the two identical on
  300 random workspaces.
- **Window pictures.** It shows a live picture of each window, captured
  through Hyprland's toplevel-export protocol (Quickshell's
  `ScreencopyView`).
- **Backdrop.** Your wallpaper, drawn the way hyprpaper draws it.
- **Data.** Opening reads `hyprctl -j clients` and `monitors`, and nothing
  else.
- **What it ever sends Hyprland.** The only thing the overview ever tells
  Hyprland is to focus the window you click, plus the pan you confirm for
  an off-screen one.

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
- **Bar and dock.** They stay visible, dimmed, until the wallpaper fades in
  during the first third of the zoom, and come back in the last third of the
  way out. While zoomed out the overlay must cover them: the bar is separate
  islands, and windows reaching under them would otherwise show through
  around the overview.
- **Infinite-desktop panning.** SUPER-drag panning reads input devices
  directly, so it still moves your real windows while the overview is open.
  The overview follows as it re-reads, but it's best not to pan while zoomed
  out.
- **The key's own delay.** Most of what's left comes from the keybind
  itself: about 30 ms, the `qs ipc call` client process every DXrice panel
  key uses. Quickshell's Hyprland global-shortcut binding
  (`hl.dsp.global(...)`) would remove it. Hyprland's parser accepts it, but
  whether Quickshell receives the shortcut can only be confirmed live. If it
  didn't, the keys would silently do nothing, so the proven path is kept.
- **Off-screen windows** need the confirmed pan described above. That pan
  is the one action in the overview that moves windows, and only when you
  click twice.
- **One monitor at a time.** Only the focused monitor zooms out.

## Testing

- `scripts/dxrice_test_overview.py` (22 tests, no compositor). It covers:
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
  - speed;
  - the keybinds: present, unique, accepted by Hyprland's own parser (with
    a bogus key name rejected as a control), and seen by the drift checker;
  - the pan for an off-screen window: every floating window moves by one
    delta, and the target ends up centred.
- `tests/qml/test_overview.py` (16 tests, offscreen harness, the real
  shell). It covers:
  - opening to the fitted view and closing back;
  - the first and last frames lying exactly on the real windows;
  - repeated toggles, fast and slow;
  - reversing mid-zoom without a jump;
  - Esc and clicks on empty space;
  - clicking every thumbnail: each focuses its own window's address and
    closes. Off-screen windows ask first, then pan to that address on the
    second click;
  - focus always sent in Lua syntax;
  - a single click on an off-screen window never focusing or panning;
  - feedback on the first frame even when the window data never arrives;
  - JS geometry identical to the Python reference on 300 random workspaces;
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
  - and `overview_opening_sequence.png`: the frame after the keypress, the
    data arriving, the crossfade, zoomed out, and the off-screen notice.
  - the zoom at 0, 25, 50, 75 and 100%.

**Latency**, measured stage by stage, sandboxed:

| stage | before | now |
|---|---|---|
| keypress → `qs ipc call` delivered | about 30 ms | about 30 ms |
| first visible feedback after that | waited for data, then a 150 ms fade | the next frame (the dim) |
| window data | `python3 dxrice_overview.py`, about 60 ms | 2 × `hyprctl -j` in parallel, about 5 ms |
| geometry | inside the Python run | `OverviewGeometry.js`, under 1 ms for 16 windows |
| zoom starts | about 90 ms, then after the 150 ms fade | about 35 ms (the fade runs alongside) |

Window pictures start capturing as soon as the data is in. A picture that
isn't ready yet is simply not drawn, and the real window shows through until
the wallpaper covers it.

## Activation

The first version went live on 2026-10-15. These fixes are not activated
yet. When you're ready:

1. `git -C ~/dxrice merge --ff-only origin/claude/task-kcttpa`, then
   `systemctl --user restart dxrice-quickshell.service`. On the first
   activation, the fast-forward alone did not reload the shell. The restart
   makes the bar and dock blink once, so do it when you're not mid-game.
2. In `~/.config/hypr/hyprland.lua` (DXrice never overwrites your copy),
   replace the overview's three `hl.bind` lines after SUPER+G with these
   six:

   ```lua
   local function overview(action)
       return hl.dsp.exec_cmd("sh -c 'qs -p " .. repo .. "/quickshell/shell.qml ipc call overview "
           .. action .. " 2>/dev/null'")
   end
   hl.bind(mainMod .. " + Tab", overview("toggle"))             -- zoom out / back in
   hl.bind(mainMod .. " + minus", overview("zoomOut"))             -- zoom out: SUPER and -
   hl.bind(mainMod .. " + KP_Subtract", overview("zoomOut"))       --   ... or the keypad's -
   hl.bind(mainMod .. " + SHIFT + equal", overview("zoomIn"))     -- zoom in: SUPER and + (Shift and =)
   hl.bind(mainMod .. " + equal", overview("zoomIn"))             --   ... or = without Shift
   hl.bind(mainMod .. " + KP_Add", overview("zoomIn"))            --   ... or the keypad's +
   ```

   Hyprland reloads its config on save. `install.sh update`'s drift check
   lists these three binds as new if they're missing.

Fresh installs get both: the keybinds in the template, and the overview in
the shell.
