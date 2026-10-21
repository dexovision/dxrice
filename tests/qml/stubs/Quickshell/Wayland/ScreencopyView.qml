import QtQuick

// Test stub. The real ScreencopyView shows a live capture of a window
// (Hyprland toplevel export); this paints a stand-in app window from the
// fake toplevel the Hyprland stub hands out -- the same painting the test
// scene uses for the "real" windows, so before/after renders compare like
// with like. A toplevel with `noContent: true` models a window the
// compositor declines to capture (one panned off screen).
//
// It follows the real one's lifecycle (quickshell src/wayland/screencopy/
// view.cpp): setting a source makes a capture context and asks for a frame;
// a frame arriving sets hasContent; a refused copy stops the context and
// clears hasContent -- the last picture is gone -- and captureFrame() then
// does nothing until a source is set again. A live view asks again and
// again; a non-live one keeps its frame until asked.
Item {
    id: root
    property var captureSource: null
    property bool live: false
    property bool paintCursor: false
    property size constraintSize
    property bool hasContent: false
    property bool _context: false
    // what the last captured frame showed (a fake window's colour and title)
    property var _frame: null
    readonly property size sourceSize: Qt.size(root.width, root.height)
    function _attempt() {
        if (!root._context) return;
        const s = root.captureSource;
        if (!s || s.noContent) { root._context = false; root.hasContent = false; root._frame = null; return; }
        root._frame = { color: s.color, title: s.title || "", logicalWidth: s.logicalWidth };
        root.hasContent = true;
    }
    onCaptureSourceChanged: { root.hasContent = false; root._frame = null; root._context = !!root.captureSource; root._attempt(); }
    Component.onCompleted: { root._context = !!root.captureSource; root._attempt(); }
    function captureFrame() { root._attempt(); }
    Timer { running: root.live && root._context; interval: 100; repeat: true; onTriggered: root._attempt() }
    visible: root.hasContent
    FakeAppWindow {
        anchors.fill: parent
        fill: root._frame && root._frame.color ? root._frame.color : "#2b3140"
        title: root._frame ? root._frame.title : ""
        // the picture of a window scales with it, like a real capture
        logicalWidth: root._frame && root._frame.logicalWidth ? root._frame.logicalWidth : root.width
    }
}
