pragma Singleton
import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Hyprland

// How far the focused workspace's infinite desktop has been panned, as the
// pan daemon reports it (scripts/dxrice_viewport.py writes
// $XDG_RUNTIME_DIR/dxrice/viewport.json while you pan). World-attached
// desktop widgets add this to where they sit, so they travel with the
// windows; screen-fixed UI never reads it.
QtObject {
    id: root
    readonly property string path: (Quickshell.env("XDG_RUNTIME_DIR") || "/tmp") + "/dxrice/viewport.json"
    property var offsets: ({})
    readonly property var workspace: {
        const list = Hyprland.workspaces ? Hyprland.workspaces.values : [];
        for (let i = 0; i < list.length; i++) if (list[i].focused) return list[i].id;
        return null;
    }
    readonly property var offset: root.workspace !== null && root.offsets[String(root.workspace)] ? root.offsets[String(root.workspace)] : [0, 0]
    readonly property real x: Number(root.offset[0]) || 0
    readonly property real y: Number(root.offset[1]) || 0

    property FileView file: FileView {
        path: root.path
        watchChanges: true
        printErrors: false
        onFileChanged: this.reload()
        onLoaded: {
            try { root.offsets = JSON.parse(this.text()).offsets || {}; }
            catch (e) { /* half-written or gone: keep the last good one */ }
        }
    }
}
