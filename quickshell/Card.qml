import QtQuick

// The QML equivalent of dxrice_gtk_widgets.make_card(): a rounded glass
// panel every section sits inside. Content goes in `contentItem`'s
// implicit children (this is a Column by default so rows just stack).
Rectangle {
    id: root
    default property alias data: column.data
    property alias spacing: column.spacing
    // Set true while a drag-and-drop reorder is hovering over this card
    // (see TaskbarManager.qml's DropArea) for a dashed accent highlight.
    property bool highlighted: false

    radius: Theme.entryRadius
    color: Theme.bgIdle
    border.width: root.highlighted ? 2 : 1
    border.color: root.highlighted ? Theme.accent : Theme.borderIdle
    implicitWidth: column.implicitWidth + Theme.padMd * 2
    implicitHeight: column.implicitHeight + Theme.padMd * 2

    Behavior on border.color { ColorAnimation { duration: Theme.animMs } }

    Column {
        id: column
        x: Theme.padMd
        y: Theme.padMd
        width: parent.width - Theme.padMd * 2
        spacing: Theme.padSm
    }
}
