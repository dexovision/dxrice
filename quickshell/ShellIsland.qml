import QtQuick
import QtQuick.Effects

// One surface that changes shape -- the control and the panel it summons are
// the same object, not two.
//
// This is the clock. It is also the calendar. Collapsed it is a pill the
// width of the time; expanded it is the calendar surface. There is no second
// rectangle anywhere in the transition -- the same surface widens, deepens,
// and relaxes its corner radius.
//
// Earlier versions of this file cross-faded the collapsed content OUT and a
// completely different panel header IN (a "Quick Settings" title replacing
// the status icons, a "September 2026" title replacing the clock). The SHAPE
// was one continuous object; the CONTENT was not, and that is what read as
// "capsule, then a separate panel" even once the geometry was pixel-correct.
// A viewer identifies a transformation by what stays recognizable through it,
// not by the outline alone.
//
// So now the collapsed content NEVER disappears. `controlHolder` stays fully
// opaque and pinned to the origin edge for the entire time the island is
// open -- it IS the panel's header, not a thing the header politely waits
// its turn behind. The clock keeps showing the time at the top of the
// calendar; the status icons keep showing at the top of Quick Settings; the
// dock's own shortcut row keeps showing at the bottom of Taskbar (its origin
// edge is the bottom, so its header-equivalent sits there instead of the
// top). The panel's own content is laid out in the space that remains,
// revealed alongside it rather than underneath it.
//
// The parent positions the island with anchors that match `pinX`/`pinY`, so
// the growth direction falls out of the layout rather than being animated:
// a right-anchored island grows leftward because its right edge is pinned by
// the anchor, and a bottom-anchored one grows upward for the same reason.
Item {
    id: root

    property bool expanded: false
    signal closeRequested()

    property real collapsedWidth: 100
    property real collapsedHeight: 32
    property real expandedWidth: 320
    property real expandedHeight: 360

    // Which edge stays put as the surface grows, and which edge the
    // persistent control sticks to -- for a bottom-pinned island that is the
    // BOTTOM, matching where its collapsed self already lives, not the top.
    property string pinX: "center"   // "center" | "left" | "right"
    property string pinY: "top"      // "top" | "bottom"

    // The shell's one corner arc (see ShellSurface.qml). Not a per-surface
    // choice: the same value is used by the collapsed capsule, the dock and
    // every expanded panel, so the corner is literally invariant through a
    // morph rather than easing between two different roundings.
    property real maxRadius: ShellSurface.radius
    property color surfaceColor: Theme.panel
    property int elevation: 3

    // Vertical centre of the close button, in surface coordinates. Defaults
    // to the centre of the persistent header for top-pinned islands (the X
    // sits on the same line as the clock/status capsule); a bottom-pinned
    // island's own header is the TOP row of its panel content instead, so
    // the host passes that row's centre (Dock.qml, from TaskbarManager).
    property real closeCenterY: collapsedHeight / 2

    // Constructed on first expand and torn down once fully collapsed again,
    // so an unopened panel costs nothing (the old LazyLoader behaviour, kept).
    property Component panel: null

    default property alias controlContent: controlHolder.data

    // The hosted panel, once it exists -- lets the parent size the expanded
    // surface from the panel's own content instead of a guessed constant.
    readonly property alias panelItem: panelLoader.item

    function sub(p, from, to) {
        return Math.max(0, Math.min(1, (p - from) / (to - from)));
    }

    // ONE animated value drives the whole transition -- everything else
    // (size, opacity, shadow) is a plain function of it, so nothing can drift
    // out of sync with anything else. Height leads, width follows a beat
    // later (pH's range starts at 0.18 not 0), so the surface visibly
    // drops/rises out of its origin before it widens, rather than inflating
    // on both axes identically at once.
    property real morph: expanded ? 1 : 0
    Behavior on morph {
        NumberAnimation {
            duration: Theme.durationEnter
            easing.type: Theme.easingType
            easing.bezierCurve: Theme.curveStandard
        }
    }
    readonly property real pV: morph
    readonly property real pH: sub(morph, 0.18, 1.0)

    property real surfaceW: collapsedWidth + (expandedWidth - collapsedWidth) * pH
    property real surfaceH: collapsedHeight + (expandedHeight - collapsedHeight) * pV

    width: surfaceW
    height: surfaceH

    // Keeps the panel constructed through the close animation, then drops it.
    // A plain Timer with no dependency on any animated value -- see git
    // history/PR notes if this ever gets rewired to depend on `morph`
    // instead: that exact mistake once produced a genuine binding cycle
    // (Qt logged "Binding loop detected for property morph") that pegged the
    // process at 60% CPU, because the panel's creation would depend on
    // morph, which depended on the panel's own reported content size.
    property bool _keepAlive: false
    onExpandedChanged: {
        if (expanded) {
            // Stopped, not left to fire stale: without this, closing then
            // reopening inside the same durationEnter+40 window leaves a
            // pending collapseTimer from the close still counting down: it
            // would flip _keepAlive back to false while the panel is open
            // again. That was never an observable bug -- panelLoader.active
            // is `expanded || _keepAlive`, so `expanded` alone keeps it alive
            // regardless -- but leaving the timer running relies on that OR
            // to silently absorb a stale event instead of the intent (one
            // open, one matching close) being explicit.
            collapseTimer.stop();
            root._keepAlive = true;
        } else {
            collapseTimer.start();
        }
    }
    Timer {
        id: collapseTimer
        interval: Theme.durationEnter + 40
        onTriggered: root._keepAlive = false
    }

    RectangularShadow {
        anchors.fill: surface
        radius: surface.radius
        color: Theme.shadowColor
        blur: Theme.elevationBlur(root.elevation)
        spread: Theme.elevationSpread(root.elevation)
        offset.y: (root.pinY === "bottom" ? -1 : 1) * Theme.elevationOffsetY(root.elevation)
        opacity: 0.55 + 0.45 * root.morph
    }

    Rectangle {
        id: surface
        anchors.fill: parent
        // A pill when it is control-sized and a panel when it is panel-sized,
        // with no radius animation of its own: at 32px tall half the height is
        // 16, at 360 tall it clamps to the panel radius. The shape is a
        // consequence of the size, so it can never lag behind the morph.
        //
        // But that formula only ever applies to the FAR corners now (the two
        // away from the origin control). The two corners on the origin edge
        // -- the edge the collapsed pill's own header sits flush against --
        // are pinned to exactly root.collapsedHeight/2 permanently, at every
        // morph value including 1. That is deliberately never the panel's
        // own radius: a viewer can see that the header edge is still built
        // out of the same pill it started as, even at full size, which is
        // what makes the panel read as a literal continuation of the control
        // rather than a new shape that merely started near it.
        readonly property real originRadius: Math.min(root.collapsedHeight / 2, width / 2)
        radius: Math.min(root.maxRadius, height / 2, width / 2)
        topLeftRadius: root.pinY === "top" ? originRadius : radius
        topRightRadius: root.pinY === "top" ? originRadius : radius
        bottomLeftRadius: root.pinY === "bottom" ? originRadius : radius
        bottomRightRadius: root.pinY === "bottom" ? originRadius : radius
        color: root.surfaceColor
        border.width: 1
        border.color: Theme.borderIdle
        clip: true

        function pinnedX(w) {
            if (root.pinX === "left") return 0;
            if (root.pinX === "right") return surface.width - w;
            return (surface.width - w) / 2;
        }

        // ---- the persistent header: the collapsed control itself ----
        // Always fully opaque, pinned to whichever edge is the origin, at its
        // natural collapsed size. This never fades and never gets swapped for
        // something else -- it is the one piece of content that is visibly
        // the SAME THING before, during and after the transition, which is
        // what makes the rest of the surface read as having grown out of it
        // rather than having appeared next to it.
        Item {
            id: controlHolder
            width: root.collapsedWidth
            height: root.collapsedHeight
            // Right-pinned islands (the status cluster) collapse with their
            // content already hugging the surface's right edge -- exactly
            // where the close button (below) also lives once expanded. Left
            // uncorrected the two sit on top of each other once the panel
            // opens (confirmed by looking at a screenshot: the volume
            // percentage and the close button visibly overlapped). Nudging
            // the header left, only once there is a close button to make
            // room for, keeps the collapsed capsule untouched (morph is 0,
            // so no shift) and only steps aside once one actually appears.
            x: surface.pinnedX(width) - (root.pinX === "right" ? root.sub(root.morph, 0.3, 0.7) * 34 : 0)
            y: root.pinY === "bottom" ? surface.height - height : 0
        }

        // ---- the seam: a literal line between the persistent header and
        // the content it reveals ----
        // Without this, "clock, gap, calendar body" reads as one continuous
        // surface with nothing marking where the persistent piece ends and
        // the new content begins -- the eye has to infer the boundary from
        // spacing alone. One hairline removes the ambiguity: it exists only
        // once there is a boundary to draw (faded in well after the header
        // has separated from the content, never visible on the collapsed
        // pill, which has no seam to show), and it tracks the header's own
        // edge exactly rather than a fixed offset, so it stays glued to
        // controlHolder's boundary through the whole morph.
        Rectangle {
            id: seam
            width: root.expandedWidth
            height: 1
            x: surface.pinnedX(width)
            y: root.pinY === "bottom" ? (surface.height - root.collapsedHeight) : root.collapsedHeight
            color: Theme.seam
            opacity: root.sub(root.morph, 0.5, 0.85)
            visible: opacity > 0.01
        }

        // A small close affordance, fading in once the panel is meaningfully
        // open -- the one bit of chrome every expanded island needs that its
        // collapsed self doesn't. Always the same corner (top-right of the
        // SURFACE, not of the header) regardless of which edge the island
        // grows from, so every panel in the shell closes the same way.
        CloseButton {
            id: closeButton
            x: surface.width - width - 8
            // Always the top-right corner of the SURFACE regardless of pinY,
            // so every panel closes from the same corner; vertically centred
            // on that panel's own header line (closeCenterY) rather than a
            // fixed offset, which sat 1px low on the 36px capsules and ~10px
            // high against Taskbar's taller header row.
            y: Math.round(root.closeCenterY - height / 2)
            opacity: root.sub(root.morph, 0.35, 0.7)
            visible: opacity > 0.01
            onClicked: root.closeRequested()
        }

        // ---- the panel's own content, laid out in whatever space remains
        // once the persistent header's edge is excluded ----
        //
        // Deliberately no opacity fade here any more. `surface.clip: true`
        // already clips this Loader to the surface's OWN live, growing
        // bounds -- so as the surface expands, more of this fixed-position,
        // fixed-size, always-fully-opaque content is progressively exposed,
        // like a blind lifting. A fade layered on top of that was fighting
        // it: the surface would grow (a shape unfolding) while its content
        // simultaneously faded in (a cross-dissolve), two different visual
        // grammars running at once, which is a good part of why this kept
        // reading as "a window opens and fades in" instead of "the surface
        // physically unfolds to reveal what was inside it". A pure clip
        // reveal has no first-frame flash to worry about either -- there is
        // nothing to draw until the surface has grown enough for the clip
        // to expose it.
        Loader {
            id: panelLoader
            active: root.expanded || root._keepAlive
            width: root.expandedWidth
            height: root.expandedHeight - root.collapsedHeight
            x: surface.pinnedX(width)
            y: root.pinY === "bottom" ? 0 : root.collapsedHeight
            sourceComponent: root.panel
        }
    }
}
