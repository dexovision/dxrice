import QtQuick
import Harness

// Test stub. A real PanelWindow is a separate wlr-layer-shell surface; here
// it is an Item sized like the surface the compositor would give it, so the
// whole desktop composites into one offscreen scene. `anchors {..}` and
// WlrLayershell.* lines are stripped by the harness's source preprocessor
// (see harness.py) since they are not meaningful on an Item.
Item {
    id: root
    property var screen: ({ width: Harness.screenWidth, height: Harness.screenHeight })
    property color color: "transparent"
    property int exclusionMode: 0
    property real exclusiveZone: 0
    property bool aboveWindows: true
    property bool focusable: false
    property var mask: null
    component Margins: QtObject { property real top: 0; property real bottom: 0; property real left: 0; property real right: 0 }
    property Margins margins: Margins {}
    // OSD-style single-edge panels are centred by the compositor on the free axis.
    x: implicitWidth < Harness.screenWidth ? (Harness.screenWidth - implicitWidth) / 2 : 0
    y: margins.top
    // Lets the harness locate every shell surface without knowing ids.
    readonly property bool isShellSurface: true
    implicitWidth: Harness.screenWidth
    width: implicitWidth
    height: implicitHeight
}
