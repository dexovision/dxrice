import QtQuick

// Test stub. The real ScreencopyView shows a live capture of a window
// (Hyprland toplevel export); this paints a stand-in app window from the
// fake toplevel the Hyprland stub hands out -- the same painting the test
// scene uses for the "real" windows, so before/after renders compare like
// with like. A toplevel with `noContent: true` models a window the
// compositor declines to capture.
Item {
    id: root
    property var captureSource: null
    property bool live: false
    property bool paintCursor: false
    property size constraintSize
    readonly property bool hasContent: root.captureSource !== null && root.captureSource !== undefined
                                       && !root.captureSource.noContent
    readonly property size sourceSize: Qt.size(root.width, root.height)
    function captureFrame() {}
    visible: root.hasContent
    FakeAppWindow {
        anchors.fill: parent
        fill: root.hasContent && root.captureSource.color ? root.captureSource.color : "#2b3140"
        title: root.hasContent ? (root.captureSource.title || "") : ""
        // the picture of a window scales with it, like a real capture
        logicalWidth: root.hasContent && root.captureSource.logicalWidth ? root.captureSource.logicalWidth : root.width
    }
}
