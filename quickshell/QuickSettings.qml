import QtQuick
import QtQuick.Effects
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import Quickshell.Services.Pipewire

// DXrice Quick Settings -- Quickshell rewrite of dxrice_quick_settings.py.
// This is the system-status region's panel: the right-edge waybar strip
// (volume/network/cpu/ram/tray -- see waybar/config-right) is its trigger,
// so it originates from the RIGHT EDGE and slides in horizontally, flush
// against that edge, rather than dropping down from the top the way
// Theme/Taskbar/Calendar do. Anchoring only `right` (no top/bottom) lets
// the compositor center it vertically on screen automatically, matching
// "the user's action explains where the panel came from" -- toggled via
// `qs -p <repo>/quickshell/shell.qml ipc call quicksettings toggle`.
//
// Square right corners (flush with the screen edge it came from), rounded
// left corners only -- the mirror of the top panels' "square where it's
// attached, rounded where it floats free" geometry.
//
// A real tab bar (Overview / Media / Performance) instead of one long
// scroll -- matching the multi-tab dashboards (caelestia's own
// Dashboard/Media/Performance/Weather tabs) this is chasing. Each tab is a
// separate Component behind a Loader, same pattern as ThemeEditor.qml's
// category panes.
PanelWindow {
    id: root
    // shell.qml's LazyLoader destroys this panel entirely the instant
    // closeRequested() fires -- fine for the open animation (which plays
    // naturally on creation) but with nothing to animate the CLOSE, since
    // the object would just be gone mid-transition. requestClose() plays
    // the reveal in reverse first, and only then emits the real
    // closeRequested() shell.qml is listening for. Every internal close
    // path (Escape, the close button, etc.) should call requestClose(),
    // never closeRequested() directly.
    signal closeRequested()
    property bool closing: false
    function requestClose() {
        if (root.closing) return;
        root.closing = true;
        closeTimer.start();
    }
    Timer { id: closeTimer; interval: Theme.durationEnter + 20; onTriggered: root.closeRequested() }

    implicitWidth: 720
    color: "transparent"
    anchors { right: true }
    margins { right: 0 }
    exclusionMode: ExclusionMode.Ignore
    aboveWindows: true
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.namespace: "dxrice-quicksettings"
    focusable: true

    implicitHeight: Math.min(760, (paneLoader.item ? paneLoader.item.implicitHeight : 400) + Theme.padMd * 2 + header.implicitHeight + tabBar.implicitHeight + 8)

    property string currentTab: "overview"
    readonly property var tabs: [
        { id: "overview", glyph: "", label: "Overview" },
        { id: "media", glyph: "", label: "Media" },
        { id: "performance", glyph: "", label: "Performance" },
    ]

    // ---- audio (pipewire, native -- no wpctl subprocess) ----
    PwObjectTracker {
        objects: [Pipewire.defaultAudioSink, Pipewire.defaultAudioSource]
    }
    readonly property var sink: Pipewire.defaultAudioSink
    readonly property var source: Pipewire.defaultAudioSource

    // ---- live stats (read straight from /proc, no subprocess) ----
    property var prevCpuTimes: null
    property real cpuPercent: 0
    property real memPercent: 0

    FileView { id: statFile; path: "/proc/stat" }
    FileView { id: memFile; path: "/proc/meminfo" }

    function sampleCpu() {
        const line = statFile.text().split("\n")[0];
        const fields = line.trim().split(/\s+/).slice(1).map(Number);
        if (root.prevCpuTimes) {
            const prev = root.prevCpuTimes;
            const prevIdle = prev[3] + prev[4];
            const curIdle = fields[3] + fields[4];
            const prevTotal = prev.reduce((a, b) => a + b, 0);
            const curTotal = fields.reduce((a, b) => a + b, 0);
            const totalDelta = curTotal - prevTotal;
            const idleDelta = curIdle - prevIdle;
            root.cpuPercent = totalDelta > 0 ? Math.max(0, Math.min(100, (totalDelta - idleDelta) / totalDelta * 100)) : 0;
        }
        root.prevCpuTimes = fields;
    }

    function sampleMem() {
        const info = {};
        for (const line of memFile.text().split("\n")) {
            const m = line.match(/^(\w+):\s*(\d+)/);
            if (m) info[m[1]] = Number(m[2]);
        }
        const total = info.MemTotal || 1;
        const avail = info.MemAvailable !== undefined ? info.MemAvailable : total;
        root.memPercent = Math.max(0, Math.min(100, (total - avail) / total * 100));
    }

    Timer {
        interval: 1500
        running: true
        repeat: true
        triggeredOnStart: true
        onTriggered: { statFile.reload(); memFile.reload(); root.sampleCpu(); root.sampleMem(); }
    }

    // ---- disk usage (statvfs via df, sampled far less often -- it never
    // changes fast enough to justify /proc-speed polling) ----
    property real diskPercent: 0
    property string diskUsedLabel: ""
    Process {
        id: diskProc
        command: ["df", "-B1", "--output=used,size", "/"]
        stdout: StdioCollector {
            onStreamFinished: {
                const lines = this.text.trim().split("\n");
                if (lines.length < 2) return;
                const parts = lines[1].trim().split(/\s+/).map(Number);
                if (parts.length < 2 || !parts[1]) return;
                root.diskPercent = Math.max(0, Math.min(100, (parts[0] / parts[1]) * 100));
                root.diskUsedLabel = (parts[0] / 1e9).toFixed(0) + " / " + (parts[1] / 1e9).toFixed(0) + " GB";
            }
        }
    }
    Timer { interval: 30000; running: true; repeat: true; triggeredOnStart: true; onTriggered: diskProc.running = true }

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

    Component.onCompleted: root.refreshToggleStates()

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
        root.visible = false;
        screenshotHideTimer.region = region;
        screenshotHideTimer.start();
    }
    Timer {
        id: screenshotHideTimer
        property bool region: true
        interval: 150
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

    // ---- root visuals: a drawer that unrolls DOWN from the bar. Clean
    // rectangular geometry, no decorative seam -- square top (it's flush
    // against the bar it came from), large-radius bottom corners only.
    // The reveal is height + opacity + a small upward settle together,
    // not just a growing rectangle, so opening this reads as "entering
    // from the bar" rather than "a box appearing." ----
    Item {
        id: drawer
        anchors.fill: parent
        clip: true

        // Slides in from the right -- the edge its own trigger (the
        // right-hand waybar status strip) lives on -- instead of dropping
        // down from the top. Width is the animated reveal dimension here;
        // height still just follows the content (root.implicitHeight).
        property real revealWidth: 0
        readonly property real revealProgress: root.implicitWidth > 0 ? Math.min(1, drawer.revealWidth / root.implicitWidth) : 0
        Behavior on revealWidth { NumberAnimation { duration: Theme.durationEnter; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveEmphasizedDecel } }
        Component.onCompleted: revealWidth = root.implicitWidth
        Connections {
            target: root
            function onClosingChanged() { drawer.revealWidth = root.closing ? 0 : root.implicitWidth; }
        }

        RectangularShadow {
            anchors.fill: panelSurface
            radius: 0
            topLeftRadius: Theme.roundingXl
            bottomLeftRadius: Theme.roundingXl
            color: Theme.shadowColor
            blur: Theme.elevationBlur(3)
            spread: Theme.elevationSpread(3)
            offset.y: Theme.elevationOffsetY(3)
            opacity: drawer.revealProgress
        }

        Rectangle {
            id: panelSurface
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            anchors.right: parent.right
            width: Math.max(0, drawer.revealWidth)
            radius: 0
            topLeftRadius: Theme.roundingXl
            bottomLeftRadius: Theme.roundingXl
            color: Theme.bg
            opacity: drawer.revealProgress
            clip: true

            Column {
                id: outer
                width: parent.width
                spacing: 0

                Item {
                    id: header
                    width: parent.width
                    height: 52

                    Text {
                        text: "Quick Settings"
                        color: Theme.textActive
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSizeLarge
                        font.weight: Font.DemiBold
                        anchors.verticalCenter: parent.verticalCenter
                        x: Theme.padLg
                    }
                    Text {
                        id: headerClock
                        color: Theme.text
                        opacity: 0.65
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSizeSmall
                        anchors.right: closeBtn.left
                        anchors.rightMargin: Theme.padMd
                        anchors.verticalCenter: parent.verticalCenter
                    }
                    Timer {
                        interval: 1000; running: true; repeat: true; triggeredOnStart: true
                        onTriggered: headerClock.text = Qt.formatDateTime(new Date(), "h:mm AP")
                    }
                    IconButton {
                        id: closeBtn
                        glyph: "✕"
                        anchors.verticalCenter: parent.verticalCenter
                        x: outer.width - width - Theme.padLg
                        onClicked: root.requestClose()
                    }
                }

                // ---- tab bar: icon + label, accent underline on the
                // active tab -- the actual multi-tab dashboard shape from
                // the reference screenshots, not a single scrolling page. --
                Row {
                    id: tabBar
                    x: Theme.padLg
                    width: parent.width - Theme.padLg * 2
                    height: 40
                    readonly property real tabWidth: width / root.tabs.length

                    Repeater {
                        model: root.tabs
                        delegate: Item {
                            required property var modelData
                            width: tabBar.tabWidth
                            height: tabBar.height
                            readonly property bool active: root.currentTab === modelData.id

                            Column {
                                anchors.centerIn: parent
                                spacing: Theme.padXs
                                Row {
                                    anchors.horizontalCenter: parent.horizontalCenter
                                    spacing: Theme.padSm
                                    Text {
                                        text: modelData.glyph
                                        font.family: Theme.fontFamily
                                        font.pixelSize: Theme.fontSizeNormal
                                        color: parent.parent.parent.active ? Theme.textActive : Theme.text
                                        opacity: parent.parent.parent.active ? 1 : 0.6
                                    }
                                    Text {
                                        text: modelData.label
                                        font.family: Theme.fontFamily
                                        font.pixelSize: Theme.fontSizeSmaller
                                        font.weight: parent.parent.parent.active ? Font.DemiBold : Font.Normal
                                        color: parent.parent.parent.active ? Theme.textActive : Theme.text
                                        opacity: parent.parent.parent.active ? 1 : 0.6
                                    }
                                }
                                Rectangle {
                                    anchors.horizontalCenter: parent.horizontalCenter
                                    width: 22
                                    height: 2
                                    radius: Theme.roundingFull
                                    color: Theme.accent
                                    opacity: parent.parent.active ? 1 : 0
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

                Rectangle {
                    x: Theme.padLg
                    width: parent.width - Theme.padLg * 2
                    height: 1
                    color: Theme.borderIdle
                }

                Flickable {
                    readonly property real paneHeight: (paneLoader.item ? paneLoader.item.implicitHeight : 0) + Theme.padMd * 2
                    width: parent.width
                    height: Math.min(700, paneHeight)
                    contentHeight: paneHeight
                    clip: true
                    Behavior on contentY { NumberAnimation { duration: Theme.durationFast } }

                    Loader {
                        id: paneLoader
                        x: Theme.padLg
                        y: Theme.padMd
                        width: parent.width - Theme.padLg * 2
                        sourceComponent: {
                            switch (root.currentTab) {
                            case "media": return mediaPane;
                            case "performance": return performancePane;
                            default: return overviewPane;
                            }
                        }
                    }
                }
            }
        }
    }

    // ==================== OVERVIEW ====================
    // A composition, not a stack of cards: toggles and sliders sit
    // directly on the panel surface as plain rows, separated by spacing
    // and the occasional hairline -- the only "container" is the panel
    // itself. Secondary information on the right uses quiet section
    // labels instead of card titles.
    Component {
        id: overviewPane
        Row {
            width: parent ? parent.width : implicitWidth
            spacing: Theme.padLg

            Column {
                id: leftCol
                width: (parent.width - parent.spacing) / 2
                spacing: Theme.padLg

                Row {
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

                Text {
                    text: "Audio"
                    color: Theme.text
                    opacity: 0.55
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSizeSmall
                    font.letterSpacing: 0.5
                }
                Row {
                    width: parent.width
                    spacing: Theme.padSm
                    IconButton {
                        glyph: (root.sink && root.sink.audio && root.sink.audio.muted) ? "" : ""
                        size: 26
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
                        size: 26
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
                    Text { text: "\u2600"; color: Theme.text; opacity: 0.85; anchors.verticalCenter: parent.verticalCenter; width: 26; horizontalAlignment: Text.AlignHCenter }
                    SliderRow {
                        width: parent.width - 26 - Theme.padSm
                        from: 1; to: 100
                        value: brightnessBackend.percent
                        onChanged: (v) => brightnessBackend.set(v)
                    }
                }
            }

            Column {
                id: rightCol
                width: (parent.width - parent.spacing) / 2
                spacing: Theme.padLg

                Expandable {
                    width: parent.width
                    visible: root.wifiEnabled && wifiBackend.networks.length > 0
                    height: visible ? implicitHeight : 0
                    title: "Networks"
                    trailingText: wifiBackend.networks.length + " found"
                    expanded: wifiBackend.networks.length <= 3
                    Repeater {
                        model: wifiBackend.networks
                        delegate: Row {
                            width: parent.width
                            height: 32
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
                                opacity: 0.55
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
                    title: "Devices"
                    trailingText: btBackend.devices.length + " paired"
                    expanded: btBackend.devices.length <= 3
                    Repeater {
                        model: btBackend.devices
                        delegate: Row {
                            width: parent.width
                            height: 32
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
                                opacity: 0.55
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

                Column {
                    width: parent.width
                    spacing: Theme.padXs
                    Text {
                        text: "This device"
                        color: Theme.text
                        opacity: 0.55
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
                        opacity: 0.7
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSizeSmaller
                        elide: Text.ElideRight
                    }
                }

                Column {
                    width: parent.width
                    spacing: Theme.padXs
                    Text {
                        text: "World clock"
                        color: Theme.text
                        opacity: 0.55
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSizeSmall
                    }
                    Repeater {
                        model: worldClock.cities
                        delegate: Row {
                            width: parent.width
                            Text { text: modelData.label; color: Theme.text; opacity: 0.85; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSmaller; width: parent.width - 50 }
                            Text { text: modelData.time; color: Theme.textActive; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSmaller; width: 50; horizontalAlignment: Text.AlignRight }
                        }
                    }
                }
            }
        }
    }


    // ==================== MEDIA ====================
    Component {
        id: mediaPane
        Item {
            width: parent ? parent.width : implicitWidth
            implicitHeight: loader.implicitHeight
            Loader {
                id: loader
                width: Math.min(420, parent.width)
                anchors.horizontalCenter: parent.horizontalCenter
                sourceComponent: mediaBackend.available ? mediaPlayerContent : mediaEmptyContent
            }
        }
    }

    Component {
        id: mediaPlayerContent
        Column {
            width: parent ? parent.width : implicitWidth
            spacing: Theme.padLg

            Item {
                width: 220
                height: 220
                anchors.horizontalCenter: parent.horizontalCenter

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
                        text: ""
                        font.family: Theme.fontFamily
                        // Hero glyph, deliberately outside the type scale (a single
                        // large placeholder icon, not body text).
                        font.pixelSize: 48
                        color: Theme.text
                        opacity: 0.4
                    }
                }
            }

            Column {
                width: parent.width
                spacing: 2
                Text {
                    width: parent.width
                    horizontalAlignment: Text.AlignHCenter
                    text: mediaBackend.title
                    color: Theme.textActive
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSizeLarger
                    font.weight: Font.DemiBold
                    elide: Text.ElideRight
                }
                Text {
                    width: parent.width
                    horizontalAlignment: Text.AlignHCenter
                    visible: mediaBackend.artist.length > 0
                    text: mediaBackend.artist
                    color: Theme.text
                    opacity: 0.7
                    font.pixelSize: Theme.fontSizeSmaller
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
                anchors.horizontalCenter: parent.horizontalCenter
                spacing: Theme.padLg

                IconButton {
                    visible: mediaBackend.shuffleSupported
                    glyph: ""
                    size: 30
                    tint: mediaBackend.shuffle ? Theme.accent : null
                    onClicked: mediaBackend.toggleShuffle()
                }
                IconButton { glyph: ""; size: 36; onClicked: mediaBackend.previous() }
                IconButton { glyph: mediaBackend.playing ? "" : ""; size: 46; onClicked: mediaBackend.playPause() }
                IconButton { glyph: ""; size: 36; onClicked: mediaBackend.next() }
                IconButton {
                    visible: mediaBackend.loopSupported
                    glyph: ""
                    size: 30
                    tint: mediaBackend.loopState !== 0 ? Theme.accent : null
                    onClicked: mediaBackend.cycleLoop()
                }
            }
        }
    }

    Component {
        id: mediaEmptyContent
        Column {
            width: parent ? parent.width : implicitWidth
            spacing: Theme.padSm
            Item { width: 1; height: Theme.pad2xl }
            Text {
                width: parent.width
                horizontalAlignment: Text.AlignHCenter
                text: ""
                font.family: Theme.fontFamily
                // Hero glyph, deliberately outside the type scale.
                font.pixelSize: 40
                color: Theme.text
                opacity: 0.3
            }
            Text {
                width: parent.width
                horizontalAlignment: Text.AlignHCenter
                text: "Nothing playing"
                color: Theme.text
                opacity: 0.5
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSizeNormal
            }
            Item { width: 1; height: Theme.pad2xl }
        }
    }

    // ==================== PERFORMANCE ====================
    Component {
        id: performancePane
        Column {
            width: parent ? parent.width : implicitWidth
            spacing: Theme.padLg

            Column {
                width: parent.width
                spacing: Theme.padSm
                Row {
                    width: parent.width
                    Text { text: "CPU"; color: Theme.text; opacity: 0.8; width: 60; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSmaller }
                    LevelBar { width: parent.width - 130; value: root.cpuPercent / 100; anchors.verticalCenter: parent.verticalCenter }
                    Text { text: Math.round(root.cpuPercent) + "%"; color: Theme.text; opacity: 0.8; width: 40; horizontalAlignment: Text.AlignRight; font.pixelSize: Theme.fontSizeSmaller }
                }
                Row {
                    width: parent.width
                    Text { text: "Memory"; color: Theme.text; opacity: 0.8; width: 60; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSmaller }
                    LevelBar { width: parent.width - 130; value: root.memPercent / 100; anchors.verticalCenter: parent.verticalCenter }
                    Text { text: Math.round(root.memPercent) + "%"; color: Theme.text; opacity: 0.8; width: 40; horizontalAlignment: Text.AlignRight; font.pixelSize: Theme.fontSizeSmaller }
                }
                Row {
                    width: parent.width
                    Text { text: "Disk"; color: Theme.text; opacity: 0.8; width: 60; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSmaller }
                    LevelBar { width: parent.width - 130; value: root.diskPercent / 100; anchors.verticalCenter: parent.verticalCenter }
                    Text { text: Math.round(root.diskPercent) + "%"; color: Theme.text; opacity: 0.8; width: 40; horizontalAlignment: Text.AlignRight; font.pixelSize: Theme.fontSizeSmaller }
                }
                Text {
                    visible: root.diskUsedLabel.length > 0
                    text: root.diskUsedLabel
                    color: Theme.text
                    opacity: 0.5
                    font.pixelSize: Theme.fontSizeSmall
                    anchors.right: parent.right
                }
            }

            Rectangle { width: parent.width; height: 1; color: Theme.borderIdle }

            Column {
                width: parent.width
                spacing: Theme.padSm
                Row {
                    width: parent.width
                    Text {
                        text: "Clipboard"
                        color: Theme.text
                        opacity: 0.55
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSizeSmall
                        anchors.verticalCenter: parent.verticalCenter
                        width: parent.width - 30
                    }
                    IconButton { glyph: ""; size: 26; onClicked: clipboardBackend.refresh() }
                }
                Expandable {
                    width: parent.width
                    title: "History"
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

            Rectangle { width: parent.width; height: 1; color: Theme.borderIdle }

            Column {
                width: parent.width
                spacing: Theme.padSm
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
                    width: parent.width
                    spacing: Theme.padSm
                    IconButton { glyph: ""; size: (parent.width - parent.spacing * 3) / 4; onClicked: Quickshell.execDetached(["hyprlock"]) }
                    IconButton { glyph: ""; size: (parent.width - parent.spacing * 3) / 4; onClicked: Quickshell.execDetached(["hyprctl", "dispatch", "exit"]) }
                    IconButton { glyph: ""; size: (parent.width - parent.spacing * 3) / 4; onClicked: Quickshell.execDetached(["systemctl", "reboot"]) }
                    IconButton { glyph: ""; size: (parent.width - parent.spacing * 3) / 4; destructive: true; onClicked: Quickshell.execDetached(["systemctl", "poweroff"]) }
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
