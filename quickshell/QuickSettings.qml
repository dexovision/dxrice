import QtQuick
import QtQuick.Effects
import Quickshell
import Quickshell.Io
import Quickshell.Services.Pipewire

// Quick Settings' content -- deliberately NOT a window.
//
// Hosted inside the bar's status-cluster ShellIsland (see TopBar.qml). The
// cluster pill and this panel are one rectangle that changes shape; see
// ShellIsland.qml for why that requires living in the same item tree as the
// control rather than in a window of its own.
//
// A real tab bar (Overview / Media / Performance) instead of one long scroll,
// each tab a separate Component behind a Loader (same pattern as
// ThemeEditor.qml's category panes).
Item {
    id: root
    // Width mirrors the Loader's width (a plain constant from ShellIsland, so
    // this can't create a cycle); height stays unbound -- see the long
    // comment on `contentHeight` just below for why binding it to the
    // Loader's height, which TopBar derives from this file's OWN measured
    // content, pegged the shell at 90%+ CPU during testing and never settled.
    width: parent.width
    signal closeRequested()

    // Read by TopBar.qml (via ShellIsland's panelItem alias) so its own
    // click-outside-to-dismiss region can suspend itself while the Wifi
    // password dialog is open -- see wifiBackend.onPasswordNeeded below for
    // why that's needed (same fix as TaskbarManager's addDialogOpen).
    property bool wifiDialogOpen: false

    // ==================== LAYOUT CONTRACT ====================
    // `contentHeight` (read by TopBar.qml to size the island) must NEVER be
    // bound directly to the live pane's implicitHeight: this file's internals
    // tick continuously (CPU/mem every 1.5s, media position every 1s), and the
    // pane Loader's implicitHeight moves by a pixel or two on some of those
    // ticks. Feeding that into the island's animated `expandedHeight` -- which
    // the shared `Behavior on surfaceH` (see ShellIsland.qml) restarts every
    // time its target changes -- meant the surface's grow/shrink animation
    // kept restarting itself indefinitely rather than ever settling: confirmed
    // by testing, CPU climbed from 14% to 34%+ and never came back down,
    // purely from this panel being open and idle.
    //
    // But a flat guessed constant is exactly what caused the OTHER failure
    // mode: this used to be a bare `300`, sized for the old flat-rows Overview
    // layout. Once Overview became four cards (Connectivity/Audio/Networks/
    // World Clock), its real measured implicitHeight is 382px (confirmed by
    // temporarily logging paneLoader.item.implicitHeight and reading it back
    // from the running shell, not guessed) -- 130px more than the old content,
    // and the 300 constant was never updated, so the bottom of the Audio and
    // World Clock cards were being clipped by `surface.clip: true` in
    // ShellIsland.qml with NO way to reach them: the Flickable below had its
    // own `height` bound to that same live content size, so it was never
    // actually a fixed viewport shorter than its content -- there was nothing
    // to scroll TO.
    //
    // The fix keeps the constant (still immune to the CPU bug: nothing here
    // depends on a ticking property) but makes it an actual contract instead
    // of a guess, and gives the Flickable below a REAL fixed viewport that is
    // independent of its content, so anything taller genuinely scrolls
    // instead of vanishing:
    //   preferred pane height : sized for Overview at its current content
    //                           (382px measured + padding + margin)
    //   available height      : this screen's real usable vertical space,
    //                           via ShellSurface.screenHeight -- so a shorter
    //                           display shrinks the viewport instead of
    //                           letting the panel run off the bottom edge
    //   viewport height       : min(preferred, available) -- what the
    //                           Flickable is actually given
    //   contentHeight (below) : header stack + viewport height, so the outer
    //                           island is always EXACTLY as tall as what is
    //                           visually allocated, never a mismatched guess
    readonly property real headerStackHeight: Theme.padSm + ShellSurface.navHeight + 1
    readonly property real preferredPaneHeight: 420
    // Matches TopBar.qml's islands: collapsedHeight is ShellSurface.unit and
    // each island sits ShellSurface.gap from the top AND needs the same gap
    // free at the bottom, so this is the real ceiling on how tall the pane
    // below the header can ever be before the panel would run off-screen.
    readonly property real maxAvailableHeight: ShellSurface.screenHeight - ShellSurface.gap * 2 - ShellSurface.unit
    readonly property real viewportHeight: Math.max(120, Math.min(preferredPaneHeight, maxAvailableHeight - headerStackHeight))
    readonly property real contentHeight: headerStackHeight + viewportHeight
    // What a pane can fill without scrolling: the viewport minus the pane
    // loader's own top/bottom inset. A per-screen constant, like the rest of
    // this contract -- safe for panes to size themselves from.
    readonly property real paneAvailableHeight: viewportHeight - Theme.padLg * 2


    property string currentTab: "overview"
    // "overview" stays the internal id (PerformanceService sync, IPC/tab-
    // switch tests elsewhere all key off this string) -- only the
    // user-facing label changes to "Dashboard" now that its content is a
    // real dashboard home, not a flat settings list.
    readonly property var tabs: [
        { id: "overview", glyph: "", label: "Dashboard" },
        { id: "media", glyph: "", label: "Media" },
        { id: "performance", glyph: "", label: "Performance" },
    ]

    // ---- audio (pipewire, native -- no wpctl subprocess) ----
    PwObjectTracker {
        objects: [Pipewire.defaultAudioSink, Pipewire.defaultAudioSource]
    }
    readonly property var sink: Pipewire.defaultAudioSink
    readonly property var source: Pipewire.defaultAudioSource

    // ---- live stats: CPU/memory/disk sampling lives in PerformanceService
    // now, not here -- see that file's own comment for why. This root only
    // owns turning that service on/off, tied to the Performance tab
    // specifically being selected AND this panel still existing, never just
    // "the panel is open on some other tab."
    function _syncPerformanceActive() {
        PerformanceService.active = (root.currentTab === "performance");
    }
    onCurrentTabChanged: {
        root._syncPerformanceActive();
        tabFade.restart();
    }
    Component.onDestruction: PerformanceService.active = false

    // ---- live media position, polled locally since MPRIS doesn't push a
    // tick every second on its own ----
    property real mediaPosition: 0
    Timer {
        interval: 1000; running: mediaBackend.playing; repeat: true; triggeredOnStart: true
        onTriggered: root.mediaPosition = mediaBackend.position
    }

    // ---- quick toggles state ----
    property bool wifiEnabled: false
    property bool bluetoothEnabled: false
    property bool dndActive: false
    property bool idleInhibited: false

    Process {
        id: wifiRadioCheck
        command: ["nmcli", "radio", "wifi"]
        stdout: StdioCollector { onStreamFinished: root.wifiEnabled = this.text.trim() === "enabled" }
    }
    Process {
        id: btPowerCheck
        command: ["bluetoothctl", "show"]
        stdout: StdioCollector { onStreamFinished: root.bluetoothEnabled = /Powered:\s*yes/.test(this.text) }
    }
    Process {
        id: dndCheck
        command: ["makoctl", "mode"]
        stdout: StdioCollector { onStreamFinished: root.dndActive = this.text.split(/\s+/).includes("dnd") }
    }

    function refreshToggleStates() {
        wifiRadioCheck.running = true;
        btPowerCheck.running = true;
        dndCheck.running = true;
    }

    Component.onCompleted: {
        root.refreshToggleStates();
        root._syncPerformanceActive();
    }

    Process {
        id: idleInhibitProc
        command: ["systemd-inhibit", "--what=idle:sleep", "--who=DXrice", "--why=Quick Settings Keep Awake", "sleep", "infinity"]
    }

    function setWifi(on) {
        root.wifiEnabled = on;
        Quickshell.execDetached(["nmcli", "radio", "wifi", on ? "on" : "off"]);
        refreshTimer.restart();
    }
    function setBluetooth(on) {
        root.bluetoothEnabled = on;
        Quickshell.execDetached(["bluetoothctl", "power", on ? "on" : "off"]);
        refreshTimer.restart();
    }
    function setDnd(on) {
        root.dndActive = on;
        Quickshell.execDetached(["makoctl", "mode", on ? "-a" : "-r", "dnd"]);
    }
    function setIdleInhibit(on) {
        root.idleInhibited = on;
        idleInhibitProc.running = on;
    }
    Timer { id: refreshTimer; interval: 800; onTriggered: root.refreshToggleStates() }

    // ---- screenshots ----
    function takeScreenshot(region) {
        root.closeRequested();
        screenshotHideTimer.region = region;
        screenshotHideTimer.start();
    }
    Timer {
        id: screenshotHideTimer
        property bool region: true
        interval: Theme.durationEnter + 80
        onTriggered: {
            const path = "~/Pictures/Screenshots/Screenshot-" +
                Qt.formatDateTime(new Date(), "yyyy-MM-dd-HHmmss") + ".png";
            const cmd = screenshotHideTimer.region
                ? 'mkdir -p ~/Pictures/Screenshots && geom="$(slurp)" && [ -n "$geom" ] && grim -g "$geom" ' + path + ' && wl-copy < ' + path
                : 'mkdir -p ~/Pictures/Screenshots && grim ' + path + ' && wl-copy < ' + path;
            Quickshell.execDetached(["sh", "-c", cmd]);
            root.closeRequested();
        }
    }
    // ---- content ----
    Column {
        id: outer
        width: parent.width
        spacing: 0

        // No title/clock/close row here any more: the status cluster itself
        // is this panel's header now (see ShellIsland.qml) and stays visible
        // above this content the whole time, rather than being replaced by a
        // "Quick Settings" title that has nothing to do with what was
        // clicked. Close is the shared affordance the island itself draws.
        Item { width: 1; height: Theme.padSm }

        // ---- tab bar: icon + label, accent underline on the
        // active tab -- the actual multi-tab dashboard shape from
        // the reference screenshots, not a single scrolling page. --
        // ---- the quiet integrated nav (layer 4) ----
        // A soft pill slides under whichever tab is active, using the same
        // card material and radius (ShellSurface.cardRadius, Theme.layer1)
        // as the content cards it sits above -- so the nav reads as part of
        // this surface's own grammar, not a separately-styled strip of tabs
        // with an underline bolted on top of the bare panel background.
        Item {
            id: tabBar
            // Wider inset than before (padLg -> padXl): the panel's own
            // tone needs to visibly frame the content it hosts, not butt
            // right up against it, or the panel never reads as a container
            // -- it reads as more content.
            x: Theme.padXl
            width: parent.width - Theme.padXl * 2
            height: ShellSurface.navHeight
            readonly property real tabWidth: width / root.tabs.length
            readonly property int activeIndex: Math.max(0, root.tabs.findIndex((t) => t.id === root.currentTab))

            // A thin underline instead of a filled pill: a pill behind the
            // active tab reads as "a button sitting on the surface" (its
            // own fill, its own border, its own little card) -- exactly
            // the "control bolted onto the panel" look this is meant to
            // avoid. A slim accent-colored bar under the active label is
            // the actual integrated-tab language (the tab bar IS the
            // surface; only a mark of where you are on it moves), and it
            // doesn't compete with Card.qml's cards for the same "bordered
            // rounded rectangle" visual vocabulary anywhere on this panel.
            Rectangle {
                id: activeIndicator
                width: tabBar.tabWidth * 0.4
                height: 3
                radius: 1.5
                x: tabBar.activeIndex * tabBar.tabWidth + (tabBar.tabWidth - width) / 2
                // A few px clear of tabBar's own bottom edge -- flush
                // against it put this accent bar's bottom edge touching the
                // nav-strip seam immediately below (see that Rectangle's own
                // comment), reading as one confused double line under the
                // active tab instead of two separate, legible marks.
                y: tabBar.height - height - 4
                color: Theme.accent
                Behavior on x {
                    NumberAnimation { duration: Theme.durationFast; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveStandard }
                }
            }

            Row {
                anchors.fill: parent
                Repeater {
                    model: root.tabs
                    delegate: Item {
                        required property var modelData
                        width: tabBar.tabWidth
                        height: tabBar.height
                        readonly property bool active: root.currentTab === modelData.id

                        Row {
                            anchors.centerIn: parent
                            spacing: Theme.padSm
                            Text {
                                text: modelData.glyph
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSizeNormal
                                color: parent.parent.active ? Theme.textActive : Theme.text
                                opacity: parent.parent.active ? 1 : 0.6
                                Behavior on opacity { NumberAnimation { duration: Theme.durationFast } }
                            }
                            Text {
                                text: modelData.label
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSizeSmaller
                                font.weight: parent.parent.active ? Font.DemiBold : Font.Normal
                                color: parent.parent.active ? Theme.textActive : Theme.text
                                opacity: parent.parent.active ? 1 : 0.6
                                Behavior on opacity { NumberAnimation { duration: Theme.durationFast } }
                            }
                        }

                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: root.currentTab = modelData.id
                        }
                    }
                }
            }
        }

        // The nav-strip -> content boundary -- same structural role and
        // same Theme.seam token as ShellIsland.qml's header seam (see its
        // comment), not the decorative Theme.borderIdle other hairlines in
        // this file use.
        Rectangle {
            x: Theme.padXl
            width: parent.width - Theme.padXl * 2
            height: 1
            color: Theme.seam
        }

        // A real fixed viewport (root.viewportHeight -- see the layout
        // contract above) containing a Flickable whose OWN height matches
        // that viewport exactly, independent of its content: `contentHeight`
        // is the only thing allowed to reflect the pane's real size, so
        // content taller than the viewport genuinely scrolls (with a visible
        // ScrollHint) instead of being clipped by `surface.clip: true` in
        // ShellIsland.qml with no way to reach it.
        Item {
            id: paneViewport
            width: parent.width
            height: root.viewportHeight

            Flickable {
                id: paneFlickable
                readonly property real paneHeight: (paneLoader.item ? paneLoader.item.implicitHeight : 0) + Theme.padLg * 2
                anchors.fill: parent
                contentHeight: paneHeight
                clip: true
                Behavior on contentY { NumberAnimation { duration: Theme.durationFast } }

                Loader {
                    id: paneLoader
                    x: Theme.padXl
                    // Top-aligned. This used to centre each pane vertically
                    // in the fixed viewport, which split any leftover space
                    // into two dead bands (one between the tabs and the
                    // content, one under it); panes now fill the viewport
                    // deliberately instead, via root.paneAvailableHeight.
                    y: Theme.padLg
                    width: parent.width - Theme.padXl * 2
                    // Content-level motion for a tab switch: the indicator
                    // slides (micro) while the new pane fades up (content),
                    // instead of the pane hard-cutting under a moving mark.
                    NumberAnimation on opacity {
                        id: tabFade
                        running: false
                        from: 0; to: 1
                        duration: Theme.durationFast
                        easing.type: Theme.easingType
                        easing.bezierCurve: Theme.curveStandard
                    }
                    sourceComponent: {
                        switch (root.currentTab) {
                        case "media": return mediaPane;
                        case "performance": return performancePane;
                        default: return overviewPane;
                        }
                    }
                }
            }

            ScrollHint {
                flickable: paneFlickable
                anchors.top: parent.top
                anchors.bottom: parent.bottom
                anchors.right: parent.right
                anchors.margins: 3
            }
        }
    }

    // ==================== DASHBOARD ====================
    // Three registers, read top to bottom:
    //   PRIMARY   the time, large, alone on the left of a hero band, with
    //             the date under it;
    //   SECONDARY the things you actually touch -- the four toggles and
    //             Audio on the left, Networks on the right -- as two equal
    //             columns sharing one baseline and one bottom edge;
    //   TERTIARY  world clocks (quiet, right side of the hero band) and the
    //             device line at the very bottom: plain text, no surfaces.
    //
    // The previous layout split the pane into 27% / 46% / 27% columns, so
    // the clock owned the middle while Networks -- the one list that needs
    // horizontal room for a name, a detail and an action -- got ~160px and
    // had to break every row over two lines with its Connect chips clipped.
    // The clock keeps its size; it simply no longer costs a column.
    Component {
        id: overviewPane
        Column {
            id: dash
            width: parent ? parent.width : implicitWidth
            spacing: Theme.padXl

            // ---- hero band ----
            Item {
                id: hero
                width: parent.width
                height: heroClock.implicitHeight

                Column {
                    id: heroClock
                    spacing: 0
                    property string timeText: Qt.formatDateTime(new Date(), "HH:mm")
                    property string dateText: Qt.formatDateTime(new Date(), "dddd, MMMM d")
                    Timer {
                        interval: 1000; running: true; repeat: true; triggeredOnStart: true
                        onTriggered: {
                            heroClock.timeText = Qt.formatDateTime(new Date(), "HH:mm");
                            heroClock.dateText = Qt.formatDateTime(new Date(), "dddd, MMMM d");
                        }
                    }
                    Text {
                        text: heroClock.timeText
                        color: Theme.textActive
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSizeHero
                        font.weight: Font.Light
                        // The glyph box carries ~15% empty leading above
                        // the digits at this size; pulling the date up by
                        // part of it keeps the two reading as one block.
                        bottomPadding: -Math.round(Theme.fontSizeHero * 0.12)
                    }
                    Text {
                        leftPadding: 3
                        text: heroClock.dateText
                        color: Theme.text
                        opacity: Theme.opacitySecondary
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSizeLarger
                    }
                }

                // Tertiary: other time zones, aligned to the date line so
                // they sit inside the hero band instead of competing with
                // the time itself.
                Grid {
                    id: worldGrid
                    anchors.right: parent.right
                    anchors.bottom: parent.bottom
                    anchors.bottomMargin: 2
                    columns: 2
                    columnSpacing: Theme.pad2xl
                    rowSpacing: Theme.padSm
                    visible: worldClock.cities.length > 0
                    Repeater {
                        model: worldClock.cities
                        delegate: Row {
                            required property var modelData
                            spacing: Theme.padSm
                            Text {
                                width: 72
                                text: modelData.label
                                color: Theme.text
                                opacity: Theme.opacityMuted
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSizeSmaller
                                elide: Text.ElideRight
                            }
                            Text {
                                text: modelData.time
                                color: Theme.textActive
                                opacity: Theme.opacityFaint
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSizeSmaller
                                font.weight: Font.Medium
                            }
                        }
                    }
                }
            }

            // ---- the controls ----
            Row {
                id: lower
                width: parent.width
                spacing: Theme.padLg
                // Fills whatever the fixed pane viewport leaves (a constant
                // per screen -- see the layout contract at the top of this
                // file -- never a ticking value), so the Networks card's
                // bottom edge lines up with the Audio card's instead of each
                // column ending wherever its own content happens to.
                // From the cards' IMPLICIT (content) heights, never their
                // laid-out ones: the Audio card stretches to this row's
                // height, so reading its `height` here would be a cycle.
                height: Math.max(toggleRow.height + ShellSurface.cardGap + audioCard.implicitHeight,
                                 root.paneAvailableHeight - hero.height - footer.height - dash.spacing * 2)
                readonly property real colWidth: (width - spacing) / 2

                Column {
                    id: controlsCol
                    width: lower.colWidth
                    spacing: ShellSurface.cardGap

                    // The toggles sit directly on the panel: each tile is
                    // already its own Level-2 control, and wrapping four of
                    // them in a bordered "Connectivity" card was a card
                    // holding cards.
                    Row {
                        id: toggleRow
                        width: parent.width
                        spacing: Theme.padSm
                        readonly property real tileWidth: (width - spacing * 3) / 4
                        ToggleChip {
                            width: toggleRow.tileWidth
                            glyph: "\uf1eb"; label: "Wi-Fi"
                            active: root.wifiEnabled
                            onToggled: (next) => root.setWifi(next)
                        }
                        ToggleChip {
                            width: toggleRow.tileWidth
                            glyph: "\uf294"; label: "Bluetooth"
                            active: root.bluetoothEnabled
                            onToggled: (next) => root.setBluetooth(next)
                        }
                        ToggleChip {
                            width: toggleRow.tileWidth
                            glyph: "\uf1f6"; label: "Do Not Disturb"
                            active: root.dndActive
                            onToggled: (next) => root.setDnd(next)
                        }
                        ToggleChip {
                            width: toggleRow.tileWidth
                            glyph: "⏻"; label: "Keep Awake"
                            active: root.idleInhibited
                            onToggled: (next) => root.setIdleInhibit(next)
                        }
                    }

                    Card {
                        id: audioCard
                        width: parent.width
                        // Fills the rest of the column so its bottom edge
                        // lines up with the Networks card's across the gutter.
                        height: Math.max(implicitHeight, lower.height - toggleRow.height - parent.spacing)
                        title: "Audio"
                        Row {
                            width: parent.width
                            spacing: Theme.padSm
                            IconButton {
                                glyph: (root.sink && root.sink.audio && root.sink.audio.muted) ? "\u{f075f}" : "\uf028"
                                size: Theme.iconSm
                                anchors.verticalCenter: parent.verticalCenter
                                onClicked: if (root.sink && root.sink.audio) root.sink.audio.muted = !root.sink.audio.muted
                            }
                            SliderRow {
                                width: parent.width - Theme.iconSm - Theme.padSm
                                from: 0; to: 100
                                value: (root.sink && root.sink.audio) ? Math.round(root.sink.audio.volume * 100) : 0
                                onChanged: (v) => { if (root.sink && root.sink.audio) root.sink.audio.volume = v / 100; }
                            }
                        }
                        Expandable {
                            width: parent.width
                            title: "Output"
                            trailingText: root.sink ? audioDeviceBackend.label(root.sink) : ""
                            visible: audioDeviceBackend.outputs.length > 1
                            height: visible ? implicitHeight : 0
                            Repeater {
                                model: audioDeviceBackend.outputs
                                delegate: DeviceChoice {
                                    label: audioDeviceBackend.label(modelData)
                                    selected: root.sink && root.sink.name === modelData.name
                                    onPicked: audioDeviceBackend.setOutput(modelData)
                                }
                            }
                        }

                        Row {
                            width: parent.width
                            spacing: Theme.padSm
                            IconButton {
                                glyph: (root.source && root.source.audio && root.source.audio.muted) ? "\uf131" : "\uf130"
                                size: Theme.iconSm
                                anchors.verticalCenter: parent.verticalCenter
                                onClicked: if (root.source && root.source.audio) root.source.audio.muted = !root.source.audio.muted
                            }
                            SliderRow {
                                width: parent.width - Theme.iconSm - Theme.padSm
                                from: 0; to: 100
                                value: (root.source && root.source.audio) ? Math.round(root.source.audio.volume * 100) : 0
                                onChanged: (v) => { if (root.source && root.source.audio) root.source.audio.volume = v / 100; }
                            }
                        }
                        Expandable {
                            width: parent.width
                            title: "Input"
                            trailingText: root.source ? audioDeviceBackend.label(root.source) : ""
                            visible: audioDeviceBackend.inputs.length > 1
                            height: visible ? implicitHeight : 0
                            Repeater {
                                model: audioDeviceBackend.inputs
                                delegate: DeviceChoice {
                                    label: audioDeviceBackend.label(modelData)
                                    selected: root.source && root.source.name === modelData.name
                                    onPicked: audioDeviceBackend.setInput(modelData)
                                }
                            }
                        }

                        // Brightness rides in the same card as one more
                        // level you set, behind the same icon-then-slider
                        // grammar as the two audio rows (no separate
                        // caption + hairline: on a laptop it is simply a
                        // third row).
                        Row {
                            width: parent.width
                            spacing: Theme.padSm
                            visible: brightnessBackend.hasBacklight
                            height: visible ? implicitHeight : 0
                            Text {
                                width: Theme.iconSm
                                anchors.verticalCenter: parent.verticalCenter
                                horizontalAlignment: Text.AlignHCenter
                                text: ""
                                color: Theme.text
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSizeNormal
                            }
                            SliderRow {
                                width: parent.width - Theme.iconSm - Theme.padSm
                                from: 1; to: 100
                                value: brightnessBackend.percent
                                onChanged: (v) => brightnessBackend.set(v)
                            }
                        }
                    }
                }

                // ---- Networks: one card, two sections, one scroll ----
                Card {
                    id: networksCard
                    width: lower.colWidth
                    height: lower.height
                    // No card title: the Wi-Fi | Bluetooth switch is the
                    // heading, so a "Networks" label above it would only eat
                    // a row of an already-short card.

                    // Wi-Fi | Bluetooth: one list at a time, each given the
                    // whole card. Stacked, the second list always started
                    // below the fold of a ~200px card.
                    Item {
                        id: netHeader
                        width: parent.width
                        height: 26
                        property string tab: "wifi"
                        Row {
                            id: segRow
                            spacing: Theme.padXs
                            anchors.verticalCenter: parent.verticalCenter
                            Repeater {
                                model: [{ id: "wifi", label: "Wi-Fi" }, { id: "bt", label: "Bluetooth" }]
                                delegate: Rectangle {
                                    required property var modelData
                                    readonly property bool active: netHeader.tab === modelData.id
                                    width: segLabel.implicitWidth + Theme.padMd * 2
                                    height: 24
                                    radius: height / 2
                                    color: active ? Theme.layer2Active : (segArea.containsMouse ? Theme.layer2Hover : "transparent")
                                    Behavior on color { ColorAnimation { duration: Theme.durationFast } }
                                    Text {
                                        id: segLabel
                                        anchors.centerIn: parent
                                        text: parent.modelData.label
                                        color: parent.active ? Theme.textActive : Theme.text
                                        opacity: parent.active ? 1 : Theme.opacitySecondary
                                        font.family: Theme.fontFamily
                                        font.pixelSize: Theme.fontSizeSmaller
                                        font.weight: parent.active ? Font.Medium : Font.Normal
                                    }
                                    MouseArea {
                                        id: segArea
                                        anchors.fill: parent
                                        hoverEnabled: true
                                        cursorShape: Qt.PointingHandCursor
                                        onClicked: { netHeader.tab = parent.modelData.id; netFlick.contentY = 0; }
                                    }
                                }
                            }
                        }
                        Text {
                            anchors.right: parent.right
                            anchors.rightMargin: Theme.padXs
                            anchors.verticalCenter: parent.verticalCenter
                            text: netHeader.tab === "wifi"
                                ? (root.wifiEnabled && wifiBackend.hasScanned && wifiBackend.networks.length > 0
                                    ? wifiBackend.networks.length + (wifiBackend.networks.length === 1 ? " network" : " networks") : "")
                                : (root.bluetoothEnabled && btBackend.hasScanned && btBackend.devices.length > 0
                                    ? btBackend.devices.length + " paired" : "")
                            color: Theme.text
                            opacity: Theme.opacityMuted
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSizeSmall
                        }
                    }

                    Item {
                        width: parent.width
                        // The card's own fixed height minus its padding and
                        // header -- a real viewport, so a long list scrolls
                        // inside the card rather than stretching the panel.
                        height: networksCard.height - networksCard.padding * 2 - netHeader.height - networksCard.spacing
                    Flickable {
                        id: netFlick
                        anchors.fill: parent
                        contentHeight: netColumn.implicitHeight
                        clip: true
                        boundsBehavior: Flickable.StopAtBounds

                        Column {
                            id: netColumn
                            width: netFlick.width
                            spacing: 2

                            Repeater {
                                model: root.wifiEnabled && netHeader.tab === "wifi" ? wifiBackend.networks : []
                                delegate: DeviceRow {
                                    required property var modelData
                                    glyph: root.wifiGlyph(modelData.signal)
                                    title: modelData.ssid
                                    detail: (modelData.connected ? "Connected \u00b7 " : "") + modelData.signal + "%"
                                        + (root.isOpenNetwork(modelData.security) ? " \u00b7 Open" : " \u00b7 Secured")
                                    connected: modelData.connected
                                    actionText: modelData.connected ? "" : "Connect"
                                    canForget: modelData.known
                                    onActionClicked: wifiBackend.connectTo(modelData.ssid, modelData.security)
                                    onForgetClicked: wifiBackend.forget(modelData.ssid)
                                }
                            }
                            EmptyLine {
                                visible: netHeader.tab === "wifi" && (!root.wifiEnabled || !wifiBackend.hasScanned || wifiBackend.networks.length === 0)
                                text: !root.wifiEnabled ? "Wi-Fi is off"
                                    : (!wifiBackend.hasScanned ? "Scanning\u2026" : "No networks found")
                            }

                            Repeater {
                                model: root.bluetoothEnabled && netHeader.tab === "bt" ? btBackend.devices : []
                                delegate: DeviceRow {
                                    required property var modelData
                                    glyph: modelData.connected ? "\u{f00b1}" : "\u{f00af}"
                                    title: modelData.name
                                    // Battery as a glyph + number: the word "battery"
                                    // was what got elided on a connected row
                                    // (its Disconnect chip is the widest action).
                                    detail: (modelData.connected ? "Connected" : "Paired")
                                        + (modelData.battery >= 0 ? " \u00b7 \u{f0079} " + modelData.battery + "%" : "")
                                    connected: modelData.connected
                                    actionText: modelData.connected ? "Disconnect" : "Connect"
                                    canForget: true
                                    onActionClicked: btBackend.toggleConnect(modelData.mac, modelData.connected)
                                    onForgetClicked: btBackend.forget(modelData.mac)
                                }
                            }
                            EmptyLine {
                                visible: netHeader.tab === "bt" && (!root.bluetoothEnabled || !btBackend.hasScanned || btBackend.devices.length === 0)
                                text: !root.bluetoothEnabled ? "Bluetooth is off"
                                    : (!btBackend.hasScanned ? "Looking for devices\u2026" : "No paired devices")
                            }
                        }
                    }
                    ScrollHint {
                        flickable: netFlick
                        height: parent.height
                        anchors.right: parent.right
                        anchors.rightMargin: -networksCard.padding + 4
                    }
                    }
                }
            }

            // ---- tertiary: this machine ----
            Text {
                id: footer
                width: parent.width
                text: [systemInfo.osName, systemInfo.kernel, systemInfo.hostname, systemInfo.uptime ? "up " + systemInfo.uptime : ""]
                    .filter((s) => s && s.length > 0).join("  ·  ")
                color: Theme.text
                opacity: Theme.opacityMuted
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSizeSmall
                elide: Text.ElideRight
            }
        }
    }

    function wifiGlyph(signal) {
        if (signal >= 80) return "\u{f0928}";
        if (signal >= 60) return "\u{f0925}";
        if (signal >= 40) return "\u{f0922}";
        if (signal >= 20) return "\u{f091f}";
        return "\u{f092f}";
    }
    function isOpenNetwork(security) { return !security || security === "--" || security === ""; }

    // A pickable audio device in the Output/Input lists.
    component DeviceChoice: Rectangle {
        id: choice
        property string label: ""
        property bool selected: false
        signal picked()
        width: parent ? parent.width : 0
        height: 30
        radius: Theme.roundingXs
        color: choiceArea.containsMouse ? Theme.layer2Hover : "transparent"
        Text {
            anchors.verticalCenter: parent.verticalCenter
            anchors.left: parent.left
            anchors.leftMargin: Theme.padSm
            anchors.right: choiceCheck.left
            anchors.rightMargin: Theme.padSm
            text: choice.label
            color: choice.selected ? Theme.textActive : Theme.text
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSizeSmaller
            elide: Text.ElideRight
        }
        Text {
            id: choiceCheck
            anchors.verticalCenter: parent.verticalCenter
            anchors.right: parent.right
            anchors.rightMargin: Theme.padSm
            visible: choice.selected
            text: ""
            color: Theme.accent
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSizeSmall
        }
        MouseArea {
            id: choiceArea
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: choice.picked()
        }
    }

    // The honest "nothing here" line for a list section -- off, loading or
    // empty -- at the same left inset as a row's name, so an empty section
    // still lines up with the populated one above or below it.
    component EmptyLine: Text {
        width: parent ? parent.width : 0
        height: 36
        leftPadding: Theme.padSm + 20 + Theme.padSm
        verticalAlignment: Text.AlignVCenter
        color: Theme.text
        opacity: Theme.opacityMuted
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fontSizeSmaller
        elide: Text.ElideRight
    }



    // ==================== MEDIA ====================
    // A real three-region composition (art | title/transport | secondary
    // info) spanning the pane's actual available width, replacing a single
    // column that was hard-capped at 420px and centered -- on this panel's
    // real ~648px content width that cap alone was the entire "huge unused
    // horizontal space" complaint, independent of anything inside the
    // column. There is no lyrics source anywhere in this codebase, so the
    // right region shows what MPRIS actually publishes beyond title/artist
    // instead of standing in for lyrics: which app is playing, the album,
    // and a real per-player volume control (see MediaBackend.qml).
    Component {
        id: mediaPane
        // Owns the whole pane viewport and centres whichever content it has,
        // so neither a short player layout nor the empty state leaves a dead
        // band under it now that panes are top-aligned.
        Item {
            width: parent ? parent.width : implicitWidth
            implicitHeight: Math.max(loader.implicitHeight, root.paneAvailableHeight)
            Loader {
                id: loader
                width: parent ? parent.width : implicitWidth
                anchors.verticalCenter: parent.verticalCenter
                sourceComponent: mediaBackend.available ? mediaPlayerContent : mediaEmptyContent
            }
        }
    }

    Component {
        id: mediaPlayerContent
        Row {
            id: mediaRow
            width: parent ? parent.width : implicitWidth
            spacing: Theme.padLg
            // Bigger than before (168/152): the whole point of the
            // three-region composition was to use the panel's real width,
            // and a small art tile plus small type in the middle of a wide
            // row was still reading as "content compressed into the
            // middle" even with real regions either side of it.
            // Art and the info column give width back to the centre column,
            // which carries the title -- this pane's primary element.
            readonly property real artSize: 184
            readonly property real sideWidth: 144

            Item {
                width: mediaRow.artSize
                height: mediaRow.artSize
                anchors.verticalCenter: parent.verticalCenter

                RectangularShadow {
                    anchors.fill: art
                    radius: art.radius
                    color: Theme.shadowColor
                    blur: Theme.elevationBlur(2)
                    spread: Theme.elevationSpread(2)
                    offset.y: Theme.elevationOffsetY(2)
                }
                Rectangle {
                    id: art
                    anchors.fill: parent
                    radius: Theme.roundingLg
                    color: Theme.layer1
                    clip: true
                    Image {
                        anchors.fill: parent
                        source: mediaBackend.artUrl
                        fillMode: Image.PreserveAspectCrop
                        asynchronous: true
                        visible: status === Image.Ready
                    }
                    Text {
                        anchors.centerIn: parent
                        visible: mediaBackend.artUrl.length === 0
                        text: "\uf001"
                        font.family: Theme.fontFamily
                        // Large placeholder icon, not body text -- the
                        // Display tier is the right token for a glyph this
                        // size even though it's an icon, not a number.
                        font.pixelSize: Theme.fontSizeDisplay
                        color: Theme.text
                        opacity: 0.4
                    }
                }
            }

            // ---- center: title/artist, transport, playback controls ----
            Column {
                width: mediaRow.width - mediaRow.artSize - mediaRow.sideWidth - mediaRow.spacing * 2
                anchors.verticalCenter: parent.verticalCenter
                spacing: Theme.padMd

                Column {
                    width: parent.width
                    spacing: Theme.padXs
                    Text {
                        width: parent.width
                        text: mediaBackend.title
                        color: Theme.textActive
                        font.family: Theme.fontFamily
                        // Raised from fontSizeLarger(15): a track title is
                        // this pane's own equivalent of the Dashboard's
                        // hero clock -- the one thing the whole composition
                        // is organized around -- and reading at almost the
                        // same size as a card's own title label undercut
                        // that entirely. Wraps up to 2 lines rather than
                        // eliding to one -- real track/video titles routinely
                        // run long, and at this size a single-line elide cut
                        // most of them down to a few words (the same
                        // truncation-vs-neighboring-space lesson as
                        // ToggleChip's "Do Not Disturb" fix earlier).
                        // Wrap (not WordWrap): breaks between words when it
                        // can, inside a word only when one word alone is
                        // wider than the line -- never an orphaned "An" over
                        // "Extraordina...".
                        wrapMode: Text.Wrap
                        maximumLineCount: 2
                        elide: Text.ElideRight
                        font.pixelSize: Theme.fontSizeHeadline
                        font.weight: Font.DemiBold
                    }
                    Text {
                        font.family: Theme.fontFamily
                        width: parent.width
                        visible: mediaBackend.artist.length > 0
                        text: mediaBackend.artist
                        color: Theme.text
                        opacity: Theme.opacitySecondary
                        font.pixelSize: Theme.fontSizeNormal
                        elide: Text.ElideRight
                    }
                }

                Column {
                    width: parent.width
                    spacing: 2
                    visible: mediaBackend.seekable
                    height: visible ? implicitHeight : 0
                    SliderRow {
                        width: parent.width
                        showValue: false
                        from: 0
                        to: Math.max(1, mediaBackend.length)
                        value: root.mediaPosition
                        onChanged: (v) => mediaBackend.seekTo(v)
                    }
                    Row {
                        width: parent.width
                        Text {
                            font.family: Theme.fontFamily
                            text: mediaBackend.formatTime(root.mediaPosition)
                            color: Theme.text
                            opacity: 0.6
                            font.pixelSize: Theme.fontSizeSmall
                            width: parent.width / 2
                        }
                        Text {
                            font.family: Theme.fontFamily
                            text: mediaBackend.formatTime(mediaBackend.length)
                            color: Theme.text
                            opacity: 0.6
                            font.pixelSize: Theme.fontSizeSmall
                            width: parent.width / 2
                            horizontalAlignment: Text.AlignRight
                        }
                    }
                }

                Row {
                    spacing: Theme.padLg

                    IconButton {
                        visible: mediaBackend.shuffleSupported
                        glyph: "\uf074"
                        size: Theme.iconMd
                        tint: mediaBackend.shuffle ? Theme.accent : null
                        onClicked: mediaBackend.toggleShuffle()
                    }
                    IconButton { glyph: "\uf048"; size: Theme.iconMd; onClicked: mediaBackend.previous() }
                    // The one hero-scale icon in this row on purpose -- the
                    // primary transport action, matching the Dashboard's
                    // own "one dominant element" language rather than five
                    // same-weight buttons in a row.
                    IconButton { glyph: mediaBackend.playing ? "\uf04c" : "\uf04b"; size: Theme.iconLg; onClicked: mediaBackend.playPause() }
                    IconButton { glyph: "\uf051"; size: Theme.iconMd; onClicked: mediaBackend.next() }
                    IconButton {
                        visible: mediaBackend.loopSupported
                        glyph: "\uf021"
                        size: Theme.iconMd
                        tint: mediaBackend.loopState !== 0 ? Theme.accent : null
                        onClicked: mediaBackend.cycleLoop()
                    }
                }
            }

            // ---- right: secondary info, real content instead of a lyrics
            // placeholder this codebase has no data source for ----
            Column {
                width: mediaRow.sideWidth
                anchors.verticalCenter: parent.verticalCenter
                spacing: Theme.padMd

                Column {
                    width: parent.width
                    spacing: 2
                    visible: mediaBackend.source.length > 0
                    Text {
                        text: "Playing via"
                        color: Theme.text
                        opacity: Theme.opacityMuted
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSizeSmall
                    }
                    Text {
                        width: parent.width
                        text: mediaBackend.source
                        color: Theme.textActive
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSizeSmaller
                        elide: Text.ElideRight
                    }
                }

                Column {
                    width: parent.width
                    spacing: 2
                    visible: mediaBackend.album.length > 0
                    Text {
                        text: "Album"
                        color: Theme.text
                        opacity: Theme.opacityMuted
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSizeSmall
                    }
                    Text {
                        width: parent.width
                        text: mediaBackend.album
                        color: Theme.textActive
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSizeSmaller
                        elide: Text.ElideRight
                        wrapMode: Text.WordWrap
                        maximumLineCount: 2
                    }
                }

                Column {
                    width: parent.width
                    spacing: Theme.padXs
                    visible: mediaBackend.volumeSupported
                    Text {
                        text: "Player volume"
                        color: Theme.text
                        opacity: Theme.opacityMuted
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSizeSmall
                    }
                    SliderRow {
                        width: parent.width
                        from: 0; to: 100
                        value: Math.round(mediaBackend.volume * 100)
                        onChanged: (v) => mediaBackend.setVolume(v / 100)
                    }
                }
            }
        }
    }

    // The honest empty state: an icon and two lines centred in the pane,
    // straight on the panel. It used to sit in a bordered card the size of
    // the pane -- a frame around nothing, the clearest case of a border that
    // communicated no boundary worth drawing.
    Component {
        id: mediaEmptyContent
        Column {
            width: parent ? parent.width : implicitWidth
            spacing: Theme.padSm
            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                text: "\uf001"
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSizeDisplay
                color: Theme.text
                opacity: 0.35
                bottomPadding: Theme.padSm
            }
            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                text: "Nothing playing"
                color: Theme.textActive
                opacity: Theme.opacityFaint
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSizeLarger
                font.weight: Font.Medium
            }
            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                text: "Media from any MPRIS player will appear here"
                color: Theme.text
                opacity: Theme.opacityMuted
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSizeSmaller
            }
        }
    }

    // ==================== PERFORMANCE ====================
    // One monitoring surface, then two small utility groups -- sized to fit
    // the pane's viewport without scrolling.
    //
    //   System   CPU / GPU / Memory as three hero readouts (the numbers are
    //            the point, so they get the big type), with Storage and
    //            Network as one quieter secondary line underneath -- they
    //            change slowly and are glanced at, not watched.
    //   Clipboard | Actions   side by side: the recent entries are shown
    //            directly (the old card repeated "3 items" twice, once as a
    //            row and once as a collapsed Expandable, and showed nothing),
    //            and the screenshot/session actions beside it.
    //
    // Cells are separated by space, not by vertical rules: the old dividers
    // ran into the ends of the level bars, which read as one broken line.
    // GPU shows a genuine "Unavailable" (never a made-up value) when this
    // machine exposes no utilisation source -- see PerformanceService.
    Component {
        id: performancePane
        Column {
            id: perf
            width: parent ? parent.width : implicitWidth
            spacing: ShellSurface.cardGap

            Card {
                id: systemCard
                width: parent.width
                title: "System"
                spacing: Theme.padLg

                Row {
                    width: parent.width
                    spacing: Theme.pad2xl
                    readonly property real cellWidth: (width - spacing * 2) / 3
                    Metric {
                        width: parent.cellWidth
                        label: "CPU"
                        value: Math.round(PerformanceService.cpuPercent) + "%"
                        fraction: PerformanceService.cpuPercent / 100
                    }
                    Metric {
                        width: parent.cellWidth
                        label: "GPU"
                        available: PerformanceService.gpuAvailable
                        value: Math.round(PerformanceService.gpuPercent) + "%"
                        fraction: PerformanceService.gpuPercent / 100
                    }
                    Metric {
                        width: parent.cellWidth
                        label: "Memory"
                        value: Math.round(PerformanceService.memPercent) + "%"
                        fraction: PerformanceService.memPercent / 100
                    }
                }

                Rectangle { width: parent.width; height: 1; color: Theme.withAlpha(Theme.borderTint, 0.08) }

                Row {
                    width: parent.width
                    spacing: Theme.pad2xl
                    readonly property real cellWidth: (width - spacing) / 2
                    SecondaryMetric {
                        width: parent.cellWidth
                        label: "Storage"
                        value: Math.round(PerformanceService.diskPercent) + "%"
                        detail: PerformanceService.diskUsedLabel
                        fraction: PerformanceService.diskPercent / 100
                    }
                    SecondaryMetric {
                        width: parent.cellWidth
                        label: "Network"
                        value: PerformanceService.networkRateKBs >= 1024
                            ? (PerformanceService.networkRateKBs / 1024).toFixed(1) + " MB/s"
                            : Math.round(PerformanceService.networkRateKBs) + " KB/s"
                        detail: "rx + tx"
                        fraction: -1
                    }
                }
            }

            Row {
                id: utilRow
                width: parent.width
                spacing: ShellSurface.cardGap
                // Actions' content sets the floor; Clipboard is a viewport
                // that fits whatever it is given (reading its implicit
                // height here would be a cycle -- it sizes itself from this).
                height: Math.max(actionsCard.implicitHeight,
                                 root.paneAvailableHeight - systemCard.implicitHeight - perf.spacing)

                Card {
                    id: clipCard
                    width: (parent.width - parent.spacing) * 0.58
                    height: parent.height
                    title: "Clipboard"
                    Item {
                        width: parent.width
                        height: clipCard.height - clipCard.padding * 2 - clipCard.titleHeight
                        Flickable {
                            id: clipFlick
                            anchors.fill: parent
                            contentHeight: clipList.implicitHeight
                            clip: true
                            boundsBehavior: Flickable.StopAtBounds
                            Column {
                                id: clipList
                                width: clipFlick.width
                                Repeater {
                                    model: clipboardBackend.entries
                                    delegate: Rectangle {
                                        required property var modelData
                                        width: clipList.width
                                        height: 30
                                        radius: Theme.roundingXs
                                        color: clipArea.containsMouse ? Theme.layer2Hover : "transparent"
                                        Behavior on color { ColorAnimation { duration: Theme.durationFast } }
                                        Text {
                                            anchors.verticalCenter: parent.verticalCenter
                                            x: Theme.padSm
                                            width: parent.width - Theme.padSm * 2
                                            text: parent.modelData.preview.replace(/\s+/g, " ")
                                            color: Theme.text
                                            font.family: Theme.fontFamily
                                            font.pixelSize: Theme.fontSizeSmaller
                                            elide: Text.ElideRight
                                        }
                                        MouseArea {
                                            id: clipArea
                                            anchors.fill: parent
                                            hoverEnabled: true
                                            cursorShape: Qt.PointingHandCursor
                                            onClicked: clipboardBackend.copyEntry(parent.modelData.raw)
                                        }
                                    }
                                }
                            }
                        }
                        ScrollHint {
                            flickable: clipFlick
                            height: parent.height
                            anchors.right: parent.right
                            anchors.rightMargin: -clipCard.padding + 4
                        }
                        Text {
                            anchors.centerIn: parent
                            visible: clipboardBackend.entries.length === 0
                            text: "Clipboard history is empty"
                            color: Theme.text
                            opacity: Theme.opacityMuted
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSizeSmaller
                        }
                    }
                }
                // Refresh lives on the card's title line, not as a row of
                // its own.
                IconButton {
                    parent: clipCard
                    x: clipCard.width - width - Theme.padSm
                    y: Theme.padXs + 2
                    glyph: "\uf021"
                    size: 24
                    onClicked: clipboardBackend.refresh()
                }

                Card {
                    id: actionsCard
                    width: (parent.width - parent.spacing) * 0.42
                    height: parent.height
                    title: "Actions"
                    Row {
                        width: parent.width
                        spacing: Theme.padSm
                        GlassButton {
                            text: "Region"
                            width: (parent.width - parent.spacing) / 2
                            onClicked: root.takeScreenshot(true)
                        }
                        GlassButton {
                            text: "Screen"
                            width: (parent.width - parent.spacing) / 2
                            onClicked: root.takeScreenshot(false)
                        }
                    }
                    Text {
                        text: "Saved to Pictures/Screenshots"
                        width: parent.width
                        color: Theme.text
                        opacity: Theme.opacityMuted
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSizeSmall
                        elide: Text.ElideRight
                    }
                    Row {
                        id: powerRow
                        width: parent.width
                        readonly property real slot: width / 4
                        Item {
                            width: powerRow.slot; height: Theme.iconMd
                            IconButton { anchors.centerIn: parent; glyph: "\uf023"; size: Theme.iconMd; onClicked: Quickshell.execDetached(["hyprlock"]) }
                        }
                        Item {
                            width: powerRow.slot; height: Theme.iconMd
                            // NOT `hyprctl dispatch exit`: this system launches
                            // Hyprland through `start-hyprland`, Hyprland's own
                            // official watchdog binary, which automatically
                            // restarts Hyprland on anything it reads as a "not
                            // clean" exit -- confirmed via the watchdog's own
                            // embedded strings ("Hyprland exit not-cleanly,
                            // restarting"). `dispatch exit` is the textbook-correct
                            // way to close a plain Hyprland session, but on this
                            // launcher it doesn't complete the watchdog's clean-exit
                            // handshake, so the compositor just silently respawns --
                            // reboot/shutdown "worked" only because they tear down
                            // the whole system, watchdog included, not because the
                            // compositor-level exit path was ever fine.
                            // `loginctl terminate-session $XDG_SESSION_ID` ends
                            // JUST this graphical session at the systemd-logind
                            // layer, the same mechanism a real desktop's own "Log
                            // out" uses, bypassing the compositor (and its
                            // watchdog) entirely -- WITHOUT `terminate-user`'s
                            // blast radius. `terminate-user` kills every session
                            // AND the whole user@.service slice; on this machine
                            // that includes the sddm-helper process that IS this
                            // session's logind session leader, so killing it made
                            // SDDM read the session's own clean end as a helper
                            // "crash" and give up restarting the greeter instead
                            // of returning to it -- reproduced live: a real
                            // terminate-user logout left a black screen with no
                            // greeter until a manual reboot. XDG_SESSION_ID is
                            // fixed for this process's whole lifetime (set once by
                            // logind/PAM when the session started), so reading it
                            // via Quickshell.env here is exactly as reliable as
                            // reading USER above it.
                            IconButton {
                                anchors.centerIn: parent
                                glyph: "\uf2f5"; size: Theme.iconMd
                                onClicked: {
                                    const sid = Quickshell.env("XDG_SESSION_ID");
                                    if (sid) {
                                        Quickshell.execDetached(["loginctl", "terminate-session", sid]);
                                    } else {
                                        // XDG_SESSION_ID missing for some reason. Ask
                                        // logind directly which session is this user's
                                        // DISPLAY session rather than falling back to
                                        // `terminate-user` -- that command is exactly
                                        // what caused the black-screen-no-greeter
                                        // failure this whole fix exists to remove, so
                                        // reaching for it on a technicality would just
                                        // reintroduce the bug on the rarer path.
                                        // Verified to resolve to the same session id
                                        // as the env var, including with the env var
                                        // explicitly unset. Does nothing if even that
                                        // fails: a Log Out button that no-ops is a far
                                        // better failure than one that strands the
                                        // machine with no greeter.
                                        Quickshell.execDetached(["sh", "-c",
                                            'sid="$(loginctl show-user "$(id -un)" -p Display --value 2>/dev/null)"; '
                                            + '[ -n "$sid" ] && exec loginctl terminate-session "$sid"']);
                                    }
                                }
                            }
                        }
                        Item {
                            width: powerRow.slot; height: Theme.iconMd
                            IconButton { anchors.centerIn: parent; glyph: "\uf2ea"; size: Theme.iconMd; onClicked: Quickshell.execDetached(["systemctl", "reboot"]) }
                        }
                        Item {
                            width: powerRow.slot; height: Theme.iconMd
                            IconButton { anchors.centerIn: parent; glyph: "\uf011"; size: Theme.iconMd; destructive: true; onClicked: Quickshell.execDetached(["systemctl", "poweroff"]) }
                        }
                    }
                }
            }
        }
    }

    // A hero readout: label, big number, thin bar. `available: false` is the
    // honest no-data state (GPU without a utilisation source).
    component Metric: Column {
        id: metric
        property string label: ""
        property string value: ""
        property real fraction: 0
        property bool available: true
        spacing: Theme.padXs
        Text {
            text: metric.label
            color: Theme.text
            opacity: Theme.opacityMuted
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSizeSmall
            font.letterSpacing: 0.5
        }
        Text {
            text: metric.available ? metric.value : "\u2014"
            color: Theme.textActive
            opacity: metric.available ? 1 : 0.4
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSizeExtraLarge
            font.weight: Font.Light
        }
        LevelBar {
            width: parent.width
            implicitHeight: 4
            visible: metric.available
            value: metric.fraction
        }
        Text {
            visible: !metric.available
            height: 4
            verticalAlignment: Text.AlignVCenter
            text: "Unavailable"
            color: Theme.text
            opacity: Theme.opacityMuted
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSizeSmall
        }
    }

    // A secondary readout: one line -- label, value, detail -- over a thin
    // bar (fraction < 0 for rates, which have no "full").
    component SecondaryMetric: Column {
        id: sm
        property string label: ""
        property string value: ""
        property string detail: ""
        property real fraction: 0
        spacing: Theme.padXs + 2
        Row {
            width: parent.width
            spacing: Theme.padSm
            Text {
                anchors.baseline: smValue.baseline
                text: sm.label
                color: Theme.text
                opacity: Theme.opacityMuted
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSizeSmall
                font.letterSpacing: 0.5
            }
            Text {
                id: smValue
                text: sm.value
                color: Theme.textActive
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSizeLarger
                font.weight: Font.Medium
            }
            Text {
                anchors.baseline: smValue.baseline
                text: sm.detail
                color: Theme.text
                opacity: Theme.opacityMuted
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSizeSmall
            }
        }
        LevelBar {
            width: parent.width
            implicitHeight: 4
            visible: sm.fraction >= 0
            value: Math.max(0, sm.fraction)
        }
    }



    // Tracks the one live password dialog, if any -- see onPasswordNeeded
    // below for why there must never be more than one at a time.
    property var _activeWifiDialog: null

    WifiBackend {
        id: wifiBackend
        radioOn: root.wifiEnabled
        onPasswordNeeded: (ssid) => {
            // Clicking "Connect" on a second network before resolving the
            // first password prompt used to create a SECOND dialog while
            // wifiDialogOpen stayed a single shared boolean: closing
            // whichever dialog happened to be first set wifiDialogOpen back
            // to false even though the second one was still open, silently
            // re-arming TopBar's full-screen click-outside catcher underneath
            // it. The next click into that still-open dialog's password
            // field would then be swallowed exactly like the original bug
            // this flag exists to prevent -- closing Quick Settings and, since
            // the dialog is a child of `root`, destroying it mid-entry.
            // Only ever one dialog now: a new request replaces, rather than
            // joins, any dialog already open.
            if (root._activeWifiDialog) {
                root._activeWifiDialog.visible = false;
            }
            const dlg = Qt.createComponent("WifiPasswordDialog.qml").createObject(root, { ssid: ssid });
            root._activeWifiDialog = dlg;
            // WifiPasswordDialog is a real, separate top-level window (a
            // FloatingWindow, not a rectangle inside this panel's own
            // surface) -- same architectural gap as TaskbarManager's
            // Add-Shortcut dialog. Without wifiDialogOpen, TopBar.qml's own
            // full-screen click-outside-to-dismiss region has no way to
            // know this dialog exists, so clicking into its password field
            // to type would be caught by that catcher instead and close
            // Quick Settings -- destroying this dialog (a child of `root`)
            // before the user could enter a password at all.
            root.wifiDialogOpen = true;
            dlg.visibleChanged.connect(() => {
                if (!dlg.visible) {
                    // Guarded on identity: a stale close from a dialog that
                    // was already replaced must never clear the flag (or the
                    // reference) for the CURRENT one.
                    if (root._activeWifiDialog === dlg) {
                        root._activeWifiDialog = null;
                        root.wifiDialogOpen = false;
                    }
                }
            });
            dlg.submitted.connect((password) => wifiBackend.connectWithPassword(ssid, password));
            dlg.visible = true;
        }
    }
    BluetoothBackend { id: btBackend; radioOn: root.bluetoothEnabled }
    AudioDeviceBackend { id: audioDeviceBackend }
    SystemInfoBackend { id: systemInfo }
    WorldClockBackend { id: worldClock }
    BrightnessBackend { id: brightnessBackend }
    MediaBackend { id: mediaBackend }
    ClipboardBackend { id: clipboardBackend; Component.onCompleted: refresh() }
}
