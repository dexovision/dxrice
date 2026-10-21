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
    // a real window's root item; here the stub itself is the surface's content
    readonly property Item contentItem: root
    component Margins: QtObject { property real top: 0; property real bottom: 0; property real left: 0; property real right: 0 }
    property Margins margins: Margins {}
    // OSD-style single-edge panels are centred by the compositor on the free axis.
    x: implicitWidth < Harness.screenWidth ? (Harness.screenWidth - implicitWidth) / 2 : 0
    // anchored to the bottom edge only (the harness sets this from the
    // stripped `anchors {..}` line): the compositor puts it at the bottom
    property bool anchorBottom: false
    y: anchorBottom ? Harness.screenHeight - height - margins.bottom : margins.top
    // Lets the harness locate every shell surface without knowing ids.
    readonly property bool isShellSurface: true
    implicitWidth: Harness.screenWidth
    width: implicitWidth
    height: implicitHeight

    // Hyprland fades every layer-shell surface in when it maps (animation leaf
    // fadeLayersIn, inherited from `fade`: the ramp seen on a real recording of
    // the overview). Off unless a scene sets the bridge's layer_fade_ms, so only
    // the tests that reproduce it see it: the whole surface, however opaque the
    // shell paints it, is composited at this alpha over the real desktop.
    property real layerAlpha: 1
    opacity: layerAlpha
    // the compositor blends the flattened surface, not each of its items
    layer.enabled: layerAlpha < 1
    onVisibleChanged: {
        if (visible && Harness.layerFadeMs > 0) layerFadeIn.restart();
        else if (!visible) { layerFadeIn.stop(); layerAlpha = 1; }
    }
    NumberAnimation {
        id: layerFadeIn
        target: root; property: "layerAlpha"; from: 0; to: 1
        duration: Harness.layerFadeMs
        easing.type: Easing.BezierSpline; easing.bezierCurve: [0.15, 0.0, 0.1, 1.0, 1, 1]
    }
}
