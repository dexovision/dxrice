import QtQuick
import QtQuick.Effects
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import Quickshell.Services.Pipewire

// DXrice Quick Settings -- Quickshell rewrite of dxrice_quick_settings.py.
// Docks flush under the top-right corner of the bar (waybar is 44px tall
// with an 8px top margin -- see ~/.config/waybar/config -- so 52px is its
// bottom edge) as a real wlr-layer-shell panel, toggled via
// `qs -p <repo>/quickshell/shell.qml ipc call quicksettings toggle`.
//
// Deliberately zero gap and square top corners (only the bottom is
// rounded, plus a WavyTopRect seam) so this reads as a drawer hanging off
// the bar rather than a separate floating card -- the actual end-4/
// caelestia pattern, ported from caelestia-dots/shell's own
// modules/drawers/Panels.qml + components/widgets/WavyTopRect.qml.
PanelWindow {
    id: root
    signal closeRequested()

    implicitWidth: 390
    color: "transparent"
    anchors { top: true; right: true }
    margins { top: 52; right: 14 }
    exclusionMode: ExclusionMode.Ignore
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.namespace: "dxrice-quicksettings"
    focusable: true

    implicitHeight: Math.min(760, content.implicitHeight + Theme.padMd * 2 + header.implicitHeight)

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

    // ---- root visuals: a drawer that unrolls DOWN from the bar, not a
    // card that pops in from its center -- the wavy strip is the seam that
    // visually welds it to the bar sitting right above (see
    // WavyTopRect.qml); only the bottom corners round off. ----
    Item {
        id: drawer
        anchors.fill: parent
        clip: true

        property real revealHeight: 0
        Behavior on revealHeight { NumberAnimation { duration: Theme.durationEnter; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveEmphasizedDecel } }
        Component.onCompleted: revealHeight = root.implicitHeight
        Connections {
            target: root
            function onImplicitHeightChanged() { drawer.revealHeight = root.implicitHeight; }
        }

        RectangularShadow {
            anchors.fill: panelSurface
            radius: 0
            bottomLeftRadius: Theme.roundingXl
            bottomRightRadius: Theme.roundingXl
            color: Theme.shadowColor
            blur: Theme.shadowBlurLg
            offset.y: 4
        }

        WavyTopRect {
            id: wavyRect
            anchors.top: parent.top
            anchors.left: parent.left
            width: parent.width
            height: 7
            color: Theme.bg
        }

        Rectangle {
            id: panelSurface
            anchors.top: wavyRect.bottom
            anchors.left: parent.left
            anchors.right: parent.right
            height: Math.max(0, drawer.revealHeight - wavyRect.height)
            radius: 0
            bottomLeftRadius: Theme.roundingXl
            bottomRightRadius: Theme.roundingXl
            color: Theme.bg
            clip: true

        Column {
            id: outer
            width: parent.width
            spacing: 0

            Item {
                id: header
                width: parent.width
                height: 64

                Column {
                    x: Theme.padLg
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 2
                    Text {
                        text: "Quick Settings"
                        color: Theme.textActive
                        font.family: Theme.fontFamily
                        font.pixelSize: 17
                        font.weight: Font.DemiBold
                    }
                    Text {
                        id: headerClock
                        color: Theme.text
                        opacity: 0.7
                        font.family: Theme.fontFamily
                        font.pixelSize: 12
                    }
                }
                Timer {
                    interval: 1000; running: true; repeat: true; triggeredOnStart: true
                    onTriggered: headerClock.text = Qt.formatDateTime(new Date(), "dddd, h:mm AP")
                }
                IconButton {
                    glyph: "✕"
                    anchors.verticalCenter: parent.verticalCenter
                    x: outer.width - width - Theme.padLg
                    onClicked: root.closeRequested()
                }
            }

            Flickable {
                width: parent.width
                height: Math.min(700, content.implicitHeight)
                contentHeight: content.implicitHeight
                clip: true

                Column {
                    id: content
                    x: Theme.padLg
                    width: parent.width - Theme.padLg * 2
                    spacing: Theme.padMd

                    // -- quick toggles: 2x2 grid so Do Not Disturb fits
                    // alongside Wi-Fi/Bluetooth/Awake instead of being left
                    // out entirely (its state/toggle already existed on the
                    // backend above, just never had a UI control before).
                    Card {
                        width: parent.width
                        Grid {
                            width: parent.width
                            columns: 2
                            rowSpacing: Theme.padSm
                            columnSpacing: Theme.padSm
                            ToggleChip {
                                width: (parent.width - parent.columnSpacing) / 2
                                glyph: ""; label: "Wi-Fi"
                                active: root.wifiEnabled
                                onToggled: (next) => root.setWifi(next)
                            }
                            ToggleChip {
                                width: (parent.width - parent.columnSpacing) / 2
                                glyph: ""; label: "Bluetooth"
                                active: root.bluetoothEnabled
                                onToggled: (next) => root.setBluetooth(next)
                            }
                            ToggleChip {
                                width: (parent.width - parent.columnSpacing) / 2
                                glyph: ""; label: "Do Not Disturb"
                                active: root.dndActive
                                onToggled: (next) => root.setDnd(next)
                            }
                            ToggleChip {
                                width: (parent.width - parent.columnSpacing) / 2
                                glyph: "⏻"; label: "Awake"
                                active: root.idleInhibited
                                onToggled: (next) => root.setIdleInhibit(next)
                            }
                        }
                    }

                    // -- media --
                    Card {
                        width: parent.width
                        visible: mediaBackend.available
                        height: visible ? implicitHeight : 0
                        Row {
                            width: parent.width
                            spacing: Theme.padSm
                            Column {
                                width: parent.width - 3 * 34 - Theme.padSm * 3
                                Text {
                                    text: mediaBackend.title
                                    color: Theme.textActive
                                    font.family: Theme.fontFamily
                                    font.weight: Font.DemiBold
                                    elide: Text.ElideRight
                                    width: parent.width
                                }
                                Text {
                                    visible: mediaBackend.artist.length > 0
                                    text: mediaBackend.artist
                                    color: Theme.text
                                    opacity: 0.7
                                    font.pixelSize: 12
                                    elide: Text.ElideRight
                                    width: parent.width
                                }
                            }
                            IconButton { glyph: ""; size: 34; onClicked: mediaBackend.previous() }
                            IconButton { glyph: mediaBackend.playing ? "" : ""; size: 34; onClicked: mediaBackend.playPause() }
                            IconButton { glyph: ""; size: 34; onClicked: mediaBackend.next() }
                        }
                    }

                    // -- audio & display: one card, not three, for output
                    // volume / mic / brightness -- three closely related
                    // sliders dont each need their own floating box. Device
                    // pickers are expandable sub-sections, not always-shown
                    // dropdowns, since most opens of this panel dont need them.
                    Card {
                        width: parent.width
                        Row {
                            width: parent.width
                            spacing: Theme.padSm
                            IconButton {
                                glyph: (root.sink && root.sink.audio && root.sink.audio.muted) ? "" : ""
                                anchors.verticalCenter: parent.verticalCenter
                                onClicked: if (root.sink && root.sink.audio) root.sink.audio.muted = !root.sink.audio.muted
                            }
                            SliderRow {
                                width: parent.width - 76
                                from: 0; to: 100
                                value: (root.sink && root.sink.audio) ? Math.round(root.sink.audio.volume * 100) : 0
                                onChanged: (v) => { if (root.sink && root.sink.audio) root.sink.audio.volume = v / 100; }
                            }
                        }
                        Expandable {
                            title: "Output device"
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
                                        font.pixelSize: 12
                                        elide: Text.ElideRight
                                    }
                                    Text {
                                        id: check
                                        anchors.verticalCenter: parent.verticalCenter
                                        anchors.right: parent.right
                                        anchors.rightMargin: Theme.padSm
                                        visible: root.sink && root.sink.name === modelData.name
                                        text: "✓"
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
                                anchors.verticalCenter: parent.verticalCenter
                                onClicked: if (root.source && root.source.audio) root.source.audio.muted = !root.source.audio.muted
                            }
                            SliderRow {
                                width: parent.width - 76
                                from: 0; to: 100
                                value: (root.source && root.source.audio) ? Math.round(root.source.audio.volume * 100) : 0
                                onChanged: (v) => { if (root.source && root.source.audio) root.source.audio.volume = v / 100; }
                            }
                        }
                        Expandable {
                            title: "Input device"
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
                                        font.pixelSize: 12
                                        elide: Text.ElideRight
                                    }
                                    Text {
                                        id: inCheck
                                        anchors.verticalCenter: parent.verticalCenter
                                        anchors.right: parent.right
                                        anchors.rightMargin: Theme.padSm
                                        visible: root.source && root.source.name === modelData.name
                                        text: "✓"
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
                            Text { text: "☀"; color: Theme.text; anchors.verticalCenter: parent.verticalCenter; width: 30; horizontalAlignment: Text.AlignHCenter }
                            SliderRow {
                                width: parent.width - 76
                                from: 1; to: 100
                                value: brightnessBackend.percent
                                onChanged: (v) => brightnessBackend.set(v)
                            }
                        }
                    }

                    // -- wifi networks: collapsed by default once there are
                    // more than a couple, since a full scan list dumped open
                    // every time you turn Wi-Fi on is exactly the kind of
                    // clutter an expanding section is supposed to replace. --
                    Card {
                        width: parent.width
                        visible: root.wifiEnabled && wifiBackend.networks.length > 0
                        height: visible ? implicitHeight : 0
                        Expandable {
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
                                        anchors.verticalCenter: parent.verticalCenter
                                        width: parent.width - (modelData.connected ? 130 : 150)
                                        elide: Text.ElideRight
                                    }
                                    Text {
                                        text: modelData.signal + "%"
                                        color: Theme.text
                                        opacity: 0.55
                                        font.pixelSize: 11
                                        width: 34
                                        anchors.verticalCenter: parent.verticalCenter
                                    }
                                    Text {
                                        visible: modelData.connected
                                        text: "✓"
                                        color: Theme.accent
                                        anchors.verticalCenter: parent.verticalCenter
                                        width: 16
                                    }
                                    IconButton {
                                        visible: modelData.known
                                        glyph: ""
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
                    }

                    // -- bluetooth devices --
                    Card {
                        width: parent.width
                        visible: root.bluetoothEnabled && btBackend.devices.length > 0
                        height: visible ? implicitHeight : 0
                        Expandable {
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
                                        anchors.verticalCenter: parent.verticalCenter
                                        width: parent.width - (modelData.battery >= 0 ? 190 : 160)
                                        elide: Text.ElideRight
                                    }
                                    Text {
                                        visible: modelData.battery >= 0
                                        text: modelData.battery + "%"
                                        color: Theme.text
                                        opacity: 0.55
                                        font.pixelSize: 11
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

                    // -- live stats --
                    Card {
                        width: parent.width
                        Row {
                            width: parent.width
                            Text { text: "CPU"; color: Theme.text; width: 60; font.family: Theme.fontFamily }
                            LevelBar { width: parent.width - 130; value: root.cpuPercent / 100; anchors.verticalCenter: parent.verticalCenter }
                            Text { text: Math.round(root.cpuPercent) + "%"; color: Theme.text; width: 40; horizontalAlignment: Text.AlignRight }
                        }
                        Row {
                            width: parent.width
                            Text { text: "Memory"; color: Theme.text; width: 60; font.family: Theme.fontFamily }
                            LevelBar { width: parent.width - 130; value: root.memPercent / 100; anchors.verticalCenter: parent.verticalCenter }
                            Text { text: Math.round(root.memPercent) + "%"; color: Theme.text; width: 40; horizontalAlignment: Text.AlignRight }
                        }
                    }

                    // -- clipboard history --
                    Card {
                        width: parent.width
                        Row {
                            width: parent.width
                            Text {
                                text: "Clipboard"
                                color: Theme.textActive
                                font.family: Theme.fontFamily
                                font.weight: Font.DemiBold
                                width: parent.width - 34
                            }
                            IconButton { glyph: "\uf021"; size: 30; onClicked: clipboardBackend.refresh() }
                        }
                        Expandable {
                            title: "History"
                            trailingText: clipboardBackend.entries.length + " items"
                            Repeater {
                                model: clipboardBackend.entries
                                delegate: Rectangle {
                                    width: parent.width
                                    height: 28
                                    radius: Theme.entryRadius
                                    color: clipArea.containsMouse ? Theme.active : "transparent"
                                    Behavior on color { ColorAnimation { duration: Theme.animMs } }
                                    Text {
                                        anchors.verticalCenter: parent.verticalCenter
                                        anchors.left: parent.left
                                        anchors.leftMargin: 6
                                        width: parent.width - 12
                                        text: modelData.preview.replace(/\n/g, " ")
                                        color: Theme.text
                                        font.family: Theme.fontFamily
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

                    // -- actions: screenshots + power, one card -- these
                    // are all one-tap utility actions, they read better as
                    // one grouped strip than two separate boxes.
                    Card {
                        width: parent.width
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
    BrightnessBackend { id: brightnessBackend }
    MediaBackend { id: mediaBackend }
    ClipboardBackend { id: clipboardBackend; Component.onCompleted: refresh() }
}
