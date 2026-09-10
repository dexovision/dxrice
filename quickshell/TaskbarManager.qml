import QtQuick
import QtQuick.Dialogs
import QtQuick.Effects
import Quickshell
import Quickshell.Io

// DXrice Taskbar manager -- Quickshell rewrite of dxrice_taskbar_gui.py.
// Edits ~/.config/waybar/config directly (same file, same rules: never
// synced back into the repo, so personal shortcuts survive an update --
// see dxrice_deploy.py's copy-once handling of that file) and restarts
// waybar after every change.
FloatingWindow {
    id: root
    signal closeRequested()
    title: "DXrice Taskbar"
    color: "transparent"
    onVisibleChanged: if (!visible) root.closeRequested()

    readonly property string repoDir: Quickshell.shellDir + "/.."
    readonly property string configPath: Quickshell.env("HOME") + "/.config/waybar/config"
    readonly property string launcherId: "custom/launcher"
    readonly property var iconModes: ["auto", "text", "image"]
    readonly property var iconModeLabels: ["Automatic icon", "Text label", "Custom image"]

    property var cfg: ({})
    property bool loaded: false

    Shortcut { sequence: "Escape"; onActivated: root.closeRequested() }

    // blockLoading is required here, not optional: without it text() can
    // return "" if this runs before the async read finishes, which a
    // naive catch-and-default then writes straight over the real file on
    // the first commit() -- this genuinely happened once during testing
    // and wiped a real waybar config. loadFailed is a second, independent
    // guard: commit() refuses to write at all unless a real parse of the
    // real file succeeded first, so no future bug in this class can repeat
    // that failure mode.
    property bool loadFailed: false

    FileView {
        id: configFile
        path: root.configPath
        blockLoading: true
    }
    FileView {
        id: configWriter
        path: root.configPath
    }

    Component.onCompleted: {
        try {
            const text = configFile.text();
            root.cfg = JSON.parse(text);
            root.loaded = true;
        } catch (e) {
            console.warn("TaskbarManager: could not read/parse", root.configPath, e);
            root.loadFailed = true;
        }
    }

    function commit() {
        if (!root.loaded || root.loadFailed) {
            console.warn("TaskbarManager: refusing to write -- config was never successfully loaded");
            return;
        }
        root.cfg = JSON.parse(JSON.stringify(root.cfg));
        configWriter.setText(JSON.stringify(root.cfg, null, 4));
        restartProc.running = true;
    }

    Process {
        id: restartProc
        command: ["sh", "-c", "pkill -x waybar; sleep 0.3; setsid waybar >/dev/null 2>&1 &"]
    }

    function slugify(label) {
        const slug = label.replace(/[^a-zA-Z0-9]/g, "").toLowerCase();
        return slug || ("app" + Date.now());
    }
    function modidFor(label, mode) {
        return (mode === "image" ? "image#" : "custom/") + root.slugify(label);
    }
    function uniqueModid(modid, exclude) {
        if (!(modid in root.cfg) || modid === exclude) return modid;
        let i = 2;
        while ((modid + i) in root.cfg && (modid + i) !== exclude) i++;
        return modid + i;
    }
    function unwrapShellCmd(onClick) {
        const m = /^sh -c '(.*) >\/dev\/null 2>&1 &'$/.exec(onClick || "");
        return m ? m[1] : (onClick || "");
    }
    function iconsEnabled() {
        return root.cfg["dxrice_icons_enabled"] !== false;
    }

    // ---- icon glyph resolution (reuses the existing Python lookup table --
    // one source of truth for taskbar icon matching, not duplicated in JS) ----
    Process {
        id: iconProc
        property var onDone: null
        stdout: StdioCollector {
            onStreamFinished: { if (iconProc.onDone) iconProc.onDone(this.text.trim()); }
        }
    }
    function resolveIcon(label, cmd, callback) {
        iconProc.onDone = callback;
        iconProc.command = ["python3", root.repoDir + "/scripts/dxrice_icons.py", label, cmd];
        iconProc.running = true;
    }

    function rebuildModule(modid, glyph) {
        const meta = root.cfg[modid];
        const label = meta.dxrice_label;
        const cmd = meta.dxrice_cmd;
        const mode = meta.dxrice_icon_mode || "auto";
        const onClick = "sh -c '" + cmd + " >/dev/null 2>&1 &'";

        if (mode === "image" && meta.dxrice_icon_path) {
            root.cfg[modid] = {
                dxrice_label: label, dxrice_cmd: cmd, dxrice_icon_mode: "image", dxrice_icon_path: meta.dxrice_icon_path,
                path: meta.dxrice_icon_path, size: root.cfg["dxrice_icon_size"] || 24,
                "on-click": onClick, tooltip: false, "class": "app-icon",
            };
            return;
        }
        const showGlyph = mode === "auto" && root.iconsEnabled();
        root.cfg[modid] = {
            dxrice_label: label, dxrice_cmd: cmd, dxrice_icon_mode: mode,
            format: showGlyph ? glyph : label, "on-click": onClick,
            tooltip: true, "tooltip-format": label, "class": "app-icon",
        };
    }

    function addShortcut(label, cmd) {
        const modid = root.uniqueModid(root.modidFor(label, "auto"));
        root.resolveIcon(label, cmd, (glyph) => {
            root.cfg[modid] = { dxrice_label: label, dxrice_cmd: cmd, dxrice_icon_mode: "auto" };
            root.rebuildModule(modid, glyph);
            if (!root.cfg["modules-left"]) root.cfg["modules-left"] = [];
            root.cfg["modules-left"].push(modid);
            root.commit();
        });
    }

    function setIconMode(modid, newMode, imagePath) {
        const meta = root.cfg[modid];
        if (newMode === "image" && !imagePath && !meta.dxrice_icon_path) {
            // Waiting for the file picker -- nothing to persist yet.
            return;
        }
        let targetId = modid;
        const newModid = root.modidFor(meta.dxrice_label, newMode);
        if (newModid !== modid) {
            targetId = root.uniqueModid(newModid, modid);
            const mods = root.cfg["modules-left"];
            const idx = mods.indexOf(modid);
            if (idx >= 0) mods[idx] = targetId;
            delete root.cfg[modid];
            root.cfg[targetId] = meta;
        }
        meta.dxrice_icon_mode = newMode;
        if (newMode === "image" && imagePath) meta.dxrice_icon_path = imagePath;
        if (newMode === "image") {
            root.rebuildModule(targetId, "");
            root.commit();
        } else {
            root.resolveIcon(meta.dxrice_label, meta.dxrice_cmd, (glyph) => {
                root.rebuildModule(targetId, glyph);
                root.commit();
            });
        }
    }

    function removeShortcut(modid) {
        const mods = root.cfg["modules-left"];
        const idx = mods.indexOf(modid);
        if (idx >= 0) mods.splice(idx, 1);
        delete root.cfg[modid];
        root.commit();
    }

    function moveShortcut(modid, direction) {
        const mods = root.cfg["modules-left"];
        const idx = mods.indexOf(modid);
        if (idx < 0) return;
        if (direction === "up" && idx > 0) {
            [mods[idx - 1], mods[idx]] = [mods[idx], mods[idx - 1]];
        } else if (direction === "down" && idx < mods.length - 1) {
            [mods[idx + 1], mods[idx]] = [mods[idx], mods[idx + 1]];
        }
        root.commit();
    }

    function moveShortcutTo(draggedModid, targetModid) {
        if (draggedModid === targetModid) return;
        const mods = root.cfg["modules-left"];
        const targetIdx = mods.indexOf(targetModid);
        if (targetIdx < 0) return;
        const draggedIdx = mods.indexOf(draggedModid);
        if (draggedIdx < 0) return;
        mods.splice(draggedIdx, 1);
        // Re-find the target's index after removal, and never let a drop
        // land before the pinned launcher.
        let insertAt = mods.indexOf(targetModid);
        if (insertAt < 0) insertAt = mods.length;
        const launcherIdx = mods.indexOf(root.launcherId);
        if (launcherIdx >= 0 && insertAt <= launcherIdx) insertAt = launcherIdx + 1;
        mods.splice(insertAt, 0, draggedModid);
        root.commit();
    }

    function setIconsEnabled(on) {
        root.cfg["dxrice_icons_enabled"] = on;
        const mods = root.cfg["modules-left"] || [];
        let remaining = mods.filter((m) => m !== root.launcherId && root.cfg[m] && root.cfg[m].dxrice_label);
        function next() {
            if (remaining.length === 0) { root.commit(); return; }
            const modid = remaining.shift();
            root.resolveIcon(root.cfg[modid].dxrice_label, root.cfg[modid].dxrice_cmd, (glyph) => {
                root.rebuildModule(modid, glyph);
                next();
            });
        }
        next();
    }

    function setIconSize(size) {
        root.cfg["dxrice_icon_size"] = size;
        for (const modid of (root.cfg["modules-left"] || [])) {
            const meta = root.cfg[modid];
            if (meta && meta.dxrice_icon_mode === "image") root.rebuildModule(modid, "");
        }
        root.commit();
    }

    readonly property var systemModuleLabels: ({
        "clock": "Clock", "pulseaudio": "Volume", "network": "Network", "cpu": "CPU", "memory": "Memory",
    })
    function systemModuleIds() {
        const ids = [];
        for (const modid of (root.cfg["modules-center"] || []).concat(root.cfg["modules-right"] || [])) {
            if (modid in root.systemModuleLabels) ids.push(modid);
        }
        return ids;
    }
    function setModuleClick(modid, key, value) {
        if (!root.cfg[modid]) root.cfg[modid] = {};
        if (value) root.cfg[modid][key] = value;
        else delete root.cfg[modid][key];
        root.commit();
    }

    // ---- image picker ----
    property string pendingImageModid: ""
    FileDialog {
        id: imageDialog
        onAccepted: {
            if (root.pendingImageModid) {
                root.setIconMode(root.pendingImageModid, "image", String(imageDialog.selectedFile).replace("file://", ""));
            }
        }
    }

    // ---- visuals ----
    implicitWidth: 480
    implicitHeight: 780

    RectangularShadow {
        anchors.fill: panelSurface
        radius: panelSurface.radius
        color: Theme.shadowColor
        blur: Theme.shadowBlurLg
        offset.y: 4
        opacity: panelSurface.opacity
    }

    Rectangle {
        id: panelSurface
        anchors.fill: parent
        radius: Theme.roundingXl
        color: Theme.bg
        border.width: 1
        border.color: Theme.border

        opacity: 0
        scale: 0.94
        transformOrigin: Item.Top
        Behavior on opacity { NumberAnimation { duration: Theme.durationEnter; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveEmphasizedDecel } }
        Behavior on scale { NumberAnimation { duration: Theme.durationEnter; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveEmphasizedDecel } }
        Component.onCompleted: { opacity = 1; scale = 1; }

        Column {
            anchors.fill: parent
            spacing: 0

            Item {
                id: header
                width: parent.width
                height: 56

                Text {
                    text: "Taskbar"
                    color: Theme.textActive
                    font.family: Theme.fontFamily
                    font.weight: Font.DemiBold
                    font.pixelSize: 17
                    anchors.verticalCenter: parent.verticalCenter
                    x: Theme.padLg
                }
                Row {
                    anchors.verticalCenter: parent.verticalCenter
                    x: header.width - width - Theme.padLg
                    spacing: Theme.padSm
                    GlassButton { text: "Add"; variant: "primary"; onClicked: addDialog.visible = true }
                    IconButton { glyph: "✕"; onClicked: root.closeRequested() }
                }
            }

            Text {
                visible: root.loadFailed
                width: parent.width - Theme.padLg * 2
                x: Theme.padLg
                y: Theme.padLg
                wrapMode: Text.WordWrap
                color: Theme.accent
                font.family: Theme.fontFamily
                text: "Could not read " + root.configPath + " -- nothing will be changed until this is fixed. Run install.sh first if this is a fresh install."
            }

            Flickable {
                width: parent.width
                height: parent.height - header.height
                contentHeight: body.implicitHeight + Theme.padLg * 2
                clip: true
                visible: root.loaded

                Column {
                    id: body
                    x: Theme.padLg
                    y: Theme.padLg
                    width: parent.width - Theme.padLg * 2
                    spacing: Theme.padMd

                    Text { text: "Options"; color: Theme.textActive; font.family: Theme.fontFamily; font.weight: Font.DemiBold }
                    Card {
                        width: parent.width
                        SettingRow {
                            width: parent.width
                            title: "Show icons"
                            subtitle: "Applies to shortcuts left on \"Automatic\""
                            Switch { checked: root.iconsEnabled(); onToggled: (next) => root.setIconsEnabled(next) }
                        }
                        SettingRow {
                            width: parent.width
                            title: "Custom icon size"
                            SliderRow {
                                width: 160
                                from: 16; to: 48; decimals: 0
                                value: root.cfg["dxrice_icon_size"] || 24
                                onChanged: (v) => root.setIconSize(Math.round(v))
                            }
                        }
                    }

                    Text { text: "Taskbar Shortcuts"; color: Theme.textActive; font.family: Theme.fontFamily; font.weight: Font.DemiBold }
                    Repeater {
                        model: root.loaded ? (root.cfg["modules-left"] || []) : []
                        delegate: Item {
                            id: shortcutCardWrap
                            width: body.width
                            visible: !!root.cfg[modelData]
                            height: visible ? shortcutCard.implicitHeight : 0

                            // DropArea is a sibling of Card, not a child of it: Card
                            // redirects its children into an internal Column (so plain
                            // `Card { Row {...} }` nesting works elsewhere), and Column
                            // rejects anchors.fill on its children outright.
                            DropArea {
                                anchors.fill: parent
                                keys: ["dxrice-shortcut"]
                                onEntered: shortcutCard.highlighted = true
                                onExited: shortcutCard.highlighted = false
                                onDropped: (drop) => {
                                    shortcutCard.highlighted = false;
                                    root.moveShortcutTo(drop.text, shortcutCard.modid);
                                }
                            }

                            Card {
                            id: shortcutCard
                            anchors.fill: parent
                            property string modid: modelData
                            property var meta: root.cfg[modid] || ({})
                            property bool expanded: false
                            property bool pinned: modid === root.launcherId

                            SettingRow {
                                width: parent.width
                                title: shortcutCard.meta.dxrice_label || shortcutCard.modid
                                subtitle: shortcutCard.meta.dxrice_cmd || ""

                                Rectangle {
                                    visible: !shortcutCard.pinned
                                    width: 20; height: 20
                                    color: "transparent"
                                    Text {
                                        anchors.centerIn: parent
                                        text: "⠿"
                                        color: Theme.text
                                        opacity: dragHandleMouse.drag.active ? 1.0 : 0.5
                                    }
                                    Drag.active: dragHandleMouse.drag.active
                                    Drag.keys: ["dxrice-shortcut"]
                                    Drag.mimeData: { "text/plain": shortcutCard.modid }
                                    MouseArea {
                                        id: dragHandleMouse
                                        anchors.fill: parent
                                        drag.target: parent
                                        cursorShape: Qt.SizeAllCursor
                                        onReleased: {
                                            parent.Drag.drop();
                                            // The handle briefly owns its own x/y while dragged;
                                            // hand control back to the Row's normal layout
                                            // immediately rather than leaving it visually stuck
                                            // wherever the drag ended.
                                            parent.x = 0;
                                            parent.y = 0;
                                        }
                                    }
                                }
                                Rectangle {
                                    visible: shortcutCard.pinned
                                    width: pinLabel.implicitWidth + 12
                                    height: 20
                                    radius: 10
                                    color: Theme.accentSoft
                                    Text { id: pinLabel; anchors.centerIn: parent; text: "Pinned"; color: Theme.textActive; font.pixelSize: 11 }
                                }
                                IconButton {
                                    visible: !shortcutCard.pinned
                                    glyph: shortcutCard.expanded ? "︿" : "﹀"
                                    onClicked: shortcutCard.expanded = !shortcutCard.expanded
                                }
                                IconButton { visible: !shortcutCard.pinned; glyph: "↑"; onClicked: root.moveShortcut(shortcutCard.modid, "up") }
                                IconButton { visible: !shortcutCard.pinned; glyph: "↓"; onClicked: root.moveShortcut(shortcutCard.modid, "down") }
                                IconButton { visible: !shortcutCard.pinned; glyph: "🗑"; destructive: true; onClicked: root.removeShortcut(shortcutCard.modid) }
                            }

                            Column {
                                width: parent.width
                                visible: shortcutCard.expanded && !shortcutCard.pinned
                                height: visible ? implicitHeight : 0
                                spacing: Theme.padSm
                                topPadding: Theme.padSm

                                Row {
                                    spacing: Theme.padSm
                                    Repeater {
                                        model: root.iconModeLabels
                                        delegate: GlassButton {
                                            text: modelData
                                            variant: root.iconModes[index] === (shortcutCard.meta.dxrice_icon_mode || "auto") ? "primary" : "secondary"
                                            onClicked: {
                                                const mode = root.iconModes[index];
                                                if (mode === "image") {
                                                    root.pendingImageModid = shortcutCard.modid;
                                                    imageDialog.open();
                                                } else {
                                                    root.setIconMode(shortcutCard.modid, mode, null);
                                                }
                                            }
                                        }
                                    }
                                }
                                Text {
                                    visible: (shortcutCard.meta.dxrice_icon_mode || "auto") === "image"
                                    text: shortcutCard.meta.dxrice_icon_path ? shortcutCard.meta.dxrice_icon_path : "No image chosen"
                                    color: Theme.text
                                    opacity: 0.7
                                    font.pixelSize: 11
                                    elide: Text.ElideMiddle
                                    width: parent.width
                                }
                            }
                            } // Card
                        }
                    }

                    Text { text: "System Modules"; color: Theme.textActive; font.family: Theme.fontFamily; font.weight: Font.DemiBold }
                    Text {
                        text: "Click actions for the volume/network/CPU/RAM/clock modules"
                        color: Theme.text; opacity: 0.7; font.pixelSize: 12; font.family: Theme.fontFamily
                    }
                    Repeater {
                        model: root.loaded ? root.systemModuleIds() : []
                        delegate: Card {
                            id: sysCard
                            width: body.width
                            property string modid: modelData
                            property bool expanded: false
                            property var meta: root.cfg[modid] || ({})

                            SettingRow {
                                width: parent.width
                                title: root.systemModuleLabels[sysCard.modid] || sysCard.modid
                                subtitle: sysCard.meta["on-click"] || "No click action set"
                                IconButton { glyph: sysCard.expanded ? "︿" : "﹀"; onClicked: sysCard.expanded = !sysCard.expanded }
                            }
                            Column {
                                width: parent.width
                                visible: sysCard.expanded
                                height: visible ? implicitHeight : 0
                                spacing: Theme.padSm
                                topPadding: Theme.padSm

                                SettingRow {
                                    width: parent.width
                                    title: "Left click"
                                    Rectangle {
                                        width: 180; height: 30; radius: Theme.entryRadius
                                        color: Qt.rgba(1, 1, 1, 0.06)
                                        border.width: 1; border.color: Theme.borderIdle
                                        TextInput {
                                            anchors.fill: parent; anchors.margins: 6
                                            text: sysCard.meta["on-click"] || ""
                                            color: Theme.textActive
                                            font.family: Theme.fontFamily
                                            verticalAlignment: TextInput.AlignVCenter
                                            onEditingFinished: root.setModuleClick(sysCard.modid, "on-click", text)
                                        }
                                    }
                                }
                                SettingRow {
                                    width: parent.width
                                    title: "Right click"
                                    Rectangle {
                                        width: 180; height: 30; radius: Theme.entryRadius
                                        color: Qt.rgba(1, 1, 1, 0.06)
                                        border.width: 1; border.color: Theme.borderIdle
                                        TextInput {
                                            anchors.fill: parent; anchors.margins: 6
                                            text: sysCard.meta["on-click-right"] || ""
                                            color: Theme.textActive
                                            font.family: Theme.fontFamily
                                            verticalAlignment: TextInput.AlignVCenter
                                            onEditingFinished: root.setModuleClick(sysCard.modid, "on-click-right", text)
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    FloatingWindow {
        id: addDialog
        visible: false
        title: "Add Shortcut"
        color: "transparent"
        implicitWidth: 380
        implicitHeight: 520

        property var allApps: []
        property string query: ""
        readonly property var filteredApps: addDialog.query.length === 0
            ? addDialog.allApps
            : addDialog.allApps.filter((a) => a.name.toLowerCase().includes(addDialog.query.toLowerCase()))

        Process {
            id: appsProc
            command: ["python3", root.repoDir + "/scripts/dxrice_list_desktop_apps.py"]
            stdout: StdioCollector {
                onStreamFinished: {
                    try { addDialog.allApps = JSON.parse(this.text); } catch (e) { addDialog.allApps = []; }
                }
            }
        }
        onVisibleChanged: if (visible) appsProc.running = true

        RectangularShadow {
            anchors.fill: addDialogSurface
            radius: addDialogSurface.radius
            color: Theme.shadowColor
            blur: Theme.shadowBlurLg
            offset.y: 4
        }

        Rectangle {
            id: addDialogSurface
            anchors.fill: parent
            radius: Theme.roundingXl
            color: Theme.bg
            border.width: 1
            border.color: Theme.border

            Column {
                anchors.fill: parent
                anchors.margins: Theme.padLg
                spacing: Theme.padMd

                Text { text: "Add Shortcut"; color: Theme.textActive; font.family: Theme.fontFamily; font.weight: Font.DemiBold }

                Rectangle {
                    width: parent.width; height: 34; radius: Theme.entryRadius
                    color: Qt.rgba(1, 1, 1, 0.06)
                    border.width: 1; border.color: Theme.borderIdle
                    TextInput {
                        id: searchInput
                        anchors.fill: parent; anchors.margins: 8
                        color: Theme.textActive
                        font.family: Theme.fontFamily
                        verticalAlignment: TextInput.AlignVCenter
                        onTextChanged: addDialog.query = text
                    }
                    Text { text: "Search installed apps..."; color: Theme.text; opacity: searchInput.text.length ? 0 : 0.5; anchors.left: parent.left; anchors.leftMargin: 8; anchors.verticalCenter: parent.verticalCenter }
                }

                Flickable {
                    width: parent.width
                    height: 220
                    contentHeight: appList.implicitHeight
                    clip: true
                    Column {
                        id: appList
                        width: parent.width
                        Repeater {
                            model: addDialog.filteredApps
                            delegate: Rectangle {
                                width: appList.width
                                height: 36
                                radius: Theme.entryRadius
                                color: appArea.containsMouse ? Theme.active : "transparent"
                                Behavior on color { ColorAnimation { duration: Theme.animMs } }
                                Column {
                                    anchors.verticalCenter: parent.verticalCenter
                                    anchors.left: parent.left
                                    anchors.leftMargin: 8
                                    width: parent.width - 16
                                    Text { text: modelData.name; color: Theme.textActive; font.family: Theme.fontFamily; font.pixelSize: 13; elide: Text.ElideRight; width: parent.width }
                                    Text { text: modelData.cmd; color: Theme.text; opacity: 0.6; font.pixelSize: 10; elide: Text.ElideRight; width: parent.width }
                                }
                                MouseArea {
                                    id: appArea
                                    anchors.fill: parent
                                    hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: {
                                        root.addShortcut(modelData.name, modelData.cmd);
                                        addDialog.visible = false;
                                    }
                                }
                            }
                        }
                    }
                }

                Text { text: "Or add a custom shortcut"; color: Theme.text; opacity: 0.7; font.pixelSize: 12; font.family: Theme.fontFamily }

                Rectangle {
                    width: parent.width; height: 34; radius: Theme.entryRadius
                    color: Qt.rgba(1, 1, 1, 0.06)
                    border.width: 1; border.color: Theme.borderIdle
                    TextInput {
                        id: nameInput
                        anchors.fill: parent; anchors.margins: 8
                        color: Theme.textActive
                        font.family: Theme.fontFamily
                        verticalAlignment: TextInput.AlignVCenter
                    }
                    Text { text: "Display name"; color: Theme.text; opacity: nameInput.text.length ? 0 : 0.5; anchors.left: parent.left; anchors.leftMargin: 8; anchors.verticalCenter: parent.verticalCenter }
                }
                Rectangle {
                    width: parent.width; height: 34; radius: Theme.entryRadius
                    color: Qt.rgba(1, 1, 1, 0.06)
                    border.width: 1; border.color: Theme.borderIdle
                    TextInput {
                        id: cmdInput
                        anchors.fill: parent; anchors.margins: 8
                        color: Theme.textActive
                        font.family: Theme.fontFamily
                        verticalAlignment: TextInput.AlignVCenter
                    }
                    Text { text: "Command to run"; color: Theme.text; opacity: cmdInput.text.length ? 0 : 0.5; anchors.left: parent.left; anchors.leftMargin: 8; anchors.verticalCenter: parent.verticalCenter }
                }

                GlassButton {
                    text: "Add"
                    variant: "primary"
                    onClicked: {
                        if (nameInput.text.length && cmdInput.text.length) {
                            root.addShortcut(nameInput.text, cmdInput.text);
                            nameInput.text = ""; cmdInput.text = "";
                            addDialog.visible = false;
                        }
                    }
                }
            }
        }

        Shortcut { sequence: "Escape"; onActivated: addDialog.visible = false }
    }
}
