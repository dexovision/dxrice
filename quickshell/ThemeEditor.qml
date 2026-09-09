import QtQuick
import QtQuick.Dialogs
import Quickshell
import Quickshell.Io

// DXrice Theme editor -- Quickshell rewrite of dxrice_theme_gui.py.
// Edits the same live ~/.config/dxrice/theme.json and, on Apply, shells
// out to the existing scripts/dxrice_apply_theme.py to do the actual
// template rendering + hot-reload -- that pipeline (waybar/wofi/mako/
// kitty/hyprlock templates, the hyprland.lua patcher) stays exactly as
// it is; this window only needs to read/write the JSON.
FloatingWindow {
    id: root
    signal closeRequested()
    title: "DXrice Theme"
    color: "transparent"
    onVisibleChanged: if (!visible) root.closeRequested()

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
    readonly property var sliderGroups: [
        { title: "Transparency and Blur", fields: [
            { key: "opacity_idle", label: "Panel opacity (idle)", min: 0, max: 1, decimals: 2 },
            { key: "opacity_active", label: "Panel opacity (active)", min: 0, max: 1, decimals: 2 },
            { key: "border_opacity_idle", label: "Border opacity (idle)", min: 0, max: 1, decimals: 2 },
            { key: "border_opacity_active", label: "Border opacity (active)", min: 0, max: 1, decimals: 2 },
            { key: "kitty_opacity", label: "Terminal opacity", min: 0, max: 1, decimals: 2 },
            { key: "hypr_blur_size", label: "Window blur size", min: 0, max: 20, decimals: 0 },
            { key: "hypr_blur_passes", label: "Window blur passes", min: 0, max: 10, decimals: 0 },
            { key: "hypr_blur_vibrancy", label: "Window blur vibrancy", min: 0, max: 1, decimals: 2 },
        ]},
        { title: "Layout", fields: [
            { key: "radius", label: "Panel corner radius", min: 0, max: 30, decimals: 0 },
            { key: "hypr_rounding", label: "Window corner rounding", min: 0, max: 30, decimals: 0 },
            { key: "hypr_gaps_in", label: "Gaps between windows", min: 0, max: 40, decimals: 0 },
            { key: "hypr_gaps_out", label: "Gaps to screen edge", min: 0, max: 60, decimals: 0 },
            { key: "hypr_border_size", label: "Window border thickness", min: 0, max: 10, decimals: 0 },
            { key: "hypr_active_opacity", label: "Focused window opacity", min: 0, max: 1, decimals: 2 },
            { key: "hypr_inactive_opacity", label: "Unfocused window opacity", min: 0, max: 1, decimals: 2 },
            { key: "hypr_active_border_angle", label: "Active border gradient angle", min: 0, max: 360, decimals: 0 },
        ]},
        { title: "Lock Screen", fields: [
            { key: "lock_blur_passes", label: "Blur passes", min: 0, max: 10, decimals: 0 },
            { key: "lock_blur_size", label: "Blur size", min: 0, max: 20, decimals: 0 },
            { key: "lock_blur_vibrancy", label: "Blur vibrancy", min: 0, max: 1, decimals: 2 },
            { key: "lock_bg_opacity", label: "Input field background opacity", min: 0, max: 1, decimals: 2 },
        ]},
        { title: "Fonts", fields: [
            { key: "font_size_waybar", label: "Taskbar text size", min: 8, max: 24, decimals: 0 },
            { key: "font_size_waybar_icons", label: "Taskbar app icon size", min: 8, max: 40, decimals: 0 },
            { key: "font_size_wofi", label: "App launcher font size", min: 8, max: 24, decimals: 0 },
            { key: "font_size_mako", label: "Notification font size", min: 8, max: 24, decimals: 0 },
        ]},
        { title: "Experience", fields: [
            { key: "anim_duration_ms", label: "Animation speed (ms, lower = snappier)", min: 0, max: 500, decimals: 0 },
            { key: "ui_density", label: "Settings app spacing", min: 0.5, max: 1.5, decimals: 2 },
        ]},
    ]
    readonly property var presets: ({
        "Glass Charcoal": { glass_bg: "12141a", glass_bg_active: "232630", glass_text: "e6e6e6", glass_text_active: "ffffff", glass_border: "ffffff", accent: "e67878", radius: 12, hypr_active_border_1: "8090a0", hypr_active_border_2: "c0a0b0", hypr_inactive_border: "1d2021" },
        "Nord": { glass_bg: "2e3440", glass_bg_active: "3b4252", glass_text: "d8dee9", glass_text_active: "eceff4", glass_border: "88c0d0", accent: "bf616a", radius: 8, hypr_active_border_1: "88c0d0", hypr_active_border_2: "81a1c1", hypr_inactive_border: "3b4252" },
        "Dracula": { glass_bg: "282a36", glass_bg_active: "44475a", glass_text: "f8f8f2", glass_text_active: "ffffff", glass_border: "bd93f9", accent: "ff5555", radius: 10, hypr_active_border_1: "ff79c6", hypr_active_border_2: "bd93f9", hypr_inactive_border: "44475a" },
        "Sunset": { glass_bg: "1a1210", glass_bg_active: "3a2420", glass_text: "f0e0d6", glass_text_active: "ffffff", glass_border: "ffb385", accent: "ff6b4a", radius: 16, hypr_active_border_1: "ff7e5f", hypr_active_border_2: "feb47b", hypr_inactive_border: "2a1d18" },
    })

    function allKeys() {
        const keys = ["font_family", "wallpaper"];
        for (const f of colorFields) keys.push(f.key);
        for (const f of borderColorFields) keys.push(f.key);
        for (const group of sliderGroups) for (const f of group.fields) keys.push(f.key);
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

    // ---- visuals ----
    implicitWidth: 480
    implicitHeight: 780

    Shortcut { sequence: "Escape"; onActivated: root.closeRequested() }

    Rectangle {
        anchors.fill: parent
        radius: Theme.radius
        color: Theme.bg
        border.width: 1
        border.color: Theme.border

        opacity: 0
        Behavior on opacity { NumberAnimation { duration: Theme.animMs * 3; easing.type: Easing.OutCubic } }
        Component.onCompleted: opacity = 1

        Column {
            anchors.fill: parent
            spacing: 0

            Row {
                id: header
                width: parent.width
                height: 48
                Text {
                    text: "Theme"
                    color: Theme.textActive
                    font.family: Theme.fontFamily
                    font.weight: Font.DemiBold
                    font.pixelSize: 16
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

            Flickable {
                width: parent.width
                height: parent.height - header.height
                contentHeight: body.implicitHeight + Theme.padLg * 2
                clip: true

                Column {
                    id: body
                    x: Theme.padLg
                    y: Theme.padLg
                    width: parent.width - Theme.padLg * 2
                    spacing: Theme.padMd

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
                    Card {
                        width: parent.width
                        Repeater {
                            model: root.colorFields
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

                    Text { text: "Window Border Gradient"; color: Theme.textActive; font.family: Theme.fontFamily; font.weight: Font.DemiBold }
                    Card {
                        width: parent.width
                        Repeater {
                            model: root.borderColorFields
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

                    Repeater {
                        model: root.sliderGroups
                        delegate: Column {
                            width: body.width
                            spacing: Theme.padMd
                            property var group: modelData
                            Text { text: group.title; color: Theme.textActive; font.family: Theme.fontFamily; font.weight: Font.DemiBold }
                            Card {
                                width: parent.width
                                Repeater {
                                    model: group.fields
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
                        }
                    }

                    Text { text: "Font"; color: Theme.textActive; font.family: Theme.fontFamily; font.weight: Font.DemiBold }
                    Card {
                        width: parent.width
                        SettingRow {
                            width: parent.width
                            title: "Font family"
                            Rectangle {
                                width: 180; height: 30; radius: Theme.entryRadius
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

                    Text { text: "Wallpaper"; color: Theme.textActive; font.family: Theme.fontFamily; font.weight: Font.DemiBold }
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
    }
}
