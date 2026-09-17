import QtQuick
import QtQuick.Effects

// A rounded, borderless surface with a soft, barely-there drop shadow for
// separation -- end-4/caelestia-style cards are flat fills at a slightly
// different tone than the panel behind them, not bordered boxes. Content
// goes in `contentItem`'s implicit children (this is a Column by default
// so rows just stack).
//
// This is the shell's Level-2 surface: the panel itself (ShellIsland.qml) is
// Level 1, using ShellSurface.radius; this uses the deliberately smaller
// ShellSurface.cardRadius, so a viewer can tell "content grouped inside the
// panel" from "the panel itself" by the corner alone, not just by a color
// shift. Padding likewise comes from ShellSurface.cardPad, not the panel's
// own Theme.padLg, for the same reason: a card should read as visibly
// tighter than the surface hosting it.
//
// Root is a plain Item, not a Rectangle: the shadow has to be a true
// sibling painted *before* the visible surface, not a child nested inside
// it (a shadow child anchored to its own rectangle paints on top of that
// rectangle's fill, not behind it -- parent fills always paint under their
// children regardless of z).
Item {
    id: root
    default property alias data: column.data
    property alias spacing: column.spacing
    // A quiet label baked into the card itself, rather than a separate
    // Text sibling above it -- so "this is a group" and "this group is
    // called Audio" are the same visual object, not two things a caller
    // has to remember to keep next to each other.
    property string title: ""
    // Set true while a drag-and-drop reorder is hovering over this card
    // (see TaskbarManager.qml's DropArea) for an accent-colored edge.
    property bool highlighted: false

    property alias color: surface.color
    property alias radius: surface.radius
    // Overridable per instance (default ShellSurface.cardPad, same as
    // always) for the rare case where a card's own content is dense enough
    // to fill nearly the whole surface edge-to-edge -- Theme's settings
    // lists (ColorList/SliderList rows) are packed tightly enough that at
    // the standard cardPad, almost no bare card tone was left exposed
    // around them, which is why the card read as "technically a different
    // color" but not "visibly a distinct surface" (confirmed by pixel
    // sampling: a real ~20-unit tone difference that wasn't perceptible
    // because the card's own background barely showed). This does NOT
    // change cardPad itself -- Quick Settings and Taskbar's cards, which
    // already have real breathing room, are untouched.
    property real padding: ShellSurface.cardPad

    implicitWidth: column.implicitWidth + root.padding * 2
    implicitHeight: (root.title.length > 0 ? titleLabel.implicitHeight + Theme.padXs : 0)
        + column.implicitHeight + root.padding * 2

    RectangularShadow {
        anchors.fill: surface
        radius: surface.radius
        color: Theme.shadowColor
        // Restrained on purpose: a strong shadow was making individual
        // cards the loudest thing on the surface, competing with the panel
        // for attention instead of sitting quietly inside it. Definition
        // now comes mainly from the border + the closer-to-panel fill
        // below (Theme.cardTone), with the shadow only adding a whisper of
        // separation, not a spotlight.
        blur: Theme.elevationBlur(1)
        spread: Theme.elevationSpread(1)
        offset.y: Theme.elevationOffsetY(1)
    }

    Rectangle {
        id: surface
        anchors.fill: parent
        radius: ShellSurface.cardRadius
        // Theme.cardTone, not Theme.layer1: sits closer to the panel's own
        // tone on purpose (see Theme.qml's comment on cardTone) so the
        // PANEL stays the visually dominant surface and cards read as
        // content grouped inside it, not as competing blocks of similar
        // visual weight. The border below is what still makes a card's
        // boundary legible without needing a loud fill to do it.
        color: Theme.cardTone
        border.width: root.highlighted ? 2 : Theme.borderWidth
        border.color: root.highlighted ? Theme.accent : Theme.borderFaint
        clip: true

        Behavior on border.width {
            NumberAnimation { duration: Theme.durationFast; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveStandard }
        }
        Behavior on border.color {
            ColorAnimation { duration: Theme.durationFast; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveStandard }
        }

        // The top-edge light catch that makes this read as a raised object
        // rather than a flat fill -- see Theme.surfaceHighlight. Inset from
        // both sides by the card's own radius so it never pokes past the
        // rounded corners, and clipped by `surface` above for the same
        // reason at the very top corners specifically.
        Rectangle {
            anchors.top: parent.top
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.leftMargin: surface.radius
            anchors.rightMargin: surface.radius
            height: 1
            color: Theme.surfaceHighlight
        }

        Text {
            id: titleLabel
            visible: root.title.length > 0
            x: root.padding
            y: root.padding
            text: root.title
            color: Theme.text
            opacity: Theme.opacityMuted
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSizeSmall
            font.letterSpacing: 0.5
        }

        Column {
            id: column
            x: root.padding
            y: root.title.length > 0 ? titleLabel.y + titleLabel.implicitHeight + Theme.padXs : root.padding
            width: parent.width - root.padding * 2
            spacing: Theme.padMd
        }
    }
}
