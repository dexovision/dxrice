import QtQuick
import Quickshell
import Quickshell.Io

// nmcli-backed wifi network list. Kept as a plain CLI wrapper (like the
// old Python version) rather than Quickshell.Network for this first pass
// -- opened far less often than the volume slider, so subprocess latency
// here matters less than getting the native Pipewire binding right did.
Item {
    id: root
    property bool radioOn: false
    property var networks: []
    // Refreshed alongside the scan (not per-row) so "Forget" only shows for
    // networks nmcli actually has a saved connection profile for.
    property var savedNames: []

    onRadioOnChanged: if (radioOn) refresh()

    function refresh() {
        scanProc.running = true;
        savedNamesProc.running = true;
    }

    Process {
        id: savedNamesProc
        command: ["nmcli", "-t", "-f", "NAME", "connection", "show"]
        stdout: StdioCollector {
            onStreamFinished: root.savedNames = this.text.split("\n").filter((n) => n.length > 0)
        }
    }

    Process {
        id: scanProc
        command: ["nmcli", "-t", "-f", "active,ssid,signal,security", "dev", "wifi", "list"]
        stdout: StdioCollector {
            onStreamFinished: {
                const seen = {};
                for (const line of this.text.split("\n")) {
                    const parts = line.split(":");
                    if (parts.length < 4 || !parts[1]) continue;
                    const ssid = parts[1];
                    const signal = Number(parts[2]) || 0;
                    const connected = parts[0] === "yes";
                    if (!(ssid in seen) || signal > seen[ssid].signal) {
                        seen[ssid] = { ssid, signal, security: parts[3], connected, known: root.savedNames.includes(ssid) };
                    }
                }
                const list = Object.values(seen).sort((a, b) => (b.connected - a.connected) || (b.signal - a.signal));
                root.networks = list.slice(0, 8);
            }
        }
    }

    signal passwordNeeded(string ssid)

    Process {
        id: savedCheckProc
        property string ssid: ""
        command: ["nmcli", "-t", "-f", "NAME", "connection", "show"]
        stdout: StdioCollector {
            onStreamFinished: {
                const names = this.text.split("\n");
                if (names.includes(savedCheckProc.ssid)) {
                    root._doConnect(savedCheckProc.ssid);
                } else {
                    root.passwordNeeded(savedCheckProc.ssid);
                }
            }
        }
    }

    function connectTo(ssid, security) {
        const isOpen = !security || security === "--" || security === "";
        if (isOpen) {
            root._doConnect(ssid);
        } else {
            savedCheckProc.ssid = ssid;
            savedCheckProc.running = true;
        }
    }

    function connectWithPassword(ssid, password) {
        Quickshell.execDetached(["nmcli", "device", "wifi", "connect", ssid, "password", password]);
        refreshTimer.restart();
    }

    function _doConnect(ssid) {
        Quickshell.execDetached(["nmcli", "device", "wifi", "connect", ssid]);
        refreshTimer.restart();
    }

    function forget(ssid) {
        Quickshell.execDetached(["nmcli", "connection", "delete", ssid]);
        refreshTimer.restart();
    }

    Timer { id: refreshTimer; interval: 1000; onTriggered: root.refresh() }
}
