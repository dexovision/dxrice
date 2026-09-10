import QtQuick
import QtQuick.Effects

// A rounded glass panel with real elevation (a soft drop shadow, not just
// a border) -- this + the bigger rounding scale is most of what was
// missing to stop this looking like a flat settings dialog. Content goes
// in `contentItem`'s implicit children (this is a Column by default so
// rows just stack).
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
    // Set true while a drag-and-drop reorder is hovering over this card
    // (see TaskbarManager.qml's DropArea) for a dashed accent highlight.
    property bool highlighted: false

    property alias color: surface.color
    property alias radius: surface.radius
    property alias border: surface.border

    implicitWidth: column.implicitWidth + Theme.padLg * 2
    implicitHeight: column.implicitHeight + Theme.padLg * 2

    RectangularShadow {
        anchors.fill: surface
        radius: surface.radius
        color: Theme.shadowColor
        blur: Theme.shadowBlurSm
        offset.y: 2
    }

    Rectangle {
        id: surface
        anchors.fill: parent
        radius: Theme.roundingMd
        color: Theme.layer1
        border.width: root.highlighted ? 2 : 1
        border.color: root.highlighted ? Theme.accent : Theme.borderIdle

        Behavior on border.color {
            ColorAnimation { duration: Theme.durationFast; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveStandard }
        }

        Column {
            id: column
            x: Theme.padLg
            y: Theme.padLg
            width: parent.width - Theme.padLg * 2
            spacing: Theme.padMd
        }
    }
}
