pragma Singleton
import QtQuick
import Quickshell
import Quickshell.Io

// Shared design tokens for every DXrice Quickshell widget. Reads the same
// live theme.json the GTK-era apps used (~/.config/dxrice/theme.json,
// seeded from <repo>/theme/theme.json on first run by
// scripts/dxrice_apply_theme.py) so this is never a second source of
// truth -- editing colors still only ever happens in one file.
//
// watchChanges is on, so every open panel re-reads and re-colors itself
// live the moment theme.json changes on disk, with no restart needed.
QtObject {
    id: root

    readonly property string path: Quickshell.env("HOME") + "/.config/dxrice/theme.json"

    property var data: ({})

    function reload() {
        file.reload();
    }

    function _applyText(text) {
        try {
            root.data = JSON.parse(text);
        } catch (e) {
            console.warn("Theme.qml: could not parse theme.json:", e);
            root.data = {};
        }
    }

    property FileView file: FileView {
        path: root.path
        watchChanges: true
        // Blocking, not async, is deliberate: a window that reads Theme.data
        // the instant it opens (e.g. ThemeEditor.qml seeding its draft
        // fields) must never see stale/default values because the async
        // read hadn't finished yet -- that's exactly the bug class that
        // once wiped a real config file elsewhere in this shell (see
        // TaskbarManager.qml's commit() comment).
        blockLoading: true
        onFileChanged: this.reload()
        onLoaded: root._applyText(this.text())
        onLoadFailed: (error) => console.warn("Theme.qml: could not load", root.path, error)
    }

    function _str(key, fallback) {
        const v = root.data[key];
        return v !== undefined ? String(v) : fallback;
    }

    function _num(key, fallback) {
        const v = root.data[key];
        return v !== undefined ? Number(v) : fallback;
    }

    function _color(hex, alpha) {
        return Qt.rgba(
            parseInt(hex.substring(0, 2), 16) / 255,
            parseInt(hex.substring(2, 4), 16) / 255,
            parseInt(hex.substring(4, 6), 16) / 255,
            alpha === undefined ? 1.0 : alpha
        );
    }

    // ---- raw hex tokens (no alpha) ----
    readonly property string glassBgHex: root._str("glass_bg", "12141a")
    readonly property string glassBgActiveHex: root._str("glass_bg_active", "232630")
    readonly property string glassBorderHex: root._str("glass_border", "ffffff")
    readonly property string accentHex: root._str("accent", "e67878")
    readonly property string textHex: root._str("glass_text", "e6e6e6")
    readonly property string textActiveHex: root._str("glass_text_active", "ffffff")

    // ---- opacities ----
    readonly property real opacityIdle: root._num("opacity_idle", 0.55)
    readonly property real opacityActive: root._num("opacity_active", 0.85)
    readonly property real borderOpacityIdle: root._num("border_opacity_idle", 0.08)
    readonly property real borderOpacityActive: root._num("border_opacity_active", 0.25)

    // ---- composed colors, ready to use directly as `color:` values ----
    readonly property color bg: root._color(glassBgHex, opacityActive)
    readonly property color bgIdle: root._color(glassBgActiveHex, opacityIdle)
    readonly property color active: root._color(glassBgActiveHex, opacityActive)
    readonly property color border: root._color(glassBorderHex, borderOpacityActive)
    readonly property color borderIdle: root._color(glassBorderHex, borderOpacityIdle)
    readonly property color accent: root._color(accentHex, 1.0)
    readonly property color accentSoft: root._color(accentHex, 0.85)
    readonly property color text: root._color(textHex, 1.0)
    readonly property color textActive: root._color(textActiveHex, 1.0)
    readonly property color scrim: Qt.rgba(0, 0, 0, 0.28)

    // ---- layout / motion ----
    readonly property real radius: root._num("radius", 12)
    readonly property real entryRadius: Math.max(0, radius - 2)
    readonly property real density: root._num("ui_density", 1.0)
    readonly property real padSm: Math.round(4 * density)
    readonly property real padMd: Math.round(8 * density)
    readonly property real padLg: Math.round(12 * density)
    readonly property int animMs: Math.max(1, root._num("anim_duration_ms", 150))
    readonly property string fontFamily: root._str("font_family", "sans-serif")

    readonly property string wallpaper: root._str("wallpaper", "")
}
