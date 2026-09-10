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
// The rounding scale, motion curves, and layered surface colors below are
// deliberately modeled on the Material 3 Expressive tokens end-4/dots-
// hyprland and caelestia's shell both actually use under the hood (varied,
// generous corner radii; overshoot/spring-like bezier curves instead of
// flat ease-out; surfaces that get progressively lighter/more contrasted
// as they layer on top of each other, with hover/press states mixed from
// the surface and foreground colors rather than swapped outright) -- that
// structure is most of what separates "looks like a rice" from "looks like
// a plain settings dialog," independent of which colors you've picked.
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

    // Linearly blends two colors (Material's "surface + N% of foreground"
    // pattern for hover/press states) -- ratio 0 is pure a, 1 is pure b.
    function mix(a, b, ratio) {
        const r = Math.max(0, Math.min(1, ratio));
        return Qt.rgba(
            a.r + (b.r - a.r) * r,
            a.g + (b.g - a.g) * r,
            a.b + (b.b - a.b) * r,
            a.a + (b.a - a.a) * r
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

    // ---- base colors ----
    readonly property color accent: root._color(accentHex, 1.0)
    readonly property color accentSoft: root._color(accentHex, 0.85)
    readonly property color text: root._color(textHex, 1.0)
    readonly property color textActive: root._color(textActiveHex, 1.0)
    readonly property color scrim: Qt.rgba(0, 0, 0, 0.32)

    // Real end-4/caelestia panels stay monochrome at rest and reveal color
    // only on interaction (hover/press) -- a row of icons that are all
    // pre-tinted different colors reads busier, not more designed. This is
    // used only for the one genuinely destructive action (power off).
    readonly property color dangerTint: Qt.rgba(0.95, 0.4, 0.42, 1)
    function tintBg(tint, hovered) { return hovered ? root.mix(layer1, tint, 0.28) : layer1; }
    function tintBorder(tint, hovered) { return hovered ? Qt.rgba(tint.r, tint.g, tint.b, 0.5) : borderIdle; }

    // ---- layered surfaces: each layer reads as a step "closer to the
    // viewer" than the one under it, exactly like a real card stack rather
    // than everything sharing one flat tone. panel < layer1 (cards) <
    // layer2 (nested rows/hovers) < layer3 (pressed/selected). ----
    readonly property color panel: root._color(glassBgHex, opacityActive)
    readonly property color layer1: root.mix(root._color(glassBgActiveHex, opacityIdle), root._color(glassBgHex, 1), 0.15)
    readonly property color layer1Hover: root.mix(layer1, textActive, 0.08)
    readonly property color layer1Active: root.mix(layer1, textActive, 0.14)
    readonly property color layer2: root.mix(layer1, textActive, 0.05)
    readonly property color layer2Hover: root.mix(layer1, textActive, 0.12)
    readonly property color layer2Active: root.mix(layer1, textActive, 0.18)
    // Raw glass_border can be any hue/opacity the user picks (including a
    // fully-opaque, fully-saturated one) -- rendered as-is on every nested
    // card, row, and chip that used to reach for it, that reads as a
    // wireframe of colored outlines rather than glass. Real glass edges are
    // a whisper: mostly neutral (blended toward the foreground color, not
    // the raw hue) and capped well under full strength no matter how high
    // the opacity sliders are turned up. The sliders still matter -- they
    // move you across this capped range -- they just can't leave it.
    readonly property color borderTint: root.mix(root._color(glassBorderHex, 1.0), textActive, 0.6)
    readonly property color border: Qt.rgba(borderTint.r, borderTint.g, borderTint.b, Math.min(borderOpacityActive, 0.22))
    readonly property color borderIdle: Qt.rgba(borderTint.r, borderTint.g, borderTint.b, Math.min(borderOpacityIdle, 0.06))

    // Old flat names kept as aliases so existing call sites keep working;
    // new code should reach for the layer* tokens above instead.
    readonly property color bg: panel
    readonly property color bgIdle: layer1
    readonly property color active: layer2

    // ---- rounding scale: caelestia-dots/shell's own RoundingTokens are
    // fixed absolute values (config/tokens.hpp: extraSmall 4, small 8,
    // medium 12, large 16, extraLarge 28), not a single radius knob
    // stretched by ratios -- a real type-scale, not an approximation of
    // one. `radius` still works as a scale multiplier around that real
    // scale (default 12 = exactly a 1.0x multiplier, so out of the box
    // this matches their numbers exactly; turning the slider scales all
    // five steps together rather than picking one flat value). ----
    readonly property real radius: root._num("radius", 12)
    readonly property real roundingScale: radius / 12
    readonly property real roundingXs: Math.max(2, Math.round(4 * roundingScale))
    readonly property real roundingSm: Math.round(8 * roundingScale)
    readonly property real roundingMd: Math.round(12 * roundingScale)
    readonly property real roundingLg: Math.round(16 * roundingScale)
    readonly property real roundingXl: Math.round(28 * roundingScale)
    readonly property real roundingFull: 9999
    // Old name kept as an alias (small elements: chips, entries, inner rows).
    readonly property real entryRadius: roundingSm

    // Same story for spacing/padding: caelestia's SpacingTokens/
    // PaddingTokens are the identical fixed 4/8/12/16/28 scale as
    // rounding, scaled here by ui_density the same way.
    readonly property real density: root._num("ui_density", 1.0)
    readonly property real padXs: Math.round(4 * density)
    readonly property real padSm: Math.round(8 * density)
    readonly property real padMd: Math.round(12 * density)
    readonly property real padLg: Math.round(16 * density)
    readonly property real padXl: Math.round(28 * density)

    // FontSizeTokens: small 11, normal 13, larger 15, large 18, extraLarge
    // 28 -- a real type scale instead of picking pixel sizes ad hoc per
    // Text element, which is most of what made spacing/hierarchy feel
    // arbitrary rather than designed.
    readonly property int fontSizeSmall: 11
    readonly property int fontSizeNormal: 13
    readonly property int fontSizeLarger: 15
    readonly property int fontSizeLarge: 18
    readonly property int fontSizeExtraLarge: 28

    // ---- motion: Material 3 Expressive-style overshoot curves instead of
    // flat ease-out, so a reveal/settle genuinely feels alive rather than
    // just linear-with-rounded-corners. animMs is still your own slider;
    // these curves scale their duration off it so "snappier" stays snappier
    // across all of them. ----
    readonly property int animMs: Math.max(1, root._num("anim_duration_ms", 150))
    readonly property int easingType: Easing.BezierSpline
    readonly property var curveExpressiveFast: [0.42, 1.67, 0.21, 0.90, 1, 1]
    readonly property var curveExpressiveDefault: [0.38, 1.21, 0.22, 1.00, 1, 1]
    readonly property var curveEmphasizedDecel: [0.05, 0.7, 0.1, 1, 1, 1]
    readonly property var curveStandard: [0.2, 0, 0, 1, 1, 1]
    readonly property int durationFast: Math.round(animMs * 1.0)
    readonly property int durationDefault: Math.round(animMs * 2.2)
    readonly property int durationEnter: Math.round(animMs * 2.8)

    // ---- elevation: ported directly from caelestia-dots/shell's own
    // components/effects/Elevation.qml -- a real Material 3 discrete
    // elevation scale (dp = [0, 1, 3, 6, 8, 12] for levels 0-5), not one
    // flat blur radius reused everywhere. blur and (negative) spread are
    // both derived from dp with the exact same formulas they use, which is
    // why the result is a tight, soft lift rather than a big blurry glow --
    // real shadows tuck in at the edges instead of spreading outward.
    // Level 1 = a resting card, level 2-3 = a floating panel, use higher
    // for anything that should read as "closer to the viewer." ----
    readonly property real shadowIntensity: root._num("shadow_intensity", 1.0)
    readonly property var elevationDp: [0, 1, 3, 6, 8, 12]
    function elevationBlur(level) {
        const dp = elevationDp[level] * shadowIntensity;
        return Math.pow(dp * 5, 0.7);
    }
    function elevationSpread(level) {
        const dp = elevationDp[level] * shadowIntensity;
        return -dp * 0.3 + Math.pow(dp * 0.1, 2);
    }
    function elevationOffsetY(level) {
        return (elevationDp[level] * shadowIntensity) / 2;
    }
    // Shadows are tinted very slightly toward the border hue instead of
    // flat black, matching caelestia's own Colours.palette.m3shadow role
    // (a real generated color, not literal black) without needing this
    // rice's own Material You palette generator.
    readonly property color shadowColor: Qt.rgba(
        borderTint.r * 0.4, borderTint.g * 0.4, borderTint.b * 0.4, 0.5)

    readonly property string fontFamily: root._str("font_family", "sans-serif")
    readonly property string wallpaper: root._str("wallpaper", "")
}
