import QtQuick
import Harness
Item {
    id: root
    anchors.fill: parent
    property bool active: false
    property url source
    property Component component: null
    readonly property var item: loader.item
    Loader {
        id: loader
        anchors.fill: parent
        active: root.active
        // Qt 6 no longer resolves a url at assignment; shell.qml's relative
        // "ThemeEditor.qml" is relative to the shell directory.
        source: root.component ? "" : (String(root.source).indexOf(":") >= 0 ? root.source : "file://" + Harness.shellDir + "/" + root.source)
        sourceComponent: root.component
    }
}
