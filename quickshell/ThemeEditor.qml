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
// pattern as QuickSettings.qml: zero gap, bottom-only rounding, a
// WavyTopRect seam), centered under it -- not a separate floating OS
// window. A standalone window is exactly the "still a standalone GUI"
// complaint this replaces.
PanelWindow {
    id: root
    signal closeRequested()
    color: "transparent"
    exclusionMode: ExclusionMode.Ignore
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.namespace: "dxrice-theme"
    focusable: true

    implicitWidth: 700
    implicitHeight: 640
    anchors { top: true; left: true }
    margins {
        top: 52
        left: Math.round(((root.screen ? root.screen.width : 1920) - root.implicitWidth) / 2)
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
        { key: "hypr_blur_size", label: "Window blur size", min: 0, max: 20, decimals: 0 },
        { key: "hypr_blur_passes", label: "Window blur passes", min: 0, max: 10, decimals: 0 },
        { key: "hypr_blur_vibrancy", label: "Window blur vibrancy", min: 0, max: 1, decimals: 2 },
    ]
    readonly property var layoutFields: [
        { key: "radius", label: "Panel corner radius", min: 0, max: 30, decimals: 0 },
        { key: "hypr_rounding", label: "Window corner rounding", min: 0, max: 30, decimals: 0 },
        { key: "hypr_gaps_in", label: "Gaps between windows", min: 0, max: 40, decimals: 0 },
        { key: "hypr_gaps_out", label: "Gaps to screen edge", min: 0, max: 60, decimals: 0 },
        { key: "hypr_border_size", label: "Window border thickness", min: 0, max: 10, decimals: 0 },
        { key: "hypr_active_opacity", label: "Focused window opacity", min: 0, max: 1, decimals: 2 },
        { key: "hypr_inactive_opacity", label: "Unfocused window opacity", min: 0, max: 1, decimals: 2 },
        { key: "hypr_active_border_angle", label: "Active border gradient angle", min: 0, max: 360, decimals: 0 },
    ]
    readonly property var lockFields: [
        { key: "lock_blur_passes", label: "Blur passes", min: 0, max: 10, decimals: 0 },
        { key: "lock_blur_size", label: "Blur size", min: 0, max: 20, decimals: 0 },
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
        { key: "anim_duration_ms", label: "Animation speed (ms, lower = snappier)", min: 0, max: 500, decimals: 0 },
        { key: "ui_density", label: "Settings app spacing", min: 0.5, max: 1.5, decimals: 2 },
        { key: "shadow_intensity", label: "Panel shadow strength (Quickshell only)", min: 0, max: 1.5, decimals: 2 },
    ]
    readonly property var presets: ({
        "Glass Charcoal": { glass_bg: "12141a", glass_bg_active: "232630", glass_text: "e6e6e6", glass_text_active: "ffffff", glass_border: "ffffff", accent: "e67878", radius: 12, hypr_active_border_1: "8090a0", hypr_active_border_2: "c0a0b0", hypr_inactive_border: "1d2021" },
        "Nord": { glass_bg: "2e3440", glass_bg_active: "3b4252", glass_text: "d8dee9", glass_text_active: "eceff4", glass_border: "88c0d0", accent: "bf616a", radius: 8, hypr_active_border_1: "88c0d0", hypr_active_border_2: "81a1c1", hypr_inactive_border: "3b4252" },
        "Dracula": { glass_bg: "282a36", glass_bg_active: "44475a", glass_text: "f8f8f2", glass_text_active: "ffffff", glass_border: "bd93f9", accent: "ff5555", radius: 10, hypr_active_border_1: "ff79c6", hypr_active_border_2: "bd93f9", hypr_inactive_border: "44475a" },
        "Sunset": { glass_bg: "1a1210", glass_bg_active: "3a2420", glass_text: "f0e0d6", glass_text_active: "ffffff", glass_border: "ffb385", accent: "ff6b4a", radius: 16, hypr_active_border_1: "ff7e5f", hypr_active_border_2: "feb47b", hypr_inactive_border: "2a1d18" },
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
                    width: 32; height: 24; radius: 6
                    color: "#" + root[modelData.key]
                    border.width: 1
                    border.color: Theme.borderIdle
                    MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: root.pickColor(modelData.key) }
                }
            }
        }
    }

    component SliderList: Column {
        property var fields: []
        width: parent.width
        spacing: Theme.padMd
        Repeater {
            model: parent.fields
            delegate: SettingRow {
                width: parent.width
                title: modelData.label
                SliderRow {
                    width: 180
                    from: modelData.min; to: modelData.max; decimals: modelData.decimals
                    value: root[modelData.key]
                    onChanged: (v) => { root[modelData.key] = modelData.decimals === 0 ? Math.round(v) : v; root.dirty = true; }
                }
            }
        }
    }

    // ---- visuals: a drawer that unrolls down from the bar, matching
    // QuickSettings.qml exactly -- zero gap, square top corners, a
    // WavyTopRect seam, bottom-only rounding. ----
    Shortcut { sequence: "Escape"; onActivated: root.closeRequested() }

    Item {
        id: drawer
        anchors.fill: parent
        clip: true

        property real revealHeight: 0
        Behavior on revealHeight { NumberAnimation { duration: Theme.durationEnter; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveEmphasizedDecel } }
        Component.onCompleted: revealHeight = root.implicitHeight

        RectangularShadow {
            anchors.fill: panelSurface
            radius: 0
            bottomLeftRadius: Theme.roundingXl
            bottomRightRadius: Theme.roundingXl
            color: Theme.shadowColor
            blur: Theme.shadowBlurLg
            offset.y: 4
        }

        WavyTopRect {
            id: wavyRect
            anchors.top: parent.top
            anchors.left: parent.left
            width: parent.width
            height: 7
            color: Theme.bg
        }

        Rectangle {
            id: panelSurface
            anchors.top: wavyRect.bottom
            anchors.left: parent.left
            anchors.right: parent.right
            height: Math.max(0, drawer.revealHeight - wavyRect.height)
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
                    font.pixelSize: 17
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
                    IconButton { glyph: "✕"; onClicked: root.closeRequested() }
                }
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
                        height: 34
                        radius: Theme.roundingSm
                        color: Theme.layer1

                        Text {
                            anchors.verticalCenter: parent.verticalCenter
                            anchors.left: parent.left
                            anchors.leftMargin: Theme.padSm
                            text: ""
                            font.family: Theme.fontFamily
                            font.pixelSize: 11
                            color: Theme.text
                            opacity: 0.6
                        }
                        TextInput {
                            anchors.left: parent.left
                            anchors.leftMargin: 26
                            anchors.right: parent.right
                            anchors.rightMargin: Theme.padSm
                            anchors.verticalCenter: parent.verticalCenter
                            color: Theme.textActive
                            font.family: Theme.fontFamily
                            font.pixelSize: 12
                            text: root.searchText
                            onTextChanged: root.searchText = text
                            Text {
                                text: "Search settings"
                                color: Theme.text
                                opacity: parent.text.length ? 0 : 0.5
                                font.family: Theme.fontFamily
                                font.pixelSize: 12
                            }
                        }
                    }

                    Flickable {
                        width: parent.width
                        height: parent.height - 34 - Theme.padSm
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
                                        radius: 2
                                        color: Theme.accent
                                    }

                                    Text {
                                        id: catGlyph
                                        anchors.left: parent.left
                                        anchors.leftMargin: Theme.padMd
                                        anchors.verticalCenter: parent.verticalCenter
                                        text: catRow.modelData.glyph
                                        font.family: Theme.fontFamily
                                        font.pixelSize: 15
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
                                            font.pixelSize: 12
                                            font.weight: Font.Medium
                                            elide: Text.ElideRight
                                        }
                                        Text {
                                            width: parent.width
                                            text: catRow.modelData.sub
                                            color: Theme.text
                                            opacity: 0.55
                                            font.family: Theme.fontFamily
                                            font.pixelSize: 10
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
                }

                Rectangle {
                    width: 1
                    height: parent.height
                    color: Theme.borderIdle
                }

                // ---- content pane: one category's fields at a time ----
                Flickable {
                    id: contentFlick
                    width: sidebarLayout.width - sidebar.width - 1
                    height: parent.height
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
            }
        }
        }
    }

    Component {
        id: colorsPane
        Column {
            width: parent ? parent.width : implicitWidth
            spacing: Theme.padLg
            Text { text: "Presets"; color: Theme.textActive; font.family: Theme.fontFamily; font.weight: Font.DemiBold }
            Card {
                width: parent.width
                Row {
                    width: parent.width
                    spacing: Theme.padSm
                    Repeater {
                        model: Object.keys(root.presets)
                        delegate: GlassButton {
                            text: modelData
                            variant: "secondary"
                            onClicked: root.applyPreset(root.presets[modelData])
                        }
                    }
                }
            }
            Text { text: "Glass Palette"; color: Theme.textActive; font.family: Theme.fontFamily; font.weight: Font.DemiBold }
            Card { width: parent.width; ColorList { fields: root.colorFields } }
            Text { text: "Window Border Gradient"; color: Theme.textActive; font.family: Theme.fontFamily; font.weight: Font.DemiBold }
            Card { width: parent.width; ColorList { fields: root.borderColorFields } }
        }
    }

    Component {
        id: blurPane
        Column {
            width: parent ? parent.width : implicitWidth
            spacing: Theme.padLg
            Card { width: parent.width; SliderList { fields: root.blurFields } }
        }
    }

    Component {
        id: layoutPane
        Column {
            width: parent ? parent.width : implicitWidth
            spacing: Theme.padLg
            Card { width: parent.width; SliderList { fields: root.layoutFields } }
        }
    }

    Component {
        id: lockPane
        Column {
            width: parent ? parent.width : implicitWidth
            spacing: Theme.padLg
            Card { width: parent.width; SliderList { fields: root.lockFields } }
        }
    }

    Component {
        id: fontsPane
        Column {
            width: parent ? parent.width : implicitWidth
            spacing: Theme.padLg
            Card { width: parent.width; SliderList { fields: root.fontSizeFields } }
            Text { text: "Font family"; color: Theme.textActive; font.family: Theme.fontFamily; font.weight: Font.DemiBold }
            Card {
                width: parent.width
                SettingRow {
                    width: parent.width
                    title: "Font family"
                    Rectangle {
                        width: 200; height: 30; radius: Theme.entryRadius
                        color: Qt.rgba(1, 1, 1, 0.06)
                        border.width: 1; border.color: Theme.borderIdle
                        TextInput {
                            anchors.fill: parent
                            anchors.margins: 6
                            text: root.font_family
                            color: Theme.textActive
                            font.family: Theme.fontFamily
                            verticalAlignment: TextInput.AlignVCenter
                            onEditingFinished: { root.font_family = text; root.dirty = true; }
                        }
                    }
                }
            }
        }
    }

    Component {
        id: experiencePane
        Column {
            width: parent ? parent.width : implicitWidth
            spacing: Theme.padLg
            Card { width: parent.width; SliderList { fields: root.experienceFields } }
        }
    }

    Component {
        id: wallpaperPane
        Column {
            width: parent ? parent.width : implicitWidth
            spacing: Theme.padLg
            Card {
                width: parent.width
                SettingRow {
                    width: parent.width
                    title: "Current wallpaper"
                    subtitle: root.wallpaper
                    GlassButton { text: "Choose..."; variant: "secondary"; onClicked: wallpaperDialog.open() }
                }
            }
        }
    }
}
