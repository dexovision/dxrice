import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Services.Pipewire

// One section of the bar's right-hand island, opened from its own
// indicator: Network, Bluetooth, Audio, Power or Notifications. It is the
// same surface for all of them (the island morphs to fit), and changing
// section slides the old content out and the new in, so moving along the
// indicators reads as one panel turning, not five panels popping.
//
// Everything is the system's own state, read and set through the same
// backends the Dashboard uses (WifiBackend, BluetoothBackend,
// AudioDeviceBackend, BrightnessBackend, Pipewire, BatteryService, mako):
// a slider here and the Dashboard's are the same device, never two copies.
Item {
    id: root
    objectName: "statusPanel"
    anchors.fill: parent
    signal closeRequested()
    signal dashboardRequested()

    property string section: "network"
    // the island sizes itself to this (TopBar)
    readonly property real contentHeight: body.implicitHeight + Theme.padLg * 2
    // a separate top-level window the bar's click-outside catcher can't see
    property bool wifiDialogOpen: false

    // ---- section changes: the old slides away, the new comes in ----
    readonly property var order: ["network", "bluetooth", "audio", "power", "notifications"]
    property string shown: root.section
    property int direction: 1
    onSectionChanged: {
        root.direction = root.order.indexOf(root.section) >= root.order.indexOf(root.shown) ? 1 : -1;
        swap.restart();
    }
    SequentialAnimation {
        id: swap
        NumberAnimation { target: body; property: "opacity"; to: 0; duration: Theme.reduceMotion ? 0 : 90; easing.type: Easing.InQuad }
        ScriptAction { script: { root.shown = root.section; slide.x = root.direction * 22; } }
        ParallelAnimation {
            NumberAnimation { target: body; property: "opacity"; to: 1; duration: Theme.durationDefault; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveStandard }
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
    // notifications: summaries and app names only (never bodies), newest first
    property var notifications: []
    Process {
        id: historyProc
        command: ["makoctl", "history"]
        stdout: StdioCollector {
            onStreamFinished: {
                const out = [];
                let cur = null;
                for (const line of this.text.split("\n")) {
                    const m = /^Notification (\d+): (.*)$/.exec(line);
                    if (m) { cur = { id: Number(m[1]), summary: m[2].replace(/[⁨⁩]/g, ""), app: "" }; out.push(cur); continue; }
                    const a = /^\s+App name: (.*)$/.exec(line);
                    if (a && cur) cur.app = a[1];
                }
                root.notifications = out.slice(0, 6);
            }
        }
    }
    function refresh() { wifiCheck.running = true; btCheck.running = true; dndCheck.running = true; historyProc.running = true; }
    Component.onCompleted: root.refresh()
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
    BluetoothBackend { id: btBackend; radioOn: root.btOn }
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
            color: Theme.accent
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
            text: ""; color: Theme.accent; font.family: Theme.iconFamily; font.pixelSize: Theme.fontSizeSmall
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
                    model: root.btOn ? btBackend.devices.slice(0, 6) : []
                    delegate: DeviceRow {
                        required property var modelData
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
                    visible: !root.btAvailable || !root.btOn || (btBackend.hasScanned && btBackend.devices.length === 0)
                    text: !root.btAvailable ? "There is no Bluetooth adapter to switch on."
                        : (!root.btOn ? "Bluetooth is off." : "No paired devices.")
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
                    GlassButton {
                        text: "Log out"; variant: "secondary"
                        onClicked: Quickshell.execDetached(["sh", "-c", 'sid="$(loginctl show-user "$(id -un)" -p Display --value 2>/dev/null)"; [ -n "$sid" ] && exec loginctl terminate-session "$sid"'])
                    }
                    GlassButton { text: "Restart"; variant: "secondary"; onClicked: Quickshell.execDetached(["sh", Quickshell.shellDir + "/../scripts/dxrice_power.sh", "reboot"]) }
                    GlassButton { text: "Shut down"; variant: "secondary"; onClicked: Quickshell.execDetached(["sh", Quickshell.shellDir + "/../scripts/dxrice_power.sh", "poweroff"]) }
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
                    detail: root.dnd ? "Do not disturb" : (root.notifications.length ? "Recent" : "Nothing recent")
                    hasSwitch: true; checked: root.dnd
                    onToggled: (next) => root.setDnd(next)
                }
                Hairline {}
                Repeater {
                    model: root.notifications
                    delegate: Item {
                        required property var modelData
                        width: body.width; height: 40
                        Text {
                            y: 4; width: parent.width
                            text: modelData.summary; elide: Text.ElideRight
                            color: Theme.textActive; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSmall
                        }
                        Text {
                            y: 22; width: parent.width
                            text: modelData.app; elide: Text.ElideRight
                            color: Theme.text; opacity: Theme.opacityMuted; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSmaller
                        }
                    }
                }
                Note { visible: root.notifications.length === 0; text: "No notifications yet." }
            }

            Hairline {}
            // the full Dashboard (Media, Performance, everything at once)
            Item {
                width: parent.width; height: 28
                Text {
                    objectName: "statusOpenDashboard"
                    anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
                    text: "Dashboard  "
                    color: dashArea.containsMouse ? Theme.accent : Theme.text
                    font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSmall
                    MouseArea { id: dashArea; anchors.fill: parent; anchors.margins: -6; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: root.dashboardRequested() }
                }
            }
        }
    }
}
