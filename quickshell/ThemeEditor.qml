import QtQuick
import QtQuick.Dialogs
import QtQuick.Effects
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
    Timer { id: closeTimer; interval: Theme.durationEnter + 20; onTriggered: root.closeRequested() }
    color: "transparent"
    exclusionMode: ExclusionMode.Ignore
    aboveWindows: true
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.namespace: "dxrice-theme"
    focusable: true

    // The panel's own natural size -- was the whole window's implicitWidth/
    // Height back when this was a plain top-center window with no
    // click-outside-to-dismiss. Now the window itself spans the full screen
    // (same reasoning as Dock.qml's implicitHeight: root.screen.height even
    // though the dock pill only occupies its bottom strip) so a click
    // anywhere outside the panel has somewhere on THIS window's surface to
    // land; panelSurface below is what actually gets positioned/sized to
    // this box.
    readonly property real panelWidth: 700
    // Capped against the real screen, not just a bare 640: a fixed constant
    // never grows from content (this window's sidebar/content already scroll
    // internally, see catFlickable/contentFlick above), but a fixed constant
    // can still be too tall for a short display -- and "fits its own
    // Rectangle" is not the same claim as "fits on this screen."
    readonly property real panelHeight: Math.min(640, (root.screen ? root.screen.height : 1080) - ShellSurface.topEdgeHeight - ShellSurface.gap)
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
    // still reaches `dismissArea` below and closes it. There is no state
    // where this sits there as a permanent invisible click-blocker: the
    // whole window (and this mask with it) is torn down by the LazyLoader
    // once the close sequence described above finishes.
    mask: Region {
        Region { item: panelSurface }
        Region { x: 0; y: 0; width: root.width; height: root.height }
    }

    MouseArea {
        id: dismissArea
        anchors.fill: parent
        onClicked: PanelManager.close("theme")
    }

    readonly property string repoDir: Quickshell.shellDir + "/.."
    readonly property string themeJsonPath: Quickshell.env("HOME") + "/.config/dxrice/theme.json"

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

    property string font_family: "JetBrainsMono Nerd Font"
    property string wallpaper: ""

    property bool dirty: false
    property bool applying: false

    readonly property var colorFields: [
        { key: "glass_bg", label: "Panel background", sub: "Waybar/wofi/kitty base color" },
        { key: "glass_bg_active", label: "Active panel background", sub: "Focused workspace, selected entries" },
        { key: "glass_text", label: "Text", sub: "Base text color" },
        { key: "glass_text_active", label: "Active text", sub: "Text on focused/selected elements" },
        { key: "glass_border", label: "Panel border", sub: "Hairline border around panels" },
        { key: "accent", label: "Accent", sub: "Critical notifications, mute/destructive actions" },
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
        { key: "radius", label: "Panel corner radius", min: 0, max: 30, decimals: 0, unit: "px" },
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
        { key: "lock_bg_opacity", label: "Input field background opacity", min: 0, max: 1, decimals: 2 },
    ]
    readonly property var fontSizeFields: [
        { key: "font_size_waybar", label: "Taskbar text size", min: 8, max: 24, decimals: 0 },
        { key: "font_size_waybar_icons", label: "Taskbar app icon size", min: 8, max: 40, decimals: 0 },
        { key: "font_size_wofi", label: "App launcher font size", min: 8, max: 24, decimals: 0 },
        { key: "font_size_mako", label: "Notification font size", min: 8, max: 24, decimals: 0 },
    ]
    readonly property var experienceFields: [
        { key: "anim_duration_ms", label: "Animation speed (lower = snappier)", min: 0, max: 500, decimals: 0, unit: "ms" },
        { key: "ui_density", label: "Settings app spacing", min: 0.5, max: 1.5, decimals: 2 },
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
        { id: "colors", glyph: "", label: "Colors", sub: "Presets, palette, window borders" },
        { id: "blur", glyph: "", label: "Transparency & Blur", sub: "Panel opacity, window blur" },
        { id: "layout", glyph: "", label: "Layout", sub: "Rounding, gaps, window borders" },
        { id: "lock", glyph: "", label: "Lock Screen", sub: "Blur, vibrancy, input field" },
        { id: "fonts", glyph: "", label: "Fonts", sub: "Sizes and font family" },
        { id: "experience", glyph: "", label: "Experience", sub: "Animation speed, density, shadows" },
        { id: "wallpaper", glyph: "", label: "Wallpaper", sub: "Desktop background image" },
    ]
    property string currentCategory: "colors"
    property string searchText: ""
    readonly property var filteredCategories: {
        const q = root.searchText.trim().toLowerCase();
        if (!q) return root.categories;
        return root.categories.filter((c) => c.label.toLowerCase().includes(q) || c.sub.toLowerCase().includes(q));
    }

    function allKeys() {
        const keys = ["font_family", "wallpaper"];
        for (const f of colorFields) keys.push(f.key);
        for (const f of borderColorFields) keys.push(f.key);
        for (const f of blurFields) keys.push(f.key);
        for (const f of layoutFields) keys.push(f.key);
        for (const f of lockFields) keys.push(f.key);
        for (const f of fontSizeFields) keys.push(f.key);
        for (const f of experienceFields) keys.push(f.key);
        return keys;
    }

    function loadFromTheme(data) {
        for (const key of allKeys()) {
            if (data[key] !== undefined) root[key] = data[key];
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
        root.dirty = false;
    }

    Component.onCompleted: loadFromTheme(Theme.data)

    function applyPreset(colors) {
        for (const key in colors) root[key] = colors[key];
        root.dirty = true;
    }

    FileView {
        id: writer
        path: root.themeJsonPath
    }

    function save() {
        const obj = {};
        for (const key of allKeys()) obj[key] = root[key];
        writer.setText(JSON.stringify(obj, null, 4));
    }

    Process {
        id: applyProc
        command: ["python3", root.repoDir + "/scripts/dxrice_apply_theme.py"]
        onExited: { root.applying = false; }
    }

    // ---- generate a full color palette from the current wallpaper --
    // the actual mechanism real end-4/caelestia rices use to make the
    // theme "match the wallpaper": sample it, derive background/accent/
    // border tones from what's actually in the image (see the script's own
    // comment for why this needs no PIL/numpy). Applies to the draft only,
    // same as a preset button -- still needs Apply to take effect. ----
    property bool generatingFromWallpaper: false
    property string wallpaperGenerateError: ""
    Process {
        id: generateProc
        command: ["python3", root.repoDir + "/scripts/dxrice_wallpaper_theme.py", root.wallpaper]
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
        root.save();
        root.applying = true;
        applyProc.running = true;
    }

    function revert() {
        loadFromTheme(Theme.data);
    }

    // ---- shared dialogs ----
    property string editingColorKey: ""
    function colorToHex(c) {
        const toHex = (v) => Math.max(0, Math.min(255, Math.round(v * 255))).toString(16).padStart(2, "0");
        return toHex(c.r) + toHex(c.g) + toHex(c.b);
    }

    ColorDialog {
        id: colorDialog
        onAccepted: {
            if (root.editingColorKey) {
                root[root.editingColorKey] = root.colorToHex(colorDialog.selectedColor);
                root.dirty = true;
            }
        }
    }
    function _rgba(hex, alpha) {
        return Qt.rgba(
            parseInt(hex.substring(0, 2), 16) / 255,
            parseInt(hex.substring(2, 4), 16) / 255,
            parseInt(hex.substring(4, 6), 16) / 255,
            alpha
        );
    }
    function pickColor(key) {
        root.editingColorKey = key;
        colorDialog.selectedColor = "#" + root[key];
        colorDialog.open();
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
                    width: 32; height: 24; radius: Theme.roundingXs
                    color: "#" + root[modelData.key]
                    border.width: Theme.borderWidth
                    border.color: Theme.borderIdle
                    MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: root.pickColor(modelData.key) }
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
        spacing: Theme.padSm
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
    Shortcut { sequence: "Escape"; onActivated: PanelManager.close("theme") }

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

        Column {
            anchors.fill: parent
            spacing: 0

            Item {
                id: header
                width: parent.width
                height: 56

                Text {
                    text: "Theme"
                    color: Theme.textActive
                    font.family: Theme.fontFamily
                    font.weight: Font.DemiBold
                    font.pixelSize: Theme.fontSizeLarge
                    anchors.verticalCenter: parent.verticalCenter
                    x: Theme.padLg
                }
                Row {
                    anchors.verticalCenter: parent.verticalCenter
                    x: header.width - width - Theme.padLg
                    spacing: Theme.padSm
                    GlassButton { text: "Revert"; variant: "secondary"; onClicked: root.revert() }
                    GlassButton {
                        text: root.applying ? "Applying..." : (root.dirty ? "Apply*" : "Apply")
                        variant: "primary"
                        enabled: !root.applying
                        onClicked: root.apply()
                    }
                    IconButton { glyph: "✕"; onClicked: PanelManager.close("theme") }
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

                    Rectangle {
                        x: Theme.padMd
                        width: parent.width - Theme.padMd * 2
                        height: ShellSurface.rowHeight
                        radius: Theme.roundingSm
                        color: Theme.inputFill

                        Text {
                            anchors.verticalCenter: parent.verticalCenter
                            anchors.left: parent.left
                            anchors.leftMargin: Theme.padSm
                            text: ""
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSizeSmall
                            color: Theme.text
                        opacity: Theme.opacitySecondary
                        }
                        TextInput {
                            anchors.left: parent.left
                            anchors.leftMargin: 26
                            anchors.right: parent.right
                            anchors.rightMargin: Theme.padSm
                            anchors.verticalCenter: parent.verticalCenter
                            color: Theme.textActive
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSizeSmaller
                            text: root.searchText
                            onTextChanged: root.searchText = text
                            Text {
                                text: "Search settings"
                                color: Theme.text
                                opacity: parent.text.length ? 0 : Theme.opacityMuted
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSizeSmaller
                            }
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
                                        text: catRow.modelData.glyph
                                        font.family: Theme.fontFamily
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
                        Behavior on contentY { NumberAnimation { duration: Theme.durationFast } }

                        Loader {
                            id: paneLoader
                            x: Theme.padLg
                            y: Theme.padLg
                            width: contentFlick.width - Theme.padLg * 2
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

    Component {
        id: colorsPane
        Column {
            width: parent ? parent.width : implicitWidth
            spacing: Theme.pad3xl

            Text { text: "Presets"; color: Theme.text; opacity: Theme.opacityMuted; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSmall }
            // -- presets communicate visually (an actual mini palette),
            // not as a row of plain text-labeled buttons the user has to
            // read one at a time. --
            Flow {
                width: parent.width
                spacing: Theme.padSm
                Repeater {
                    model: Object.keys(root.presets)
                    delegate: Rectangle {
                        id: presetSwatch
                        readonly property var colors: root.presets[modelData]
                        width: 108
                        height: 64
                        radius: Theme.roundingSm
                        color: presetArea.containsMouse ? Theme.layer1 : "transparent"
                        border.width: Theme.borderWidth
                        border.color: Theme.borderIdle
                        Behavior on color { ColorAnimation { duration: Theme.durationFast } }

                        Column {
                            anchors.centerIn: parent
                            spacing: Theme.padXs
                            Row {
                                anchors.horizontalCenter: parent.horizontalCenter
                                spacing: 4
                                Rectangle { width: 16; height: 16; radius: Theme.roundingXs; color: "#" + presetSwatch.colors.glass_bg }
                                Rectangle { width: 16; height: 16; radius: Theme.roundingXs; color: "#" + presetSwatch.colors.glass_bg_active }
                                Rectangle { width: 16; height: 16; radius: Theme.roundingFull; color: "#" + presetSwatch.colors.accent }
                            }
                            Text {
                                anchors.horizontalCenter: parent.horizontalCenter
                                text: modelData
                                color: Theme.text
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSizeSmall
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

            // Grouped as Level-2 cards (see Card.qml) rather than
            // hairline-divided sections -- the same grammar Quick Settings
            // and Taskbar's own setting groups use, so Theme reads as part
            // of the same shell rather than a plain settings dialog that
            // happens to share a color palette with it.
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

            Card {
                width: parent.width
                padding: Theme.pad2xl
                title: "Transparency & Blur"
                // A real live preview of the opacity/border values against a
                // colorful backdrop -- actual compositor blur only happens on
                // a real Hyprland surface, so this is honestly just alpha +
                // border (which is most of what these sliders change), not a
                // blur simulation, but it's the same "see it, don't just read
                // a number" idea as the Fonts specimen.
                Item {
                    width: parent.width
                    height: 130
                    Rectangle {
                        anchors.fill: parent
                        radius: Theme.roundingLg
                        clip: true
                        gradient: Gradient {
                            GradientStop { position: 0.0; color: "#3a6b4a" }
                            GradientStop { position: 1.0; color: "#1a2e22" }
                        }
                        Rectangle {
                            anchors.centerIn: parent
                            width: parent.width * 0.62
                            height: parent.height * 0.62
                            radius: Theme.roundingMd
                            color: root._rgba(root.glass_bg, root.opacity_idle)
                            border.width: Theme.borderWidth
                            border.color: Qt.rgba(1, 1, 1, root.border_opacity_idle)
                            Text {
                                anchors.centerIn: parent
                                text: "Panel preview"
                                color: "#ffffff"
                                opacity: Theme.opacityFaint
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSizeSmaller
                            }
                        }
                    }
                }

                SliderList { width: parent.width; fields: root.blurFields }
            }
        }
    }

    Component {
        id: layoutPane
        Column {
            width: parent ? parent.width : implicitWidth
            spacing: Theme.padLg

            Card {
                width: parent.width
                padding: Theme.pad2xl
                title: "Layout"
                // Corner radius and window gaps are pure geometry -- a number
                // by itself doesn't communicate "how rounded" or "how much
                // space" the way an actual shape does.
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
                            color: Theme.layer1
                            border.width: Theme.borderWidth
                            border.color: Theme.borderIdle
                        }
                    }
                    Column {
                        width: (parent.width - parent.spacing) / 2
                        spacing: Theme.padXs
                        Text { text: "Window gaps"; color: Theme.text; opacity: Theme.opacityMuted; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSmall }
                        Row {
                            spacing: Math.max(2, root.hypr_gaps_in)
                            Rectangle { width: 42; height: 90; radius: root.hypr_rounding * 0.5; color: Theme.layer1; border.width: Theme.borderWidth; border.color: Theme.borderIdle }
                            Rectangle { width: 42; height: 90; radius: root.hypr_rounding * 0.5; color: Theme.layer1; border.width: Theme.borderWidth; border.color: Theme.borderIdle }
                        }
                    }
                }

                SliderList { width: parent.width; fields: root.layoutFields }
            }
        }
    }

    Component {
        id: lockPane
        Column {
            width: parent ? parent.width : implicitWidth
            spacing: Theme.padLg
            Card {
                width: parent.width
                padding: Theme.pad2xl
                title: "Lock Screen"
                SliderList { width: parent.width; fields: root.lockFields }
            }
        }
    }

    Component {
        id: fontsPane
        Column {
            width: parent ? parent.width : implicitWidth
            spacing: Theme.pad3xl

            // ---- typography: a live specimen, not a text field in a box.
            // Typing a new family updates the "Aa" + sample sentence
            // immediately (previewFamily), but only commits to the real
            // theme (and marks the draft dirty) once you leave the field --
            // the same "see it before you commit it" idea Colors/Presets
            // already use, just for text instead of swatches. ----
            Card {
                width: parent.width
                padding: Theme.pad2xl
                title: "Typography"

                Text {
                    id: specimenGlyphs
                    text: "Aa"
                    color: Theme.textActive
                    font.family: previewFamilyInput.text || Theme.fontFamily
                    font.pixelSize: 48
                    font.weight: Font.Light
                }
                Text {
                    text: "The quick brown fox jumps over the lazy dog"
                    color: Theme.text
                    opacity: Theme.opacityFaint
                    font.family: previewFamilyInput.text || Theme.fontFamily
                    font.pixelSize: Theme.fontSizeLarger
                    wrapMode: Text.WordWrap
                    width: parent.width
                }

                Item {
                    width: parent.width
                    height: 30
                    Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: previewFamilyInput.activeFocus ? Theme.accent : Theme.borderIdle }
                    TextInput {
                        id: previewFamilyInput
                        anchors.fill: parent
                        text: root.font_family
                        color: Theme.textActive
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSizeNormal
                        verticalAlignment: TextInput.AlignVCenter
                        onEditingFinished: { root.font_family = text; root.dirty = true; }
                    }
                }
            }

            // ---- sizes: each slider's own sample renders live at that
            // exact pixel size right underneath it. ----
            Card {
                width: parent.width
                padding: Theme.pad2xl
                title: "Sizes"
                TypeSizeRow { width: parent.width; label: "Taskbar text"; key: "font_size_waybar"; min: 8; max: 24; sampleText: "12:30 PM   Sep 10" }
                TypeSizeRow { width: parent.width; label: "Taskbar app icons"; key: "font_size_waybar_icons"; min: 8; max: 40; sampleText: "★ ✎ ⚙" }
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
            Card {
                width: parent.width
                padding: Theme.pad2xl
                title: "Experience"
                SliderList { width: parent.width; fields: root.experienceFields }
            }
        }
    }

    Component {
        id: wallpaperPane
        Column {
            width: parent ? parent.width : implicitWidth
            spacing: Theme.pad3xl

            // A real thumbnail instead of a text path -- "wallpaper should
            // have a preview" means an actual image, not its filename.
            Card {
                width: parent.width
                padding: Theme.pad2xl
                title: "Current Wallpaper"
                Item {
                    width: parent.width
                    height: 200
                    Rectangle {
                        anchors.fill: parent
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
                            opacity: 0.5
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSizeSmaller
                        }
                    }
                }
                SettingRow {
                    width: parent.width
                    title: "Current wallpaper"
                    subtitle: root.wallpaper
                    GlassButton { text: "Choose..."; variant: "secondary"; onClicked: wallpaperDialog.open() }
                }
            }

            Card {
                width: parent.width
                padding: Theme.pad2xl
                title: "Match Theme to Wallpaper"
                SettingRow {
                    width: parent.width
                    title: "Generate colors from the current wallpaper"
                    subtitle: "Samples it for a background tone and accent -- overwrites the Colors tab below (Apply to keep, Revert to undo)"
                    GlassButton {
                        text: root.generatingFromWallpaper ? "Sampling..." : "Generate"
                        variant: "primary"
                        enabled: !root.generatingFromWallpaper
                        onClicked: root.generateFromWallpaper()
                    }
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
}
