import QtQuick
import Quickshell
import Quickshell.Io

// bluetoothctl-backed paired device list.
Item {
    id: root
    property bool radioOn: false
    property var devices: []

    onRadioOnChanged: if (radioOn) refresh()

    function refresh() {
        listProc.running = true;
    }

    property var pendingMacs: []
    property var results: ({})

    Process {
        id: listProc
        command: ["bluetoothctl", "devices"]
        stdout: StdioCollector {
            onStreamFinished: {
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

    property var _pendingNames: ({})

    function _checkNext() {
        if (root.pendingMacs.length === 0) {
            const list = [];
            for (const mac in root.results) {
                list.push({ mac, name: root._pendingNames[mac] || mac, connected: root.results[mac] });
            }
            root.devices = list;
            return;
        }
        const mac = root.pendingMacs.shift();
        infoProc.mac = mac;
        infoProc.command = ["bluetoothctl", "info", mac];
        infoProc.running = true;
    }

    Process {
        id: infoProc
        property string mac: ""
        stdout: StdioCollector {
            onStreamFinished: {
                root.results[infoProc.mac] = /Connected:\s*yes/.test(this.text);
                root._checkNext();
            }
        }
    }

    function toggleConnect(mac, currentlyConnected) {
        Quickshell.execDetached(["bluetoothctl", currentlyConnected ? "disconnect" : "connect", mac]);
        refreshTimer.restart();
    }

    Timer { id: refreshTimer; interval: 1500; onTriggered: root.refresh() }
}
