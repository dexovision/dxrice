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
    onCurrentTabChanged: root._syncPerformanceActive()
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
                y: tabBar.height - height
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
                readonly property real paneHeight: (paneLoader.item ? paneLoader.item.implicitHeight : 0) + Theme.padMd * 2
                anchors.fill: parent
                contentHeight: paneHeight
                clip: true
                Behavior on contentY { NumberAnimation { duration: Theme.durationFast } }

                Loader {
                    id: paneLoader
                    x: Theme.padXl
                    // Centered, not pinned to the top: viewportHeight is a
                    // fixed constant sized for Overview's content (see the
                    // layout contract above) so it stays independent of any
                    // per-tick-changing implicitHeight -- but that means a
                    // shorter tab (Media, once its content-cap width bug was
                    // fixed, is ~200px against a 420px viewport) left a
                    // literal empty rectangle pinned below it. paneLoader's
                    // own height already tracks its *loaded* item's
                    // implicitHeight (a one-time value per tab switch, not a
                    // ticking one), so centering against that is a paint-time
                    // position, never a source of the restart-loop bug.
                    y: Math.max(Theme.padMd, (paneFlickable.height - height) / 2)
                    width: parent.width - Theme.padXl * 2
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
    // A real 3-region dashboard home -- LEFT (connectivity + device
    // identity), CENTER (a dominant hero clock + Audio, the one control
    // surface people reach for most), RIGHT (networks + world clock) --
    // instead of a flat two-column settings list. Every card here is the
    // same real functionality/data that existed before, just given an
    // actual dashboard composition with a genuine focal point instead of
    // two evenly-weighted columns and no hierarchy.
    Component {
        id: overviewPane
        Row {
            width: parent ? parent.width : implicitWidth
            spacing: Theme.pad2xl

            Column {
                id: leftCol
                width: parent.width * 0.27
                spacing: ShellSurface.cardGap

                Card {
                    width: parent.width
                    title: "Connectivity"
                    // 2x2 rather than a 4-wide row: at this card's real
                    // width (now the narrow left column, ~27% of the
                    // dashboard) a row of four 74px tiles was the exact
                    // cause of "Do Not Disturb" truncating -- not
                    // neighboring cards, the row itself had no room. Two
                    // columns gives each tile its full natural width
                    // regardless of card width, fixed at the composition
                    // level rather than by shrinking text or widening the
                    // whole dashboard.
                    Grid {
                        columns: 2
                        spacing: Theme.padSm
                        ToggleChip {
                            glyph: ""; label: "Wi-Fi"
                            active: root.wifiEnabled
                            onToggled: (next) => root.setWifi(next)
                        }
                        ToggleChip {
                            glyph: ""; label: "Bluetooth"
                            active: root.bluetoothEnabled
                            onToggled: (next) => root.setBluetooth(next)
                        }
                        ToggleChip {
                            glyph: ""; label: "Do Not Disturb"
                            active: root.dndActive
                            onToggled: (next) => root.setDnd(next)
                        }
                        ToggleChip {
                            glyph: "\u23fb"; label: "Keep Awake"
                            active: root.idleInhibited
                            onToggled: (next) => root.setIdleInhibit(next)
                        }
                    }
                }

                Column {
                    width: parent.width
                    spacing: Theme.padXs
                    Text {
                        text: "This device"
                        color: Theme.text
                        opacity: Theme.opacityMuted
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSizeSmall
                    }
                    Text {
                        width: parent.width
                        text: systemInfo.osName + " \u00b7 " + systemInfo.kernel
                        color: Theme.textActive
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSizeSmaller
                        elide: Text.ElideRight
                    }
                    Text {
                        width: parent.width
                        text: systemInfo.hostname + " \u00b7 " + systemInfo.user + " \u00b7 up " + systemInfo.uptime
                        color: Theme.text
                        opacity: Theme.opacitySecondary
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSizeSmaller
                        elide: Text.ElideRight
                    }
                }
            }

            // CENTER: the dominant region -- a real focal point (the shell
            // never had one), then the control people actually touch most.
            Column {
                id: centerCol
                width: parent.width - leftCol.width - rightCol.width - parent.spacing * 2
                spacing: Theme.padLg

                Column {
                    id: heroClock
                    width: parent.width
                    spacing: Theme.padXs
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
                    }
                    Text {
                        text: heroClock.dateText
                        color: Theme.text
                        opacity: Theme.opacitySecondary
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSizeNormal
                    }
                }

                Card {
                    width: parent.width
                    title: "Audio"
                    Row {
                        width: parent.width
                        spacing: Theme.padSm
                        IconButton {
                            glyph: (root.sink && root.sink.audio && root.sink.audio.muted) ? "" : ""
                            size: Theme.iconSm
                            anchors.verticalCenter: parent.verticalCenter
                            onClicked: if (root.sink && root.sink.audio) root.sink.audio.muted = !root.sink.audio.muted
                        }
                        SliderRow {
                            width: parent.width - 26 - Theme.padSm
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
                            delegate: Rectangle {
                                width: parent.width
                                height: 30
                                radius: Theme.roundingXs
                                color: outArea.containsMouse ? Theme.layer2Hover : "transparent"
                                Text {
                                    anchors.verticalCenter: parent.verticalCenter
                                    anchors.left: parent.left
                                    anchors.leftMargin: Theme.padSm
                                    anchors.right: check.left
                                    text: audioDeviceBackend.label(modelData)
                                    color: Theme.text
                                    font.family: Theme.fontFamily
                                    font.pixelSize: Theme.fontSizeSmaller
                                    elide: Text.ElideRight
                                }
                                Text {
                                    id: check
                                    anchors.verticalCenter: parent.verticalCenter
                                    anchors.right: parent.right
                                    anchors.rightMargin: Theme.padSm
                                    visible: root.sink && root.sink.name === modelData.name
                                    text: "\u2713"
                                    color: Theme.accent
                                }
                                MouseArea {
                                    id: outArea
                                    anchors.fill: parent
                                    hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: audioDeviceBackend.setOutput(modelData)
                                }
                            }
                        }
                    }

                    Row {
                        width: parent.width
                        spacing: Theme.padSm
                        IconButton {
                            glyph: (root.source && root.source.audio && root.source.audio.muted) ? "" : ""
                            size: Theme.iconSm
                            anchors.verticalCenter: parent.verticalCenter
                            onClicked: if (root.source && root.source.audio) root.source.audio.muted = !root.source.audio.muted
                        }
                        SliderRow {
                            width: parent.width - 26 - Theme.padSm
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
                            delegate: Rectangle {
                                width: parent.width
                                height: 30
                                radius: Theme.roundingXs
                                color: inArea.containsMouse ? Theme.layer2Hover : "transparent"
                                Text {
                                    anchors.verticalCenter: parent.verticalCenter
                                    anchors.left: parent.left
                                    anchors.leftMargin: Theme.padSm
                                    anchors.right: inCheck.left
                                    text: audioDeviceBackend.label(modelData)
                                    color: Theme.text
                                    font.family: Theme.fontFamily
                                    font.pixelSize: Theme.fontSizeSmaller
                                    elide: Text.ElideRight
                                }
                                Text {
                                    id: inCheck
                                    anchors.verticalCenter: parent.verticalCenter
                                    anchors.right: parent.right
                                    anchors.rightMargin: Theme.padSm
                                    visible: root.source && root.source.name === modelData.name
                                    text: "\u2713"
                                    color: Theme.accent
                                }
                                MouseArea {
                                    id: inArea
                                    anchors.fill: parent
                                    hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: audioDeviceBackend.setInput(modelData)
                                }
                            }
                        }
                    }

                    Row {
                        width: parent.width
                        spacing: Theme.padSm
                        visible: brightnessBackend.hasBacklight
                        height: visible ? implicitHeight : 0
                        Text { text: "\u2600"; color: Theme.text; opacity: Theme.opacityFaint; anchors.verticalCenter: parent.verticalCenter; width: 26; horizontalAlignment: Text.AlignHCenter }
                        SliderRow {
                            width: parent.width - 26 - Theme.padSm
                            from: 1; to: 100
                            value: brightnessBackend.percent
                            onChanged: (v) => brightnessBackend.set(v)
                        }
                    }
                }
            }

            Column {
                id: rightCol
                width: parent.width * 0.27
                spacing: ShellSurface.cardGap

                Card {
                    width: parent.width
                    title: "Networks"
                    visible: (root.wifiEnabled && wifiBackend.networks.length > 0) || (root.bluetoothEnabled && btBackend.devices.length > 0)
                    height: visible ? implicitHeight : 0
                    Expandable {
                        width: parent.width
                        visible: root.wifiEnabled && wifiBackend.networks.length > 0
                        height: visible ? implicitHeight : 0
                        title: "Wi-Fi"
                        trailingText: wifiBackend.networks.length + " found"
                        expanded: wifiBackend.networks.length <= 3
                        Repeater {
                            model: wifiBackend.networks
                            delegate: Row {
                                width: parent.width
                                height: 26
                                Text {
                                    text: modelData.ssid
                                    color: Theme.text
                                    font.family: Theme.fontFamily
                                    font.pixelSize: Theme.fontSizeSmaller
                                    anchors.verticalCenter: parent.verticalCenter
                                    width: parent.width - (modelData.connected ? 130 : 150)
                                    elide: Text.ElideRight
                                }
                                Text {
                                    text: modelData.signal + "%"
                                    color: Theme.text
                                    opacity: Theme.opacityMuted
                                    font.pixelSize: Theme.fontSizeSmall
                                    width: 34
                                    anchors.verticalCenter: parent.verticalCenter
                                }
                                Text {
                                    visible: modelData.connected
                                    text: "\u2713"
                                    color: Theme.accent
                                    anchors.verticalCenter: parent.verticalCenter
                                    width: 16
                                }
                                IconButton {
                                    visible: modelData.known
                                    glyph: "_forget"
                                    size: 24
                                    destructive: true
                                    anchors.verticalCenter: parent.verticalCenter
                                    onClicked: wifiBackend.forget(modelData.ssid)
                                }
                                GlassButton {
                                    visible: !modelData.connected
                                    text: "Connect"
                                    variant: "secondary"
                                    anchors.verticalCenter: parent.verticalCenter
                                    onClicked: wifiBackend.connectTo(modelData.ssid, modelData.security)
                                }
                            }
                        }
                    }

                    Expandable {
                        width: parent.width
                        visible: root.bluetoothEnabled && btBackend.devices.length > 0
                        height: visible ? implicitHeight : 0
                        title: "Bluetooth"
                        trailingText: btBackend.devices.length + " paired"
                        expanded: btBackend.devices.length <= 3
                        Repeater {
                            model: btBackend.devices
                            delegate: Row {
                                width: parent.width
                                height: 26
                                Text {
                                    text: modelData.name
                                    color: Theme.text
                                    font.family: Theme.fontFamily
                                    font.pixelSize: Theme.fontSizeSmaller
                                    anchors.verticalCenter: parent.verticalCenter
                                    width: parent.width - (modelData.battery >= 0 ? 190 : 160)
                                    elide: Text.ElideRight
                                }
                                Text {
                                    visible: modelData.battery >= 0
                                    text: modelData.battery + "%"
                                    color: Theme.text
                                    opacity: Theme.opacityMuted
                                    font.pixelSize: Theme.fontSizeSmall
                                    width: 34
                                    anchors.verticalCenter: parent.verticalCenter
                                }
                                IconButton {
                                    glyph: ""
                                    size: 24
                                    destructive: true
                                    anchors.verticalCenter: parent.verticalCenter
                                    onClicked: btBackend.forget(modelData.mac)
                                }
                                GlassButton {
                                    text: modelData.connected ? "Disconnect" : "Connect"
                                    variant: "secondary"
                                    anchors.verticalCenter: parent.verticalCenter
                                    onClicked: btBackend.toggleConnect(modelData.mac, modelData.connected)
                                }
                            }
                        }
                    }
                }

                Card {
                    width: parent.width
                    title: "World Clock"
                    visible: worldClock.cities.length > 0
                    height: visible ? implicitHeight : 0
                        Repeater {
                            model: worldClock.cities
                            delegate: Row {
                                width: parent.width
                                Text { text: modelData.label; color: Theme.text; opacity: Theme.opacityFaint; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSmaller; width: parent.width - 50 }
                                Text { text: modelData.time; color: Theme.textActive; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSmaller; width: 50; horizontalAlignment: Text.AlignRight }
                            }
                        }
                }
            }
        }
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
        Item {
            width: parent ? parent.width : implicitWidth
            implicitHeight: loader.implicitHeight
            Loader {
                id: loader
                width: parent ? parent.width : implicitWidth
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
            readonly property real artSize: 210
            readonly property real sideWidth: 168

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
                        // Hero glyph, deliberately outside the type scale (a single
                        // large placeholder icon, not body text).
                        font.pixelSize: 40
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
                        wrapMode: Text.WordWrap
                        maximumLineCount: 2
                        elide: Text.ElideRight
                        font.pixelSize: Theme.fontSizeExtraLarge
                        font.weight: Font.DemiBold
                    }
                    Text {
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
                        from: 0
                        to: Math.max(1, mediaBackend.length)
                        value: root.mediaPosition
                        onChanged: (v) => mediaBackend.seekTo(v)
                    }
                    Row {
                        width: parent.width
                        Text {
                            text: mediaBackend.formatTime(root.mediaPosition)
                            color: Theme.text
                            opacity: 0.6
                            font.pixelSize: Theme.fontSizeSmall
                            width: parent.width / 2
                        }
                        Text {
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

    // A real, framed empty-state card instead of an icon and a caption
    // floating alone against bare panel -- the same cardTone/border/radius
    // language as everything else in this shell, so "nothing is playing"
    // still reads as a deliberate part of the composition, not an
    // afterthought that happens to render when there's no data. No
    // fabricated player data appears here -- this is honestly empty, just
    // no longer *look* orphaned.
    Component {
        id: mediaEmptyContent
        Item {
            width: parent ? parent.width : implicitWidth
            implicitHeight: 260

            Rectangle {
                anchors.fill: parent
                radius: ShellSurface.cardRadius
                color: Theme.cardTone
                border.width: Theme.borderWidth
                border.color: Theme.borderFaint

                Column {
                    anchors.centerIn: parent
                    spacing: Theme.padSm
                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: "\uf001"
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSizeHero
                        color: Theme.text
                        opacity: Theme.opacityMuted
                    }
                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: "Nothing playing"
                        color: Theme.text
                        opacity: Theme.opacitySecondary
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSizeNormal
                    }
                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: "Media from any MPRIS player will appear here"
                        color: Theme.text
                        opacity: Theme.opacityMuted
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSizeSmall
                    }
                }
            }
        }
    }

    // ==================== PERFORMANCE ====================
    // A real 3-column metric card grid (CPU/Memory/Storage) instead of a
    // stack of label+bar+percentage rows -- matches the shell's Level-2
    // card language (Card.qml) instead of being the one pane in this file
    // still built from plain hairline-divided Columns. GPU and Network
    // cards are intentionally NOT here: there is no backend data source for
    // either yet anywhere in this codebase, and a fake/placeholder card
    // would be worse than the honest gap. Clipboard and the screenshot/
    // power actions are their own cards below, each sized to its own
    // content rather than stretched to fill leftover width -- the old
    // power-action icons scaled to `(width-spacing*3)/4`, which is exactly
    // how they became "four enormous circles" once this pane had real
    // spare width to divide up.
    Component {
        id: performancePane
        Column {
            width: parent ? parent.width : implicitWidth
            spacing: ShellSurface.cardGap

            // Row 1: CPU / GPU / Memory. Row 2: Storage / Network, at the
            // same card width -- two cards using the panel's full width
            // reads as deliberate, not as three cards with a fourth slot
            // left dangling. GPU shows a genuine "unavailable" state
            // (never a fabricated percentage) when this machine has no
            // working GPU-utilization interface -- see PerformanceService's
            // own comment on why no single cross-vendor source exists.
            Row {
                width: parent.width
                spacing: ShellSurface.cardGap
                readonly property real cardWidth: (width - spacing * 2) / 3

                Card {
                    width: parent.cardWidth
                    title: "CPU"
                    Text { text: Math.round(PerformanceService.cpuPercent) + "%"; color: Theme.textActive; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeLarge; font.weight: Font.DemiBold }
                    LevelBar { width: parent.width; value: PerformanceService.cpuPercent / 100 }
                }
                Card {
                    width: parent.cardWidth
                    title: "GPU"
                    Text {
                        visible: PerformanceService.gpuAvailable
                        text: Math.round(PerformanceService.gpuPercent) + "%"
                        color: Theme.textActive
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSizeLarge
                        font.weight: Font.DemiBold
                    }
                    LevelBar { visible: PerformanceService.gpuAvailable; width: parent.width; value: PerformanceService.gpuPercent / 100 }
                    Text {
                        visible: !PerformanceService.gpuAvailable
                        text: "Unavailable"
                        color: Theme.text
                        opacity: Theme.opacityMuted
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSizeNormal
                    }
                }
                Card {
                    width: parent.cardWidth
                    title: "Memory"
                    Text { text: Math.round(PerformanceService.memPercent) + "%"; color: Theme.textActive; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeLarge; font.weight: Font.DemiBold }
                    LevelBar { width: parent.width; value: PerformanceService.memPercent / 100 }
                }
            }

            Row {
                width: parent.width
                spacing: ShellSurface.cardGap
                readonly property real cardWidth: (width - spacing) / 2

                Card {
                    width: parent.cardWidth
                    title: "Storage"
                    Text { text: Math.round(PerformanceService.diskPercent) + "%"; color: Theme.textActive; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeLarge; font.weight: Font.DemiBold }
                    LevelBar { width: parent.width; value: PerformanceService.diskPercent / 100 }
                    Text {
                        visible: PerformanceService.diskUsedLabel.length > 0
                        text: PerformanceService.diskUsedLabel
                        color: Theme.text
                        opacity: Theme.opacityMuted
                        font.pixelSize: Theme.fontSizeSmall
                    }
                }
                Card {
                    width: parent.cardWidth
                    title: "Network"
                    Text {
                        text: PerformanceService.networkRateKBs >= 1024
                            ? (PerformanceService.networkRateKBs / 1024).toFixed(1) + " MB/s"
                            : Math.round(PerformanceService.networkRateKBs) + " KB/s"
                        color: Theme.textActive
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSizeLarge
                        font.weight: Font.DemiBold
                    }
                    Text {
                        text: "combined rx + tx"
                        color: Theme.text
                        opacity: Theme.opacityMuted
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSizeSmall
                    }
                }
            }

            Card {
                width: parent.width
                title: "Clipboard"
                SettingRow {
                    width: parent.width
                    title: "History"
                    subtitle: clipboardBackend.entries.length + " items"
                    IconButton { glyph: "\uf021"; size: Theme.iconSm; onClicked: clipboardBackend.refresh() }
                }
                Expandable {
                    width: parent.width
                    title: "Recent"
                    trailingText: clipboardBackend.entries.length + " items"
                    Repeater {
                        model: clipboardBackend.entries
                        delegate: Rectangle {
                            width: parent.width
                            height: 28
                            radius: Theme.roundingXs
                            color: clipArea.containsMouse ? Theme.layer2Hover : "transparent"
                            Behavior on color { ColorAnimation { duration: Theme.durationFast } }
                            Text {
                                anchors.verticalCenter: parent.verticalCenter
                                anchors.left: parent.left
                                anchors.leftMargin: Theme.padSm
                                width: parent.width - Theme.padSm * 2
                                text: modelData.preview.replace(/\n/g, " ")
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
                                onClicked: clipboardBackend.copyEntry(modelData.raw)
                            }
                        }
                    }
                }
            }

            Card {
                width: parent.width
                title: "Quick Actions"
                Row {
                    width: parent.width
                    spacing: Theme.padSm
                    GlassButton {
                        text: "Region"
                        variant: "secondary"
                        width: (parent.width - parent.spacing) / 2
                        onClicked: root.takeScreenshot(true)
                    }
                    GlassButton {
                        text: "Full Screen"
                        variant: "secondary"
                        width: (parent.width - parent.spacing) / 2
                        onClicked: root.takeScreenshot(false)
                    }
                }
                Row {
                    spacing: Theme.padSm
                    IconButton { glyph: "\uf023"; size: Theme.iconLg; onClicked: Quickshell.execDetached(["hyprlock"]) }
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
                        glyph: "\uf2f5"; size: Theme.iconLg
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
                    IconButton { glyph: "\uf2ea"; size: Theme.iconLg; onClicked: Quickshell.execDetached(["systemctl", "reboot"]) }
                    IconButton { glyph: "\uf011"; size: Theme.iconLg; destructive: true; onClicked: Quickshell.execDetached(["systemctl", "poweroff"]) }
                }
            }
        }
    }



    WifiBackend {
        id: wifiBackend
        radioOn: root.wifiEnabled
        onPasswordNeeded: (ssid) => {
            const dlg = Qt.createComponent("WifiPasswordDialog.qml").createObject(root, { ssid: ssid });
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
