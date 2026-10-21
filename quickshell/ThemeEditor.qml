import QtQuick
import QtQuick.Dialogs
import QtQuick.Effects
import "LayoutPreviews.js" as Prev
import Quickshell
import Quickshell.Io
import Quickshell.Wayland

// DXrice Theme editor -- Quickshell rewrite of dxrice_theme_gui.py.
// Edits the same live ~/.config/dxrice/theme.json and, on Apply, shells
// out to the existing scripts/dxrice_apply_theme.py to do the actual
// template rendering + hot-reload -- that pipeline (waybar/wofi/mako/
// kitty/hyprlock templates, the hyprland.lua patcher) stays exactly as
// it is; this window only needs to read/write the JSON.
//
// Laid out as a real settings app -- a searchable sidebar of categories
// (icon + title + subtitle) next to a content pane that swaps per
// category -- instead of every field dumped down one long scrolling
// column. This is the actual structure end-4/caelestia-style settings
// apps use; a single flat list is what was reading as "cheap."
//
// A real wlr-layer-shell panel hanging flush off the bar (same drawer
// pattern as QuickSettings.qml: zero gap, bottom-only rounding, no
// decorative seam), centered under it -- not a separate floating OS
// window. A standalone window is exactly the "still a standalone GUI"
// complaint this replaces.
PanelWindow {
    id: root
    // shell.qml destroys this panel the instant closeRequested() fires, so
    // requestClose() plays the reveal in reverse first and only then emits
    // the real signal. requestClose() itself is triggered reactively by
    // shell.qml watching PanelManager.current (see its Connections block) --
    // every internal dismissal path here (X, Escape, click-outside) goes
    // through `PanelManager.close("theme")`, never `root.requestClose()`
    // directly, so PanelManager.current stays the one accurate record of
    // what's open regardless of which of the three dismissed it.
    signal closeRequested()
    property bool closing: false
    function requestClose() {
        if (root.closing) return;
        root.closing = true;
        closeTimer.start();
    }
    // Reopening while still mid-close (PanelManager.current leaving
    // "theme" and coming right back within the close-animation window) used
    // to be silently swallowed: closeTimer, already running from the
    // original close, had no way to know the user changed their mind, so it
    // fired on schedule and tore the whole panel down regardless -- the
    // user's last action said "open" but the panel ended up closed with no
    // feedback. shell.qml calls this before re-activating the loader so the
    // pending close is cancelled instead of racing it.
    function cancelClose() {
        if (!root.closing) return;
        closeTimer.stop();
        root.closing = false;
    }
    Timer { id: closeTimer; interval: Theme.durationEnter + 20; onTriggered: root.closeRequested() }
    color: "transparent"
    exclusionMode: ExclusionMode.Ignore
    aboveWindows: true
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.namespace: "dxrice-theme"
    // Released the moment the close starts, like TopBar's own focusable:
    // keystrokes typed right after closing belong to the app underneath,
    // not to a panel that is only still alive to finish animating away.
    focusable: !root.closing

    // The panel's own natural size -- was the whole window's implicitWidth/
    // Height back when this was a plain top-center window with no
    // click-outside-to-dismiss. Now the window itself spans the full screen
    // (same reasoning as Dock.qml's implicitHeight: root.screen.height even
    // though the dock pill only occupies its bottom strip) so a click
    // anywhere outside the panel has somewhere on THIS window's surface to
    // land; panelSurface below is what actually gets positioned/sized to
    // this box.
    // Scales with the real screen instead of one constant that only looks
    // right at one resolution: wider screens give Wallpaper/Lock Screen's
    // ResponsiveSplit previews real room to sit beside their controls,
    // narrower screens (1536px class) stay at the already-verified 700
    // floor. Every category's own content already sizes off this width via
    // `parent.width` bindings, so widening it is a pure gain everywhere,
    // never a source of new clipping.
    readonly property real panelWidth: Math.round(Math.min(920, Math.max(700, (root.screen ? root.screen.width : 1920) * 0.46)))
    // Content-driven, not one fixed slab for every category: a sparse
    // category (Lock Screen, Experience) gets a shorter panel instead of
    // the old "always 640, leave the rest bare" behavior -- the same
    // fixed-height-Card problem this file's Lock Screen/Experience panes
    // used to have, just one level up, at the panel itself. `maxPanelHeight`
    // is still capped against the real screen (a fixed max, not a fixed
    // value: "fits its own Rectangle" is not the same claim as "fits on
    // this screen"), and `minPanelHeight` keeps the sidebar's 7 categories
    // legible without needing its own internal scroll on every category.
    // 800, not 640: at 640 a 1080p screen cut the Colors page off mid-row
    // with a third of the screen still free. Bounded by the dock's reserved
    // strip as well as the bar's: the colour picker stays within the
    // panel's span, so a panel reaching over the dock put the picker's
    // buttons under the dock, which took their clicks (1024x768).
    readonly property real maxPanelHeight: Math.min(800, (root.screen ? root.screen.height : 1080)
        - ShellSurface.topEdgeHeight - ShellSurface.bottomEdgeHeight - ShellSurface.gap)
    readonly property real minPanelHeight: Math.min(root.maxPanelHeight, 480)
    readonly property real contentNaturalHeight: header.height + Theme.padLg * 2 + (paneLoader.item ? paneLoader.item.implicitHeight : 0)
    readonly property real panelHeight: Math.max(root.minPanelHeight, Math.min(root.maxPanelHeight, root.contentNaturalHeight))
    readonly property real panelX: Math.round(((root.screen ? root.screen.width : 1920) - root.panelWidth) / 2)
    readonly property real panelY: ShellSurface.topEdgeHeight

    implicitWidth: root.screen ? root.screen.width : 1920
    implicitHeight: root.screen ? root.screen.height : 1080
    anchors { top: true; left: true; right: true; bottom: true }

    // Without this, the window's own full-screen rectangle would accept
    // input everywhere for its entire lifetime. The first Region keeps the
    // panel itself exact to `panelSurface`'s own live geometry (so the click
    // target always matches what's actually visible, growing and shrinking
    // with the reveal animation rather than being some fixed box from frame
    // one); the second is click-outside-to-dismiss -- the rest of the
    // now-full-screen window, so a click that misses the panel entirely
    // still reaches `dismissArea` below and closes it.
    //
    // Both collapse to nothing the moment a close STARTS (`closing`), not
    // when the window is torn down: the window has to outlive the close for
    // its reverse-reveal to play (closeTimer, ~440ms at the default speed),
    // and for all of that time the full-screen region used to keep catching
    // every click anywhere on the desktop -- an invisible catcher over the
    // whole screen, right after the user asked for the panel to go away.
    // Reopening mid-close (cancelClose) restores both.
    mask: Region {
        Region { item: root.closing ? null : panelSurface }
        Region { x: 0; y: 0; width: root.closing ? 0 : root.width; height: root.closing ? 0 : root.height }
    }

    MouseArea {
        id: dismissArea
        anchors.fill: parent
        enabled: !root.closing
        // Outside both the panel and the picker: the picker goes first,
        // the same peel order as Escape (and as the Taskbar's Add
        // Shortcut branch) -- a stray click while choosing a colour must
        // not throw away the whole unapplied theme.
        onClicked: root.pickerOpen ? root.closePicker() : PanelManager.close("theme")
    }

    readonly property string repoDir: Quickshell.shellDir + "/.."
    readonly property string themeJsonPath: Xdg.configDir + "/theme.json"

    // ---- draft fields (mirrors theme.json 1:1; camelCase would need a
    // translation table for every read/write, so these stay snake_case) ----
    property string glass_bg: "12141a"
    property string glass_bg_active: "232630"
    property string glass_text: "e6e6e6"
    property string glass_text_active: "ffffff"
    property string glass_border: "ffffff"
    property string accent: "e67878"
    property string hypr_active_border_1: "8090a0"
    property string hypr_active_border_2: "c0a0b0"
    property string hypr_inactive_border: "1d2021"

    property real opacity_idle: 0.55
    property real opacity_active: 0.85
    property real border_opacity_idle: 0.08
    property real border_opacity_active: 0.25
    property real kitty_opacity: 0.7643
    property real hypr_blur_size: 6
    property real hypr_blur_passes: 3
    property real hypr_blur_vibrancy: 0.2

    property real radius: 12
    property real hypr_rounding: 12
    property real hypr_gaps_in: 5
    property real hypr_gaps_out: 12
    property real hypr_border_size: 2
    property real hypr_active_opacity: 0.92
    property real hypr_inactive_opacity: 0.85
    property real hypr_active_border_angle: 45

    property real lock_blur_passes: 3
    property real lock_blur_size: 8
    property real lock_blur_vibrancy: 0.1696
    property real lock_bg_opacity: 0.7

    property real font_size_waybar: 13
    property real font_size_waybar_icons: 22
    property real font_size_wofi: 14
    property real font_size_mako: 11

    property real anim_duration_ms: 150
    property real ui_density: 1.0
    property real shadow_intensity: 1.0
    property real text_scale: 1.0

    // Behaviour switches. Saved in theme.json beside everything else (one
    // file, one Apply, one Revert), but nothing a preset or "Generate from
    // wallpaper" touches -- those only carry colour keys.
    property bool auto_place_windows: true
    // Window arrangement, chosen separately for windows opening on their own
    // and for SUPER+G: the Galaxy Spiral (the default, and what a theme.json
    // without the key has always meant), Compact or Expansion -- see
    // scripts/dxrice_layout_apply.py.
    property string window_layout: "galaxy"
    property bool reduce_motion: false
    // Desktop widgets (see DesktopWidget.qml): whether each is shown and in
    // which corner, plus how the clock reads.
    property bool widget_clock: true
    property bool widget_music: true
    property bool widget_system: false
    property string widget_clock_pos: "top-left"
    property string widget_music_pos: "bottom-left"
    property string widget_system_pos: "top-right"
    property bool clock_24h: true
    property bool clock_seconds: false
    property string clock_style: "type"
    property bool widget_visualizer: true
    property string visualizer_style: "bars"
    property bool widget_weather: false
    property string widget_weather_pos: "bottom-right"
    property string weather_location: ""
    property string weather_units: "metric"

    property string font_family: "JetBrainsMono Nerd Font"
    // Empty = automatic (see Theme.fontFamily): Noto Sans while font_family
    // is the shipped terminal font, otherwise font_family itself.
    property string ui_font_family: ""
    property string wallpaper: ""

    property bool dirty: false
    property bool applying: false
    // Inline, non-modal feedback in the header (see `header`): why the last
    // Apply failed, or that a kept draft had to be dropped. Cleared by the
    // next edit, Apply or Revert.
    property string applyError: ""
    property string draftNotice: ""
    onDirtyChanged: if (root.dirty) { root.applyError = ""; root.draftNotice = ""; root.justApplied = false; }

    readonly property var colorFields: [
        { key: "glass_bg", label: "Panel background", sub: "Panels, launcher and terminal background" },
        { key: "glass_bg_active", label: "Active panel background", sub: "Focused workspace, selected entries" },
        { key: "glass_text", label: "Text", sub: "Base text color" },
        { key: "glass_text_active", label: "Active text", sub: "Text on focused/selected elements" },
        { key: "glass_border", label: "Panel border", sub: "Hairline border around panels" },
        { key: "accent", label: "Accent", sub: "Selection, indicators and progress -- used sparingly" },
    ]
    readonly property var borderColorFields: [
        { key: "hypr_active_border_1", label: "Active border -- color 1", sub: "Focused window gradient start" },
        { key: "hypr_active_border_2", label: "Active border -- color 2", sub: "Focused window gradient end" },
        { key: "hypr_inactive_border", label: "Inactive border", sub: "Unfocused window border" },
    ]
    readonly property var blurFields: [
        { key: "opacity_idle", label: "Panel opacity (idle)", min: 0, max: 1, decimals: 2 },
        { key: "opacity_active", label: "Panel opacity (active)", min: 0, max: 1, decimals: 2 },
        { key: "border_opacity_idle", label: "Border opacity (idle)", min: 0, max: 1, decimals: 2 },
        { key: "border_opacity_active", label: "Border opacity (active)", min: 0, max: 1, decimals: 2 },
        { key: "kitty_opacity", label: "Terminal opacity", min: 0, max: 1, decimals: 2 },
        { key: "hypr_blur_size", label: "Window blur size", min: 0, max: 20, decimals: 0, unit: "px" },
        { key: "hypr_blur_passes", label: "Window blur passes", min: 0, max: 10, decimals: 0 },
        { key: "hypr_blur_vibrancy", label: "Window blur vibrancy", min: 0, max: 1, decimals: 2 },
    ]
    readonly property var layoutFields: [
        { key: "radius", label: "Corner roundness (panels, launcher)", min: 0, max: 30, decimals: 0 },
        { key: "hypr_rounding", label: "Window corner rounding", min: 0, max: 30, decimals: 0, unit: "px" },
        { key: "hypr_gaps_in", label: "Gaps between windows", min: 0, max: 40, decimals: 0, unit: "px" },
        { key: "hypr_gaps_out", label: "Gaps to screen edge", min: 0, max: 60, decimals: 0, unit: "px" },
        { key: "hypr_border_size", label: "Window border thickness", min: 0, max: 10, decimals: 0, unit: "px" },
        { key: "hypr_active_opacity", label: "Focused window opacity", min: 0, max: 1, decimals: 2 },
        { key: "hypr_inactive_opacity", label: "Unfocused window opacity", min: 0, max: 1, decimals: 2 },
        { key: "hypr_active_border_angle", label: "Active border gradient angle", min: 0, max: 360, decimals: 0, unit: "°" },
    ]
    readonly property var lockFields: [
        { key: "lock_blur_passes", label: "Blur passes", min: 0, max: 10, decimals: 0 },
        { key: "lock_blur_size", label: "Blur size", min: 0, max: 20, decimals: 0, unit: "px" },
        { key: "lock_blur_vibrancy", label: "Blur vibrancy", min: 0, max: 1, decimals: 2 },
        { key: "lock_bg_opacity", label: "Input opacity", min: 0, max: 1, decimals: 2 },
    ]
    readonly property var shellTextFields: [
        { key: "text_scale", label: "Shell text size (bar, panels, this editor)", min: 0.8, max: 1.4, decimals: 2 },
    ]
    readonly property var fontSizeFields: [
        { key: "font_size_waybar", label: "Taskbar text size", min: 8, max: 24, decimals: 0 },
        { key: "font_size_waybar_icons", label: "Taskbar app icon size", min: 8, max: 40, decimals: 0 },
        { key: "font_size_wofi", label: "App launcher font size", min: 8, max: 24, decimals: 0 },
        { key: "font_size_mako", label: "Notification font size", min: 8, max: 24, decimals: 0 },
    ]
    readonly property var behaviorFields: [
        { key: "auto_place_windows", objectName: "autoPlaceSwitch", label: "Automatic window placement",
          sub: "Newly opened windows join the arrangement on their own, next to what's already open. Nothing else moves. SUPER+G still rearranges everything." },
        { key: "reduce_motion", objectName: "reduceMotionSwitch", label: "Reduce motion",
          sub: "Panels appear and disappear without sliding or scaling." },
    ]
    readonly property var widgetFields: [
        { key: "widget_clock", objectName: "widgetClockSwitch", label: "Clock",
          sub: "The time and date, in a corner of the desktop." },
        { key: "clock_24h", objectName: "clock24hSwitch", label: "24-hour clock", sub: "Off shows AM and PM." },
        { key: "clock_seconds", objectName: "clockSecondsSwitch", label: "Show seconds", sub: "Beside the time, ticking once a second." },
        { key: "widget_music", objectName: "widgetMusicSwitch", label: "Now playing",
          sub: "The track from whichever media player is open, with play, skip and a seekable bar. Nothing shows while nothing plays." },
        { key: "widget_visualizer", objectName: "widgetVisualizerSwitch", label: "Audio visualizer",
          sub: "A real spectrum of what is playing (from cava), along the bottom of the desktop. It runs only while music plays." },
        { key: "widget_weather", objectName: "widgetWeatherSwitch", label: "Weather",
          sub: "Now and the next three days, from Open-Meteo, for the place you type below. Nothing is shown for a place you haven't set." },
        { key: "widget_system", objectName: "widgetSystemSwitch", label: "System monitor",
          sub: "Processor, memory, graphics and network, with the last minute of each. Measured only while it is on." },
    ]
    readonly property var experienceFields: [
        { key: "anim_duration_ms", label: "Animation speed (lower = snappier)", min: 0, max: 500, decimals: 0, unit: "ms" },
        { key: "ui_density", label: "Spacing inside panels", min: 0.5, max: 1.5, decimals: 2 },
        { key: "shadow_intensity", label: "Panel shadow strength (Quickshell only)", min: 0, max: 1.5, decimals: 2 },
    ]
    readonly property var presets: ({
        "Glass Charcoal": { glass_bg: "12141a", glass_bg_active: "232630", glass_text: "e6e6e6", glass_text_active: "ffffff", glass_border: "ffffff", accent: "e67878", radius: 12, hypr_active_border_1: "8090a0", hypr_active_border_2: "c0a0b0", hypr_inactive_border: "1d2021" },
        "Nord": { glass_bg: "2e3440", glass_bg_active: "3b4252", glass_text: "d8dee9", glass_text_active: "eceff4", glass_border: "88c0d0", accent: "bf616a", radius: 8, hypr_active_border_1: "88c0d0", hypr_active_border_2: "81a1c1", hypr_inactive_border: "3b4252" },
        "Dracula": { glass_bg: "282a36", glass_bg_active: "44475a", glass_text: "f8f8f2", glass_text_active: "ffffff", glass_border: "bd93f9", accent: "ff5555", radius: 10, hypr_active_border_1: "ff79c6", hypr_active_border_2: "bd93f9", hypr_inactive_border: "44475a" },
        "Sunset": { glass_bg: "1a1210", glass_bg_active: "3a2420", glass_text: "f0e0d6", glass_text_active: "ffffff", glass_border: "ffb385", accent: "ff6b4a", radius: 16, hypr_active_border_1: "ff7e5f", hypr_active_border_2: "feb47b", hypr_inactive_border: "2a1d18" },
        "Monochrome": { glass_bg: "0a0a0a", glass_bg_active: "1c1c1c", glass_text: "cfcfcf", glass_text_active: "ffffff", glass_border: "ffffff", accent: "5a5a5a", radius: 12, hypr_active_border_1: "e8e8e8", hypr_active_border_2: "ffffff", hypr_inactive_border: "1a1a1a" },
    })

    // ---- sidebar categories ----
    readonly property var categories: [
        { id: "colors", glyph: "", label: "Colors", sub: "Presets and palette" },
        { id: "blur", glyph: "", label: "Transparency & Blur", sub: "Opacity and blur" },
        { id: "layout", glyph: "", label: "Layout", sub: "Rounding and gaps" },
        { id: "lock", glyph: "", label: "Lock Screen", sub: "Blur and input field" },
        { id: "fonts", glyph: "", label: "Fonts", sub: "Family and sizes" },
        { id: "experience", glyph: "", label: "Experience", sub: "Motion and windows" },
        { id: "wallpaper", glyph: "", label: "Wallpaper", sub: "Background image" },
    ]
    property string currentCategory: "colors"
    property string searchText: ""
    readonly property var filteredCategories: {
        const q = root.searchText.trim().toLowerCase();
        if (!q) return root.categories;
        return root.categories.filter((c) => c.label.toLowerCase().includes(q) || c.sub.toLowerCase().includes(q));
    }

    function allKeys() {
        const keys = ["font_family", "ui_font_family", "wallpaper"];
        for (const f of colorFields) keys.push(f.key);
        for (const f of borderColorFields) keys.push(f.key);
        for (const f of blurFields) keys.push(f.key);
        for (const f of layoutFields) keys.push(f.key);
        for (const f of lockFields) keys.push(f.key);
        for (const f of shellTextFields) keys.push(f.key);
        for (const f of fontSizeFields) keys.push(f.key);
        for (const f of experienceFields) keys.push(f.key);
        for (const f of behaviorFields) keys.push(f.key);
        keys.push("window_layout");
        for (const f of widgetFields) keys.push(f.key);
        keys.push("widget_clock_pos", "widget_music_pos", "widget_system_pos", "clock_style", "visualizer_style",
                   "widget_weather_pos", "weather_location", "weather_units");
        return keys;
    }

    // Each field's own default, captured before the first load: a key
    // theme.json doesn't have yet (any setting newer than the user's file)
    // must go back to it on Revert -- only overwriting keys present in
    // the file left such an edit in place after Revert.
    property var _fieldDefaults: null
    function loadFromTheme(data) {
        if (!root._fieldDefaults) root._fieldDefaults = root.snapshot();
        for (const key of allKeys()) {
            if (data[key] !== undefined) root[key] = data[key];
            else if (root._fieldDefaults[key] !== undefined) root[key] = root._fieldDefaults[key];
        }
        // theme.json's own wallpaper field can be empty on an install that
        // never used the Theme app's own "Choose..." picker (the real
        // desktop wallpaper is set independently via hyprland.lua's
        // BG_WALLPAPER) -- fall back to the same shipped-default path
        // hyprland.lua itself falls back to, so this pane and "Generate
        // from Wallpaper" have something real to work with immediately.
        if (!root.wallpaper) {
            root.wallpaper = Quickshell.env("HOME") + "/Pictures/Wallpapers/default.png";
        }
        // a layout this version doesn't know reads as the Galaxy Spiral, as
        // the placement scripts read it (so Apply can't turn it into anything else)
        // the one window-arrangement choice, read by the shared migration
        // rule (Theme.windowLayoutOf); nothing is written until Apply
        root.window_layout = Theme.windowLayoutOf(data);
        root.dirty = false;
        root._draftBase = JSON.stringify(data);
        root._loaded = root.snapshot();
    }
    // What the fields held right after loading: Apply writes a field only if
    // the file already has it or it was changed since, so a setting you never
    // touched is never written in with the editor's default (that is how a
    // layout once got saved that nobody had chosen).
    property var _loaded: ({})

    // ---- unapplied edits survive closing (see ThemeDraft.qml) ----
    // The theme.json content the current edits are relative to. Follows the
    // live theme while there is nothing unapplied (an Apply, a change made
    // elsewhere), and stays put once there is, so a draft is always compared
    // against the theme it was actually made on.
    property string _draftBase: ""
    Connections {
        target: Theme
        function onDataChanged() { if (!root.dirty) root._draftBase = JSON.stringify(Theme.data); }
    }
    function snapshot() {
        const out = {};
        for (const key of allKeys()) out[key] = root[key];
        return out;
    }

    Component.onCompleted: {
        loadFromTheme(Theme.data);
        if (ThemeDraft.fields) {
            if (ThemeDraft.base === root._draftBase) {
                const keys = allKeys();
                for (const key in ThemeDraft.fields) {
                    if (keys.indexOf(key) >= 0) root[key] = ThemeDraft.fields[key];
                }
                if (ThemeDraft.category) root.currentCategory = ThemeDraft.category;
                root.dirty = true;
            } else {
                root.draftNotice = "Unapplied changes were discarded: the theme changed outside the editor.";
            }
            ThemeDraft.clear();
        }
    }
    // Every close path ends here (the LazyLoader destroys this window once
    // its close animation finishes), so this is the one place a draft is
    // kept -- or, with nothing unapplied, any older one dropped.
    Component.onDestruction: {
        if (root.dirty) ThemeDraft.save(root.snapshot(), root._draftBase, root.currentCategory);
        else ThemeDraft.clear();
    }

    function applyPreset(colors) {
        for (const key in colors) root[key] = colors[key];
        root.dirty = true;
    }

    FileView {
        id: writer
        path: root.themeJsonPath
    }

    function save() {
        // Starts from the live theme.json and overlays the editor's own
        // fields: keys the editor doesn't model must survive a save. Writing
        // only allKeys() dropped schema_version, so every Apply then made
        // dxrice_apply_theme.py "migrate" the file again -- a fresh backup
        // per Apply, rotating real pre-migration backups out of the 10 kept.
        const obj = {};
        for (const key in Theme.data) obj[key] = Theme.data[key];
        for (const key of allKeys()) {
            if (key in Theme.data || JSON.stringify(root[key]) !== JSON.stringify(root._loaded[key]))
                obj[key] = root[key];
        }
        // one window-arrangement setting: the two an earlier build had are
        // replaced by it (the one migration Apply performs)
        if ("layout_auto_place" in obj || "layout_super_g" in obj) {
            obj.window_layout = root.window_layout;
            delete obj.layout_auto_place;
            delete obj.layout_super_g;
        }
        writer.setText(JSON.stringify(obj, null, 4));
        // Written to theme.json, so there is no longer anything unapplied
        // to keep (even if rendering it fails -- see applyProc).
        root.dirty = false;
        root._draftBase = JSON.stringify(obj);
    }

    // Apply's outcome. Before, onExited only cleared `applying`: a script
    // that failed (a template error, an unreadable theme.json -- it exits
    // non-zero) looked exactly like one that worked. And Quickshell's
    // Process emits no `exited` at all when the program cannot start (it
    // only drops `running`), which left the button on "Applying..." for
    // good. The start-failure check runs one event-loop turn after
    // `running` drops, so it sees `exited` first whichever order the two
    // signals arrive in.
    property bool _applyExited: false
    property bool justApplied: false
    Timer { id: appliedTimer; interval: 2400; onTriggered: root.justApplied = false }
    Process {
        id: applyProc
        command: ["python3", root.repoDir + "/scripts/dxrice_apply_theme.py"]
        stderr: StdioCollector { id: applyStderr }
        onExited: (exitCode, exitStatus) => {
            root._applyExited = true;
            root.applying = false;
            root.applyError = (exitCode === 0 && exitStatus === 0) ? "" : root._applyFailure(applyStderr.text, exitCode);
            // Success says so, briefly -- the Apply dot going away on its
            // own was easy to miss.
            root.justApplied = root.applyError.length === 0;
            if (root.justApplied) appliedTimer.restart();
        }
        onRunningChanged: if (!running && root.applying) Qt.callLater(root._checkApplyStarted)
    }
    function _checkApplyStarted() {
        if (root.applying && !root._applyExited) {
            root.applying = false;
            root.applyError = "Apply failed: couldn't run the theme script (is python3 installed?)";
        }
    }
    function _applyFailure(stderrText, exitCode) {
        // The last non-empty stderr line is the useful one: a Python
        // traceback ends with the exception, the script's own messages are
        // single lines.
        const lines = String(stderrText || "").split("\n").map((l) => l.trim()).filter((l) => l.length > 0);
        return lines.length ? "Apply failed: " + lines[lines.length - 1] : "Apply failed (exit code " + exitCode + ")";
    }

    // ---- generate a full color palette from the current wallpaper --
    // the actual mechanism real end-4/caelestia rices use to make the
    // theme "match the wallpaper": sample it, derive background/accent/
    // border tones from what's actually in the image (see the script's own
    // comment for why this needs no PIL/numpy). Applies to the draft only,
    // same as a preset button -- still needs Apply to take effect. ----
    // The pictures offered in Wallpaper (scripts/dxrice_list_wallpapers.py:
    // ~/Pictures/Wallpapers and the folder of the one in use).
    property var wallpaperChoices: []
    function loadWallpaperChoices() { if (!listWallpapersProc.running) listWallpapersProc.running = true; }
    Process {
        id: listWallpapersProc
        command: ["python3", root.repoDir + "/scripts/dxrice_list_wallpapers.py", root.wallpaper]
        stdout: StdioCollector {
            onStreamFinished: {
                try { root.wallpaperChoices = JSON.parse(this.text.trim()); }
                catch (e) { root.wallpaperChoices = []; }
            }
        }
    }
    property bool generatingFromWallpaper: false
    property string wallpaperGenerateError: ""
    Process {
        id: generateProc
        // --print-only: the palette lands in this draft, nothing on disk.
        command: ["python3", root.repoDir + "/scripts/dxrice_wallpaper_theme.py", "--print-only", root.wallpaper]
        stdout: StdioCollector {
            onStreamFinished: {
                root.generatingFromWallpaper = false;
                try {
                    const palette = JSON.parse(this.text.trim());
                    root.applyPreset(palette);
                    root.wallpaperGenerateError = "";
                } catch (e) {
                    root.wallpaperGenerateError = "Could not parse the generated palette.";
                }
            }
        }
        stderr: StdioCollector {
            onStreamFinished: {
                if (this.text.trim().length > 0) root.wallpaperGenerateError = this.text.trim();
            }
        }
    }
    function generateFromWallpaper() {
        if (!root.wallpaper) {
            root.wallpaperGenerateError = "Set a wallpaper first.";
            return;
        }
        root.wallpaperGenerateError = "";
        root.generatingFromWallpaper = true;
        generateProc.running = true;
    }

    function apply() {
        if (Object.keys(Theme.data).length === 0) {
            // Theme.qml never successfully loaded the real theme.json (see
            // its blockLoading comment) -- writing now would silently
            // overwrite it with these fields' hardcoded QML defaults.
            console.warn("ThemeEditor: refusing to apply -- theme.json was never successfully loaded");
            return;
        }
        root.applyError = "";
        root.draftNotice = "";
        root.save();
        root._applyExited = false;
        root.applying = true;
        applyProc.running = true;
    }

    // Revert means "throw my edits away": that includes a kept draft.
    function revert() {
        root.closePicker();
        ThemeDraft.clear();
        root.applyError = "";
        root.draftNotice = "";
        loadFromTheme(Theme.data);
    }

    // ---- shared dialogs ----
    property string editingColorKey: ""
    // The colour picker is ColorPopover, a branch that grows out of the
    // swatch that opened it (see its own header). The swatch's rect is
    // captured relative to the drawer when it opens and then corrected for
    // how far the content pane has scrolled since, so the picker follows
    // the swatch -- panel settle, scrolling -- with plain bindings, not a
    // per-frame lookup. A swatch scrolled fully out of the pane closes it
    // (onContentYChanged below): there is nothing left to be attached to.
    property bool pickerOpen: false
    property string pickerTitle: ""
    property int pickerSession: 0
    property rect _pickerSwatch: Qt.rect(0, 0, 0, 0)
    property real _pickerScrollAtOpen: 0
    readonly property real _pickerScroll: contentFlick.contentY - root._pickerScrollAtOpen
    // editingColorKey is deliberately left set: the picker is still
    // animating closed and keeps showing that colour until it is gone.
    function closePicker() {
        root.pickerOpen = false;
    }
    function _rgba(hex, alpha) {
        return Qt.rgba(
            parseInt(hex.substring(0, 2), 16) / 255,
            parseInt(hex.substring(2, 4), 16) / 255,
            parseInt(hex.substring(4, 6), 16) / 255,
            alpha
        );
    }
    function pickColor(key, swatch, label) {
        // The same swatch again is an intentional toggle; a different one
        // retargets the open picker in place.
        if (root.pickerOpen && root.editingColorKey === key) {
            root.closePicker();
            return;
        }
        const p = swatch.mapToItem(drawer, 0, 0);
        root._pickerSwatch = Qt.rect(p.x, p.y, swatch.width, swatch.height);
        root._pickerScrollAtOpen = contentFlick.contentY;
        root.editingColorKey = key;
        root.pickerTitle = label || "Colour";
        root.pickerSession += 1;
        root.pickerOpen = true;
    }
    // Anything that invalidates what the picker is attached to closes it:
    // the panel closing, the swatch's category being swapped out, Revert
    // replacing the value it was opened on.
    onClosingChanged: if (root.closing) root.closePicker()
    onCurrentCategoryChanged: root.closePicker()
    Connections {
        target: contentFlick
        enabled: root.pickerOpen
        function onContentYChanged() {
            const view = contentViewport.mapToItem(drawer, 0, 0);
            const cy = root._pickerSwatch.y + root._pickerSwatch.height / 2 - root._pickerScroll;
            if (cy < view.y || cy > view.y + contentViewport.height) root.closePicker();
        }
    }

    FileDialog {
        id: wallpaperDialog
        onAccepted: { root.wallpaper = String(wallpaperDialog.selectedFile).replace("file://", ""); root.dirty = true; }
    }

    // ---- reusable field renderers (used by whichever category pane is
    // active -- see the Loader-per-category in the content pane below) ----
    component ColorList: Column {
        property var fields: []
        width: parent.width
        spacing: Theme.padMd
        Repeater {
            model: parent.fields
            delegate: SettingRow {
                width: parent.width
                title: modelData.label
                subtitle: modelData.sub
                Rectangle {
                    id: swatch
                    objectName: "swatch_" + modelData.key
                    width: 28; height: 28; radius: 14
                    color: "#" + root[modelData.key]
                    border.width: root.pickerOpen && root.editingColorKey === modelData.key ? 2 : Theme.borderWidth
                    border.color: root.pickerOpen && root.editingColorKey === modelData.key ? Theme.accent : Theme.borderIdle
                    MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: root.pickColor(modelData.key, swatch, modelData.label) }
                }
            }
        }
    }

    // Each numeric setting is one filled slab -- label baked into the
    // left of the fill, live value on the right, drag anywhere on the
    // bar to change it -- instead of a label line stacked over a
    // separate generic slider control.
    component SliderList: Column {
        property var fields: []
        width: parent.width
        spacing: Theme.padLg
        Repeater {
            model: parent.fields
            delegate: FillSlider {
                width: parent.width
                label: modelData.label
                unit: modelData.unit || ""
                from: modelData.min; to: modelData.max; decimals: modelData.decimals
                value: root[modelData.key]
                onChanged: (v) => { root[modelData.key] = modelData.decimals === 0 ? Math.round(v) : v; root.dirty = true; }
            }
        }
    }

    // On/off settings: a title, a sentence that says what it does
    // (wrapped, never elided -- these are the explanations), the switch.
    // One of the three layouts as a card: the picture is the real layout
    // (LayoutPreviews.js is generated from it), drawn for four windows.
    // One setting with a few named values, as a row of chips.
    component ChoiceRow: Item {
        id: choiceRow
        property string settingKey: ""
        property string idPrefix: ""
        property string label: ""
        property var options: []        // [{ value, label }]
        width: parent.width
        height: 34
        Text {
            anchors.verticalCenter: parent.verticalCenter
            text: choiceRow.label
            color: Theme.textActive; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeNormal; font.weight: Font.Medium
        }
        Row {
            anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
            spacing: Theme.padSm
            Repeater {
                model: choiceRow.options
                delegate: Rectangle {
                    id: opt
                    required property var modelData
                    readonly property bool picked: root[choiceRow.settingKey] === opt.modelData.value
                    objectName: choiceRow.idPrefix + opt.modelData.value
                    width: Math.max(92, optLabel.implicitWidth + 28); height: 30
                    radius: Theme.roundingSm
                    color: Theme.mix(Theme.layer1, Theme.accent, opt.picked ? 0.2 : (optHover.hovered ? 0.07 : 0))
                    border.width: opt.picked ? 2 : 1
                    border.color: opt.picked ? Theme.accent : Theme.borderIdle
                    Behavior on color { ColorAnimation { duration: Theme.durationFast; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveStandard } }
                    Behavior on border.color { ColorAnimation { duration: Theme.durationFast; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveStandard } }
                    HoverHandler { id: optHover; cursorShape: Qt.PointingHandCursor }
                    Text {
                        id: optLabel
                        anchors.centerIn: parent
                        text: opt.modelData.label
                        color: opt.picked ? Theme.textActive : Theme.text
                        font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSmaller; font.weight: opt.picked ? Font.DemiBold : Font.Normal
                    }
                    MouseArea {
                        anchors.fill: parent
                        onClicked: { root[choiceRow.settingKey] = opt.modelData.value; root.dirty = true; }
                    }
                }
            }
        }
    }

    // One widget's corner: four small chips laid out like the corners they name.
    component CornerRow: Item {
        id: cornerRow
        property string settingKey: ""
        property string idPrefix: ""
        property string label: ""
        width: parent.width
        height: 34
        Text {
            anchors.verticalCenter: parent.verticalCenter
            text: cornerRow.label
            color: Theme.textActive; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeNormal; font.weight: Font.Medium
        }
        Row {
            anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
            spacing: Theme.padSm
            Repeater {
                model: Theme.widgetCorners
                delegate: Rectangle {
                    id: chip
                    required property string modelData
                    readonly property bool picked: root[cornerRow.settingKey] === chip.modelData
                    objectName: cornerRow.idPrefix + chip.modelData
                    width: 92; height: 30
                    radius: Theme.roundingSm
                    color: Theme.mix(Theme.layer1, Theme.accent, chip.picked ? 0.2 : (chipHover.hovered ? 0.07 : 0))
                    border.width: chip.picked ? 2 : 1
                    border.color: chip.picked ? Theme.accent : Theme.borderIdle
                    Behavior on color { ColorAnimation { duration: Theme.durationFast; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveStandard } }
                    Behavior on border.color { ColorAnimation { duration: Theme.durationFast; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveStandard } }
                    HoverHandler { id: chipHover; cursorShape: Qt.PointingHandCursor }
                    Text {
                        anchors.centerIn: parent
                        text: chip.modelData.replace("-", " ")
                        color: chip.picked ? Theme.textActive : Theme.text
                        font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSmaller; font.weight: chip.picked ? Font.DemiBold : Font.Normal
                    }
                    MouseArea {
                        anchors.fill: parent
                        onClicked: { root[cornerRow.settingKey] = chip.modelData; root.dirty = true; }
                    }
                }
            }
        }
    }

    component LayoutPicker: Column {
        id: picker
        property string settingKey: ""
        property string title: ""
        property string sub: ""
        property string idPrefix: ""
        width: parent.width
        spacing: Theme.padMd
        Column {
            width: parent.width
            spacing: Theme.padXs
            Text { text: picker.title; color: Theme.textActive; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeNormal; font.weight: Font.Medium }
            Text { width: parent.width; text: picker.sub; color: Theme.text; opacity: Theme.opacityMuted; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSmall; wrapMode: Text.WordWrap }
        }
        Row {
            spacing: Theme.padMd
            Repeater {
                model: Prev.modes
                delegate: Item {
                    id: card
                    required property string modelData
                    required property int index
                    readonly property bool picked: root[picker.settingKey] === card.modelData
                    objectName: picker.idPrefix + card.modelData
                    width: (picker.width - (Prev.modes.length - 1) * Theme.padMd) / Prev.modes.length
                    height: stage.y + stage.height + Theme.padSm + 62
                    scale: cardHover.hovered && !card.picked ? 1.025 : 1
                    Behavior on scale { NumberAnimation { duration: Theme.durationFast; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveStandard } }
                    HoverHandler { id: cardHover; cursorShape: Qt.PointingHandCursor }
                    Rectangle {
                        anchors.fill: parent
                        radius: Theme.roundingSm
                        color: Theme.mix(Theme.layer1, Theme.accent, card.picked ? 0.14 : (cardHover.hovered ? 0.06 : 0))
                        border.width: card.picked ? 2 : 1
                        border.color: card.picked ? Theme.accent : Theme.borderIdle
                        Behavior on color { ColorAnimation { duration: Theme.durationFast; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveStandard } }
                        Behavior on border.color { ColorAnimation { duration: Theme.durationFast; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveStandard } }
                    }
                    Item {
                        id: stage
                        x: Theme.padMd; y: Theme.padMd
                        width: parent.width - 2 * Theme.padMd
                        height: width * 0.625
                        // the screen, inside a preview that reaches past it (Galaxy)
                        Rectangle {
                            readonly property var r: Prev.screens[card.modelData] ? Prev.screens[card.modelData][4] : null
                            visible: r !== null
                            x: r ? r[0] * stage.width : 0; y: r ? r[1] * stage.height : 0
                            width: r ? r[2] * stage.width : 0; height: r ? r[3] * stage.height : 0
                            radius: 3
                            color: "transparent"
                            border.width: 1
                            border.color: Theme.mix(Theme.borderIdle, Theme.textActive, card.picked ? 0.5 : 0.25)
                        }
                        Repeater {
                            model: Prev.rects[card.modelData][4]
                            delegate: Rectangle {
                                id: pane
                                required property var modelData
                                required property int index
                                readonly property bool lead: index === 0    // the first (and largest) window
                                x: modelData[0] * stage.width; y: modelData[1] * stage.height
                                width: modelData[2] * stage.width; height: modelData[3] * stage.height
                                radius: 3
                                color: lead ? Theme.mix(Theme.layer1, Theme.accent, card.picked ? 0.85 : 0.5)
                                            : Theme.mix(Theme.layer1, Theme.textActive, card.picked ? 0.3 : 0.18)
                                Behavior on color { ColorAnimation { duration: Theme.durationDefault; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveStandard } }
                                // the layout draws itself in once, window by window
                                opacity: 0
                                scale: 0.8
                                Component.onCompleted: entrance.start()
                                SequentialAnimation {
                                    id: entrance
                                    PauseAnimation { duration: Theme.reduceMotion ? 0 : pane.index * 55 }
                                    ParallelAnimation {
                                        NumberAnimation { target: pane; property: "opacity"; to: 1; duration: Theme.durationDefault; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveStandard }
                                        NumberAnimation { target: pane; property: "scale"; to: 1; duration: Theme.durationDefault; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveEmphasizedDecel }
                                    }
                                }
                            }
                        }
                    }
                    Column {
                        x: Theme.padMd; y: stage.y + stage.height + Theme.padSm
                        width: parent.width - 2 * Theme.padMd
                        spacing: 2
                        Text { text: Prev.names[card.modelData]; color: Theme.textActive; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeNormal; font.weight: card.picked ? Font.DemiBold : Font.Medium }
                        Text { width: parent.width; text: Prev.blurbs[card.modelData]; color: Theme.text; opacity: Theme.opacityMuted; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSmaller; wrapMode: Text.WordWrap; maximumLineCount: 3; elide: Text.ElideRight }
                    }
                    MouseArea {
                        anchors.fill: parent
                        onClicked: { root[picker.settingKey] = card.modelData; root.dirty = true; }
                    }
                }
            }
        }
    }

    component SwitchList: Column {
        property var fields: []
        width: parent.width
        spacing: Theme.padLg
        Repeater {
            model: parent.fields
            delegate: Item {
                width: parent.width
                implicitHeight: Math.max(switchText.implicitHeight, fieldSwitch.implicitHeight)
                Column {
                    id: switchText
                    anchors.left: parent.left
                    anchors.right: fieldSwitch.left
                    anchors.rightMargin: Theme.padLg
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: Theme.padXs
                    Text {
                        width: parent.width
                        text: modelData.label
                        color: Theme.textActive
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSizeNormal
                        font.weight: Font.Medium
                        wrapMode: Text.WordWrap
                    }
                    Text {
                        width: parent.width
                        text: modelData.sub
                        color: Theme.text
                        opacity: Theme.opacityMuted
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSizeSmall
                        wrapMode: Text.WordWrap
                        lineHeight: 1.15
                    }
                }
                Switch {
                    id: fieldSwitch
                    objectName: modelData.objectName
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    checked: root[modelData.key] === true
                    onToggled: (next) => { root[modelData.key] = next; root.dirty = true; }
                }
            }
        }
    }

    // A slider whose own effect renders live underneath it -- "the user
    // should understand what the setting does by looking at it" -- instead
    // of a bare label+slider row that says nothing about what the number
    // means until you go find the real thing it controls.
    component TypeSizeRow: Column {
        id: typeSizeRoot
        property string label: ""
        property string sampleText: "Sample"
        property string key: ""
        property real min: 8
        property real max: 24
        width: parent ? parent.width : implicitWidth
        spacing: Theme.padXs

        FillSlider {
            width: parent.width
            label: typeSizeRoot.label
            unit: "px"
            from: typeSizeRoot.min; to: typeSizeRoot.max; decimals: 0
            value: root[typeSizeRoot.key]
            onChanged: (v) => { root[typeSizeRoot.key] = Math.round(v); root.dirty = true; }
        }
        Text {
            text: typeSizeRoot.sampleText
            color: Theme.textActive
            font.family: Theme.fontFamily
            font.pixelSize: Math.max(8, root[typeSizeRoot.key])
            elide: Text.ElideRight
            width: parent.width
        }
    }

    // ---- visuals: a drawer that unrolls down from the bar, matching
    // QuickSettings.qml exactly -- zero gap, square top corners (flush
    // against the bar), large-radius bottom corners only, no decorative
    // seam. Reveal is height + opacity + a small upward settle together. ----
    // The window's ONE Escape: the colour picker first, then the panel.
    Shortcut { objectName: "themeEscape"; sequence: "Escape"; onActivated: root.pickerOpen ? root.closePicker() : PanelManager.close("theme") }

    Item {
        id: drawer
        // Positioned/sized to the panel's own box (panelX/Y/Width/Height),
        // not anchors.fill: parent -- parent (root) is now the full screen,
        // see the mask/dismissArea comment above.
        x: root.panelX
        y: root.panelY
        width: root.panelWidth
        height: root.panelHeight
        clip: true

        property real revealHeight: 0
        readonly property real revealProgress: root.panelHeight > 0 ? Math.min(1, drawer.revealHeight / root.panelHeight) : 0
        Behavior on revealHeight { NumberAnimation { duration: Theme.durationEnter; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveEmphasizedDecel } }
        Component.onCompleted: revealHeight = root.panelHeight
        Connections {
            target: root
            function onClosingChanged() { drawer.revealHeight = root.closing ? 0 : root.panelHeight; }
            // panelHeight is content-driven now (see its own property
            // comment) -- switching to a sparser or denser category while
            // already open has to resize the drawer to match, using the
            // same Behavior-driven animation as open/close, not just take
            // effect on the next open.
            function onPanelHeightChanged() { if (!root.closing) drawer.revealHeight = root.panelHeight; }
        }

        RectangularShadow {
            anchors.fill: panelSurface
            radius: 0
            bottomLeftRadius: Theme.roundingXl
            bottomRightRadius: Theme.roundingXl
            color: Theme.shadowColor
            blur: Theme.elevationBlur(3)
            spread: Theme.elevationSpread(3)
            offset.y: Theme.elevationOffsetY(3)
            opacity: drawer.revealProgress
        }

        Rectangle {
            id: panelSurface
            anchors.top: parent.top
            anchors.topMargin: (1 - drawer.revealProgress) * -10
            anchors.left: parent.left
            anchors.right: parent.right
            height: Math.max(0, drawer.revealHeight)
            opacity: drawer.revealProgress
            radius: 0
            bottomLeftRadius: Theme.roundingXl
            bottomRightRadius: Theme.roundingXl
            color: Theme.bg
            clip: true

            // Bare areas of the panel absorb clicks. Without this, a click
            // on any non-control spot inside the panel fell through to
            // dismissArea underneath and closed the whole Theme editor --
            // the same fall-through the island panels were fixed for.
            MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons }

        Column {
            anchors.fill: parent
            spacing: 0

            Item {
                id: header
                width: parent.width
                height: 56

                Text {
                    id: headerTitle
                    text: "Theme"
                    color: Theme.textActive
                    font.family: Theme.fontFamily
                    font.weight: Font.DemiBold
                    font.pixelSize: Theme.fontSizeLarge
                    anchors.verticalCenter: parent.verticalCenter
                    x: Theme.padLg
                }
                // One quiet line between the title and the buttons: an Apply
                // failure (danger tint), or a dropped draft (muted). Elided;
                // feedback, never a dialog.
                Text {
                    id: headerMessage
                    objectName: "themeHeaderMessage"
                    readonly property bool isError: root.applyError.length > 0
                    readonly property bool isSuccess: !isError && root.justApplied
                    visible: opacity > 0.01
                    text: isError ? root.applyError : (isSuccess ? "\u2713  Applied" : root.draftNotice)
                    color: isError ? Theme.dangerTint : (isSuccess ? Theme.textActive : Theme.text)
                    opacity: (isError || isSuccess) ? (isSuccess ? Theme.opacitySecondary : 1)
                           : (root.draftNotice.length > 0 ? Theme.opacityMuted : 0)
                    Behavior on opacity { NumberAnimation { duration: Theme.durationFadeIn; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveStandard } }
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSizeSmaller
                    elide: Text.ElideRight
                    anchors.verticalCenter: parent.verticalCenter
                    x: headerTitle.x + headerTitle.width + Theme.padLg
                    width: Math.max(0, headerButtons.x - x - Theme.padLg)
                }
                Row {
                    id: headerButtons
                    anchors.verticalCenter: parent.verticalCenter
                    x: header.width - width - Theme.padLg
                    spacing: Theme.padSm
                    GlassButton { text: "Revert"; variant: "secondary"; onClicked: root.revert() }
                    GlassButton {
                        objectName: "themeApply"
                        text: "Apply"
                        variant: "primary"
                        badge: root.dirty
                        busy: root.applying
                        onClicked: root.apply()
                    }
                    CloseButton {
                        anchors.verticalCenter: parent.verticalCenter
                        onClicked: PanelManager.close("theme")
                    }
                }
            }

            // Same header->content seam as Dashboard/Media/Performance/
            // Taskbar now use -- Theme's header was the one persistent
            // toolbar in the shell with no boundary marking where it ends,
            // which read as a generic app title bar rather than this
            // shell's own structural language.
            Rectangle {
                x: Theme.padXl
                width: parent.width - Theme.padXl * 2
                height: 1
                color: Theme.seam
            }

            Row {
                id: sidebarLayout
                width: parent.width
                height: parent.height - header.height

                // ---- sidebar: search + category list ----
                Column {
                    id: sidebar
                    width: 208
                    height: parent.height
                    spacing: Theme.padSm

                    InputField {
                        x: Theme.padMd
                        width: parent.width - Theme.padMd * 2
                        compact: false
                        glyph: "\uf002"
                        placeholder: "Search settings"
                        input: settingsSearch
                        TextInput {
                            id: settingsSearch
                            objectName: "themeSearch"
                            anchors.fill: parent
                            color: Theme.textActive
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSizeNormal
                            verticalAlignment: TextInput.AlignVCenter
                            clip: true
                            text: root.searchText
                            onTextChanged: root.searchText = text
                        }
                    }

                    Item {
                        width: parent.width
                        height: parent.height - 34 - Theme.padSm

                        Flickable {
                            id: catFlickable
                            anchors.fill: parent
                            contentHeight: catColumn.implicitHeight
                            clip: true

                        Column {
                            id: catColumn
                            width: parent.width
                            spacing: 2

                            Repeater {
                                model: root.filteredCategories
                                delegate: Rectangle {
                                    id: catRow
                                    required property var modelData
                                    width: parent.width - Theme.padMd
                                    x: Theme.padMd / 2
                                    height: 52
                                    radius: Theme.roundingSm
                                    readonly property bool selected: root.currentCategory === modelData.id
                                    color: selected ? Theme.layer2Active : (catArea.containsMouse ? Theme.layer1Hover : "transparent")
                                    Behavior on color { ColorAnimation { duration: Theme.durationFast; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveStandard } }

                                    Rectangle {
                                        visible: catRow.selected
                                        anchors.left: parent.left
                                        anchors.verticalCenter: parent.verticalCenter
                                        width: 3
                                        height: 22
                                        radius: Theme.roundingFull
                                        color: Theme.accent
                                    }

                                    Text {
                                        id: catGlyph
                                        anchors.left: parent.left
                                        anchors.leftMargin: Theme.padMd
                                        anchors.verticalCenter: parent.verticalCenter
                                        // A fixed, centred icon column: the
                                        // glyphs have different advances, so
                                        // labels placed after their natural
                                        // width started at 4 different x's.
                                        width: 20
                                        horizontalAlignment: Text.AlignHCenter
                                        text: catRow.modelData.glyph
                                        font.family: Theme.iconFamily
                                        font.pixelSize: Theme.fontSizeLarger
                                        color: catRow.selected ? Theme.accent : Theme.text
                                    }
                                    Column {
                                        anchors.left: catGlyph.right
                                        anchors.leftMargin: Theme.padSm
                                        anchors.right: parent.right
                                        anchors.rightMargin: Theme.padSm
                                        anchors.verticalCenter: parent.verticalCenter
                                        spacing: 1
                                        Text {
                                            width: parent.width
                                            text: catRow.modelData.label
                                            color: catRow.selected ? Theme.textActive : Theme.text
                                            font.family: Theme.fontFamily
                                            font.pixelSize: Theme.fontSizeSmaller
                                            font.weight: Font.Medium
                                            elide: Text.ElideRight
                                        }
                                        Text {
                                            width: parent.width
                                            text: catRow.modelData.sub
                                            color: Theme.text
                                            opacity: Theme.opacityMuted
                                            font.family: Theme.fontFamily
                                            font.pixelSize: Theme.fontSizeSmall
                                            elide: Text.ElideRight
                                        }
                                    }
                                    MouseArea {
                                        id: catArea
                                        anchors.fill: parent
                                        hoverEnabled: true
                                        cursorShape: Qt.PointingHandCursor
                                        onClicked: root.currentCategory = catRow.modelData.id
                                    }
                                }
                            }
                        }
                        }

                        ScrollHint {
                            flickable: catFlickable
                            anchors.top: parent.top
                            anchors.bottom: parent.bottom
                            anchors.right: parent.right
                            anchors.margins: 2
                        }
                    }
                }

                // Sidebar (navigation) -> content boundary -- same
                // structural role and Theme.seam token as the other three
                // panels' header/nav seams, not a decorative hairline.
                Rectangle {
                    width: 1
                    height: parent.height
                    color: Theme.seam
                }

                // ---- content pane: one category's fields at a time ----
                Item {
                    id: contentViewport
                    width: sidebarLayout.width - sidebar.width - 1
                    height: parent.height

                    Flickable {
                        id: contentFlick
                        anchors.fill: parent
                        contentHeight: paneLoader.item ? paneLoader.item.implicitHeight + Theme.padLg * 2 : 0
                        clip: true
                        Behavior on contentY { NumberAnimation { duration: Theme.durationMove; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveStandard } }

                        Loader {
                            id: paneLoader
                            x: Theme.padLg
                            y: Theme.padLg
                            width: contentFlick.width - Theme.padLg * 2
                            // A category switch: the new page fades up into
                            // place (the same grammar as Quick Settings'
                            // tabs) and starts from its top.
                            transform: Translate { id: paneRise }
                            ParallelAnimation {
                                id: paneEnter
                                NumberAnimation {
                                    target: paneLoader; property: "opacity"; from: 0; to: 1
                                    duration: Theme.durationFadeIn
                                    easing.type: Theme.easingType; easing.bezierCurve: Theme.curveStandard
                                }
                                NumberAnimation {
                                    target: paneRise; property: "y"; from: Theme.contentShift; to: 0
                                    duration: Theme.durationEnter
                                    easing.type: Theme.easingType; easing.bezierCurve: Theme.curveEnter
                                }
                            }
                            Connections {
                                target: root
                                function onCurrentCategoryChanged() { contentFlick.contentY = 0; paneEnter.restart(); }
                            }
                            sourceComponent: {
                                switch (root.currentCategory) {
                                case "colors": return colorsPane;
                                case "blur": return blurPane;
                                case "layout": return layoutPane;
                                case "lock": return lockPane;
                                case "fonts": return fontsPane;
                                case "experience": return experiencePane;
                                case "wallpaper": return wallpaperPane;
                                default: return colorsPane;
                                }
                            }
                        }
                    }

                    ScrollHint {
                        flickable: contentFlick
                        anchors.top: parent.top
                        anchors.bottom: parent.bottom
                        anchors.right: parent.right
                        anchors.margins: 2
                    }
                }
            }
        }
        }
    }

    // A sibling of `drawer`, not a child: the drawer clips to its own
    // bounds, and the picker hangs BESIDE the panel. It stays inside this
    // same full-screen window, whose mask already takes input everywhere
    // while the Theme editor is open, so it needs no input region of its
    // own -- and when the editor starts closing, the picker closes with
    // it (onClosingChanged) as the mask empties.
    ColorPopover {
        id: colorPopover
        open: root.pickerOpen
        title: root.pickerTitle
        initialHex: root.editingColorKey ? root[root.editingColorKey] : "ffffff"
        session: root.pickerSession
        targetRect: Qt.rect(drawer.x + root._pickerSwatch.x,
                            drawer.y + root._pickerSwatch.y - root._pickerScroll,
                            root._pickerSwatch.width, root._pickerSwatch.height)
        // Horizontally the screen minus the shell's edge margin; vertically
        // the panel's own span (or the picker's height, if the panel is
        // shorter), so it stays level with the Theme editor -- never up over
        // the bar, never down over the dock.
        bounds: Qt.rect(ShellSurface.gap, drawer.y, root.width - ShellSurface.gap * 2,
                        Math.min(root.height - ShellSurface.gap - drawer.y,
                                 Math.max(drawer.revealHeight, colorPopover.wantH)))
        occluder: Qt.rect(drawer.x, drawer.y, drawer.width, drawer.revealHeight)
        onAccepted: (hex) => {
            if (root.editingColorKey) {
                root[root.editingColorKey] = hex;
                root.dirty = true;
            }
            root.closePicker();
        }
        onDismissed: root.closePicker()
    }

    // ==================== shared: a bordered content REGION, not a
    // Card -- this is what keeps Theme from becoming Card-in-Card-in-Card.
    // A region has no title chip, no card shadow, no card fill: it's a
    // quiet frame around a composition (a preview, a specimen, a demo)
    // that itself IS the content, the way Dashboard's left/center/right
    // regions are frames around composition rather than settings lists. ====
    component PreviewRegion: Rectangle {
        default property alias data: inner.data
        // The same inset as the settings Cards stacked beside/below it
        // (padding: Theme.pad2xl), so a preview's label and a settings
        // group's title start on one vertical line instead of 8px apart.
        property real regionPadding: Theme.pad2xl
        radius: ShellSurface.cardRadius
        color: Theme.cardTone
        // Same borderless group as Card: tone carries the boundary.
        implicitHeight: inner.implicitHeight + regionPadding * 2
        Item {
            id: inner
            x: parent.regionPadding
            y: parent.regionPadding
            width: parent.width - parent.regionPadding * 2
            implicitHeight: children.length > 0 ? children[0].implicitHeight : 0
        }
    }

    // A big preview alongside its controls when there's room, stacked full-
    // width when there isn't -- genuinely responsive (re-evaluates on any
    // width change, e.g. this panel's own content-driven width growing on a
    // wider screen -- see panelWidth above) rather than a layout tuned to
    // look right at one specific resolution. Reads `.height` off each
    // slot's actual child, not `.implicitHeight`: a plain Rectangle (the
    // preview) never populates implicitHeight on its own the way a Column
    // does, and `.height` is correct for both.
    component ResponsiveSplit: Item {
        id: splitRoot
        default property alias media: mediaSlot.data
        property alias aside: asideSlot.data
        property real asideWidth: 260
        property real breakpoint: 560
        width: parent ? parent.width : implicitWidth
        readonly property bool wide: width >= breakpoint
        readonly property real mediaH: mediaSlot.children.length > 0 ? mediaSlot.children[0].height : 0
        readonly property real asideH: asideSlot.children.length > 0 ? asideSlot.children[0].height : 0
        height: wide ? Math.max(mediaH, asideH) : (mediaH + Theme.padLg + asideH)

        Item {
            id: mediaSlot
            width: splitRoot.wide ? splitRoot.width - splitRoot.asideWidth - Theme.padLg : splitRoot.width
            height: splitRoot.mediaH
        }
        Item {
            id: asideSlot
            width: splitRoot.wide ? splitRoot.asideWidth : splitRoot.width
            x: splitRoot.wide ? mediaSlot.width + Theme.padLg : 0
            y: splitRoot.wide ? 0 : mediaSlot.height + Theme.padLg
            height: splitRoot.asideH
        }
    }

    Component {
        id: colorsPane
        Column {
            width: parent ? parent.width : implicitWidth
            spacing: Theme.padLg

            Text { text: "Colors"; color: Theme.textActive; font.family: Theme.fontFamily; font.weight: Font.DemiBold; font.pixelSize: Theme.fontSizeLarge }

            // -- presets communicate visually (an actual mini palette), not
            // as a row of plain text-labeled buttons the user has to read
            // one at a time. --
            Flow {
                width: parent.width
                spacing: Theme.padSm
                Repeater {
                    model: Object.keys(root.presets)
                    delegate: Rectangle {
                        id: presetSwatch
                        readonly property var colors: root.presets[modelData]
                        // The preset the draft currently matches is marked
                        // (accent edge + check), the rest are quiet tonal
                        // chips -- before, nothing said which one you had.
                        readonly property bool current: ["glass_bg", "glass_bg_active", "glass_text", "glass_text_active", "accent"]
                            .every((k) => String(root[k]).toLowerCase() === String(presetSwatch.colors[k]).toLowerCase())
                        objectName: "preset_" + modelData
                        width: 108
                        height: 64
                        radius: Theme.roundingMd
                        color: Theme.stateFill(Theme.cardTone, presetArea.containsMouse, presetArea.pressed)
                        border.width: presetSwatch.current ? 2 : 0
                        border.color: Theme.accent
                        scale: Theme.pressScale(presetArea.pressed)
                        Behavior on color { ColorAnimation { duration: Theme.durationFast; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveStandard } }
                        Behavior on scale { NumberAnimation { duration: Theme.durationMove; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveExpressiveFast } }
                        Text {
                            visible: presetSwatch.current
                            anchors.top: parent.top
                            anchors.right: parent.right
                            anchors.margins: 6
                            text: "\u2713"
                            color: Theme.accent
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSizeSmall
                            font.weight: Font.DemiBold
                        }

                        Column {
                            anchors.centerIn: parent
                            spacing: Theme.padXs
                            Row {
                                anchors.horizontalCenter: parent.horizontalCenter
                                spacing: 4
                                Rectangle { width: 16; height: 16; radius: 8; color: "#" + presetSwatch.colors.glass_bg; border.width: 1; border.color: Theme.borderIdle }
                                Rectangle { width: 16; height: 16; radius: 8; color: "#" + presetSwatch.colors.glass_bg_active; border.width: 1; border.color: Theme.borderIdle }
                                Rectangle { width: 16; height: 16; radius: 8; color: "#" + presetSwatch.colors.accent }
                            }
                            Text {
                                anchors.horizontalCenter: parent.horizontalCenter
                                text: modelData
                                color: presetSwatch.current ? Theme.textActive : Theme.text
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSizeSmaller
                                font.weight: presetSwatch.current ? Font.Medium : Font.Normal
                            }
                        }
                        MouseArea {
                            id: presetArea
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: root.applyPreset(presetSwatch.colors)
                        }
                    }
                }
            }

            // ---- the centerpiece: a real miniature SHELL, not a swatch
            // grid -- a mock top bar with a status pill, a mock card inside
            // a mock panel, and an accent button, all reading their fill
            // straight from the live draft fields. This is "theme
            // designer," not "list of hex values": the palette is judged
            // by how it looks ON shell surfaces, which is the only thing
            // that actually matters. ----
            PreviewRegion {
                width: parent.width
                Column {
                    width: parent.width
                    spacing: Theme.padSm
                    Text { text: "Live preview"; color: Theme.text; opacity: Theme.opacityMuted; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSmall }
                    Rectangle {
                        width: parent.width
                        height: 190
                        radius: ShellSurface.radius
                        color: root._rgba(root.glass_bg, root.opacity_active)
                        border.width: Theme.borderWidth
                        border.color: root._rgba(root.glass_border, Math.min(root.border_opacity_active, 0.22))
                        clip: true

                        // mock top bar
                        Item {
                            x: Theme.padLg; y: Theme.padMd
                            width: parent.width - Theme.padLg * 2
                            height: ShellSurface.unit * 0.6
                            Rectangle {
                                width: 96; height: parent.height
                                radius: height / 2
                                color: root._rgba(root.glass_bg_active, root.opacity_idle)
                                Text { anchors.centerIn: parent; text: "12:41"; color: "#" + root.glass_text_active; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSmall }
                            }
                            Rectangle {
                                anchors.right: parent.right
                                width: 64; height: parent.height
                                radius: height / 2
                                color: "#" + root.accent
                                Text { anchors.centerIn: parent; text: "Wi-Fi"; color: "#ffffff"; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSmall }
                            }
                        }

                        // mock card + accent button, demonstrating layer1/
                        // layer2 lift and the accent against the real panel
                        Rectangle {
                            x: Theme.padLg; y: Theme.padLg * 2 + ShellSurface.unit * 0.6
                            width: parent.width - Theme.padLg * 2
                            height: 84
                            radius: ShellSurface.cardRadius
                            color: root._rgba(root.glass_bg_active, root.opacity_idle)
                            border.width: Theme.borderWidth
                            border.color: root._rgba(root.glass_border, 0.15)
                            Column {
                                x: Theme.padMd; y: Theme.padMd
                                spacing: Theme.padSm
                                Text { text: "Connectivity"; color: "#" + root.glass_text; opacity: 0.7; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSmall }
                                Row {
                                    spacing: Theme.padSm
                                    Rectangle { width: 72; height: 32; radius: Theme.roundingSm; color: "#" + root.accent; opacity: 0.85
                                        Text { anchors.centerIn: parent; text: "Active"; color: "#ffffff"; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSmall }
                                    }
                                    Rectangle { width: 72; height: 32; radius: Theme.roundingSm; color: root._rgba(root.glass_bg, 0.4); border.width: 1; border.color: root._rgba(root.glass_border, 0.15)
                                        Text { anchors.centerIn: parent; text: "Idle"; color: "#" + root.glass_text; opacity: 0.7; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSmall }
                                    }
                                }
                            }
                        }
                    }
                }
            }

            // ---- color roles, below the preview they explain -- kept
            // full-width (not side-by-side) so each role's subtitle has
            // room to render without eliding: SettingRow's label/subtitle
            // column sizes off the Card's own width, and halving that width
            // for a 2-up layout truncated captions like "Waybar/wofi/kitty
            // …" mid-word, which is worse than the single centerpiece
            // preview above is worth trading for. ----
            Card {
                width: parent.width
                padding: Theme.pad2xl
                title: "Glass Palette"
                ColorList { width: parent.width; fields: root.colorFields }
            }
            Card {
                width: parent.width
                padding: Theme.pad2xl
                title: "Window Border Gradient"
                ColorList { width: parent.width; fields: root.borderColorFields }
            }
        }
    }

    Component {
        id: blurPane
        Column {
            width: parent ? parent.width : implicitWidth
            spacing: Theme.padLg

            Text { text: "Transparency & Blur"; color: Theme.textActive; font.family: Theme.fontFamily; font.weight: Font.DemiBold; font.pixelSize: Theme.fontSizeLarge }

            // ---- the material preview is the primary element now, not a
            // Card header above a slider list. Two panels side by side --
            // idle and active material -- each shown against a NEUTRAL dark
            // backdrop (not a colorful wallpaper stand-in): the whole point
            // of Theme.qml's surfaceTone lift is that the shell's material
            // stays a deliberate dark neutral regardless of what's behind
            // it, and the old green gradient here was demonstrating the
            // opposite of that -- a preview that only ever showed the
            // panel looking green undercut the actual design principle
            // instead of proving it. ----
            PreviewRegion {
                width: parent.width
                Row {
                    width: parent.width
                    spacing: Theme.padLg
                    Column {
                        width: (parent.width - parent.spacing) / 2
                        spacing: Theme.padXs
                        Text { text: "Idle material"; color: Theme.text; opacity: Theme.opacityMuted; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSmall }
                        Rectangle {
                            width: parent.width; height: 120
                            radius: Theme.roundingLg
                            color: "#1c1c1e"
                            Rectangle {
                                anchors.centerIn: parent
                                width: parent.width * 0.7; height: parent.height * 0.7
                                radius: Theme.roundingMd
                                color: root._rgba(root.glass_bg, root.opacity_idle)
                                border.width: Theme.borderWidth
                                border.color: Qt.rgba(1, 1, 1, root.border_opacity_idle)
                            }
                        }
                    }
                    Column {
                        width: (parent.width - parent.spacing) / 2
                        spacing: Theme.padXs
                        Text { text: "Active material"; color: Theme.text; opacity: Theme.opacityMuted; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSmall }
                        Rectangle {
                            width: parent.width; height: 120
                            radius: Theme.roundingLg
                            color: "#1c1c1e"
                            Rectangle {
                                anchors.centerIn: parent
                                width: parent.width * 0.7; height: parent.height * 0.7
                                radius: Theme.roundingMd
                                color: root._rgba(root.glass_bg_active, root.opacity_active)
                                border.width: Theme.borderWidth
                                border.color: Qt.rgba(1, 1, 1, root.border_opacity_active)
                            }
                        }
                    }
                }
            }

            Card {
                width: parent.width
                padding: Theme.pad2xl
                title: "Controls"
                SliderList { width: parent.width; fields: root.blurFields }
            }
        }
    }

    Component {
        id: layoutPane
        Column {
            width: parent ? parent.width : implicitWidth
            spacing: Theme.padLg

            Text { text: "Layout"; color: Theme.textActive; font.family: Theme.fontFamily; font.weight: Font.DemiBold; font.pixelSize: Theme.fontSizeLarge }

            // Corner radius and window gaps are pure geometry -- a number
            // by itself doesn't communicate "how rounded" or "how much
            // space" the way an actual shape does.
            PreviewRegion {
                width: parent.width
                Row {
                    width: parent.width
                    spacing: Theme.padLg
                    Column {
                        width: (parent.width - parent.spacing) / 2
                        spacing: Theme.padXs
                        Text { text: "Corner radius"; color: Theme.text; opacity: Theme.opacityMuted; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSmall }
                        Rectangle {
                            width: 90; height: 90
                            radius: root.radius
                            color: Theme.layer2Active
                            border.width: Theme.borderWidth
                            border.color: Theme.border
                        }
                    }
                    Column {
                        width: (parent.width - parent.spacing) / 2
                        spacing: Theme.padXs
                        Text { text: "Window gaps"; color: Theme.text; opacity: Theme.opacityMuted; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSmall }
                        Row {
                            spacing: Math.max(2, root.hypr_gaps_in)
                            Rectangle { width: 42; height: 90; radius: root.hypr_rounding * 0.5; color: Theme.layer2Active; border.width: Theme.borderWidth; border.color: Theme.border }
                            Rectangle { width: 42; height: 90; radius: root.hypr_rounding * 0.5; color: Theme.layer2Active; border.width: Theme.borderWidth; border.color: Theme.border }
                        }
                    }
                }
            }

            // Grouped by what each setting actually governs, instead of one
            // long undifferentiated list -- kept full-width per group
            // (not side-by-side) so FillSlider's baked-in label never
            // elides: it sizes its label text off the slab's own width,
            // and a half-width slab truncated "Panel corner radius" down
            // to "Panel corn…", the same class of regression the Colors
            // pane's role cards had.
            Card {
                width: parent.width
                padding: Theme.pad2xl
                title: "Panel & Window Geometry"
                SliderList { width: parent.width; fields: [root.layoutFields[0], root.layoutFields[1], root.layoutFields[4]] }
            }
            Card {
                width: parent.width
                padding: Theme.pad2xl
                title: "Spacing"
                SliderList { width: parent.width; fields: [root.layoutFields[2], root.layoutFields[3]] }
            }
            Card {
                width: parent.width
                padding: Theme.pad2xl
                title: "Window Opacity & Border Gradient"
                SliderList { width: parent.width; fields: [root.layoutFields[5], root.layoutFields[6], root.layoutFields[7]] }
            }
        }
    }

    Component {
        id: lockPane
        Column {
            width: parent ? parent.width : implicitWidth
            spacing: Theme.padLg

            Text { text: "Lock Screen"; color: Theme.textActive; font.family: Theme.fontFamily; font.weight: Font.DemiBold; font.pixelSize: Theme.fontSizeLarge }

            // A real widescreen lock screen -- 16:9, the actual shape of a
            // monitor -- with clock/date/password positioned the way a real
            // desktop lock screen lays them out (upper-third clock, password
            // pill in the lower third), not a tiny phone-shaped card. Every
            // one of the 4 sliders below visibly changes something here.
            // Same ResponsiveSplit as Wallpaper: controls sit beside the
            // preview when there's room, below it when there isn't.
            ResponsiveSplit {
                width: parent.width
                asideWidth: 280
                breakpoint: 620

                Rectangle {
                    id: lockPreviewFrame
                    width: parent.width
                    height: Math.min(420, width * 9 / 16)
                    radius: Theme.roundingLg
                    clip: true
                    color: root.wallpaper ? "#1c1c1e" : "#26221c"
                    Image {
                        anchors.fill: parent
                        source: root.wallpaper ? "file://" + root.wallpaper : ""
                        fillMode: Image.PreserveAspectCrop
                        asynchronous: true
                    }
                    // vibrancy/blur stand-in: a translucent veil whose own
                    // opacity tracks lock_bg_opacity, same honesty as the
                    // Blur pane -- real compositor blur only exists on an
                    // actual Hyprland surface, this is the alpha it pairs
                    // with, not a shader simulation.
                    Rectangle { anchors.fill: parent; color: Qt.rgba(0.06, 0.06, 0.07, root.lock_bg_opacity) }
                    Column {
                        anchors.horizontalCenter: parent.horizontalCenter
                        y: lockPreviewFrame.height * 0.16
                        spacing: Theme.padXs
                        Text {
                            anchors.horizontalCenter: parent.horizontalCenter
                            text: "14:32"
                            color: "#ffffff"
                            font.family: Theme.fontFamily
                            font.pixelSize: Math.min(Theme.fontSizeHero, lockPreviewFrame.width * 0.09)
                            font.weight: Font.Light
                        }
                        Text {
                            anchors.horizontalCenter: parent.horizontalCenter
                            text: "Thursday, September 17"
                            color: "#ffffff"
                            opacity: 0.75
                            font.family: Theme.fontFamily
                            font.pixelSize: Math.min(Theme.fontSizeLarger, lockPreviewFrame.width * 0.022)
                        }
                    }
                    Rectangle {
                        anchors.horizontalCenter: parent.horizontalCenter
                        y: lockPreviewFrame.height * 0.68
                        width: Math.min(280, lockPreviewFrame.width * 0.26)
                        height: ShellSurface.rowHeight
                        radius: Theme.roundingSm
                        color: Qt.rgba(1, 1, 1, root.lock_bg_opacity * 0.08)
                        border.width: Theme.borderWidth
                        border.color: Qt.rgba(1, 1, 1, 0.15)
                        Text { anchors.centerIn: parent; text: "Enter password"; color: "#ffffff"; opacity: 0.5; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSmall }
                    }
                }

                aside: Card {
                    width: parent.width
                    padding: Theme.pad2xl
                    title: "Controls"
                    SliderList { width: parent.width; fields: root.lockFields }
                }
            }
        }
    }

    Component {
        id: fontsPane
        Column {
            width: parent ? parent.width : implicitWidth
            spacing: Theme.padLg

            Text { text: "Fonts"; color: Theme.textActive; font.family: Theme.fontFamily; font.weight: Font.DemiBold; font.pixelSize: Theme.fontSizeLarge }

            // ---- two typefaces, two jobs, each judged by a live specimen:
            // the interface face (panels, menus, this editor) and the
            // terminal/bar face (Waybar, wofi, mako, kitty, and the shell's
            // fixed-width values). Typing updates the specimen at once and
            // commits to the draft when you leave the field. ----
            Card {
                width: parent.width
                padding: Theme.pad2xl
                title: "Interface font"
                spacing: Theme.padMd
                Text {
                    width: parent.width
                    text: "Panels, menus and this editor. Leave empty for the default, " + Theme.defaultUiFamily + "."
                    color: Theme.text; opacity: Theme.opacitySecondary
                    font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSmaller
                    wrapMode: Text.WordWrap
                }
                Column {
                    width: parent.width
                    spacing: Theme.padXs
                    readonly property string family: uiFamilyInput.text.trim() || (root.font_family === Theme.shippedMonoFamily ? Theme.defaultUiFamily : root.font_family)
                    Text { text: "Quick Settings"; color: Theme.textActive; font.family: parent.family; font.pixelSize: 28; font.weight: Font.DemiBold; elide: Text.ElideRight; width: parent.width }
                    Text { text: "Wi-Fi · Bluetooth · Do Not Disturb · Automatic window placement"; color: Theme.text; opacity: Theme.opacityFaint; font.family: parent.family; font.pixelSize: Theme.fontSizeNormal; wrapMode: Text.WordWrap; width: parent.width }
                }
                InputField {
                    placeholder: Theme.defaultUiFamily + " (default)"
                    input: uiFamilyInput
                    TextInput {
                        id: uiFamilyInput
                        objectName: "uiFontInput"
                        anchors.fill: parent
                        clip: true
                        text: root.ui_font_family
                        color: Theme.textActive
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSizeNormal
                        verticalAlignment: TextInput.AlignVCenter
                        onEditingFinished: if (text.trim() !== root.ui_font_family) { root.ui_font_family = text.trim(); root.dirty = true; }
                    }
                }
            }

            Card {
                width: parent.width
                padding: Theme.pad2xl
                title: "Terminal and bar font"
                spacing: Theme.padMd
                Text {
                    width: parent.width
                    text: "Waybar, the launcher, notifications and the terminal, plus commands and codes in the shell. Needs a Nerd Font for icons."
                    color: Theme.text; opacity: Theme.opacitySecondary
                    font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSmaller
                    wrapMode: Text.WordWrap
                }
                Column {
                    width: parent.width
                    spacing: Theme.padXs
                    Text { text: "~/dxrice $ git log --oneline"; color: Theme.textActive; font.family: previewFamilyInput.text || Theme.fontMono; font.pixelSize: Theme.fontSizeLarger; elide: Text.ElideRight; width: parent.width }
                    Text { text: "14:32   92%   3.4 GB/s   #e67878"; color: Theme.text; opacity: Theme.opacityFaint; font.family: previewFamilyInput.text || Theme.fontMono; font.pixelSize: Theme.fontSizeNormal }
                }
                InputField {
                    placeholder: Theme.shippedMonoFamily
                    input: previewFamilyInput
                    TextInput {
                        id: previewFamilyInput
                        anchors.fill: parent
                        clip: true
                        text: root.font_family
                        color: Theme.textActive
                        font.family: Theme.fontMono
                        font.pixelSize: Theme.fontSizeNormal
                        verticalAlignment: TextInput.AlignVCenter
                        onEditingFinished: if (text !== root.font_family) { root.font_family = text; root.dirty = true; }
                    }
                }
            }

            // ---- sizes: each slider's own sample renders live at that
            // exact pixel size right underneath it. ----
            Card {
                width: parent.width
                padding: Theme.pad2xl
                title: "Sizes"
                SliderList { width: parent.width; fields: root.shellTextFields }
                TypeSizeRow { width: parent.width; label: "Waybar text (fallback bar)"; key: "font_size_waybar"; min: 8; max: 24; sampleText: "12:30 PM   Sep 10" }
                TypeSizeRow { width: parent.width; label: "Waybar icons (fallback bar)"; key: "font_size_waybar_icons"; min: 8; max: 40; sampleText: "★ ✎ ⚙" }
                TypeSizeRow { width: parent.width; label: "App launcher"; key: "font_size_wofi"; min: 8; max: 24; sampleText: "Search applications..." }
                TypeSizeRow { width: parent.width; label: "Notifications"; key: "font_size_mako"; min: 8; max: 24; sampleText: "Battery low -- 12% remaining" }
            }
        }
    }

    Component {
        id: experiencePane
        Column {
            width: parent ? parent.width : implicitWidth
            spacing: Theme.padLg

            Text { text: "Experience"; color: Theme.textActive; font.family: Theme.fontFamily; font.weight: Font.DemiBold; font.pixelSize: Theme.fontSizeLarge }

            // ---- three small, honest demonstrations instead of one big
            // Card stretched to fill the panel with nothing in it: this
            // category only has 3 real settings, so it stays exactly as
            // compact as those 3 demonstrations need, per the explicit
            // "don't add fake filler, allow content to stay compact" rule.
            // Each PreviewRegion holds ONLY the live visualization -- a
            // FillSlider crammed into a 1/3-width column truncated its own
            // baked-in label down to a single letter ("S…"), the same
            // truncation-from-halving bug as Colors/Layout above, just
            // worse at a third of the width. The actual controls move to
            // one full-width SliderList below instead, reusing the same
            // fields array already declared for these 3 settings. ----
            Row {
                width: parent.width
                spacing: Theme.padLg

                PreviewRegion {
                    width: (parent.width - parent.spacing * 2) / 3
                    height: 92   // one height for the three demos, so the row reads as a row
                    Column {
                        width: parent.width
                        spacing: Theme.padSm
                        Text { text: "Animation speed"; color: Theme.text; opacity: Theme.opacityMuted; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSmall }
                        Item {
                            width: parent.width; height: 40
                            Rectangle { anchors.verticalCenter: parent.verticalCenter; width: parent.width; height: 4; radius: 2; color: Theme.layer2 }
                            Rectangle {
                                id: speedDot
                                y: parent.height / 2 - 7
                                width: 14; height: 14; radius: 7
                                color: Theme.accent
                                SequentialAnimation on x {
                                    // A demonstration of the speed setting,
                                    // so it moves -- but not under reduce
                                    // motion, and not while nobody sees it.
                                    running: !Theme.reduceMotion && speedDot.visible
                                    loops: Animation.Infinite
                                    NumberAnimation { to: speedDot.parent.width - 14; duration: Math.max(60, root.anim_duration_ms * 2.8); easing.type: Easing.InOutQuad }
                                    NumberAnimation { to: 0; duration: Math.max(60, root.anim_duration_ms * 2.8); easing.type: Easing.InOutQuad }
                                }
                            }
                        }
                    }
                }

                PreviewRegion {
                    width: (parent.width - parent.spacing * 2) / 3
                    height: 92   // one height for the three demos, so the row reads as a row
                    Column {
                        width: parent.width
                        spacing: Theme.padSm
                        Text { text: "Spacing density"; color: Theme.text; opacity: Theme.opacityMuted; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSmall }
                        Row {
                            width: parent.width
                            spacing: Math.round(8 * root.ui_density)
                            Rectangle { width: 22; height: 22; radius: Theme.roundingXs; color: Theme.layer2 }
                            Rectangle { width: 22; height: 22; radius: Theme.roundingXs; color: Theme.layer2 }
                            Rectangle { width: 22; height: 22; radius: Theme.roundingXs; color: Theme.layer2 }
                        }
                    }
                }

                PreviewRegion {
                    width: (parent.width - parent.spacing * 2) / 3
                    height: 92   // one height for the three demos, so the row reads as a row
                    Column {
                        width: parent.width
                        spacing: Theme.padSm
                        Text { text: "Panel shadow"; color: Theme.text; opacity: Theme.opacityMuted; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSmall }
                        Item {
                            width: parent.width; height: 40
                            RectangularShadow {
                                anchors.fill: shadowSwatch
                                radius: shadowSwatch.radius
                                color: Theme.shadowColor
                                blur: Theme.elevationBlur(3) * root.shadow_intensity
                                spread: Theme.elevationSpread(3) * root.shadow_intensity
                                offset.y: Theme.elevationOffsetY(3) * root.shadow_intensity
                            }
                            Rectangle { id: shadowSwatch; anchors.centerIn: parent; width: parent.width * 0.6; height: 24; radius: Theme.roundingSm; color: Theme.layer1 }
                        }
                    }
                }
            }

            Card {
                width: parent.width
                padding: Theme.pad2xl
                title: "Motion and spacing"
                SliderList { width: parent.width; fields: root.experienceFields }
            }

            Card {
                width: parent.width
                padding: Theme.pad2xl
                title: "Windows and motion"
                SwitchList { width: parent.width; fields: root.behaviorFields }
            }

            Card {
                width: parent.width
                padding: Theme.pad2xl
                title: "Window layout"
                Column {
                    width: parent.width
                    spacing: Theme.pad2xl
                    LayoutPicker {
                        settingKey: "window_layout"; idPrefix: "layout:"
                        title: "Window arrangement"
                        sub: "One choice for both: where a window goes when you open it, and what SUPER+G does to the workspace."
                    }
                }
            }

            Card {
                width: parent.width
                padding: Theme.pad2xl
                title: "Desktop widgets"
                Column {
                    width: parent.width
                    spacing: Theme.pad2xl
                    SwitchList { width: parent.width; fields: root.widgetFields }
                    ChoiceRow {
                        settingKey: "clock_style"; idPrefix: "clockStyle:"; label: "Clock style"
                        options: [{ value: "type", label: "Type" }, { value: "blocks", label: "Blocks" }]
                    }
                    ChoiceRow {
                        settingKey: "visualizer_style"; idPrefix: "visualizerStyle:"; label: "Visualizer style"
                        options: [{ value: "bars", label: "Bars" }, { value: "blocks", label: "Blocks" }]
                    }
                    Column {
                        width: parent.width
                        spacing: Theme.padSm
                        Text { text: "Weather location"; color: Theme.textActive; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeNormal; font.weight: Font.Medium }
                        Text {
                            width: parent.width
                            text: "A town or city, optionally with its region or country (\"Austin, Texas\"). Sent to Open-Meteo to look up its forecast; nothing else is."
                            color: Theme.text; opacity: Theme.opacityMuted
                            font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSmall; wrapMode: Text.WordWrap
                        }
                        InputField {
                            width: parent.width
                            placeholder: "Not set"
                            input: weatherInput
                            TextInput {
                                id: weatherInput
                                objectName: "weatherLocationInput"
                                anchors.fill: parent
                                clip: true
                                text: root.weather_location
                                color: Theme.textActive
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSizeNormal
                                verticalAlignment: TextInput.AlignVCenter
                                onEditingFinished: if (text.trim() !== root.weather_location) { root.weather_location = text.trim(); root.dirty = true; }
                            }
                        }
                    }
                    ChoiceRow {
                        settingKey: "weather_units"; idPrefix: "weatherUnits:"; label: "Weather units"
                        options: [{ value: "metric", label: "°C · km/h" }, { value: "imperial", label: "°F · mph" }]
                    }
                    Column {
                        width: parent.width
                        spacing: Theme.padMd
                        Text { text: "Corners"; color: Theme.textActive; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeNormal; font.weight: Font.Medium }
                        CornerRow { settingKey: "widget_clock_pos"; idPrefix: "widgetPos:clock:"; label: "Clock" }
                        CornerRow { settingKey: "widget_music_pos"; idPrefix: "widgetPos:music:"; label: "Now playing" }
                        CornerRow { settingKey: "widget_system_pos"; idPrefix: "widgetPos:system:"; label: "System monitor" }
                        CornerRow { settingKey: "widget_weather_pos"; idPrefix: "widgetPos:weather:"; label: "Weather" }
                    }
                }
            }
        }
    }

    Component {
        id: wallpaperPane
        Column {
            width: parent ? parent.width : implicitWidth
            spacing: Theme.padLg
            Component.onCompleted: root.loadWallpaperChoices()

            Text { text: "Wallpaper"; color: Theme.textActive; font.family: Theme.fontFamily; font.weight: Font.DemiBold; font.pixelSize: Theme.fontSizeLarge }

            // A wallpaper WORKSPACE: a big, cinematic 16:9 preview -- the
            // actual aspect ratio of a real desktop, not a small portrait-
            // ish card -- with info/actions beside it when this panel is
            // wide enough to afford that (see panelWidth/ResponsiveSplit
            // above) and stacked below it otherwise. Never both narrow AND
            // squeezed: below the breakpoint the preview keeps the full
            // width, it just gives up sharing a row to get it.
            ResponsiveSplit {
                width: parent.width
                asideWidth: 280

                Rectangle {
                    id: wallpaperPreviewFrame
                    width: parent.width
                    height: Math.min(420, width * 9 / 16)
                    radius: Theme.roundingLg
                    color: Theme.layer1
                    clip: true
                    Image {
                        id: wallpaperPreviewImage
                        anchors.fill: parent
                        source: root.wallpaper ? "file://" + root.wallpaper : ""
                        fillMode: Image.PreserveAspectCrop
                        asynchronous: true
                        visible: status === Image.Ready
                    }
                    Text {
                        anchors.centerIn: parent
                        visible: wallpaperPreviewImage.status !== Image.Ready
                        text: "No wallpaper set"
                        color: Theme.text
                        opacity: Theme.opacityMuted
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSizeSmaller
                    }
                }

                aside: Column {
                    width: parent.width
                    spacing: Theme.padLg

                    Card {
                        width: parent.width
                        padding: Theme.pad2xl
                        title: "Current wallpaper"
                        Text { width: parent.width; text: root.wallpaper || "None set"; color: Theme.text; opacity: Theme.opacitySecondary; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSmaller; elide: Text.ElideMiddle }
                        GlassButton { text: "Choose..."; variant: "secondary"; onClicked: wallpaperDialog.open() }
                    }

                    Card {
                        width: parent.width
                        padding: Theme.pad2xl
                        title: "Generate Theme"
                        Text { width: parent.width; text: "Samples the wallpaper for a background tone and accent -- overwrites Colors below (Apply to keep, Revert to undo)."; color: Theme.text; opacity: Theme.opacityMuted; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSmall; wrapMode: Text.WordWrap }
                        GlassButton {
                            text: "Generate"
                            variant: "primary"
                            busy: root.generatingFromWallpaper
                            onClicked: root.generateFromWallpaper()
                        }
                        Text {
                            visible: root.wallpaperGenerateError.length > 0
                            width: parent.width
                            wrapMode: Text.WordWrap
                            text: root.wallpaperGenerateError
                            color: Theme.accent
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSizeSmaller
                        }
                    }
                }
            }

            // Every picture found in the wallpaper folders, as real thumbnails
            // (decoded small, off the UI thread). Clicking one makes it the
            // draft's wallpaper, exactly as Choose... does; Apply keeps it.
            Card {
                visible: root.wallpaperChoices.length > 0
                width: parent.width
                padding: Theme.pad2xl
                title: "Your wallpapers"
                Flow {
                    id: wallFlow
                    objectName: "wallpaperChoices"
                    width: parent.width
                    spacing: Theme.padMd
                    readonly property int columns: Math.max(2, Math.floor((width + spacing) / (176 + spacing)))
                    readonly property real cellWidth: (width - (columns - 1) * spacing) / columns
                    Repeater {
                        model: root.wallpaperChoices
                        delegate: Item {
                            id: wall
                            required property var modelData
                            required property int index
                            readonly property bool picked: root.wallpaper === wall.modelData.path
                            objectName: "wallpaperChoice:" + wall.modelData.name
                            width: wallFlow.cellWidth
                            height: width * 9 / 16 + 22
                            scale: wallHover.hovered && !wall.picked ? 1.02 : 1
                            Behavior on scale { NumberAnimation { duration: Theme.durationFast; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveStandard } }
                            HoverHandler { id: wallHover; cursorShape: Qt.PointingHandCursor }
                            Rectangle {
                                id: thumbFrame
                                width: parent.width; height: width * 9 / 16
                                radius: Theme.roundingSm
                                color: Theme.layer1
                                border.width: wall.picked ? 2 : 1
                                border.color: wall.picked ? Theme.accent : Theme.borderIdle
                                Behavior on border.color { ColorAnimation { duration: Theme.durationFast; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveStandard } }
                                Image {
                                    objectName: "wallpaperThumb"
                                    anchors.fill: parent; anchors.margins: 2
                                    source: "file://" + wall.modelData.path
                                    sourceSize: Qt.size(320, 180)
                                    fillMode: Image.PreserveAspectCrop
                                    asynchronous: true
                                    opacity: status === Image.Ready ? 1 : 0
                                    Behavior on opacity { NumberAnimation { duration: Theme.durationDefault; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveStandard } }
                                }
                            }
                            Text {
                                y: thumbFrame.height + 4
                                width: parent.width
                                text: wall.modelData.name
                                elide: Text.ElideRight
                                color: wall.picked ? Theme.textActive : Theme.text
                                opacity: wall.picked ? 1 : Theme.opacityMuted
                                font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSmaller
                                font.weight: wall.picked ? Font.DemiBold : Font.Normal
                            }
                            MouseArea {
                                anchors.fill: parent
                                onClicked: { root.wallpaper = wall.modelData.path; root.dirty = true; }
                            }
                        }
                    }
                }
            }

            // The generated/current palette, shown as the same swatch
            // language as Colors' presets -- so "Generate" visibly feeds
            // back into the same visual system it modifies, rather than a
            // button whose effect you can only see by switching tabs.
            PreviewRegion {
                width: parent.width
                Column {
                    width: parent.width
                    spacing: Theme.padSm
                    Text { text: "Resulting palette"; color: Theme.text; opacity: Theme.opacityMuted; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSmall }
                    Row {
                        spacing: Theme.padSm
                        Rectangle { width: 36; height: 36; radius: Theme.roundingSm; color: "#" + root.glass_bg }
                        Rectangle { width: 36; height: 36; radius: Theme.roundingSm; color: "#" + root.glass_bg_active }
                        Rectangle { width: 36; height: 36; radius: Theme.roundingFull; color: "#" + root.accent }
                        Rectangle { width: 36; height: 36; radius: Theme.roundingSm; color: "#" + root.glass_text }
                    }
                }
            }
        }
    }
}
