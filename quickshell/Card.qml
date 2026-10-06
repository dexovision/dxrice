import QtQuick

// The shell's Level-2 surface: content grouped inside an open panel. The
// panel itself (ShellIsland.qml) is Level 1 -- the outer arc
// (ShellSurface.radius), the shell's elevation and its strongest edge. A
// card is told apart from it by tone (Theme.cardTone), a visibly smaller
// corner (ShellSurface.cardRadius), tighter padding (ShellSurface.cardPad)
// and only a whisper of an edge (Theme.cardBorder) -- not by a second
// shadow or a strong outline, which made every group compete with the panel
// hosting it. Level 3 (secondary information) gets no surface at all: plain
// text on the panel. Content goes in the card's default children (a Column,
// so rows just stack).
//
// Root is a plain Item rather than the Rectangle itself so a title label and
// the content column can be laid out against shared padding.
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
    // Height the title strip takes above the content column (0 untitled),
    // for callers that size a fixed viewport inside an explicitly-sized card.
    readonly property real titleHeight: root.title.length > 0 ? titleLabel.implicitHeight + Theme.padXs : 0

    implicitWidth: column.implicitWidth + root.padding * 2
    implicitHeight: root.titleHeight + column.implicitHeight + root.padding * 2

    // No drop shadow. A card is content grouped INSIDE a panel, not an
    // object floating above it: the panel (Level 1) carries the shell's
    // elevation; a second, smaller shadow under every card only muddied the
    // translucent panel behind it. Level 2 is told apart by tone (cardTone),
    // the smaller corner, and a hairline far quieter than before -- the old
    // 22%-alpha border made card outlines the loudest lines on every panel.
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
        border.color: root.highlighted ? Theme.accent : Theme.cardBorder
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
