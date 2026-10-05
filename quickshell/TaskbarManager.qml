import QtQuick
import QtQuick.Dialogs
import QtQuick.Effects
import Quickshell
import Quickshell.Io

// The Taskbar editor's content -- deliberately NOT a window.
//
// Hosted inside the dock's own ShellIsland (see Dock.qml): the dock slab and
// this panel are one surface that changes shape, so opening this reads as the
// dock unfolding upward rather than a wider rectangle appearing above it.
// See ShellIsland.qml for why that requires sharing the control's item tree.
//
// Still the only writer of ~/.config/waybar/config-dock (see the FileView
// comments below for why that file/schema stays as the storage format).
Item {
    id: root
    // Safe to bind BOTH dimensions here (unlike QuickSettings.qml, see its own
    // comment on `contentHeight` for why that one is fixed instead): this
    // file has no repeating Timer anywhere, so nothing here perturbs its own
    // measured contentHeight on a tick, which is what would be needed to
    // start the feedback loop that made QuickSettings peg the CPU. Verified
    // by testing this in isolation before committing to it.
    anchors.fill: parent
    signal closeRequested()

    // Read by Dock.qml (via ShellIsland's panelItem alias) so its own
    // click-outside-to-dismiss region can suspend itself while the
    // Add-Shortcut branch is open, and so Dock.qml knows to render that
    // branch at all -- see AddShortcutBranch.qml for the actual UI this
    // now drives (no longer a separate FloatingWindow; see that file's
    // own comment for why).
    property bool addPanelOpen: false

    // State for AddShortcutBranch.qml, which binds to this Item (passed
    // as its own `manager` property from Dock.qml) rather than owning
    // this data itself -- TaskbarManager is still the one thing that
    // knows how to list installed apps and actually add a shortcut; the
    // branch is presentation + positioning only. (repoDir is already
    // declared further down this file, reused here as-is.)
    property var allApps: []
    property string query: ""
    readonly property var filteredApps: root.query.length === 0
        ? root.allApps
        : root.allApps.filter((a) => a.name.toLowerCase().includes(root.query.toLowerCase()))

    Process {
        id: appsProc
        command: ["python3", root.repoDir + "/scripts/dxrice_list_desktop_apps.py"]
        stdout: StdioCollector {
            onStreamFinished: {
                try { root.allApps = JSON.parse(this.text); } catch (e) { root.allApps = []; }
            }
        }
    }
    onAddPanelOpenChanged: if (addPanelOpen) appsProc.running = true

    // Drives the island's expanded height, so the surface fits the list rather
    // than every taskbar being padded out to a fixed 780px with dead space
    // under it (which is what the old fixed-size window did).
    // Was `Math.min(660, header.height + body.implicitHeight + Theme.padLg*3)`
    // paired with a Flickable sized off `parent.height - header.height` --
    // i.e. off the OUTER height this very property produces, not off the
    // Flickable's own content. Whenever the true content was shorter than
    // that formula's estimate (it always was: the estimate independently
    // guessed at padding the Flickable's own contentHeight already accounts
    // for), the outer surface rendered at the guessed size and the Flickable
    // rendered at its real, smaller size -- leaving the gap between them as
    // dead panel background. That gap was almost the entire "System Modules"
    // area in the last screenshots.
    //
    // Fixed by computing the Flickable's height FIRST, directly from the same
    // expression as its own contentHeight, and having this property just add
    // the header on top -- so there is exactly one source of truth for how
    // tall the scrollable area is, and the outer surface can never disagree
    // with what the Flickable actually shows.
    //
    // The 360 preference is also capped against the real screen (see
    // ShellSurface.screenHeight): without this, a short display could make
    // Dock.qml's own clampToScreen shrink the outer surface below what THIS
    // property already promised, leaving the Flickable sized for more room
    // than the surface actually gives it -- the exact mismatch that was
    // silently clipping Quick Settings' Overview cards with no way to scroll
    // to them. Computing the cap here instead means the outer clamp in
    // Dock.qml is a pure backstop, never the thing actually doing the work.
    readonly property real maxAvailableBodyHeight: ShellSurface.screenHeight - ShellSurface.gap * 2 - ShellSurface.dockUnit - header.height
    readonly property real bodyHeight: Math.min(360, maxAvailableBodyHeight, body.implicitHeight + Theme.padXl * 2)
    readonly property real contentHeight: header.height + bodyHeight

    readonly property string repoDir: Quickshell.shellDir + "/.."
    // The app dock lives in its own bottom-edge waybar instance now (see
    // waybar/config-dock), separate from the top bar's own config -- this
    // still edits the same "modules-left" array inside that file, just a
    // different file than before.
    readonly property string configPath: Xdg.configHome + "/waybar/config-dock"
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
        // Gated on `command -v qs`, the same test hyprland.lua's autostart and
        // dxrice_apply_theme.py use to decide who owns the bar.
        //
        // When Quickshell owns it (the normal case) this does nothing at all:
        // Dock.qml watches config-dock with a FileView and reloads itself, so
        // a commit here is already reflected without restarting anything. The
        // unguarded version relaunched all four legacy waybar instances on
        // every single shortcut edit, putting the old bar back on screen on
        // top of this very shell -- two clocks, two docks, the old side
        // strips, and waybar's exclusive zones squeezing the real windows.
        // The `else` branch keeps the fallback working on machines with no
        // Quickshell, where waybar genuinely is the dock being edited.
        command: ["sh", "-c",
            "if command -v qs >/dev/null 2>&1; then exit 0; fi; " +
            "pkill -x waybar; sleep 0.3; " +
            "for c in config config-left config-right config-dock; do " +
            "setsid waybar -c \"" + Xdg.configHome + "/waybar/$c\" -s \"" + Xdg.configHome + "/waybar/style.css\" >/dev/null 2>&1 & done"]
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
    // Embeds a user-typed command (itself meant to be shell-parsed -- it
    // may legitimately contain its own quoted arguments like --title='My
    // App') inside the outer sh -c '...' wrapper this rice stores
    // on-click as. Found live: naive string concatenation here breaks the
    // instant cmd contains a single quote with a SPACE inside it -- bash's
    // adjacent-quote-concatenation rule papers over a quoted value with no
    // spaces, but a real multi-word quoted value gets silently word-split
    // and the command runs with only part of its arguments (confirmed:
    // `fake_app --title='My Cool App' arg2` previously ran as just
    // `fake_app --title=My`). Standard POSIX technique for nesting a
    // single-quoted string inside another: close the quote, emit an
    // escaped literal quote, reopen the quote, for every embedded quote.
    function wrapShellCmd(cmd) {
        const escaped = cmd.replace(/'/g, "'\\''");
        return "sh -c '" + escaped + " >/dev/null 2>&1 &'";
    }
    function unwrapShellCmd(onClick) {
        const m = /^sh -c '(.*) >\/dev\/null 2>&1 &'$/.exec(onClick || "");
        if (!m) return onClick || "";
        return m[1].replace(/'\\''/g, "'");
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
        const onClick = root.wrapShellCmd(cmd);

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
    // ---- content ----
    Column {
        anchors.fill: parent
        spacing: 0

        // No "Taskbar" title/close row here: the dock's own shortcut row is
        // this panel's header now, staying fixed at the surface's bottom
        // (its origin edge -- see ShellIsland.qml) instead of fading away
        // for an unrelated title bar. "Add" is a real action, not decoration,
        // so it stays as a slim, always-visible (non-scrolling) toolbar
        // instead of disappearing along with the old title row.
        //
        // `height` is derived from the actual button it contains plus real
        // padding, not a guessed constant: a bare `32` here (this panel's
        // real, previous value) was 10px SHORTER than GlassButton's own
        // implicitHeight (42, measured via mapToGlobal on a running shell),
        // so the button -- vertically centered in a container shorter than
        // itself -- rendered 5px above the header's own top edge, which is
        // also the SURFACE's top edge here (this is the bottom-pinned dock's
        // island, so content starts at the surface's origin with nothing
        // above it to absorb the overflow) -- a real, measured 5px escape
        // past the panel's own boundary, not a rendering illusion. The
        // Theme.padSm top margin is the same breathing room every other
        // panel already gives its first row (see QuickSettings.qml's spacer
        // Item) -- Taskbar was the one panel missing it, which is also why
        // its header sat close enough to the rounded top corner to look like
        // it was escaping the surface even before accounting for the 5px.
        Item {
            id: header
            width: parent.width
            height: headerRow.implicitHeight + Theme.padSm * 2

            // CLOSE REGION: ShellIsland.qml's own closeButton is fixed at
            // `surface.width - 22 - 8` regardless of which edge this island
            // grows from, so it always claims the surface's top-right
            // corner -- confirmed by grabbing the actual rendered surface
            // and finding the close "X" partially hidden behind this very
            // Add button, which was positioned as if that corner were free.
            // ACTION REGION (the Add button) has to stop clear of it: this
            // is that same 22+8 footprint plus a visible gap, kept as one
            // named value instead of folded into the position expression so
            // the reason isn't just a bare magic number.
            readonly property real closeButtonReserve: 22 + 8 + Theme.padSm

            Row {
                id: headerRow
                anchors.top: parent.top
                anchors.topMargin: Theme.padSm
                x: header.width - width - Theme.padLg - header.closeButtonReserve
                GlassButton { text: "Add"; variant: "primary"; onClicked: root.addPanelOpen = !root.addPanelOpen }
            }
        }

        // Same structural seam QuickSettings.qml uses between its nav strip
        // and content -- this header is genuinely a toolbar for the surface
        // below it, not a decoration, so it earns the same "this is where
        // the header ends and content begins" boundary language instead of
        // just floating above the cards with nothing marking the handoff.
        Rectangle {
            x: Theme.padXl
            width: parent.width - Theme.padXl * 2
            y: header.height
            height: 1
            color: Theme.seam
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

        Item {
            width: parent.width
            height: root.bodyHeight
            visible: root.loaded

            Flickable {
                id: bodyFlickable
                anchors.fill: parent
                contentHeight: body.implicitHeight + Theme.padXl * 2
                clip: true

                Column {
                    id: body
                    // Wider inset than before (padLg -> padXl), matching
                    // QuickSettings.qml's identical reasoning: the panel's
                    // own tone needs real visible margin around the cards
                    // it hosts to read as their container.
                    x: Theme.padXl
                    y: Theme.padXl
                    width: parent.width - Theme.padXl * 2
                    // Same spacing-hierarchy reasoning as QuickSettings.qml's
                    // overviewPane Row: this is the gap between two distinct
                    // top-level cards (Options, Shortcuts), not between
                    // items inside one -- it should read as a bigger jump
                    // than a card's own internal cardGap.
                    spacing: Theme.pad2xl

                // Options stays a single compact row (toggle + slider
                // side by side) instead of a tall stacked card: it only
                // has two controls, and a full-height column next to
                // Shortcuts previously left a measured 211px of bare
                // panel below it once Shortcuts (which owns the real
                // scrollable content) pushed the shared row taller than
                // Options' own content needed. Options is now sized
                // purely from its own content and sits ABOVE Shortcuts,
                // full width -- Shortcuts still owns the dominant
                // vertical region below it, and nothing is stretched to
                // fill space it doesn't have content for.
                Card {
                    width: parent.width
                    title: "Options"
                    Row {
                        width: parent.width
                        spacing: Theme.padLg

                        Row {
                            id: iconsToggleRow
                            anchors.verticalCenter: parent.verticalCenter
                            spacing: Theme.padMd
                            Switch { checked: root.iconsEnabled(); onToggled: (next) => root.setIconsEnabled(next) }
                            Column {
                                anchors.verticalCenter: parent.verticalCenter
                                spacing: 0
                                Text {
                                    text: "Show icons"
                                    color: Theme.textActive
                                    font.family: Theme.fontFamily
                                    font.pixelSize: Theme.fontSizeNormal
                                    font.weight: Font.Medium
                                }
                                Text {
                                    text: "Automatic-mode shortcuts only"
                                    color: Theme.text
                                    opacity: 0.65
                                    font.family: Theme.fontFamily
                                    font.pixelSize: Theme.fontSizeSmall
                                }
                            }
                        }

                        FillSlider {
                            width: parent.width - iconsToggleRow.width - parent.spacing
                            anchors.verticalCenter: parent.verticalCenter
                            label: "Icon size"
                            from: 16; to: 48; decimals: 0
                            value: root.cfg["dxrice_icon_size"] || 24
                            onChanged: (v) => root.setIconSize(Math.round(v))
                        }
                    }
                }

                Card {
                    width: parent.width
                    title: "Shortcuts"
                    Column {
                        width: parent.width
                        spacing: 0
                        Repeater {
                            model: root.loaded ? (root.cfg["modules-left"] || []) : []
                            delegate: Column {
                                id: shortcutRow
                                width: parent.width
                                visible: !!root.cfg[modelData]
                                spacing: 0
                                property string modid: modelData
                                property var meta: root.cfg[modid] || ({})
                                property bool expanded: false
                                property bool pinned: modid === root.launcherId
                                property bool dropHighlighted: false

                                Item {
                                    id: rowVisual
                                    width: parent.width
                                    height: 36

                                    HoverHandler { id: rowHover }
                                    DropArea {
                                        anchors.fill: parent
                                        keys: ["dxrice-shortcut"]
                                        onEntered: shortcutRow.dropHighlighted = true
                                        onExited: shortcutRow.dropHighlighted = false
                                        onDropped: (drop) => {
                                            shortcutRow.dropHighlighted = false;
                                            root.moveShortcutTo(drop.text, shortcutRow.modid);
                                        }
                                    }

                                    Rectangle {
                                        anchors.fill: parent
                                        radius: Theme.roundingSm
                                        color: shortcutRow.dropHighlighted
                                            ? Theme.mix(Theme.layer1, Theme.accent, 0.18)
                                            : (rowHover.hovered ? Theme.layer1 : "transparent")
                                        Behavior on color { ColorAnimation { duration: Theme.durationFast } }
                                    }

                                    Item {
                                        id: leadHandle
                                        anchors.left: parent.left
                                        anchors.leftMargin: Theme.padSm
                                        anchors.verticalCenter: parent.verticalCenter
                                        width: 18
                                        height: 20
                                        visible: !shortcutRow.pinned
                                        Text {
                                            anchors.centerIn: parent
                                            text: "⣿"
                                            color: Theme.text
                                            opacity: dragHandleMouse.drag.active ? 0.9 : (rowHover.hovered ? 0.55 : 0.22)
                                            Behavior on opacity { NumberAnimation { duration: Theme.durationFast } }
                                        }
                                        Drag.active: dragHandleMouse.drag.active
                                        Drag.keys: ["dxrice-shortcut"]
                                        Drag.mimeData: { "text/plain": shortcutRow.modid }
                                        MouseArea {
                                            id: dragHandleMouse
                                            anchors.fill: parent
                                            drag.target: parent
                                            cursorShape: Qt.SizeAllCursor
                                            onReleased: {
                                                parent.Drag.drop();
                                                // The handle briefly owns its own x/y while
                                                // dragged; hand control back to its normal
                                                // anchored position immediately.
                                                parent.x = 0;
                                                parent.y = 0;
                                            }
                                        }
                                    }
                                    Text {
                                        anchors.left: parent.left
                                        anchors.leftMargin: Theme.padSm + 6
                                        anchors.verticalCenter: parent.verticalCenter
                                        visible: shortcutRow.pinned
                                        text: "●"
                                        font.pixelSize: 8
                                        color: Theme.text
                                        opacity: 0.3
                                    }

                                    Text {
                                        id: leadIcon
                                        anchors.left: leadHandle.right
                                        anchors.leftMargin: Theme.padSm
                                        anchors.verticalCenter: parent.verticalCenter
                                        width: 20
                                        horizontalAlignment: Text.AlignHCenter
                                        font.family: Theme.fontFamily
                                        font.pixelSize: Theme.fontSizeNormal
                                        color: Theme.text
                                        opacity: 0.85
                                        text: (shortcutRow.meta.dxrice_icon_mode || "auto") !== "text" && root.iconsEnabled()
                                            ? (shortcutRow.meta.format || "")
                                            : (shortcutRow.meta.dxrice_label || "?").charAt(0).toUpperCase()
                                    }

                                    Row {
                                        id: actionsRow
                                        anchors.right: parent.right
                                        anchors.rightMargin: Theme.padSm
                                        anchors.verticalCenter: parent.verticalCenter
                                        visible: !shortcutRow.pinned
                                        opacity: (rowHover.hovered || shortcutRow.expanded) ? 1 : 0
                                        Behavior on opacity { NumberAnimation { duration: Theme.durationFast } }
                                        IconButton { glyph: shortcutRow.expanded ? "︿" : "﹀"; size: Theme.iconSm; onClicked: shortcutRow.expanded = !shortcutRow.expanded }
                                        IconButton { glyph: "↑"; size: Theme.iconSm; onClicked: root.moveShortcut(shortcutRow.modid, "up") }
                                        IconButton { glyph: "↓"; size: Theme.iconSm; onClicked: root.moveShortcut(shortcutRow.modid, "down") }
                                        IconButton { glyph: "🗑"; size: Theme.iconSm; destructive: true; onClicked: root.removeShortcut(shortcutRow.modid) }
                                    }

                                    Text {
                                        anchors.left: leadIcon.right
                                        anchors.leftMargin: Theme.padSm
                                        anchors.right: actionsRow.left
                                        anchors.rightMargin: Theme.padSm
                                        anchors.verticalCenter: parent.verticalCenter
                                        text: shortcutRow.meta.dxrice_label || shortcutRow.modid
                                        color: Theme.textActive
                                        font.family: Theme.fontFamily
                                        font.pixelSize: Theme.fontSizeNormal
                                        elide: Text.ElideRight
                                    }
                                }

                                Item {
                                    width: 1
                                    height: Theme.padSm
                                    visible: shortcutRow.expanded && !shortcutRow.pinned
                                }
                                Column {
                                    x: Theme.padSm + 18 + Theme.padSm + 20 + Theme.padSm
                                    width: parent.width - x
                                    visible: shortcutRow.expanded && !shortcutRow.pinned
                                    spacing: Theme.padSm

                                    Row {
                                        spacing: Theme.padSm
                                        Repeater {
                                            model: root.iconModeLabels
                                            delegate: GlassButton {
                                                text: modelData
                                                variant: root.iconModes[index] === (shortcutRow.meta.dxrice_icon_mode || "auto") ? "primary" : "secondary"
                                                onClicked: {
                                                    const mode = root.iconModes[index];
                                                    if (mode === "image") {
                                                        root.pendingImageModid = shortcutRow.modid;
                                                        imageDialog.open();
                                                    } else {
                                                        root.setIconMode(shortcutRow.modid, mode, null);
                                                    }
                                                }
                                            }
                                        }
                                    }
                                    Text {
                                        visible: (shortcutRow.meta.dxrice_icon_mode || "auto") === "image"
                                        text: shortcutRow.meta.dxrice_icon_path ? shortcutRow.meta.dxrice_icon_path : "No image chosen"
                                        color: Theme.text
                                        opacity: 0.7
                                        font.pixelSize: Theme.fontSizeSmall
                                        elide: Text.ElideMiddle
                                        width: parent.width
                                    }
                                    Item { width: 1; height: Theme.padXs }
                                }
                            }
                        }
                    }
                }


                // -- system modules: same compact-row language, and
                // underline-style inputs (a bottom hairline, no filled
                // box) instead of bordered text fields. --
                Text { text: "System Modules"; color: Theme.text; opacity: 0.55; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSmall }
                Text {
                    text: "Click actions for the volume/network/CPU/RAM/clock modules"
                    color: Theme.text; opacity: 0.55; font.pixelSize: Theme.fontSizeSmaller; font.family: Theme.fontFamily
                }
                Column {
                    width: body.width
                    spacing: Theme.padSm
                    Repeater {
                        model: root.loaded ? root.systemModuleIds() : []
                        delegate: Column {
                            id: sysRow
                            width: parent.width
                            spacing: Theme.padSm
                            property string modid: modelData
                            property bool expanded: false
                            property var meta: root.cfg[modid] || ({})

                            SettingRow {
                                width: parent.width
                                title: root.systemModuleLabels[sysRow.modid] || sysRow.modid
                                subtitle: sysRow.meta["on-click"] || "No click action set"
                                IconButton { glyph: sysRow.expanded ? "︿" : "﹀"; size: Theme.iconSm; onClicked: sysRow.expanded = !sysRow.expanded }
                            }
                            Column {
                                width: parent.width
                                visible: sysRow.expanded
                                spacing: Theme.padMd

                                SettingRow {
                                    width: parent.width
                                    title: "Left click"
                                    Rectangle {
                                        width: 180; height: 26
                                        color: "transparent"
                                        border.width: 0
                                        Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: leftClickInput.activeFocus ? Theme.accent : Theme.borderIdle }
                                        TextInput {
                                            id: leftClickInput
                                            anchors.fill: parent
                                            text: sysRow.meta["on-click"] || ""
                                            color: Theme.textActive
                                            font.family: Theme.fontFamily
                                            font.pixelSize: Theme.fontSizeSmaller
                                            verticalAlignment: TextInput.AlignVCenter
                                            onEditingFinished: root.setModuleClick(sysRow.modid, "on-click", text)
                                        }
                                    }
                                }
                                SettingRow {
                                    width: parent.width
                                    title: "Right click"
                                    Rectangle {
                                        width: 180; height: 26
                                        color: "transparent"
                                        Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: rightClickInput.activeFocus ? Theme.accent : Theme.borderIdle }
                                        TextInput {
                                            id: rightClickInput
                                            anchors.fill: parent
                                            text: sysRow.meta["on-click-right"] || ""
                                            color: Theme.textActive
                                            font.family: Theme.fontFamily
                                            font.pixelSize: Theme.fontSizeSmaller
                                            verticalAlignment: TextInput.AlignVCenter
                                            onEditingFinished: root.setModuleClick(sysRow.modid, "on-click-right", text)
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
                }

            ScrollHint {
                flickable: bodyFlickable
                anchors.top: parent.top
                anchors.bottom: parent.bottom
                anchors.right: parent.right
                anchors.margins: 3
            }
        }
    }

}
