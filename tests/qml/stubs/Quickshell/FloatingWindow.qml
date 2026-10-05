import QtQuick
// Test stub: a separate toplevel in reality; an invisible-by-default Item here.
Item {
    property string title: ""
    property color color: "transparent"
    readonly property bool isToplevelWindow: true
    width: implicitWidth
    height: implicitHeight
    visible: false
}
