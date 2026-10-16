import QtQuick
import Quickshell.Hyprland
import Quickshell.Wayland
import Harness

// A fake monitor for the desktop overview: the wallpaper, the workspace's
// "real" application windows at their true positions (clipped by the
// monitor, as on screen), and the REAL shell.qml on top. The overview's
// window pictures (ScreencopyView stub) paint the same FakeAppWindow as the
// windows here, so a render with the overview closed and one with it open
// compare like with like.
Item {
    id: root
    width: Harness.screenWidth
    height: Harness.screenHeight
    clip: true

    // [{x, y, w, h, color, title}] relative to the monitor, bottom first
    property var fakeWindows: []
    property string wallpaper: ""

    Rectangle { anchors.fill: parent; color: "#0d0f13" }
    Image {
        anchors.fill: parent
        source: root.wallpaper ? "file://" + root.wallpaper : ""
        fillMode: Image.PreserveAspectCrop
    }
    Repeater {
        model: root.fakeWindows
        delegate: FakeAppWindow {
            required property var modelData
            x: modelData.x; y: modelData.y; width: modelData.w; height: modelData.h
            fill: modelData.color; title: modelData.title
        }
    }

    Loader { id: shellLoader; anchors.fill: parent; source: "shell.qml" }

    readonly property QtObject panels: PanelManager
    readonly property QtObject theme: Theme
    readonly property QtObject hypr: Hyprland
    function findNamed(name) {
        const stack = [shellLoader];
        while (stack.length) {
            const it = stack.pop();
            if (!it) continue;
            if (it.objectName === name) return it;
            const kids = it.data !== undefined ? it.data : [];
            for (let i = 0; i < kids.length; i++) stack.push(kids[i]);
        }
        return null;
    }
    // every overview tile's on-screen rect, keyed by window address
    function tileRects() {
        const ov = root.findNamed("overview");
        const out = {};
        const stack = [ov];
        while (stack.length) {
            const it = stack.pop();
            if (!it) continue;
            if (it.objectName && it.objectName.indexOf("overviewTile:") === 0) {
                const p = it.mapToItem(root, 0, 0);
                out[it.objectName.substring(13)] = [p.x, p.y, it.width, it.height];
            }
            const kids = it.data !== undefined ? it.data : [];
            for (let i = 0; i < kids.length; i++) stack.push(kids[i]);
        }
        return out;
    }
}
