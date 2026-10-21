import QtQuick
import Quickshell
import Quickshell.Io

// bluetoothctl-backed device list: the devices bluez knows (paired ones,
// and any found by a scan), with connect/disconnect/forget, a timed scan for
// nearby devices, and pairing (pair, then trust, then connect).
//
// Pairing a device that asks for a PIN or a confirmation needs a pairing
// agent running in the session -- on this rice, blueman-applet -- which asks
// in its own dialog; bluetoothctl run from here has no way to answer.
// `agentRunning` says whether one is there, so the panel can say so rather
// than leave a pairing to fail silently.
Item {
    id: root
    property bool radioOn: false
    property var devices: []
    // False until the first device list actually resolves (all per-device
    // info queries done), so UI bound to devices.length can tell "no data
    // yet" apart from "scanned, found none/few" -- see the Expandable
    // auto-collapse fix in QuickSettings.
    property bool hasScanned: false
    readonly property var paired: root.devices.filter((d) => d.paired)
    readonly property var nearby: root.devices.filter((d) => !d.paired)

    // ---- discovery: a scan of `scanSeconds`, the list re-read as it goes ----
    readonly property int scanSeconds: 12
    readonly property bool scanning: scanProc.running
    function scan() {
        if (!root.radioOn || scanProc.running) return;
        scanProc.running = true;
        root.refresh();
    }
    Process {
        id: scanProc
        command: ["bluetoothctl", "--timeout", String(root.scanSeconds), "scan", "on"]
        onRunningChanged: if (!running) root.refresh()
    }
    Timer { running: scanProc.running; interval: 3000; repeat: true; onTriggered: root.refresh() }

    // ---- pairing ----
    property string pairingMac: ""
    property string pairError: ""          // "" or what went wrong, for the panel
    function pair(mac) {
        if (pairProc.running) return;
        root.pairingMac = mac;
        root.pairError = "";
        pairProc.command = ["sh", "-c", "bluetoothctl --timeout 25 pair \"$1\" && bluetoothctl trust \"$1\" && bluetoothctl --timeout 10 connect \"$1\"", "pair", mac];
        pairProc.running = true;
    }
    Process {
        id: pairProc
        stdout: StdioCollector {
            onStreamFinished: {
                const t = this.text;
                const failed = t.match(/Failed to (pair|connect)[^\n]*/);
                if (failed) {
                    root.pairError = /AuthenticationFailed|AuthenticationCanceled|AuthenticationRejected/.test(failed[0])
                        ? (root.agentRunning ? "Pairing was refused or cancelled." : "This device needs a PIN or a confirmation, and no pairing agent is running (start blueman-applet).")
                        : failed[0];
                } else if (!/Pairing successful|AlreadyExists/.test(t)) {
                    root.pairError = "Pairing didn't finish.";
                }
            }
        }
        onRunningChanged: if (!running) { root.pairingMac = ""; root.refresh(); }
    }
    property bool agentRunning: false
    Process {
        id: agentCheck
        command: ["pgrep", "-x", "blueman-applet"]
        stdout: StdioCollector { onStreamFinished: root.agentRunning = this.text.trim().length > 0 }
    }

    onRadioOnChanged: if (radioOn) { refresh(); agentCheck.running = true; }
    Component.onCompleted: agentCheck.running = true

    // One refresh at a time. Device info is read by ONE chained process,
    // device after device. A refresh that arrived mid-chain (the radio
    // toggled, or the post-connect refresh during a slow chain) used to
    // reset the queues and re-point that process while its previous
    // `bluetoothctl info` was still running, so that run's output was filed
    // under the next device's MAC: a connected headset could show as
    // disconnected, with another device's battery level. Now a refresh
    // requested mid-chain is remembered and runs once the chain finishes.
    property bool _busy: false
    property bool _again: false
    function refresh() {
        if (root._busy) { root._again = true; return; }
        root._busy = true;
        listProc.run += 1;
        listProc.running = true;
    }

    property var pendingMacs: []
    property var results: ({})
    property var _pendingNames: ({})
    // Which run of each process has delivered its output. A process that
    // stops without delivering any (bluetoothctl missing, or failing to
    // start: Quickshell then emits no streamFinished) must still end the
    // chain, or it would stay busy and no refresh would ever run again.
    // Decided a turn later, once both signals are in, whichever order the
    // stop and the stream end arrive in.
    property int _listDoneRun: 0
    property int _infoDoneRun: 0

    Process {
        id: listProc
        command: ["bluetoothctl", "devices"]
        property int run: 0
        onRunningChanged: if (!running && root._busy) {
            const r = listProc.run;
            Qt.callLater(() => {
                if (root._busy && listProc.run === r && root._listDoneRun < r) {
                    root._listDoneRun = r;
                    root.pendingMacs = [];
                    root.results = {};
                    root._finishChain();
                }
            });
        }
        stdout: StdioCollector {
            onStreamFinished: {
                root._listDoneRun = listProc.run;
                const macs = [];
                const names = {};
                for (const line of this.text.split("\n")) {
                    const m = line.match(/^Device\s+(\S+)\s+(.+)/);
                    if (m) { macs.push(m[1]); names[m[1]] = m[2]; }
                }
                root.pendingMacs = macs;
                root.results = {};
                root._pendingNames = names;
                root._checkNext();
            }
        }
    }

    function _finishChain() {
        const list = [];
        for (const mac in root.results) {
            const info = root.results[mac];
            list.push({ mac, name: root._pendingNames[mac] || mac, connected: info.connected, battery: info.battery, paired: info.paired });
        }
        root.devices = list;
        root.hasScanned = true;
        root._busy = false;
        if (root._again) { root._again = false; root.refresh(); }
    }

    function _checkNext() {
        if (root.pendingMacs.length === 0) { root._finishChain(); return; }
        const mac = root.pendingMacs.shift();
        infoProc.mac = mac;
        infoProc.run += 1;
        infoProc.command = ["bluetoothctl", "info", mac];
        infoProc.running = true;
    }

    Process {
        id: infoProc
        property string mac: ""
        property int run: 0
        // same guard as listProc: a run that delivered nothing skips its device
        onRunningChanged: if (!running && root._busy) {
            const r = infoProc.run;
            Qt.callLater(() => {
                if (root._busy && infoProc.run === r && root._infoDoneRun < r) {
                    root._infoDoneRun = r;
                    root._checkNext();
                }
            });
        }
        stdout: StdioCollector {
            onStreamFinished: {
                root._infoDoneRun = infoProc.run;
                const batteryMatch = this.text.match(/Battery Percentage:.*\((\d+)\)/);
                root.results[infoProc.mac] = {
                    connected: /Connected:\s*yes/.test(this.text),
                    // (a device with no "Paired:" line is an old listing: it was paired)
                    paired: !/Paired:\s*no/.test(this.text),
                    battery: batteryMatch ? Number(batteryMatch[1]) : -1
                };
                root._checkNext();
            }
        }
    }

    function toggleConnect(mac, currentlyConnected) {
        Quickshell.execDetached(["bluetoothctl", currentlyConnected ? "disconnect" : "connect", mac]);
        refreshTimer.restart();
    }

    function forget(mac) {
        Quickshell.execDetached(["bluetoothctl", "remove", mac]);
        refreshTimer.restart();
    }

    Timer { id: refreshTimer; interval: 1500; onTriggered: root.refresh() }
}
