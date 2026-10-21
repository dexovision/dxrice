# Reference videos: inventory and mapping to DXrice

Two phone screen recordings of short clips of someone else's Hyprland +
Quickshell desktop, sent 2026-10-21. Both are 1180x2556 portrait captures;
the desktop is a landscape band (about 1180x663) in the middle. Frames were
pulled at 6 fps (15 fps around transitions) and read one by one. No frames
are kept in this repository.

- **Video A**, `07-03-55` (11.9 s): peach theme, dated "Tue 20 Oct", so the
  newer clip. A large red caption covers most of the desktop for the whole
  clip, and the player switches to 2x speed at about 3 s, so the timings
  below are halved after that.
- **Video B**, `07-04-43` (11.5 s): green theme, dated "Mon 19 Oct", so the
  older clip, played at 1x. Nothing covers it, so most observations come
  from B.

Timestamps are clip time. **Observed** means visible in a frame.
**Inferred** means reasoned from what is visible. **Unclear** means it can't
be established from these clips.

## 1. The top bar (both videos)

**Observed:**
- One continuous light strip across the whole top edge, about 32 px tall in
  the band. It is not three pills.
- **Left to right:**
  - A round logo/launcher button.
  - A "Search app…" field drawn inside the bar, with a folder button at its
    right end.
  - A media chip with a note glyph and a truncated, live track title
    ("Who C…", later "Who Can It B…").
  - The time with the date stacked under it in small type ("3:31 PM / 19
    Oct").
- **Right end, left to right:**
  - A small dot.
  - A green round download glyph (B 0–1.5 s; replaced by a dot from 1.5 s).
  - A frame/expand glyph and a gamepad glyph.
  - A bell with a count ("1" in B, "2" in A).
  - The workspace row: the active workspace as a pill showing its number
    ("2"), the others as dots.
  - Bluetooth, Wi-Fi, and a power glyph.
- The track title in the media chip changes with the track (B 0 s vs
  1.5 s).

**Inferred:** the search field and folder button open an app search and the
file manager. **Unclear:** what the dot, download and frame glyphs do. Hover
behaviour on the bar is never shown.

## 2. Panels that open from the bar

### 2a. Control centre (B 0–1.2 s; A 0 s and 6.7 s)

**Observed:**
- **Placement:** a tall card (about 385x610 px in the band) under the right
  end of the bar, with a small gap and rounded corners on all four sides.
- **Header:** a × button, a "Control" tab (active pill with a gear) next to
  a grid tab, and a pencil edit button.
- **Sliders:** volume, microphone and brightness in one row of slim pill
  sliders.
- **Toggle tiles:** Wi-Fi (off, crossed out), Bluetooth (on, accent fill),
  Light, Notifications, a screen-recording tile showing its running timer
  ("00:00:02") in accent fill, and "Take screenshot".
- **Media card:**
  - The cover is cut into a scalloped (wavy-edged) circle, ringed by a
    circular progress arc.
  - Title and artist.
  - A wavy ("squiggle") progress line.
  - Previous, rewind, play/pause, fast-forward and next.
  - A second, round cover partly visible on the right.
- **Notifications card:** "Notifications · 1 notifications", "Clear all",
  and an item (source "Screen recording", "Recording saved", the file path)
  with its own ×.
- **Wi-Fi click** (B 0.47–0.8 s): the tile fills with the accent over about
  4 frames.
- **Close** (B 0.9–1.1 s): the card slides to the right and fades out in
  about 2–3 frames at 15 fps, roughly 150–200 ms.

**Unclear:** whether it opened by hover or by click, and which bar glyph
opened it. The close isn't shown being triggered.

### 2b. Screen-recording indicator (B 1.3 s onward; A 6 s)

**Observed:** a small card hanging under the right end of the bar, with a
red dot, a running timer ("00:00:03" … "00:00:20"), and mic-mute, pause and
stop buttons. It appears as the control centre leaves and stays while the
recording runs.

### 2c. Performance / "gaming hub" panel (A 6.6–7.0 s, at 2x)

**Observed:**
- **Placement:** a card under the left part of the bar.
- **Header:** the time and four small glyphs (a window, Bluetooth, a bell
  with "2", a tile), plus a ×.
- **Gauges:** CPU 21% and GPU 23% as ring gauges, with VRAM "1.2/8 GB",
  "37 W" and "1307 MHz" under them.
- **Other rows:**
  - "FPS: No data" with a "Shift+F2" hint.
  - A recording row with its timer and camera, mic and bell buttons.
  - "RAM 25% / 3.9 GB".
  - "Ping 39 ms 1.1.1.1".
  - A "Performance profile" row with Low, Medium (selected) and High.
  - Volume (17%) and brightness (97%) bars.
- **Motion:** it opens top-down from just under the bar (a partial
  top-only frame at 6.6 s) and is gone two frames after 7.0 s.

**Unclear:** which glyph opens it. A gamepad sits at the right of the bar,
yet the panel is on the left.

## 3. Desktop widgets

Every widget below pans with the windows (section 4). Each has its own shape.

| Widget | Seen | Observed |
|---|---|---|
| Analog clock | B throughout | Round pale face with large 12/3/6/9 numerals, dark hour hand, accent minute hand, a dot on the rim (seconds or a marker; unclear) |
| Digital clock | A 2–7 s | Hours over minutes ("08" over "01"), stacked, with a thin vertical hand crossing them (a hybrid; detail unclear under the caption) |
| Calendar / reminders | B 4 s, A 0 s | "Mon 19 Oct" heading, category chips (Reminder, Holiday, Birthday, Event), "Add a reminder…" field with a round + button, "No reminders for this day yet" |
| Date tile | B 8–10 s | "19 / Mon Oct" in a small rounded pentagon |
| Weather card | B 0 s | "21° Overcast"; Today / Tomorrow / next day as round chips with highs and lows; "Feels like 19 °C" with a wavy meter |
| Weather tile | B 4 s, A 4 s | Large "21°" with a sun-and-cloud icon in a tilted rounded square; A adds a forecast row (26°/12°, 18°/15°, 20°/14°) and "24 km/h" |
| Disk | B throughout | "Disk 32%" inside a scalloped cloud shape, filled from the bottom like liquid to its level |
| RAM | B throughout, A 3–4 s | "RAM 25%" as a liquid level in a rounded card (B); "24%" in a bowl shape (A) |
| CPU | B 7–10 s | "CPU 12%" in a rounded pentagon |
| Stopwatch | B throughout | Current time ("03:31") over "00:00.00", with reset, play (accent circle) and lap buttons |
| Mini player | B 4–9 s | Scalloped cover with progress ring, title, wavy progress line, five transport buttons |
| Sensor waves | A 3.3 s | Temperature (14 °C) and humidity (57 %) as sine-wave meters |
| Pixel blobs | A 3–4 s | Large dark pixelated blobs (a lava-lamp-like animation?). **Unclear** whether this is a widget or an app window |

Not shell widgets:
- **The tall bar visualizer** is cava in a terminal window: htop in B lists
  a `cava` process.
- **The big lyrics view** is a music application window (YouTube Music
  style: "Now playing / Listen again", Up next / Lyrics / Related / Info).
- **htop, fastfetch and a code editor** are ordinary windows.

## 4. Spatial behaviour

**Observed:**
- **Panning (B 3.8–10 s; A 2–5 s):** the whole desktop pans in several
  directions. Windows and widgets move together and keep their relative
  layout, and the motion is smooth across frames.
- **The code on screen:** the editor shows `scripts/infinite_desktop_core.py`
  with `active_drag = super_pressed and alt_pressed` and accumulated
  `acc_x`/`acc_y` in a 16 ms loop. Panning is a SUPER+ALT drag, with
  inertia hinted by `INERTIA_SAMPLE` / `INERTIA_MAX_SPEED` in A at 2.7 s.
- **The bar during the pan:** absent in B from 3.8 s to 10.0 s and back at
  10.2 s, with the recording card back too.

**Unclear:** whether the bar hides during a drag or the creator cropped or
zoomed that part of the clip. Widget scale is the same before and after, so
it's not obviously a zoom.

## 5. Differences between the clips

- **Present only in A (newer):**
  - The performance panel.
  - A Settings app with General, Canvas, Screen recording, Gaming hub and
    About pages, and an Appearance page with a wallpaper picker, a shell
    palette and a terminal palette.
  - The stacked digital clock, the sensor waves and the pixel blobs.
- **Present only in B (older):** the analog clock with numerals, the shaped
  disk, RAM and CPU tiles, and the weather card variants.
- **Present in both:** the bar layout, control centre, calendar/reminders
  widget and recording indicator.

## 6. Mapping to DXrice

Status as of `feat/redesign` at the end of the 2026-10-21 refinement pass.
**Done** means implemented and covered by a test. **Partial** means some of
the reference's behaviour exists and the rest is missing for the reason given.
**Not done** means it is absent. Nothing in this table has been checked on the
real desktop unless it says **live**. The pass's own changes have not been
deployed, so none of them are live yet.

### The bar and its panels

| Reference | DXrice | Status |
|---|---|---|
| One continuous bar with grouped sections | One strip: apps/workspaces/window left, clock centre, indicators right (`TopBar.qml`, `ShellIsland.qml`) | **Done** (4f0e2c2), live since 4f0e2c2 was deployed |
| Panels connected to the bar | Each panel grows down out of the bar under its section, joined by concave fillets; a panel that reaches a bar end squares that corner off | **Done** (4f0e2c2, 8899a80) |
| Moving between sections | Hover a neighbour: the panel turns into the next section without closing, after an 80 ms settle so a sweep doesn't flick through each one | **Done** (572614b) |
| Panel size changes | An open panel eases to its new size (another section, the Dashboard); another panel taking over fades out, then in | **Done** (572614b) |
| Search field in the bar | Search pill opens Applications (search, pinned shortcuts, open windows with focus/close, most-used, Shortcuts editor tab) | **Done** (4f0e2c2, 98143a6) |
| Folder button beside the search | none | **Not done**: a shortcut to the file manager does the same; it isn't part of the search pill |
| Media chip | Shown while a player exists; opens the Media section: cover, player choice, seek, volume, transport | **Done** (297db80, f4e5eab) |
| Time with date | Clock with date; opens calendar + agenda | **Done** |
| Bell with count | Unread count from `makoctl`; dismiss and clear all | **Done** (297db80) |
| Workspace pill with number | Active pill shows its number | **Done** (297db80) |
| Wi-Fi / Bluetooth / power | Their own sections | **Done** |
| Bluetooth pairing | A timed scan (`bluetoothctl --timeout 12 scan on`), nearby devices apart from paired ones, Pair = pair + trust + connect. A device that needs a PIN is answered by the session's agent (blueman-applet); with none running the panel says so | **Done** (4d38dc3); a real pairing not tried |
| Control-centre sliders | Volume, mic and brightness in the Sound section and Dashboard | **Done** |
| Mic mute | In the Sound section, and a red mark beside the bar's volume while the mic is muted | **Done** (4d38dc3) |
| Screenshot / record tiles | Capture section: region or screen, for shots and recordings; sound for a recording (none, desktop, microphone) | **Done** (297db80, 4d38dc3); SIGINT finishing the file and a desktop-audio stream verified with wf-recorder on this machine |
| Recording indicator under the bar | A card hangs from the capture mark while recording: time, sound, Stop | **Partial** (4d38dc3): no pause and no mid-recording mic toggle. wf-recorder can do neither, so neither control is shown |
| Performance panel | CPU/memory/GPU rings, disk, network, load, uptime, VRAM, GPU power and clock (AMD sysfs), ping (`ping_host`, default 1.1.1.1, only while shown), link to the Dashboard graphs | **Partial** (297db80, 4d38dc3): no FPS (no source), no performance profile (`powerprofilesctl` isn't installed) |
| Notifications card | Notifications section | **Done** |
| Power with confirmation | Lock, log out, restart, shut down; the last three ask once more | **Done** (297db80) |

### Desktop widgets

| Reference | DXrice | Status |
|---|---|---|
| Widgets pan with the desktop | On by default (`widgets_world`, per-widget `widget_<name>_world`). One shared spring with hyprland.lua's window constants, so they move in step with the windows; every camera move reports to the viewport (drag, SUPER+arrows, SUPER+G recentre, overview, edge push); a workspace switch cuts | **Done** (61bdb69); keeping pace with real windows is **not verified live** |
| Analog clock with numerals | `clock_style: analog`, `clock_face` | **Done** (89bc47c) |
| Stacked digital clock | none | **Not done** |
| Calendar / reminders | Reminders widget + calendar agenda, kept locally | **Done** (89bc47c, 57b23c1) |
| Date tile | Part of the reminders widget | **Partial** |
| Shaped disk / RAM / CPU | Meter widgets, one 150 px footprint, liquid level | **Done** (89bc47c, 57b23c1) |
| Weather card and tile | `weather_style` card or tile | **Done**; the Today/Tomorrow chips and wavy "feels like" meter are not |
| Stopwatch | Timer widget with laps | **Done** (89bc47c) |
| Mini player | Music widget | **Done**; scalloped cover and wavy line not done (styling only) |
| Sensor waves, pixel blobs | none | **Not done** (no humidity source; blobs unclear) |
| Visualizer | `AudioVisualizer`, a 150 px band at 1080p (scaled), kept clear of widgets while a player exists | **Done** (61bdb69) |
| Widget layout | WidgetStack: corners stack, a full side wraps beside its narrowest neighbour, everything at the screen's scale (0.72x-1.3x) | **Done** (61bdb69, 57b23c1) |
| Arranging | Drag any widget to a corner (Theme editor > Arrange on the desktop, or `qs ipc call widgets arrange`); saved to theme.json, and the editor no longer writes its stale copy over it | **Done** (this pass) |
| Dock at the bottom | Removed; shortcuts and their editor live in the bar | **Done** (4f0e2c2) |

### What only the real desktop can show

Things these tests cannot settle, to check after deploying:
- Widgets keep pace with the windows during a SUPER+ALT drag and a SUPER+arrow jump.
- Hover timing feels right moving across the bar and down into a panel.
- The fillets and shadow at the bar/panel joint with the GPU's blur.
- Typing in the reminders widget (Bottom layer, OnDemand keyboard).
- SUPER+R gives Applications the keyboard.
