# QML harness and tests

Runs the **real** `quickshell/*.qml` offscreen against small stand-ins for
Quickshell's compositor-facing types (`stubs/`), so shell behaviour can be
tested and rendered without Hyprland, a GPU or a Wayland session.

```sh
pip install PySide6-Essentials        # once
python3 tests/qml/test_input_regions.py   # invisible click-blocking regions
python3 tests/qml/test_add_shortcut.py    # Add Shortcut branch behaviour
python3 tests/qml/test_branch_geometry.py # branch placement, synthetic rects
```

Each suite skips cleanly if PySide6 is missing. None of them run as part of
`install.sh`.

## What it models

- `stubs/Quickshell/Region.qml` reproduces Quickshell's input-mask
  semantics: an `item:` region is the item's mapped rect (including scale)
  and ignores `visible`/`opacity`, and the whole mask is only rebuilt when a
  region or a tracked item's x/y/width/height changes. `Scene.input_owner()`
  answers "would the compositor deliver a click here to a shell surface or
  to the app underneath?"
- `Process`/`FileView` read fixtures (`harness.py`: `DEFAULT_COMMANDS`,
  `DEFAULT_FILES`), so the real parsing code runs. `"__HANG__"` fixtures
  model a process that never finishes (loading states).
- `scenes/Desktop.qml` loads the real `shell.qml` over a fake desktop app.

## What it cannot show

No compositor blur (panels look more transparent than they do live), no
GPU frame pacing, no real keyboard focus between separate layer surfaces
(every `PanelWindow` is an Item in one view), no `hyprctl`.

## Rendering for visual QA

```python
from harness import Scene
s = Scene(width=1920, height=1080)
s.ev("panels.open('quicksettings')"); s.wait(900)
s.grab("/tmp/qs.png", (1180, 0, 740, 520))
```
