import QtQuick
import QtQuick.Effects
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import "LauncherSearch.js" as Search

// The application launcher (SUPER+R, or `qs ipc call launcher toggle`).
//
// A full-screen overlay that is mostly empty: a dim, and one panel that
// rises into place with the search field on top and the best matches under
// it. Apps come from the same .desktop listing the Taskbar manager uses;
// matches are ranked by how the name matches and then by how often you
// launch them (scripts/dxrice_launcher_history.py). Never more than eight
// rows, so it never scrolls: type to narrow.
//
//   Up/Down, Ctrl+P/N, Tab   move the selection      Enter   launch
//   Escape, or a click outside                        close
//
// Motion: the panel opens on Theme's decelerating curve (opacity, a small
// scale and rise together), the rows arrive one after another, and the
// selection highlight glides between rows rather than jumping. Reduced
// motion makes all of it instant.
PanelWindow {
    id: root
    objectName: "launcher"
    property bool open: false
    property real progress: 0
    property string query: ""
    property var allApps: []
    property bool appsLoaded: false
    property int selected: 0
    property real _px: 0
    property real _py: 0
    property bool _pointerSeen: false
    readonly property int maxRows: 8
    readonly property var results: Search.rank(root.allApps, root.query, root.maxRows)
    readonly property real rowHeight: 54

    readonly property bool showing: root.open || root.progress > 0
    visible: root.showing
    color: "transparent"
    exclusionMode: ExclusionMode.Ignore
    aboveWindows: true
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.namespace: "dxrice-launcher"
    WlrLayershell.keyboardFocus: root.open ? WlrKeyboardFocus.Exclusive : WlrKeyboardFocus.None
    anchors { top: true; left: true; right: true; bottom: true }
    implicitWidth: root.screen && root.screen.width ? root.screen.width : 1920
    implicitHeight: root.screen && root.screen.height ? root.screen.height : 1080
    // Input only while open (same reason as the overview: the closing frames
    // must not swallow clicks meant for what is underneath).
    mask: Region {
        width: root.open ? root.width : 0
        height: root.open ? root.height : 0
    }

    function show() {
        if (root.open) return;
        PanelManager.closeCurrent();
        root.query = "";
        root.selected = 0;
        root._pointerSeen = false;
        root.open = true;
        appsProc.running = true;
        input.forceActiveFocus();
        enter.restart();
    }
    function hide() {
        if (!root.open) return;
        root.open = false;
        enter.stop();
        leave.restart();
    }
    function toggle() { if (root.open) root.hide(); else root.show(); }

    function launch(index) {
        const r = root.results[index];
        if (!r) return;
        Launcher.launch("launcher", ["sh", "-c", r.app.cmd]);
        historyProc.command = ["python3", Quickshell.shellDir + "/../scripts/dxrice_launcher_history.py", "bump", r.app.name];
        historyProc.running = true;
        root.hide();
    }
    function move(step) {
        const n = root.results.length;
        if (n > 0) root.selected = (root.selected + step + n) % n;
    }
    onResultsChanged: if (root.selected >= root.results.length) root.selected = Math.max(0, root.results.length - 1)
    onQueryChanged: root.selected = 0

    Process {
        id: appsProc
        command: ["python3", Quickshell.shellDir + "/../scripts/dxrice_list_desktop_apps.py"]
        stdout: StdioCollector {
            onStreamFinished: {
                try { root.allApps = JSON.parse(this.text); } catch (e) { root.allApps = []; }
                root.appsLoaded = true;
            }
        }
    }
    Process { id: historyProc }

    NumberAnimation {
        id: enter
        target: root; property: "progress"; to: 1
        // a spring: it rises a little past its place and settles (Theme.curveSpring)
        duration: Theme.durationSpring
        easing.type: Theme.easingType; easing.bezierCurve: Theme.curveSpring
    }
    NumberAnimation {
        id: leave
        target: root; property: "progress"; to: 0
        duration: Theme.durationFast
        easing.type: Theme.easingType; easing.bezierCurve: Theme.curveStandard
    }

    // the dim; a click on it closes
    Rectangle {
        anchors.fill: parent
        color: "black"
        opacity: 0.38 * root.progress
        MouseArea { anchors.fill: parent; onClicked: root.hide() }
    }

    Item {
        id: stage
        anchors.fill: parent
        Keys.onEscapePressed: root.hide()

        RectangularShadow {
            anchors.fill: panel
            radius: panel.radius
            color: Theme.shadowColor
            blur: Theme.elevationBlur(3)
            spread: Theme.elevationSpread(3)
            offset.y: Theme.elevationOffsetY(3)
            opacity: panel.opacity
            scale: panel.scale
            transformOrigin: Item.Top
        }
        Rectangle {
            id: panel
            objectName: "launcherPanel"
            width: 660
            height: header.height + (root.results.length > 0 || !root.appsLoaded || root.query.length > 0 ? list.height + 8 : 0) + 8
            x: (parent.width - width) / 2
            y: Math.round(parent.height * 0.17) + (1 - root.progress) * 14
            radius: Theme.radius
            color: Theme.panel
            border.width: 1
            border.color: Theme.border
            opacity: root.progress
            scale: 0.96 + 0.04 * root.progress
            transformOrigin: Item.Top
            clip: true
            Behavior on height { NumberAnimation { duration: Theme.durationFast; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveStandard } }

            MouseArea { anchors.fill: parent }   // clicks on the panel aren't "outside"

            Item {
                id: header
                width: parent.width
                height: 64
                Text {
                    id: glyph
                    x: 22; anchors.verticalCenter: parent.verticalCenter
                    text: ""
                    font.family: Theme.fontFamily; font.pixelSize: 18
                    color: Theme.accent
                }
                TextInput {
                    id: input
                    objectName: "launcherInput"
                    anchors.left: glyph.right; anchors.leftMargin: 14
                    anchors.right: parent.right; anchors.rightMargin: 22
                    anchors.verticalCenter: parent.verticalCenter
                    text: root.query
                    onTextChanged: root.query = text
                    color: Theme.textActive
                    selectionColor: Theme.accent
                    font.family: Theme.fontFamily
                    font.pixelSize: 21
                    clip: true
                    focus: true
                    Keys.onPressed: (e) => {
                        const ctrl = e.modifiers & Qt.ControlModifier;
                        if (e.key === Qt.Key_Down || e.key === Qt.Key_Tab || (ctrl && (e.key === Qt.Key_N || e.key === Qt.Key_J))) root.move(1);
                        else if (e.key === Qt.Key_Up || e.key === Qt.Key_Backtab || (ctrl && (e.key === Qt.Key_P || e.key === Qt.Key_K))) root.move(-1);
                        else if (e.key === Qt.Key_Return || e.key === Qt.Key_Enter) root.launch(root.selected);
                        else if (e.key === Qt.Key_Escape) root.hide();
                        else return;
                        e.accepted = true;
                    }
                    Text {
                        visible: input.text.length === 0
                        anchors.verticalCenter: parent.verticalCenter
                        text: "Search applications"
                        color: Theme.text; opacity: Theme.opacityFaint
                        font: input.font
                    }
                }
                Rectangle {
                    anchors.bottom: parent.bottom
                    x: 22; width: parent.width - 44; height: 1
                    color: Theme.borderIdle
                    opacity: root.results.length > 0 ? 1 : 0
                }
            }

            Item {
                id: list
                objectName: "launcherList"
                anchors.top: header.bottom; anchors.topMargin: 4
                width: parent.width
                height: root.results.length > 0 ? root.results.length * root.rowHeight : 70
                Behavior on height { NumberAnimation { duration: Theme.durationFast; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveStandard } }

                // the selection: one highlight that glides from row to row
                Rectangle {
                    id: highlight
                    objectName: "launcherHighlight"
                    visible: root.results.length > 0
                    x: 10; width: parent.width - 20
                    y: root.selected * root.rowHeight + 3
                    height: root.rowHeight - 6
                    radius: Theme.roundingSm
                    color: Theme.mix(Theme.layer1, Theme.accent, 0.2)
                    border.width: 1
                    border.color: Theme.mix(Theme.borderIdle, Theme.accent, 0.6)
                    Behavior on y { NumberAnimation { duration: Theme.durationFast; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveStandard } }
                }

                Repeater {
                    model: root.results
                    delegate: Item {
                        id: row
                        required property var modelData
                        required property int index
                        objectName: "launcherRow:" + row.index
                        width: list.width
                        height: root.rowHeight
                        y: row.index * root.rowHeight
                        readonly property bool current: row.index === root.selected
                        // rows arrive one after another when the panel opens
                        opacity: 0
                        transform: Translate { id: slide; y: 8 }
                        Component.onCompleted: arrive.start()
                        SequentialAnimation {
                            id: arrive
                            PauseAnimation { duration: Theme.reduceMotion ? 0 : Math.min(row.index, 6) * 22 }
                            ParallelAnimation {
                                NumberAnimation { target: row; property: "opacity"; to: 1; duration: Theme.durationFast; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveStandard }
                                NumberAnimation { target: slide; property: "y"; to: 0; duration: Theme.durationDefault; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveEmphasizedDecel }
                            }
                        }
                        // the app's icon, or a lettered tile in its own tint when
                        // the theme has none
                        Item {
                            id: iconBox
                            x: 24; anchors.verticalCenter: parent.verticalCenter
                            width: 34; height: 34
                            readonly property string src: row.modelData.app.icon ? String(Quickshell.iconPath(row.modelData.app.icon, true) || "") : ""
                            Image {
                                anchors.fill: parent
                                visible: iconBox.src.length > 0 && status === Image.Ready
                                source: iconBox.src
                                sourceSize: Qt.size(68, 68)
                                asynchronous: true
                                fillMode: Image.PreserveAspectFit
                            }
                            Rectangle {
                                anchors.fill: parent
                                radius: 9
                                visible: iconBox.src.length === 0 || iconBox.children[0].status !== Image.Ready
                                readonly property int hue: { let h = 0; const n = String(row.modelData.app.name); for (let i = 0; i < n.length; i++) h = (h * 31 + n.charCodeAt(i)) % 360; return h; }
                                color: Qt.hsla(hue / 360, 0.35, 0.34, 1)
                                Text {
                                    anchors.centerIn: parent
                                    text: String(row.modelData.app.name).charAt(0).toUpperCase()
                                    color: "white"; font.family: Theme.fontFamily; font.pixelSize: 16; font.weight: Font.DemiBold
                                }
                            }
                        }
                        Column {
                            anchors.left: iconBox.right; anchors.leftMargin: 16
                            anchors.right: parent.right; anchors.rightMargin: 24
                            anchors.verticalCenter: parent.verticalCenter
                            spacing: 1
                            Text {
                                width: parent.width
                                textFormat: Text.StyledText
                                elide: Text.ElideRight
                                color: row.current ? Theme.textActive : Theme.text
                                font.family: Theme.fontFamily; font.pixelSize: 16
                                font.weight: row.current ? Font.DemiBold : Font.Medium
                                text: {
                                    const n = String(row.modelData.app.name);
                                    const esc = (t) => t.replace(/&/g, "&amp;").replace(/</g, "&lt;");
                                    const a = row.modelData.start, l = row.modelData.len;
                                    if (!l) return esc(n);
                                    return esc(n.slice(0, a)) + "<font color=\"" + Theme.accent + "\">" + esc(n.slice(a, a + l)) + "</font>" + esc(n.slice(a + l));
                                }
                            }
                            Text {
                                width: parent.width
                                text: row.modelData.app.cmd
                                elide: Text.ElideRight
                                color: Theme.text; opacity: Theme.opacityMuted
                                font.family: Theme.fontMono; font.pixelSize: 11
                            }
                        }
                        MouseArea {
                            anchors.fill: parent
                            hoverEnabled: true
                            // The pointer picks a row only by really moving: a row
                            // that appears under a resting pointer (the panel just
                            // opened, or the list just changed) must not take the
                            // selection from the keyboard.
                            onPositionChanged: (m) => {
                                const p = mapToItem(null, m.x, m.y);
                                if (root._pointerSeen && Math.abs(p.x - root._px) + Math.abs(p.y - root._py) >= 3)
                                    root.selected = row.index;
                                root._px = p.x; root._py = p.y; root._pointerSeen = true;
                            }
                            onClicked: root.launch(row.index)
                        }
                    }
                }

                // nothing to show: say why
                Text {
                    objectName: "launcherEmpty"
                    visible: root.results.length === 0
                    anchors.centerIn: parent
                    text: !root.appsLoaded ? "Looking for applications…"
                          : (root.query.length > 0 ? "Nothing matches “" + root.query + "”" : "No applications found")
                    color: Theme.text; opacity: Theme.opacityMuted
                    font.family: Theme.fontFamily; font.pixelSize: 15
                }
            }
        }
    }
}
