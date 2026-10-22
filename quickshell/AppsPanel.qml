import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Hyprland
import "LauncherSearch.js" as Search

// Applications: the panel that hangs from the bar's left section (the
// search pill and the saved shortcuts). One place for launching and for
// the taskbar -- it replaces both the separate launcher overlay and the
// bottom dock.
//
//   Apps        a search field; with nothing typed, the pinned shortcuts,
//               the open windows (focus one, or close it) and the apps used
//               most; typing ranks every installed app (LauncherSearch.js).
//               Up/Down, Ctrl+N/P, Tab move; Enter launches; Escape closes
//               (the bar's own Escape handler).
//   Shortcuts   the taskbar editor (TaskbarManager): add, edit, reorder,
//               remove the saved shortcuts, and their icon settings.
//
// Which one shows is which panel is open: "apps" or "taskbar" (the name the
// `taskbar` IPC target and every earlier keybind already use).
Item {
    id: root
    objectName: "appsPanel"
    signal closeRequested()

    // which view: follows the open panel's name, and holds while closing
    // (flipping back to Apps then would tear the editor down mid-fade)
    property string view: "apps"
    readonly property real navH: ShellSurface.navHeight + Theme.padMd
    readonly property real contentHeight: root.navH + (root.view === "shortcuts"
        ? (managerLoader.item ? managerLoader.item.contentHeight : 420)
        : appsView.implicitHeight)
    // for the bar: the editor (for AddShortcutBranch) and where it sits
    readonly property var manager: root.view === "shortcuts" ? managerLoader.item : null
    readonly property real managerY: root.navH

    // ---- the app list (the same .desktop listing the editor uses) ----
    property var allApps: []
    property bool appsLoaded: false
    property string query: ""
    property int selected: 0
    readonly property int maxRows: 8
    // typed: every installed app, ranked (the ones you use most first among
    // equals); nothing typed: the apps you launched from here most recently,
    // newest first (with no history yet the section stays empty rather than
    // listing the alphabet)
    readonly property var recent: root.allApps.filter((a) => Number(a.last) > 0)
        .sort((a, b) => Number(b.last) - Number(a.last)).slice(0, 5)
    readonly property var results: root.query.length > 0 ? Search.rank(root.allApps, root.query, root.maxRows)
        : root.recent.map((a) => ({ app: a, score: 0, start: 0, len: 0 }))
    onQueryChanged: root.selected = 0
    onResultsChanged: if (root.selected >= root.results.length) root.selected = Math.max(0, root.results.length - 1)
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
    function launch(index) {
        const r = root.results[index];
        if (!r) return;
        Launcher.launch("launcher", ["sh", "-c", r.app.cmd]);
        historyProc.command = ["python3", Quickshell.shellDir + "/../scripts/dxrice_launcher_history.py", "bump", r.app.name];
        historyProc.running = true;
        root.closeRequested();
    }
    function move(step) {
        const n = root.results.length;
        if (n > 0) root.selected = (root.selected + step + n) % n;
    }
    // the search takes the keys whenever Apps is showing and the bar has them
    function focusSearch() { if (root.view === "apps") search.forceActiveFocus(); }
    // a tab changed while open: the new view rises into place as it fades
    // in, while the panel eases to its height (ShellIsland)
    property real viewIn: 1
    property bool _settled: false
    onViewChanged: { Qt.callLater(root.focusSearch); if (root._settled) viewAnim.restart(); }
    NumberAnimation { id: viewAnim; target: root; property: "viewIn"; from: 0; to: 1; duration: Theme.durationFadeIn; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveStandard }
    Component.onCompleted: {
        root.view = PanelManager.isOpen("taskbar") ? "shortcuts" : "apps";
        appsProc.running = true;
        Qt.callLater(root.focusSearch);
        Qt.callLater(() => { root._settled = true; });
    }
    // a reopen (even one quick enough to find this panel still alive from
    // the last time) starts clean
    property bool _open: true
    Connections {
        target: PanelManager
        function onCurrentChanged() {
            const open = PanelManager.isOpen("apps") || PanelManager.isOpen("taskbar");
            if (open) root.view = PanelManager.isOpen("taskbar") ? "shortcuts" : "apps";
            if (open && !root._open) { root.query = ""; root.selected = 0; Qt.callLater(root.focusSearch); }
            root._open = open;
        }
    }

    // ---- open windows (Hyprland's own list; ordinary workspaces) ----
    readonly property var windows: {
        const l = Hyprland.toplevels ? Hyprland.toplevels.values : [];
        const out = [];
        for (let i = 0; i < l.length; i++) {
            const o = l[i].lastIpcObject || {};
            const ws = o.workspace ? o.workspace.id : 0;
            if (!o.address || ws <= 0) continue;
            out.push({ address: String(o.address), cls: String(o["class"] || ""), title: String(o.title || l[i].title || ""), ws: ws });
        }
        return out.slice(0, 6);
    }
    // Goes to it: a window panned off the screen (or cut off by its edge)
    // is brought into view by panning the infinite desktop -- every window
    // sliding on its own animation, the widgets swaying along -- then
    // focused; one on another workspace takes you there
    // (dxrice_navigate_windows.py --to).
    function focusWindow(address) {
        Quickshell.execDetached(["python3", Quickshell.shellDir + "/../scripts/dxrice_navigate_windows.py", "--to", String(address)]);
        root.closeRequested();
    }
    function closeWindow(address) {
        Hyprland.dispatch('hl.dsp.window.close({ window = "address:' + address + '" })');
    }

    // ---- tabs ----
    Row {
        id: nav
        x: ShellSurface.pad; y: Theme.padSm
        height: ShellSurface.navHeight
        spacing: Theme.padXs
        Repeater {
            model: [{ id: "apps", label: "Apps", glyph: "" }, { id: "taskbar", label: "Shortcuts", glyph: "" }]
            delegate: Rectangle {
                id: tab
                required property var modelData
                objectName: "appsTab:" + modelData.id
                readonly property bool current: (modelData.id === "taskbar") === (root.view === "shortcuts")
                width: tabRow.implicitWidth + Theme.padLg * 2
                height: nav.height
                radius: height / 2
                color: tab.current ? Theme.mix(Theme.layer1, Theme.accent, 0.18) : (tabArea.containsMouse ? Theme.layer1Hover : "transparent")
                Behavior on color { ColorAnimation { duration: Theme.durationFast } }
                Row {
                    id: tabRow
                    anchors.centerIn: parent
                    spacing: Theme.padSm
                    Text { text: tab.modelData.glyph; color: tab.current ? Theme.accentText : Theme.text; font.family: Theme.iconFamily; font.pixelSize: Theme.fontSizeSmaller; anchors.verticalCenter: parent.verticalCenter }
                    Text { text: tab.modelData.label; color: tab.current ? Theme.textActive : Theme.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSmaller; font.weight: tab.current ? Font.DemiBold : Font.Normal; anchors.verticalCenter: parent.verticalCenter }
                }
                MouseArea {
                    id: tabArea
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: if (!tab.current) PanelManager.open(tab.modelData.id, PanelManager.openedBy)
                }
            }
        }
    }

    // ---- Apps ----
    Column {
        id: appsView
        objectName: "appsView"
        visible: root.view === "apps"
        y: root.navH
        opacity: root.viewIn
        transform: Translate { y: (1 - root.viewIn) * Theme.contentShift }
        width: parent.width
        spacing: Theme.padSm
        bottomPadding: Theme.padMd

        // the search
        Rectangle {
            x: ShellSurface.pad; width: parent.width - ShellSurface.pad * 2
            height: 40
            radius: height / 2
            color: Theme.layer1
            border.width: 1
            border.color: search.activeFocus ? Theme.mix(Theme.borderIdle, Theme.accent, 0.6) : Theme.borderIdle
            Text {
                id: searchGlyph
                x: 14; anchors.verticalCenter: parent.verticalCenter
                text: ""
                color: Theme.accentText
                font.family: Theme.iconFamily; font.pixelSize: Theme.fontSizeNormal
            }
            TextInput {
                id: search
                objectName: "appsSearch"
                anchors.left: searchGlyph.right; anchors.leftMargin: 12
                anchors.right: parent.right; anchors.rightMargin: 16
                anchors.verticalCenter: parent.verticalCenter
                text: root.query
                onTextChanged: root.query = text
                color: Theme.textActive
                selectionColor: Theme.accent
                font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeLarge
                clip: true
                Keys.onPressed: (e) => {
                    const ctrl = e.modifiers & Qt.ControlModifier;
                    if (e.key === Qt.Key_Down || e.key === Qt.Key_Tab || (ctrl && (e.key === Qt.Key_N || e.key === Qt.Key_J))) root.move(1);
                    else if (e.key === Qt.Key_Up || e.key === Qt.Key_Backtab || (ctrl && (e.key === Qt.Key_P || e.key === Qt.Key_K))) root.move(-1);
                    else if (e.key === Qt.Key_Return || e.key === Qt.Key_Enter) root.launch(root.selected);
                    else if (e.key === Qt.Key_Escape) root.closeRequested();
                    else return;
                    e.accepted = true;
                }
                Text {
                    visible: search.text.length === 0
                    anchors.verticalCenter: parent.verticalCenter
                    text: "Search applications"
                    color: Theme.text; opacity: Theme.opacityFaint
                    font: search.font
                }
            }
        }

        // with nothing typed: pinned shortcuts and open windows
        SectionLabel { text: "Pinned"; visible: root.query.length === 0 && Shortcuts.list.length > 0 }
        Flow {
            objectName: "appsPinned"
            visible: root.query.length === 0 && Shortcuts.list.length > 0
            x: ShellSurface.pad; width: parent.width - ShellSurface.pad * 2
            spacing: Theme.padXs
            Repeater {
                model: Shortcuts.list.filter((s) => Shortcuts.commandOf(s.onClick).trim().length > 0 && Shortcuts.commandOf(s.onClick) !== "wofi --show drun")
                delegate: Rectangle {
                    id: pin
                    required property var modelData
                    objectName: "appsPin:" + modelData.label
                    readonly property string appKey: Shortcuts.appKeyOf(modelData.onClick)
                    readonly property bool running: Shortcuts.isRunning(pin.appKey)
                    width: pinRow.implicitWidth + Theme.padLg * 2
                    height: 34
                    radius: height / 2
                    color: pinArea.containsMouse ? Theme.layer1Hover : Theme.layer1
                    scale: Theme.pressScale(pinArea.pressed, 0.94)
                    Behavior on scale { NumberAnimation { duration: Theme.durationSpringFast; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveSpringFast } }
                    Row {
                        id: pinRow
                        anchors.centerIn: parent
                        spacing: Theme.padSm
                        Text { visible: pin.modelData.glyph !== pin.modelData.label; text: pin.modelData.glyph; color: Theme.textActive; font.family: Theme.iconFamily; font.pixelSize: Theme.fontSizeNormal; anchors.verticalCenter: parent.verticalCenter }
                        Text { text: pin.modelData.label; color: Theme.textActive; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSmaller; anchors.verticalCenter: parent.verticalCenter }
                        Rectangle { visible: pin.running; width: 5; height: 5; radius: 2.5; color: Theme.accent; anchors.verticalCenter: parent.verticalCenter }
                    }
                    MouseArea {
                        id: pinArea
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: { Shortcuts.launch(pin.modelData.onClick, "bar"); root.closeRequested(); }
                    }
                }
            }
        }

        SectionLabel { text: "Open windows"; visible: root.query.length === 0 && root.windows.length > 0 }
        Column {
            objectName: "appsWindows"
            visible: root.query.length === 0 && root.windows.length > 0
            x: ShellSurface.pad; width: parent.width - ShellSurface.pad * 2
            Repeater {
                model: root.windows
                delegate: Rectangle {
                    id: win
                    required property var modelData
                    objectName: "appsWindow:" + modelData.address
                    width: parent.width; height: 38
                    radius: Theme.roundingSm
                    color: winArea.containsMouse ? Theme.layer1Hover : "transparent"
                    readonly property string icon: String(Quickshell.iconPath(win.modelData.cls.toLowerCase(), true) || "")
                    Image {
                        id: winIcon
                        x: 8; anchors.verticalCenter: parent.verticalCenter
                        width: 22; height: 22
                        source: win.icon
                        visible: win.icon.length > 0 && status === Image.Ready
                        sourceSize: Qt.size(44, 44)
                        asynchronous: true
                    }
                    Text {
                        visible: !winIcon.visible
                        x: 8; width: 22; anchors.verticalCenter: parent.verticalCenter
                        horizontalAlignment: Text.AlignHCenter
                        text: (win.modelData.cls || "?").charAt(0).toUpperCase()
                        color: Theme.accentText; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeNormal; font.weight: Font.DemiBold
                    }
                    Text {
                        x: 40; width: parent.width - 40 - 90
                        anchors.verticalCenter: parent.verticalCenter
                        text: win.modelData.title || win.modelData.cls
                        elide: Text.ElideRight
                        color: Theme.textActive; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSmaller
                    }
                    Text {
                        anchors.right: closeBtn.left; anchors.rightMargin: 10
                        anchors.verticalCenter: parent.verticalCenter
                        text: "ws " + win.modelData.ws
                        color: Theme.text; opacity: Theme.opacityMuted
                        font.family: Theme.fontMono; font.pixelSize: 11
                    }
                    MouseArea {
                        id: winArea
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: root.focusWindow(win.modelData.address)
                    }
                    Rectangle {
                        id: closeBtn
                        objectName: "appsWindowClose"
                        anchors.right: parent.right; anchors.rightMargin: 6
                        anchors.verticalCenter: parent.verticalCenter
                        width: 26; height: 26; radius: 13
                        color: closeArea.containsMouse ? Theme.mix(Theme.layer1, "#d05050", 0.35) : "transparent"
                        opacity: winArea.containsMouse || closeArea.containsMouse ? 1 : 0.45
                        Text { anchors.centerIn: parent; text: ""; color: Theme.textActive; font.family: Theme.iconFamily; font.pixelSize: 12 }
                        MouseArea {
                            id: closeArea
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: root.closeWindow(win.modelData.address)
                        }
                    }
                }
            }
        }

        // the ranked apps: the most used with nothing typed, else matches
        SectionLabel { text: root.query.length > 0 ? "Applications" : "Recent"; visible: root.results.length > 0 }
        Item {
            id: list
            objectName: "appsList"
            width: parent.width
            readonly property real rowH: 46
            height: root.results.length > 0 ? root.results.length * rowH : 56
            Rectangle {
                objectName: "appsHighlight"
                visible: root.results.length > 0
                x: ShellSurface.pad - 4; width: parent.width - (ShellSurface.pad - 4) * 2
                y: root.selected * list.rowH + 2
                height: list.rowH - 4
                radius: Theme.roundingSm
                color: Theme.mix(Theme.layer1, Theme.accent, 0.16)
                Behavior on y { NumberAnimation { duration: Theme.durationMove; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveStandard } }
            }
            Repeater {
                model: root.results
                delegate: Item {
                    id: row
                    required property var modelData
                    required property int index
                    objectName: "appsRow:" + row.index
                    width: list.width; height: list.rowH
                    y: row.index * list.rowH
                    readonly property string src: row.modelData.app.icon ? String(Quickshell.iconPath(row.modelData.app.icon, true) || "") : ""
                    Image {
                        id: rowIcon
                        x: ShellSurface.pad + 6; anchors.verticalCenter: parent.verticalCenter
                        width: 28; height: 28
                        source: row.src
                        visible: row.src.length > 0 && status === Image.Ready
                        sourceSize: Qt.size(56, 56)
                        asynchronous: true
                        fillMode: Image.PreserveAspectFit
                    }
                    Rectangle {
                        visible: !rowIcon.visible
                        x: ShellSurface.pad + 6; anchors.verticalCenter: parent.verticalCenter
                        width: 28; height: 28; radius: 8
                        color: Theme.mix(Theme.layer1, Theme.accent, 0.3)
                        Text { anchors.centerIn: parent; text: String(row.modelData.app.name).charAt(0).toUpperCase(); color: Theme.textActive; font.family: Theme.fontFamily; font.pixelSize: 14; font.weight: Font.DemiBold }
                    }
                    Text {
                        x: ShellSurface.pad + 46; width: parent.width - x - ShellSurface.pad
                        anchors.verticalCenter: parent.verticalCenter
                        textFormat: Text.StyledText
                        elide: Text.ElideRight
                        color: row.index === root.selected ? Theme.textActive : Theme.text
                        font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeNormal
                        font.weight: row.index === root.selected ? Font.DemiBold : Font.Normal
                        text: {
                            const n = String(row.modelData.app.name);
                            const esc = (t) => t.replace(/&/g, "&amp;").replace(/</g, "&lt;");
                            const a = row.modelData.start, l = row.modelData.len;
                            if (!l) return esc(n);
                            return esc(n.slice(0, a)) + "<font color=\"" + Theme.accentText + "\">" + esc(n.slice(a, a + l)) + "</font>" + esc(n.slice(a + l));
                        }
                    }
                    MouseArea {
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: root.launch(row.index)
                    }
                }
            }
            Text {
                objectName: "appsEmpty"
                visible: root.results.length === 0
                anchors.centerIn: parent
                text: !root.appsLoaded ? "Looking for applications…"
                      : (root.query.length > 0 ? "Nothing matches “" + root.query + "”" : "Type to search every installed app")
                color: Theme.text; opacity: Theme.opacityMuted
                font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSmall
            }
        }
    }

    component SectionLabel: Text {
        x: ShellSurface.pad + 4
        topPadding: Theme.padXs
        color: Theme.text; opacity: Theme.opacityMuted
        font.family: Theme.fontFamily; font.pixelSize: 11; font.weight: Font.DemiBold
        font.letterSpacing: 1.2
        font.capitalization: Font.AllUppercase
    }

    // ---- Shortcuts: the taskbar editor ----
    Loader {
        id: managerLoader
        objectName: "appsManager"
        active: root.view === "shortcuts"
        visible: active
        y: root.navH
        opacity: root.viewIn
        transform: Translate { y: (1 - root.viewIn) * Theme.contentShift }
        width: parent.width
        height: item ? item.contentHeight : 0
        sourceComponent: TaskbarManager { onCloseRequested: root.closeRequested() }
    }
}
