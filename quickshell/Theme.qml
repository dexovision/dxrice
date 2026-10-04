pragma Singleton
import QtQuick
import Quickshell
import Quickshell.Io

// Shared design tokens for every DXrice Quickshell widget. Reads the same
// live theme.json the GTK-era apps used ($XDG_CONFIG_HOME/dxrice/theme.json,
// falling back to ~/.config/dxrice/theme.json -- see Xdg.qml -- seeded from
// <repo>/theme/theme.json on first run by scripts/dxrice_apply_theme.py) so
// this is never a second source of truth -- editing colors still only ever
// happens in one file.
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

    readonly property string path: Xdg.configDir + "/theme.json"

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

    function withAlpha(c, alpha) {
        return Qt.rgba(c.r, c.g, c.b, alpha);
    }

    // Material's "elevation overlay," applied to whatever base hex the
    // active theme preset picked: mix a fixed amount of neutral light gray
    // into the raw color BEFORE it goes translucent. This exists because a
    // near-black panel (alpha or not) composited over an equally near-black
    // backdrop -- a terminal, a dark browser window -- is mathematically
    // indistinguishable no matter how that alpha is tuned: both sides of the
    // blend are dark. Confirmed by measuring the live shell: at glass_bg
    // 0d0d0d (luminance ~13/255) and opacity_active 0.85, the panel's own
    // rendered luminance over a dark backdrop was ~11/255 -- invisible next
    // to controls (buttons, dock icons) sitting right at its own edge. The
    // lift gives every Level-1/Level-2 surface a luminance FLOOR of its own,
    // independent of the backdrop, so the boundary is guaranteed visible
    // without capping translucency or forcing the surface toward opaque
    // black. Mixing toward neutral gray (not white, not the accent) rather
    // than just multiplying up the existing color is also what keeps a
    // colorful blurred backdrop (a green wallpaper) from tinting the panel
    // into green/olive: the lift dilutes whatever hue leaks through, it
    // doesn't add one of its own.
    readonly property color surfaceLift: Qt.rgba(0.82, 0.82, 0.82, 1)
    function surfaceTone(hex, lift) {
        return root.mix(root._color(hex, 1.0), root.surfaceLift, lift);
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

    // ---- opacity tiers for muted/secondary content (icon-and-caption
    // labels, de-emphasized rows) -- distinct from opacityIdle/Active above,
    // which are the user-configurable GLASS opacity sliders. This is a
    // fixed 3-step scale (0.55/0.7/0.85) naming what had become an ad hoc
    // 5-value scale (0.55/0.6/0.65/0.7/0.85) reinvented independently at
    // 30+ call sites for the same handful of "how muted is this" intents.
    readonly property real opacityMuted: 0.55
    readonly property real opacitySecondary: 0.7
    readonly property real opacityFaint: 0.85

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
    // than everything sharing one flat tone. panel (Level 1, the shell
    // surface itself) < layer1 (Level 2, cards) < layer2 (nested
    // rows/hovers) < layer3 (pressed/selected). Both of the first two go
    // through surfaceTone (see its comment above) rather than the raw
    // configured hex, and Level 2's lift (0.20) is deliberately larger than
    // Level 1's (0.10) so raising Level 1's floor can never close the gap
    // between "the shell surface" and "a card sitting on top of it" -- the
    // two levels move together, but Level 2 always ends up the lighter one.
    // Raised from an earlier 0.10/0.20 pass after checking both against a
    // self-contained material test rig (three flat/gradient backdrops in one
    // throwaway window, no live desktop involved): at 0.10 the panel composited
    // to ~28-30/255 over a near-black backdrop, which the rig showed as still
    // barely perceptible -- present in a screenshot, not present to the eye.
    // 0.22/0.32 composites to ~49/255 (panel) and ~70/255 (card) over the same
    // backdrop, a real, checkable edge, while the same rig's light-backdrop and
    // colorful-wallpaper swatches confirmed the panel still doesn't read as an
    // opaque block there.
    readonly property color panelTone: root.surfaceTone(glassBgHex, 0.22)
    readonly property color layer1Tone: root.surfaceTone(glassBgActiveHex, 0.32)
    readonly property color panel: root.withAlpha(panelTone, opacityActive)
    readonly property color layer1: root.mix(root.withAlpha(layer1Tone, opacityIdle), root.withAlpha(panelTone, 1.0), 0.15)
    readonly property color layer1Hover: root.mix(layer1, textActive, 0.08)
    readonly property color layer1Active: root.mix(layer1, textActive, 0.14)
    readonly property color layer2: root.mix(layer1, textActive, 0.05)
    readonly property color layer2Hover: root.mix(layer1, textActive, 0.12)
    readonly property color layer2Active: root.mix(layer1, textActive, 0.18)
    // Card.qml's own fill -- deliberately NOT plain `layer1` (which
    // CalendarPanel.qml's month-nav pill also reads directly, so tuning
    // layer1 itself would shift Calendar's own rendered color, which stays
    // off-limits). Sits roughly halfway between `panel` and `layer1`: a
    // full `layer1` card next to a `panel` background was reading as two
    // competing surfaces of similar visual weight rather than a container
    // and the content grouped inside it -- pulling the card fill closer to
    // the panel's own tone (while keeping a real border for definition,
    // see Card.qml) is what lets the PANEL stay the visually louder,
    // "parent" surface without needing the panel itself to change.
    readonly property color cardTone: root.mix(panel, layer1, 0.45)
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

    // A faint, fixed-opacity border tint independent of the user's own
    // border_opacity_idle/active sliders -- for the handful of places (a
    // slider track's outline, a level-bar's outline) that want a whisper of
    // definition regardless of how those sliders are set, not a decorative
    // edge that should react to them. Three call sites (SliderRow's track,
    // Switch's track, LevelBar's track) had each independently written
    // `Qt.rgba(border.r, border.g, border.b, 0.22|0.25|0.3)` -- three
    // near-identical formulas that had quietly drifted to three different
    // alphas. This is the one shared value they now all reach for.
    readonly property color borderFaint: Qt.rgba(borderTint.r, borderTint.g, borderTint.b, 0.22)
    // The hairline border width used everywhere a `border.width` is drawn --
    // was a bare literal `1` at 15+ call sites with no shared name.
    readonly property real borderWidth: 1
    // A faint white fill for text-input-style rows (the wifi password
    // field, the lock screen's password field, Taskbar's add-shortcut
    // fields) -- was `Qt.rgba(1,1,1,0.06)` copy-pasted identically at every
    // one of those call sites.
    readonly property color inputFill: Qt.rgba(1, 1, 1, 0.06)

    // A thin light catch along the top edge of an elevated surface (a card,
    // a modal) -- the cheap, reliable way to suggest "this is a raised
    // object under a light source" without a real lighting model. Same
    // numeric value as `inputFill` today, but named for a different
    // intent -- an input field's fill and a card's top highlight are
    // different concepts that only coincide by value, not meaning, so they
    // stay two names rather than one reused for both.
    readonly property color surfaceHighlight: Qt.rgba(1, 1, 1, 0.06)

    // A dedicated tone for STRUCTURAL dividers (the seam between a persistent
    // header and the panel content it reveals; the line under Quick Settings'
    // nav strip) -- deliberately NOT `borderIdle`. borderIdle is a decorative
    // hairline whose opacity is the user's own border_opacity_idle slider,
    // which in the live theme is 0.05 -- measured by pixel-sampling an actual
    // rendered seam: panel tone 56, seam pixel 69, a 13-unit difference that
    // doesn't read as a boundary at all, only as a rounding artifact. A seam
    // is communicating shell STRUCTURE (this is where the header ends and
    // content begins), not decorating an edge, so it needs a floor that
    // can't be dialed down to invisible by an unrelated slider. Mixed toward
    // the same neutral `surfaceLift` the panel/card tones use (not toward
    // pure white) so it stays a quiet gray line, not a bright accent border --
    // opaque and a single pixel tall is what keeps "visible" from becoming
    // "heavy."
    readonly property color seam: root.mix(panelTone, root.surfaceLift, 0.26)

    // Old flat names kept as aliases so existing call sites keep working;
    // new code should reach for the layer* tokens above instead.
    readonly property color bg: panel
    readonly property color bgIdle: layer1
    readonly property color active: layer2

    // ---- rounding scale: inner elements (chips, rows, list entries) stay
    // restrained (4/8/12/16, caelestia-dots/shell's own fixed
    // RoundingTokens); the outer floating panel itself gets a real jump to
    // 32 -- a deliberately larger radius so the panel reads as one
    // premium, soft "surface" rather than just a bigger version of its own
    // inner cards. Mixing radically different radii within one component
    // reads as inconsistent; having exactly two registers (inner vs.
    // outer-surface) and reusing them everywhere is what reads as
    // designed. `radius` is still a scale multiplier around these real
    // numbers (default 12 = 1.0x, so out of the box these are exact). ----
    readonly property real radius: root._num("radius", 12)
    readonly property real roundingScale: radius / 12
    readonly property real roundingXs: Math.max(2, Math.round(4 * roundingScale))
    readonly property real roundingSm: Math.round(8 * roundingScale)
    readonly property real roundingMd: Math.round(12 * roundingScale)
    readonly property real roundingLg: Math.round(16 * roundingScale)
    readonly property real roundingXl: Math.round(32 * roundingScale)
    readonly property real roundingFull: 9999
    // Old name kept as an alias (small elements: chips, entries, inner rows).
    readonly property real entryRadius: roundingSm

    // ---- spacing scale: 4/8/12/16/20/24/32 -- micro / icon-text gap /
    // small component padding / normal component padding / section
    // spacing / major spacing / large layout spacing. Every gap, margin,
    // and padding value in this shell should come from one of these seven
    // numbers; a widget picking its own one-off spacing value is exactly
    // what reads as "randomly chosen" rather than "one grid." ----
    readonly property real density: root._num("ui_density", 1.0)
    readonly property real padXs: Math.round(4 * density)
    readonly property real padSm: Math.round(8 * density)
    readonly property real padMd: Math.round(12 * density)
    readonly property real padLg: Math.round(16 * density)
    readonly property real padXl: Math.round(20 * density)
    readonly property real pad2xl: Math.round(24 * density)
    readonly property real pad3xl: Math.round(32 * density)

    // FontSizeTokens: small 11, smaller 12, normal 13, larger 15, large 18,
    // hero 28 -- a real type scale instead of picking pixel sizes ad hoc
    // per Text element, which is most of what made hierarchy feel
    // arbitrary rather than designed. "smaller" sits between small and
    // normal (caelestia's own naming) -- it's the single most-reused size
    // for secondary/metadata text.
    readonly property int fontSizeSmall: 11
    readonly property int fontSizeSmaller: 12
    readonly property int fontSizeNormal: 13
    readonly property int fontSizeLarger: 15
    readonly property int fontSizeLarge: 18
    readonly property int fontSizeExtraLarge: 28
    // Completes the scale at both ends. `fontSizeMuted` is the one home
    // for what `fontSizeSmall`(11) and `fontSizeSmaller`(12) had quietly
    // become -- the same "secondary/metadata caption" role split near-
    // randomly across dozens of call sites between two adjacent sizes with
    // no rule for which one a given spot got. Both originals stay defined
    // (existing call sites keep working); new/migrated call sites reach for
    // `fontSizeMuted` instead. `fontSizeDisplay` is a real "hero number"
    // tier (a big stat/readout, e.g. Quick Settings' Performance cards) --
    // there was no token above `fontSizeExtraLarge`(28) at all, so every
    // "big number" spot picked its own bare size (40 twice, independently).
    readonly property int fontSizeMuted: 12
    readonly property int fontSizeDisplay: 40
    // The single biggest text in the shell (the lock screen's clock) is a
    // materially different, bigger register than a card's hero stat -- kept
    // as its own named tier rather than forced onto fontSizeDisplay.
    readonly property int fontSizeHero: 72

    // ---- icon scale: IconButton's glyph derives from `size * 0.45`, and
    // every call site picked its own `size` -- 9 distinct values (24-42)
    // for what reads as 3 real tiers once you squint at them side by side.
    // These are that scale, named; IconButton's own default stays as-is.
    readonly property real iconSm: 26   // compact row icons (list actions, nav arrows)
    readonly property real iconMd: 32   // medium controls (secondary transport buttons)
    readonly property real iconLg: 40   // hero/primary actions (power row, play/pause)

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
    // The elevation level every standalone "modal surface" (a password
    // prompt, a confirmation dialog, an add-item window) already converged
    // on by convention, independently, at 3 of 4 such surfaces -- named here
    // so the 4th agrees on purpose rather than by coincidence, and so a
    // future one doesn't have to guess.
    readonly property int elevationModal: 3
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
