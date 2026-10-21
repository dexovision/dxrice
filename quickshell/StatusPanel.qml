import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Services.Pipewire

// One section of the panel that hangs from the bar's right-hand section,
// opened from its own indicator: Media, Capture, Performance, Network,
// Bluetooth, Sound, Power or Notifications. It is the same surface for all
// of them (it resizes to fit), and changing section slides the old content
// out and the new in, so moving along the indicators reads as one panel
// turning, not eight panels popping.
//
// Everything is the system's own state, read and set through the same
// backends the Dashboard uses (WifiBackend, BluetoothBackend,
// AudioDeviceBackend, BrightnessBackend, Pipewire, BatteryService,
// MediaSession, PerformanceService, NotificationService, CaptureService):
// a slider here and the Dashboard's are the same device, never two copies.
Item {
    id: root
    objectName: "statusPanel"
    anchors.fill: parent
    signal closeRequested()
    signal dashboardRequested(string tab)

    property string section: "network"
    // the island sizes itself to this (TopBar)
    readonly property real contentHeight: body.implicitHeight + Theme.padLg * 2
    // a separate top-level window the bar's click-outside catcher can't see
    property bool wifiDialogOpen: false

    // ---- section changes: the old slides away, the new comes in ----
    readonly property var order: ["media", "capture", "performance", "network", "bluetooth", "audio", "power", "notifications"]
    property string shown: root.section
    property int direction: 1
    onSectionChanged: {
        root.direction = root.order.indexOf(root.section) >= root.order.indexOf(root.shown) ? 1 : -1;
        swap.restart();
    }
    SequentialAnimation {
        id: swap
        NumberAnimation { target: body; property: "opacity"; to: 0; duration: Theme.reduceMotion ? 0 : Theme.durationFadeOut; easing.type: Easing.InQuad }
        ScriptAction { script: { root.shown = root.section; slide.x = root.direction * 22; } }
        ParallelAnimation {
            NumberAnimation { target: body; property: "opacity"; to: 1; duration: Theme.durationFadeIn; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveStandard }
            NumberAnimation { target: slide; property: "x"; to: 0; duration: Theme.durationSpring; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveSpring }
        }
    }

    // ---- real state ----
    property bool wifiOn: false
    property bool btOn: false
    property bool btAvailable: true
    property bool dnd: false
    Process { id: wifiCheck; command: ["nmcli", "radio", "wifi"]; stdout: StdioCollector { onStreamFinished: root.wifiOn = this.text.trim() === "enabled" } }
    Process {
        id: btCheck
        command: ["bluetoothctl", "show"]
        stdout: StdioCollector {
            onStreamFinished: {
                root.btAvailable = !/No default controller/i.test(this.text) && /Controller /.test(this.text);
                root.btOn = root.btAvailable && /Powered:\s*yes/.test(this.text);
            }
        }
    }
    Process { id: dndCheck; command: ["makoctl", "mode"]; stdout: StdioCollector { onStreamFinished: root.dnd = this.text.split(/\s+/).includes("dnd") } }
    function refresh() { wifiCheck.running = true; btCheck.running = true; dndCheck.running = true; NotificationService.refresh(); }
    Component.onCompleted: {
        root.refresh();
        root._countSampling();
        if (root.shown === "notifications") NotificationService.markSeen();
    }
    // looking at the notifications reads them
    onShownChanged: if (root.shown === "notifications") NotificationService.markSeen()

    // ---- media (the shell's one chosen player) ----
    MediaBackend { id: media; objectName: "statusMedia" }
    Timer {
        // MPRIS doesn't announce the position: ask once a second, only while shown and playing
        running: root.shown === "media" && media.playing
        interval: 1000; repeat: true
        onTriggered: if (media.player) media.player.positionChanged()
    }

    // ---- performance: sampled only while this section is showing ----
    property bool _sampling: false
    readonly property bool _wantSamples: root.shown === "performance"
    on_WantSamplesChanged: root._countSampling()
    function _countSampling() {
        if (root._wantSamples && !root._sampling) { PerformanceService.widgetUsers += 1; root._sampling = true; }
        else if (!root._wantSamples && root._sampling) { PerformanceService.widgetUsers -= 1; root._sampling = false; }
    }
    Component.onDestruction: if (root._sampling) PerformanceService.widgetUsers -= 1
    // ---- ping: one echo every 5 s, only while Performance is showing ----
    // theme.json "ping_host" (default 1.1.1.1, as in the reference); ""
    // turns it off. -1 = no reply (or no network), -2 = not measured yet.
    readonly property string pingHost: Theme.data.ping_host === undefined ? "1.1.1.1" : String(Theme.data.ping_host)
    property real pingMs: -2
    Process {
        id: pingProc
        command: ["ping", "-n", "-c", "1", "-W", "2", root.pingHost]
        stdout: StdioCollector {
            onStreamFinished: {
                const m = this.text.match(/time[=<]([\d.]+)\s*ms/);
                root.pingMs = m ? Number(m[1]) : -1;
            }
        }
    }
    Timer {
        running: root.shown === "performance" && root.pingHost.length > 0
        interval: 5000; repeat: true; triggeredOnStart: true
        onTriggered: pingProc.running = true
    }
    function rate(kbs) { return kbs >= 1024 ? (kbs / 1024).toFixed(1) + " MB/s" : Math.round(kbs) + " KB/s"; }
    function uptime(s) {
        const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
        return (d > 0 ? d + "d " : "") + h + "h " + m + "m";
    }

    // ---- power actions that end the session ask once more first ----
    property string confirming: ""
    Timer { id: confirmTimeout; interval: 4000; onTriggered: root.confirming = "" }
    function confirmOr(action, run) {
        if (root.confirming === action) { root.confirming = ""; confirmTimeout.stop(); run(); return; }
        root.confirming = action;
        confirmTimeout.restart();
    }
    Timer { id: reread; interval: 800; onTriggered: root.refresh() }

    function setWifi(on) { root.wifiOn = on; Quickshell.execDetached(["nmcli", "radio", "wifi", on ? "on" : "off"]); reread.restart(); }
    function setBt(on) { if (!root.btAvailable) return; root.btOn = on; Quickshell.execDetached(["bluetoothctl", "power", on ? "on" : "off"]); reread.restart(); }
    function setDnd(on) { root.dnd = on; Quickshell.execDetached(["makoctl", "mode", on ? "-a" : "-r", "dnd"]); }

    WifiBackend {
        id: wifiBackend
        radioOn: root.wifiOn
        onPasswordNeeded: (ssid) => {
            const dlg = Qt.createComponent("WifiPasswordDialog.qml").createObject(root, { ssid: ssid });
            root.wifiDialogOpen = true;
            dlg.visibleChanged.connect(() => { if (!dlg.visible) root.wifiDialogOpen = false; });
            dlg.submitted.connect((password) => wifiBackend.connectWithPassword(ssid, password));
            dlg.visible = true;
        }
    }
    BluetoothBackend { id: btBackend; radioOn: root.btOn; onScanningChanged: if (scanning) root._btSearched = true }
    property bool _btSearched: false
    AudioDeviceBackend { id: audioDevices }
    BrightnessBackend { id: brightness }
    PwObjectTracker { objects: [Pipewire.defaultAudioSink, Pipewire.defaultAudioSource] }
    readonly property var sink: Pipewire.defaultAudioSink
    readonly property var source: Pipewire.defaultAudioSource

    function wifiGlyph(signal) {
        if (signal >= 80) return "\u{f0928}";
        if (signal >= 60) return "\u{f0925}";
        if (signal >= 40) return "\u{f0922}";
        if (signal >= 20) return "\u{f091f}";
        return "\u{f092f}";
    }

    // ---- shared pieces ----
    component SectionHead: Item {
        id: head
        property string glyph: ""
        property string title: ""
        property string detail: ""
        property bool hasSwitch: false
        property bool checked: false
        property bool switchEnabled: true
        signal toggled(bool next)
        width: parent ? parent.width : 0
        height: 40
        Text {
            id: headGlyph
            anchors.verticalCenter: parent.verticalCenter
            text: head.glyph
            color: Theme.accentText
            font.family: Theme.iconFamily; font.pixelSize: 20
        }
        Column {
            anchors.left: headGlyph.right; anchors.leftMargin: Theme.padMd
            anchors.verticalCenter: parent.verticalCenter
            Text { text: head.title; color: Theme.textActive; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeLarger; font.weight: Font.DemiBold }
            Text { visible: head.detail.length > 0; text: head.detail; color: Theme.text; opacity: Theme.opacityMuted; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSmaller }
        }
        Switch {
            visible: head.hasSwitch
            enabled: head.switchEnabled
            opacity: head.switchEnabled ? 1 : 0.4
            anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
            checked: head.checked
            onToggled: (next) => head.toggled(next)
        }
    }
    component Hairline: Rectangle { width: parent ? parent.width : 0; height: 1; color: Theme.withAlpha(Theme.borderTint, 0.1) }
    component Note: Text {
        width: parent ? parent.width : 0
        color: Theme.text; opacity: Theme.opacityMuted
        font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSmall
        wrapMode: Text.WordWrap
        topPadding: 6; bottomPadding: 6
    }
    component Choice: Rectangle {
        id: choice
        property string label: ""
        property bool selected: false
        signal picked()
        width: parent ? parent.width : 0
        height: 32
        radius: Theme.roundingSm
        color: choice.selected ? Theme.mix(Theme.layer1, Theme.accent, 0.18) : (choiceArea.containsMouse ? Theme.layer1Hover : "transparent")
        Behavior on color { ColorAnimation { duration: Theme.durationFast } }
        Text {
            x: Theme.padMd; anchors.verticalCenter: parent.verticalCenter
            width: parent.width - Theme.padMd * 2 - 20
            text: choice.label; elide: Text.ElideRight
            color: choice.selected ? Theme.textActive : Theme.text
            font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSmall
        }
        Text {
            visible: choice.selected
            anchors.right: parent.right; anchors.rightMargin: Theme.padMd; anchors.verticalCenter: parent.verticalCenter
            text: ""; color: Theme.accentText; font.family: Theme.iconFamily; font.pixelSize: Theme.fontSizeSmall
        }
        MouseArea { id: choiceArea; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: choice.picked() }
    }
    component VolumeLine: Row {
        id: vol
        property var node: null
        property string glyph: ""
        property string mutedGlyph: ""
        width: parent ? parent.width : 0
        spacing: Theme.padSm
        readonly property bool muted: vol.node && vol.node.audio ? vol.node.audio.muted : false
        IconButton {
            anchors.verticalCenter: parent.verticalCenter
            glyph: vol.muted ? vol.mutedGlyph : vol.glyph
            size: Theme.iconMd
            tint: vol.muted ? Theme.accent : null
            onClicked: if (vol.node && vol.node.audio) vol.node.audio.muted = !vol.node.audio.muted
        }
        SliderRow {
            width: parent.width - Theme.iconMd - parent.spacing
            anchors.verticalCenter: parent.verticalCenter
            from: 0; to: 100
            value: vol.node && vol.node.audio ? Math.round(vol.node.audio.volume * 100) : 0
            onChanged: (v) => { if (vol.node && vol.node.audio) vol.node.audio.volume = v / 100; }
        }
    }

    component Caption: Text {
        color: Theme.text; opacity: Theme.opacityMuted
        font.family: Theme.fontFamily; font.pixelSize: 10; font.weight: Font.Bold; font.letterSpacing: 1.5
    }
    component NoteRow: Item {
        id: nrow
        property var note: ({})
        property bool dismissable: false
        width: body.width; height: 40
        Text {
            y: 4; width: parent.width - (nrow.dismissable ? 32 : 0)
            text: nrow.note.summary || ""; elide: Text.ElideRight
            color: Theme.textActive; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSmall
        }
        Text {
            y: 22; width: parent.width - (nrow.dismissable ? 32 : 0)
            text: nrow.note.app || ""; elide: Text.ElideRight
            color: Theme.text; opacity: Theme.opacityMuted; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSmaller
        }
        IconButton {
            objectName: "statusDismiss:" + nrow.note.id
            visible: nrow.dismissable
            anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
            glyph: ""; size: 26
            onClicked: NotificationService.dismiss(nrow.note.id)
        }
    }
    // a ring gauge: an arc to the value, the number in the middle
    component Gauge: Item {
        id: gauge
        property string label: ""
        property real value: 0
        property string extra: ""
        property bool available: true
        width: 92; height: 112
        Canvas {
            id: ring
            width: 76; height: 76
            anchors.horizontalCenter: parent.horizontalCenter
            readonly property real frac: gauge.available ? Math.max(0, Math.min(1, gauge.value / 100)) : 0
            property real shown: frac
            Behavior on shown { NumberAnimation { duration: Theme.durationMove; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveStandard } }
            onShownChanged: requestPaint()
            onVisibleChanged: if (visible) requestPaint()
            onAvailableChanged: if (available) requestPaint()
            // spelled out: a translucent colour handed over as-is becomes
            // Qt's "#aarrggbb", which the canvas misreads
            function rgba(c) { return "rgba(" + Math.round(c.r * 255) + "," + Math.round(c.g * 255) + "," + Math.round(c.b * 255) + "," + c.a + ")"; }
            onPaint: {
                const ctx = getContext("2d");
                ctx.reset();
                const r = width / 2 - 5;
                ctx.lineWidth = 7;
                ctx.lineCap = "round";
                ctx.strokeStyle = rgba(Theme.layer2);
                ctx.beginPath(); ctx.arc(width / 2, height / 2, r, 0, Math.PI * 2); ctx.stroke();
                if (ring.shown > 0.002) {
                    ctx.strokeStyle = rgba(Theme.accent);
                    ctx.beginPath(); ctx.arc(width / 2, height / 2, r, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * ring.shown); ctx.stroke();
                }
            }
            Text {
                anchors.centerIn: parent
                text: gauge.available ? Math.round(gauge.value) + "%" : "—"
                color: Theme.textActive; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeLarge; font.weight: Font.DemiBold
            }
        }
        Column {
            anchors.top: ring.bottom; anchors.topMargin: 2
            anchors.horizontalCenter: parent.horizontalCenter
            Text { anchors.horizontalCenter: parent.horizontalCenter; text: gauge.label; color: Theme.textActive; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSmaller; font.weight: Font.DemiBold }
            Text { anchors.horizontalCenter: parent.horizontalCenter; text: gauge.extra; visible: text.length > 0; color: Theme.text; opacity: Theme.opacityMuted; font.family: Theme.fontFamily; font.pixelSize: 10 }
        }
    }
    component Readout: Item {
        id: ro
        property string label: ""
        property string value: ""
        width: (body.width - Theme.padLg) / 2; height: 22
        Text { anchors.verticalCenter: parent.verticalCenter; text: ro.label; color: Theme.text; opacity: Theme.opacityMuted; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSmaller }
        Text { anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; text: ro.value; color: Theme.textActive; font.family: Theme.fontMono; font.pixelSize: 11 }
    }

    // ---- the sections ----
    Item {
        id: slide
        x: 0
        width: parent.width
        Column {
            id: body
            x: Theme.padLg; y: Theme.padLg
            width: root.width - Theme.padLg * 2
            spacing: Theme.padSm

            // NETWORK
            Column {
                objectName: "statusSection:network"
                visible: root.shown === "network"
                width: parent.width
                spacing: Theme.padXs
                SectionHead {
                    glyph: ""; title: "Wi-Fi"
                    detail: !root.wifiOn ? "Off" : (wifiBackend.networks.filter((n) => n.connected).map((n) => n.ssid)[0] || "Not connected")
                    hasSwitch: true; checked: root.wifiOn
                    onToggled: (next) => root.setWifi(next)
                }
                Hairline {}
                Repeater {
                    model: root.wifiOn ? wifiBackend.networks.slice(0, 6) : []
                    delegate: DeviceRow {
                        required property var modelData
                        width: body.width
                        glyph: root.wifiGlyph(modelData.signal)
                        title: modelData.ssid
                        detail: (modelData.connected ? "Connected · " : "") + modelData.signal + "%"
                            + ((!modelData.security || modelData.security === "--") ? " · Open" : " · " + modelData.security)
                        connected: modelData.connected
                        actionText: modelData.connected ? "" : "Connect"
                        canForget: modelData.known
                        onActionClicked: wifiBackend.connectTo(modelData.ssid, modelData.security)
                        onForgetClicked: wifiBackend.forget(modelData.ssid)
                    }
                }
                Note {
                    visible: !root.wifiOn || (wifiBackend.hasScanned && wifiBackend.networks.length === 0) || !wifiBackend.hasScanned
                    text: !root.wifiOn ? "Wi-Fi is off." : (!wifiBackend.hasScanned ? "Looking for networks…" : "No networks in range.")
                }
            }

            // BLUETOOTH
            Column {
                objectName: "statusSection:bluetooth"
                visible: root.shown === "bluetooth"
                width: parent.width
                spacing: Theme.padXs
                SectionHead {
                    glyph: ""; title: "Bluetooth"
                    detail: !root.btAvailable ? "No adapter on this machine" : (root.btOn ? btBackend.devices.filter((d) => d.connected).length + " connected" : "Off")
                    hasSwitch: true; checked: root.btOn; switchEnabled: root.btAvailable
                    onToggled: (next) => root.setBt(next)
                }
                Hairline {}
                Repeater {
                    model: root.btOn ? btBackend.paired.slice(0, 5) : []
                    delegate: DeviceRow {
                        required property var modelData
                        objectName: "btPaired:" + modelData.mac
                        width: body.width
                        glyph: modelData.connected ? "\u{f00b1}" : "\u{f00af}"
                        title: modelData.name
                        detail: (modelData.connected ? "Connected" : "Paired")
                            + (modelData.battery >= 0 ? " · \u{f0079} " + modelData.battery + "%" : "")
                        connected: modelData.connected
                        actionText: modelData.connected ? "Disconnect" : "Connect"
                        canForget: true
                        onActionClicked: btBackend.toggleConnect(modelData.mac, modelData.connected)
                        onForgetClicked: btBackend.forget(modelData.mac)
                    }
                }
                Note {
                    visible: !root.btAvailable || !root.btOn || (btBackend.hasScanned && btBackend.paired.length === 0)
                    text: !root.btAvailable ? "There is no Bluetooth adapter to switch on."
                        : (!root.btOn ? "Bluetooth is off." : "No paired devices yet.")
                }
                // nearby: a timed scan, then pair (and trust and connect) in one go
                Item {
                    visible: root.btOn
                    width: body.width; height: 30
                    Caption { anchors.verticalCenter: parent.verticalCenter; text: "NEARBY" }
                    Row {
                        anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
                        spacing: Theme.padSm
                        LoadingDots { visible: btBackend.scanning; anchors.verticalCenter: parent.verticalCenter }
                        CompactChip {
                            objectName: "btScan"
                            anchors.verticalCenter: parent.verticalCenter
                            text: btBackend.scanning ? "Searching…" : (btBackend.nearby.length > 0 ? "Search again" : "Search")
                            enabled: !btBackend.scanning
                            opacity: enabled ? 1 : 0.6
                            onClicked: btBackend.scan()
                        }
                    }
                }
                Repeater {
                    model: root.btOn ? btBackend.nearby.slice(0, 5) : []
                    delegate: DeviceRow {
                        required property var modelData
                        objectName: "btNearby:" + modelData.mac
                        width: body.width
                        glyph: "\u{f00af}"
                        title: modelData.name
                        detail: btBackend.pairingMac === modelData.mac ? "Pairing…" : "Not paired"
                        actionText: btBackend.pairingMac === modelData.mac ? "" : "Pair"
                        onActionClicked: btBackend.pair(modelData.mac)
                    }
                }
                Note {
                    objectName: "btNote"
                    visible: root.btOn && (btBackend.pairError.length > 0 || (!btBackend.scanning && btBackend.nearby.length === 0 && root._btSearched))
                    text: btBackend.pairError.length > 0 ? btBackend.pairError : "Nothing new nearby. Put the device in pairing mode and search again."
                }
                Note {
                    visible: root.btOn && !btBackend.agentRunning && btBackend.nearby.length > 0 && btBackend.pairError.length === 0
                    text: "No pairing agent is running: a device that asks for a PIN can't pair until blueman-applet is started."
                }
            }

            // AUDIO
            Column {
                objectName: "statusSection:audio"
                visible: root.shown === "audio"
                width: parent.width
                spacing: Theme.padSm
                SectionHead {
                    glyph: ""; title: "Sound"
                    detail: root.sink ? audioDevices.label(root.sink) : "No output device"
                }
                Hairline {}
                VolumeLine { objectName: "statusOutputVolume"; node: root.sink; glyph: ""; mutedGlyph: "\u{f075f}" }
                VolumeLine { objectName: "statusInputVolume"; visible: root.source !== null; node: root.source; glyph: ""; mutedGlyph: "" }
                Text {
                    visible: audioDevices.outputs.length > 1
                    text: "OUTPUT"; topPadding: 4
                    color: Theme.text; opacity: Theme.opacityMuted
                    font.family: Theme.fontFamily; font.pixelSize: 10; font.weight: Font.Bold; font.letterSpacing: 1.5
                }
                Repeater {
                    model: audioDevices.outputs.length > 1 ? audioDevices.outputs : []
                    delegate: Choice {
                        required property var modelData
                        width: body.width
                        label: audioDevices.label(modelData)
                        selected: root.sink === modelData
                        onPicked: audioDevices.setOutput(modelData)
                    }
                }
                Text {
                    visible: audioDevices.inputs.length > 1
                    text: "INPUT"; topPadding: 4
                    color: Theme.text; opacity: Theme.opacityMuted
                    font.family: Theme.fontFamily; font.pixelSize: 10; font.weight: Font.Bold; font.letterSpacing: 1.5
                }
                Repeater {
                    model: audioDevices.inputs.length > 1 ? audioDevices.inputs : []
                    delegate: Choice {
                        required property var modelData
                        objectName: "statusInput:" + audioDevices.label(modelData)
                        width: body.width
                        label: audioDevices.label(modelData)
                        selected: root.source === modelData
                        onPicked: audioDevices.setInput(modelData)
                    }
                }
            }

            // POWER
            Column {
                objectName: "statusSection:power"
                visible: root.shown === "power"
                width: parent.width
                spacing: Theme.padSm
                SectionHead {
                    glyph: BatteryService.available ? (BatteryService.charging ? "\u{f0084}" : "\u{f0079}") : ""
                    title: BatteryService.available ? BatteryService.percent + "%" : "Power"
                    detail: BatteryService.available ? BatteryService.status.toLowerCase() : "No battery on this machine"
                }
                Hairline {}
                Item {
                    width: parent.width; height: 26
                    visible: BatteryService.available
                    LevelBar {
                        objectName: "statusBatteryBar"
                        anchors.verticalCenter: parent.verticalCenter
                        width: parent.width
                        value: Math.max(0, BatteryService.percent) / 100
                    }
                }
                Row {
                    visible: brightness.hasBacklight
                    width: parent.width
                    spacing: Theme.padSm
                    Text { anchors.verticalCenter: parent.verticalCenter; text: "\u{f00df}"; color: Theme.text; font.family: Theme.iconFamily; font.pixelSize: Theme.fontSizeLarge; width: Theme.iconMd; horizontalAlignment: Text.AlignHCenter }
                    SliderRow {
                        width: parent.width - Theme.iconMd - parent.spacing
                        anchors.verticalCenter: parent.verticalCenter
                        from: 1; to: 100
                        value: brightness.percent
                        onChanged: (v) => brightness.set(Math.round(v))
                    }
                }
                Flow {
                    width: parent.width
                    spacing: Theme.padSm
                    topPadding: 4
                    GlassButton { text: "Lock"; variant: "secondary"; onClicked: { root.closeRequested(); Quickshell.execDetached(["loginctl", "lock-session"]); } }
                    // ending the session takes a second click, within 4 s, on
                    // the button that now asks
                    GlassButton {
                        objectName: "statusLogout"
                        text: root.confirming === "logout" ? "Log out now?" : "Log out"
                        variant: root.confirming === "logout" ? "primary" : "secondary"
                        onClicked: root.confirmOr("logout", () => Quickshell.execDetached(["sh", "-c", 'sid="$(loginctl show-user "$(id -un)" -p Display --value 2>/dev/null)"; [ -n "$sid" ] && exec loginctl terminate-session "$sid"']))
                    }
                    GlassButton {
                        objectName: "statusReboot"
                        text: root.confirming === "reboot" ? "Restart now?" : "Restart"
                        variant: root.confirming === "reboot" ? "primary" : "secondary"
                        onClicked: root.confirmOr("reboot", () => Quickshell.execDetached(["sh", Quickshell.shellDir + "/../scripts/dxrice_power.sh", "reboot"]))
                    }
                    GlassButton {
                        objectName: "statusPoweroff"
                        text: root.confirming === "poweroff" ? "Shut down now?" : "Shut down"
                        variant: root.confirming === "poweroff" ? "primary" : "secondary"
                        onClicked: root.confirmOr("poweroff", () => Quickshell.execDetached(["sh", Quickshell.shellDir + "/../scripts/dxrice_power.sh", "poweroff"]))
                    }
                }
            }

            // NOTIFICATIONS
            Column {
                objectName: "statusSection:notifications"
                visible: root.shown === "notifications"
                width: parent.width
                spacing: Theme.padXs
                SectionHead {
                    glyph: root.dnd ? "" : ""; title: "Notifications"
                    detail: root.dnd ? "Do not disturb" : (NotificationService.onScreen.length ? NotificationService.onScreen.length + " on screen"
                            : (NotificationService.history.length ? "Earlier" : "Nothing recent"))
                    // on = notifications show, like Wi-Fi and Bluetooth's
                    // switches; off is do not disturb
                    hasSwitch: true; checked: !root.dnd
                    onToggled: (next) => root.setDnd(!next)
                }
                Hairline {}
                // on screen now: each can be dismissed, or all at once
                Item {
                    visible: NotificationService.onScreen.length > 0
                    width: body.width; height: 22
                    Caption { anchors.verticalCenter: parent.verticalCenter; text: "ON SCREEN" }
                    Text {
                        objectName: "statusClearAll"
                        anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
                        text: "Clear all"
                        color: clearArea.containsMouse ? Theme.accentText : Theme.text
                        font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSmaller
                        MouseArea { id: clearArea; anchors.fill: parent; anchors.margins: -6; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: NotificationService.dismissAll() }
                    }
                }
                Repeater {
                    model: NotificationService.onScreen
                    delegate: NoteRow { required property var modelData; note: modelData; dismissable: true }
                }
                // earlier: mako keeps these and can't forget them, so they
                // are listed, not removed
                Caption { visible: NotificationService.history.length > 0; text: "EARLIER"; topPadding: 4 }
                Repeater {
                    model: NotificationService.history.slice(0, 6)
                    delegate: NoteRow { required property var modelData; note: modelData }
                }
                Note { visible: NotificationService.history.length === 0 && NotificationService.onScreen.length === 0; text: "No notifications yet." }
            }

            // MEDIA
            Column {
                objectName: "statusSection:media"
                visible: root.shown === "media"
                width: parent.width
                spacing: Theme.padSm
                Row {
                    width: parent.width
                    spacing: Theme.padMd
                    Item {
                        width: 84; height: 84
                        Rectangle {
                            anchors.fill: parent; radius: 14
                            color: Theme.mix(Theme.layer1, Theme.accent, 0.25)
                            Text { anchors.centerIn: parent; text: String.fromCodePoint(0xf075a); color: Theme.textActive; opacity: 0.7; font.family: Theme.iconFamily; font.pixelSize: 30 }
                        }
                        Image {
                            objectName: "statusMediaArt"
                            anchors.fill: parent
                            source: media.artUrl
                            visible: status === Image.Ready
                            asynchronous: true; cache: true
                            sourceSize: Qt.size(168, 168)
                            fillMode: Image.PreserveAspectCrop
                        }
                    }
                    Column {
                        width: parent.width - 84 - Theme.padMd
                        anchors.verticalCenter: parent.verticalCenter
                        spacing: 2
                        Text {
                            width: parent.width; elide: Text.ElideRight
                            text: (media.available ? media.source : "No player").toUpperCase()
                            color: Theme.accentText; font.family: Theme.fontFamily; font.pixelSize: 10; font.weight: Font.Bold; font.letterSpacing: 1.5
                        }
                        Text {
                            objectName: "statusMediaTitle"
                            width: parent.width; wrapMode: Text.Wrap; maximumLineCount: 2; elide: Text.ElideRight
                            text: media.available ? media.title : "Nothing playing"
                            color: Theme.textActive; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeLarge; font.weight: Font.DemiBold
                        }
                        Text {
                            width: parent.width; elide: Text.ElideRight
                            text: media.available ? [media.artist, media.album].filter((t) => t).join(" · ") : "Music from any MPRIS player shows here"
                            visible: text.length > 0
                            color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSmall
                        }
                    }
                }
                // where the track is; click or drag to seek, when the player allows it
                Item {
                    id: seekBar
                    objectName: "statusMediaSeek"
                    visible: media.available && media.length > 0
                    width: parent.width; height: 14
                    readonly property real frac: media.length > 0 ? Math.max(0, Math.min(1, media.position / media.length)) : 0
                    Rectangle {
                        anchors.verticalCenter: parent.verticalCenter
                        width: parent.width; height: seekArea.containsMouse ? 6 : 4; radius: height / 2
                        color: Theme.layer2
                        Rectangle {
                            height: parent.height; radius: parent.radius
                            width: parent.width * seekBar.frac
                            color: Theme.accent
                            Behavior on width { enabled: !seekArea.pressed; NumberAnimation { duration: Theme.durationTick; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveStandard } }
                        }
                    }
                    MouseArea {
                        id: seekArea
                        anchors.fill: parent
                        hoverEnabled: true
                        enabled: media.seekable
                        cursorShape: media.seekable ? Qt.PointingHandCursor : Qt.ArrowCursor
                        function seek(x) { media.seekTo(Math.max(0, Math.min(1, x / width)) * media.length); }
                        onPressed: (m) => seek(m.x)
                        onPositionChanged: (m) => { if (pressed) seek(m.x); }
                    }
                }
                Item {
                    width: parent.width; height: 40
                    Text {
                        visible: media.available && media.length > 0
                        anchors.left: parent.left; anchors.verticalCenter: parent.verticalCenter
                        text: media.formatTime(media.position) + " / " + media.formatTime(media.length)
                        color: Theme.text; font.family: Theme.fontMono; font.pixelSize: 11
                    }
                    Row {
                        anchors.centerIn: parent
                        spacing: Theme.padSm
                        enabled: media.available
                        opacity: enabled ? 1 : 0.4
                        IconButton { objectName: "statusMediaPrev"; anchors.verticalCenter: parent.verticalCenter; glyph: "\u{f04ae}"; size: 30; onClicked: media.previous() }
                        Rectangle {
                            objectName: "statusMediaPlay"
                            width: 38; height: 38; radius: 19
                            anchors.verticalCenter: parent.verticalCenter
                            color: Theme.accent
                            scale: playArea.pressed ? 0.9 : 1
                            Behavior on scale { NumberAnimation { duration: Theme.durationSpringFast; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveSpringFast } }
                            Text { anchors.centerIn: parent; text: media.playing ? "\u{f03e4}" : "\u{f040a}"; color: Theme.panelTone; font.family: Theme.iconFamily; font.pixelSize: 18 }
                            MouseArea { id: playArea; anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: media.playPause() }
                        }
                        IconButton { objectName: "statusMediaNext"; anchors.verticalCenter: parent.verticalCenter; glyph: "\u{f04ad}"; size: 30; onClicked: media.next() }
                    }
                }
                Row {
                    visible: media.volumeSupported
                    width: parent.width
                    spacing: Theme.padSm
                    Text { anchors.verticalCenter: parent.verticalCenter; text: ""; color: Theme.text; font.family: Theme.iconFamily; font.pixelSize: Theme.fontSizeLarge; width: Theme.iconMd; horizontalAlignment: Text.AlignHCenter }
                    SliderRow {
                        width: parent.width - Theme.iconMd - parent.spacing
                        anchors.verticalCenter: parent.verticalCenter
                        from: 0; to: 100
                        value: Math.round(media.volume * 100)
                        onChanged: (v) => media.setVolume(v / 100)
                    }
                }
                // more than one player: pick which, for the whole shell
                Flow {
                    objectName: "statusMediaPlayers"
                    visible: media.players.length > 1
                    width: parent.width
                    spacing: Theme.padXs
                    Repeater {
                        model: media.players
                        delegate: Rectangle {
                            id: chip
                            required property var modelData
                            required property int index
                            objectName: "statusMediaPlayer:" + index
                            readonly property bool current: media.player === chip.modelData
                            width: chipText.implicitWidth + Theme.padLg * 2; height: 28; radius: 14
                            color: chip.current ? Theme.mix(Theme.layer1, Theme.accent, 0.22) : (chipArea.containsMouse ? Theme.layer1Hover : Theme.layer1)
                            Text {
                                id: chipText
                                anchors.centerIn: parent
                                text: MediaSession.nameOf(chip.modelData) + (chip.modelData.isPlaying ? "  ♪" : "")
                                color: chip.current ? Theme.textActive : Theme.text
                                font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSmaller
                            }
                            MouseArea { id: chipArea; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: media.choose(media.players[chip.index]) }
                        }
                    }
                }
            }

            // CAPTURE
            Column {
                objectName: "statusSection:capture"
                visible: root.shown === "capture"
                width: parent.width
                spacing: Theme.padSm
                SectionHead {
                    glyph: CaptureService.recording ? "\u{f044a}" : ""
                    title: CaptureService.recording ? "Recording · " + CaptureService.clock(CaptureService.elapsed) : "Capture"
                    detail: CaptureService.recording ? "Stop it here, or from its mark in the bar" : "Screenshots and screen recordings"
                }
                Hairline {}
                Caption { text: "SCREENSHOT" }
                Flow {
                    width: parent.width
                    spacing: Theme.padSm
                    GlassButton { objectName: "statusShotRegion"; text: "Region"; variant: "secondary"; onClicked: { root.closeRequested(); CaptureService.shot("region"); } }
                    GlassButton { objectName: "statusShotScreen"; text: "Whole screen"; variant: "secondary"; onClicked: { root.closeRequested(); CaptureService.shot("screen"); } }
                }
                Caption { text: "SCREEN RECORDING"; topPadding: 4 }
                // the sound it takes, chosen before it starts
                Row {
                    visible: !CaptureService.recording
                    spacing: 2
                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        text: "Sound"; rightPadding: Theme.padSm
                        color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSmaller
                    }
                    Repeater {
                        model: [{ id: "none", label: "None" }, { id: "desktop", label: "Desktop" }, { id: "mic", label: "Microphone" }]
                        delegate: Rectangle {
                            id: seg
                            required property var modelData
                            readonly property bool picked: CaptureService.audio === modelData.id
                            objectName: "recordSound:" + modelData.id
                            width: segText.implicitWidth + Theme.padLg; height: 26; radius: 13
                            color: seg.picked ? Theme.mix(Theme.layer1, Theme.accent, 0.22) : (segArea.containsMouse ? Theme.layer1Hover : Theme.layer1)
                            Behavior on color { ColorAnimation { duration: Theme.durationFast } }
                            Text {
                                id: segText
                                anchors.centerIn: parent
                                text: seg.modelData.label
                                color: seg.picked ? Theme.textActive : Theme.text
                                font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSmaller; font.weight: seg.picked ? Font.DemiBold : Font.Normal
                            }
                            MouseArea { id: segArea; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: CaptureService.audio = seg.modelData.id }
                        }
                    }
                }
                Flow {
                    width: parent.width
                    spacing: Theme.padSm
                    GlassButton { objectName: "statusRecordRegion"; visible: !CaptureService.recording; text: "Region"; variant: "secondary"; onClicked: { root.closeRequested(); CaptureService.record("region"); } }
                    GlassButton { objectName: "statusRecordScreen"; visible: !CaptureService.recording; text: "Whole screen"; variant: "secondary"; onClicked: { root.closeRequested(); CaptureService.record("screen"); } }
                    GlassButton { objectName: "statusRecordStop"; visible: CaptureService.recording; text: "Stop recording"; variant: "primary"; onClicked: CaptureService.stop() }
                }
                Note { text: "Screenshots go to ~/Pictures/Screenshots and the clipboard; recordings to ~/Videos/Recordings." }
            }

            // PERFORMANCE
            Column {
                objectName: "statusSection:performance"
                visible: root.shown === "performance"
                width: parent.width
                spacing: Theme.padSm
                SectionHead {
                    glyph: "\u{f04c5}"; title: "Performance"
                    detail: [PerformanceService.hostName, PerformanceService.kernel].filter((t) => t).join(" · ")
                }
                Hairline {}
                Row {
                    spacing: Theme.padLg
                    anchors.horizontalCenter: parent.horizontalCenter
                    Gauge { objectName: "statusGaugeCpu"; label: "CPU"; value: PerformanceService.cpuPercent; extra: PerformanceService.cpuTempC >= 0 ? Math.round(PerformanceService.cpuTempC) + "°C" : "" }
                    Gauge { objectName: "statusGaugeMem"; label: "Memory"; value: PerformanceService.memPercent; extra: PerformanceService.memUsedGiB.toFixed(1) + " / " + PerformanceService.memTotalGiB.toFixed(0) + " GiB" }
                    Gauge {
                        objectName: "statusGaugeGpu"
                        label: "GPU"; value: PerformanceService.gpuPercent
                        available: PerformanceService.gpuAvailable
                        extra: !PerformanceService.gpuAvailable ? "no reading" : (PerformanceService.gpuTempC >= 0 ? Math.round(PerformanceService.gpuTempC) + "°C" : "")
                    }
                }
                Grid {
                    columns: 2
                    columnSpacing: Theme.padLg; rowSpacing: 4
                    width: parent.width
                    Readout { label: "Disk"; value: PerformanceService.diskUsedLabel || Math.round(PerformanceService.diskPercent) + "%" }
                    Readout { label: "Network"; value: "↓ " + root.rate(PerformanceService.netDownKBs) + "  ↑ " + root.rate(PerformanceService.netUpKBs) }
                    Readout { label: "Load"; value: PerformanceService.load1.toFixed(2) }
                    Readout { label: "Up"; value: root.uptime(PerformanceService.uptimeS) }
                    Readout {
                        objectName: "statusVram"
                        visible: PerformanceService.vramTotalGiB > 0
                        label: "VRAM"; value: PerformanceService.vramUsedGiB.toFixed(1) + " / " + PerformanceService.vramTotalGiB.toFixed(1) + " GiB"
                    }
                    Readout {
                        objectName: "statusGpuPower"
                        visible: PerformanceService.gpuPowerW >= 0 || PerformanceService.gpuClockMHz >= 0
                        label: "GPU"
                        value: [PerformanceService.gpuPowerW >= 0 ? Math.round(PerformanceService.gpuPowerW) + " W" : "",
                                PerformanceService.gpuClockMHz > 0 ? Math.round(PerformanceService.gpuClockMHz) + " MHz" : (PerformanceService.gpuClockMHz === 0 ? "idle" : "")]
                               .filter((t) => t).join(" · ")
                    }
                    Readout {
                        objectName: "statusPing"
                        visible: root.pingHost.length > 0
                        label: "Ping"
                        value: (root.pingMs >= 0 ? (root.pingMs < 10 ? root.pingMs.toFixed(1) : Math.round(root.pingMs)) + " ms"
                                : (root.pingMs === -1 ? "no reply" : "…")) + "  " + root.pingHost
                    }
                }
                Item {
                    width: parent.width; height: 24
                    Text {
                        objectName: "statusOpenGraphs"
                        anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
                        text: "Graphs in the Dashboard  ›"
                        color: graphsArea.containsMouse ? Theme.accentText : Theme.text
                        font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSmaller
                        MouseArea { id: graphsArea; anchors.fill: parent; anchors.margins: -6; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: root.dashboardRequested("performance") }
                    }
                }
            }

            Hairline {}
            // the full Dashboard (Media, Performance, everything at once)
            Item {
                width: parent.width; height: 28
                Text {
                    objectName: "statusOpenDashboard"
                    anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
                    text: "Dashboard  "
                    color: dashArea.containsMouse ? Theme.accentText : Theme.text
                    font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSmall
                    MouseArea { id: dashArea; anchors.fill: parent; anchors.margins: -6; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: root.dashboardRequested("") }
                }
            }
        }
    }
}
