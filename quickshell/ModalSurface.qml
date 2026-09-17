import QtQuick
import QtQuick.Effects

// The shell's "standalone modal" surface -- a real OS window (a password
// prompt, an add-item dialog, a confirmation), as opposed to Card.qml's
// Level-2 surface (content grouped inside an already-open panel) or
// ShellIsland.qml's morphing panel (a control that IS the surface it
// expands into). Before this, four such windows (LockScreen's unlock card,
// WifiPasswordDialog, this dialog's own addDialogSurface, OSD) each
// independently hand-wrote the identical RectangularShadow + Rectangle{
// radius: Theme.roundingXl; border.width: 1; border.color: Theme.border }
// pair -- three of the four had already converged on elevation level 3 by
// coincidence, never by a shared name. This is that pairing, named, so a
// future modal surface has something to reach for instead of a 5th copy.
//
// Root is a plain Item, not a Rectangle, for the same reason as Card.qml:
// the shadow has to be a true sibling painted BEFORE the visible surface,
// not a child nested inside it (a shadow child anchored to its own
// rectangle paints on top of that rectangle's fill, not behind it).
Item {
    id: root
    default property alias data: surface.data
    property alias color: surface.color
    property alias radius: surface.radius
    property int elevation: Theme.elevationModal

    RectangularShadow {
        anchors.fill: surface
        radius: surface.radius
        color: Theme.shadowColor
        blur: Theme.elevationBlur(root.elevation)
        spread: Theme.elevationSpread(root.elevation)
        offset.y: Theme.elevationOffsetY(root.elevation)
    }

    Rectangle {
        id: surface
        anchors.fill: parent
        radius: Theme.roundingXl
        color: Theme.bg
        border.width: Theme.borderWidth
        border.color: Theme.border
        clip: true

        // Same top-edge light catch as Card.qml, at the outer-radius scale
        // instead of the inner one -- the two surfaces are meant to read as
        // one material family (a modal is this shell's Level-1 register,
        // same as the panel itself), not as an unrelated floating window
        // that happens to share a background color.
        Rectangle {
            anchors.top: parent.top
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.leftMargin: surface.radius
            anchors.rightMargin: surface.radius
            height: 1
            color: Theme.surfaceHighlight
        }
    }
}
