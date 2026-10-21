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

## 6. Mapping to DXrice (status as of feat/redesign, 2026-10-21)

| Reference | DXrice | Status / action |
|---|---|---|
| One continuous bar | Three separate pills | **Rebuilding**: one strip, sections inside it, panels hanging from it (ShellIsland/TopBar rewrite) |
| Search field in the bar | Launcher icon button | **Add**: a search pill in the left section that opens Applications |
| Media chip in the bar | none | **Add**: shown while a player exists, opening a media section (MediaSession) |
| Time with date | Time + date in one line | Works; keep |
| Bell with count | Bell, no count | **Add** the count from `makoctl history` |
| Workspace pill with number | Pill and dots, no number | **Add** the number to the active pill |
| Bluetooth / Wi-Fi / power | Indicators, each with its own section | Works (f1e3ea5, a4a11d9 pending deploy) |
| Control centre sliders and tiles | Dashboard tab (Wi-Fi/BT/DND/Keep awake) | Mostly there; **add** screenshot and screen-record actions (grim/slurp and wf-recorder are installed) |
| Notifications card with Clear all / × | Notifications section lists history | **Add** dismiss and clear (checking `makoctl` on this machine first) |
| Recording indicator under the bar | none | **Add** with the recording action: timer, stop (wf-recorder); mic mute and pause only if wf-recorder supports them here |
| Performance panel | Dashboard Performance tab | **Add** a bar section reading PerformanceService. Ping, FPS, performance profile: powerprofilesctl isn't installed, so no profile row; no FPS source |
| Calendar/reminders widget | Calendar panel, no events | **Add** a local reminders store (labelled local) shared by the calendar panel and a desktop widget |
| Analog clock with numerals | Analog style with ticks | **Add** numerals as a face option |
| Shaped disk/RAM/CPU tiles | System widget (one card) | **Add** shaped meter widgets with a liquid fill, using real PerformanceService values |
| Weather tile | Weather card | **Add** a compact tile variant from the same weather data |
| Stopwatch | TimerWidget (stopwatch + countdown) | Works; **add** laps |
| Mini player | MusicWidget | Works, now with an idle state (f4e5eab); scalloped art and a wavy line are optional styling |
| Widgets pan with the desktop | Opt-in per widget (c035869) | Works when on; **consider** making it the default (global key, per-widget override) |
| Bar fixed while panning | Bar is screen-fixed | Works |
| Visualizer | AudioVisualizer widget | Exists; the reference's is a cava window |
| Dock at the bottom | Dock with shortcuts and taskbar editor | **Remove** after moving the editor and shortcuts into the bar (brief: no duplicate launcher) |
