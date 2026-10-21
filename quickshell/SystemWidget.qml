import QtQuick
import Quickshell

// The machine, read like a terminal: a user@host header and a rule, then a
// row per reading -- label, value, the last minute drawn in block
// characters, and a temperature where there is a sensor -- and the theme's
// own colours as a strip at the end (the fastfetch look).
//
// Everything comes from PerformanceService (/proc and sysfs), sampled only
// while this card is shown. A reading this machine can't give is not shown
// as zero: the GPU says "n/a", and a row with nothing behind it (no
// battery, no temperature sensor) is left out.
DesktopWidget {
    id: root
    name: "system"
    defaultCorner: "top-right"
    defaultOn: false
    surface: "terminal"
    interactive: false
    pad: 18
    contentWidth: 372
    contentHeight: body.implicitHeight

    readonly property int history: 24
    property var cpu: []
    property var gpu: []
    property var mem: []
    property var net: []
    function _push(list, v) { const a = list.slice(-(root.history - 1)); a.push(v); return a; }

    // count in and out of the shared sampler only while this card is shown
    property bool _counted: false
    onActiveChanged: {
        if (root.active && !root._counted) { PerformanceService.widgetUsers += 1; root._counted = true; }
        else if (!root.active && root._counted) { PerformanceService.widgetUsers -= 1; root._counted = false; }
    }
    Component.onCompleted: if (root.active && !root._counted) { PerformanceService.widgetUsers += 1; root._counted = true; }
    Component.onDestruction: if (root._counted) PerformanceService.widgetUsers -= 1

    Connections {
        target: PerformanceService
        enabled: root.active
        function onSampled() {
            const P = PerformanceService;
            root.cpu = root._push(root.cpu, P.cpuPercent);
            root.mem = root._push(root.mem, P.memPercent);
            if (P.gpuAvailable) root.gpu = root._push(root.gpu, P.gpuPercent);
            root.net = root._push(root.net, P.netDownKBs);
        }
    }

    // ---- formatting (pure, so tests can check it) ----
    readonly property string ramp: "▁▂▃▄▅▆▇█"
    // values 0..max as block characters, oldest first, padded to `history`
    function spark(values, max) {
        let out = "";
        for (let i = 0; i < root.history - values.length; i++) out += " ";
        for (const v of values) {
            const f = max > 0 ? Math.max(0, Math.min(1, v / max)) : 0;
            out += root.ramp.charAt(Math.min(7, Math.floor(f * 7.999)));
        }
        return out;
    }
    function gauge(fraction, cells) {
        const n = Math.round(Math.max(0, Math.min(1, fraction)) * cells);
        return "█".repeat(n) + "░".repeat(cells - n);
    }
    function rate(kbs) { return kbs >= 1024 ? (kbs / 1024).toFixed(1) + " MB/s" : Math.round(kbs) + " KB/s"; }
    function temp(c) { return c < 0 ? "" : Math.round(c) + "°"; }
    function uptime(s) {
        const d = Math.floor(s / 86400), h = Math.floor(s % 86400 / 3600), m = Math.floor(s % 3600 / 60);
        return (d > 0 ? d + "d " : "") + (d > 0 || h > 0 ? h + "h " : "") + m + "m";
    }
    readonly property real netMax: Math.max(64, ...root.net)

    readonly property var rows: {
        const P = PerformanceService;
        const out = [
            { id: "cpu", label: "cpu", value: Math.round(P.cpuPercent) + "%", graph: root.spark(root.cpu, 100), tail: root.temp(P.cpuTempC) },
            { id: "gpu", label: "gpu", value: P.gpuAvailable ? Math.round(P.gpuPercent) + "%" : "n/a",
              graph: P.gpuAvailable ? root.spark(root.gpu, 100) : "", tail: root.temp(P.gpuTempC) },
            { id: "mem", label: "mem", value: P.memUsedGiB.toFixed(1) + " / " + P.memTotalGiB.toFixed(1) + " GiB",
              graph: root.gauge(P.memPercent / 100, 12), tail: Math.round(P.memPercent) + "%" },
        ];
        if (P.diskUsedLabel.length > 0)
            out.push({ id: "disk", label: "disk", value: P.diskUsedLabel, graph: root.gauge(P.diskPercent / 100, 12), tail: root.temp(P.diskTempC) });
        out.push({ id: "net", label: "net", value: "↓ " + root.rate(P.netDownKBs),
                   graph: root.spark(root.net, root.netMax), tail: "↑ " + root.rate(P.netUpKBs) });
        if (P.batteryPercent >= 0)
            out.push({ id: "bat", label: "bat", value: P.batteryPercent + "%  " + P.batteryStatus.toLowerCase(),
                       graph: root.gauge(P.batteryPercent / 100, 12), tail: "" });
        out.push({ id: "up", label: "up", value: root.uptime(P.uptimeS), graph: "", tail: "load " + P.load1.toFixed(2) });
        return out;
    }

    Column {
        id: body
        width: parent.width
        spacing: 6
        Row {
            spacing: 0
            Text {
                objectName: "systemUser"
                text: Quickshell.env("USER") || "user"
                color: Theme.accent
                font.family: Theme.fontMono; font.pixelSize: 14; font.weight: Font.Bold
            }
            Text { text: "@"; color: Theme.textActive; opacity: 0.6; font.family: Theme.fontMono; font.pixelSize: 14 }
            Text {
                objectName: "systemHost"
                text: PerformanceService.hostName
                color: Theme.accent
                font.family: Theme.fontMono; font.pixelSize: 14; font.weight: Font.Bold
            }
            Text {
                text: PerformanceService.kernel.length > 0 ? "  " + PerformanceService.kernel : ""
                color: Theme.textActive; opacity: 0.5
                font.family: Theme.fontMono; font.pixelSize: 12
                anchors.baseline: parent.children[0].baseline
            }
        }
        Text {
            width: parent.width
            text: "─".repeat(Math.ceil(width / 7))
            clip: true
            color: Theme.textActive; opacity: 0.25
            font.family: Theme.fontMono; font.pixelSize: 12
        }
        Repeater {
            model: root.rows
            delegate: Item {
                id: row
                required property var modelData
                objectName: "systemRow:" + row.modelData.id
                width: body.width; height: 18
                Text {
                    width: 44
                    text: row.modelData.label
                    color: Theme.accent
                    font.family: Theme.fontMono; font.pixelSize: 13; font.weight: Font.Bold
                }
                Text {
                    objectName: "systemValue:" + row.modelData.id
                    x: 44; width: 150
                    text: row.modelData.value
                    elide: Text.ElideRight
                    color: row.modelData.value === "n/a" ? Theme.text : Theme.textActive
                    opacity: row.modelData.value === "n/a" ? 0.5 : 1
                    font.family: Theme.fontMono; font.pixelSize: 13
                }
                Text {
                    objectName: "systemGraph:" + row.modelData.id
                    x: 196
                    text: row.modelData.graph
                    color: Theme.mix(Theme.textActive, Theme.accent, 0.55)
                    font.family: Theme.fontMono; font.pixelSize: 13
                }
                Text {
                    anchors.right: parent.right
                    text: row.modelData.tail
                    color: Theme.textActive; opacity: 0.65
                    font.family: Theme.fontMono; font.pixelSize: 12
                }
            }
        }
        // the theme's colours, as fastfetch prints the terminal's
        Row {
            objectName: "systemPalette"
            topPadding: 4
            spacing: 0
            Repeater {
                model: [Theme.panel, Theme.layer1, Theme.borderIdle, Theme.text, Theme.textActive, Theme.accent,
                        "#" + String(Theme.data.hypr_active_border_1 || "8090a0"), "#" + String(Theme.data.hypr_active_border_2 || "c0a0b0")]
                delegate: Rectangle { required property var modelData; width: 26; height: 12; color: modelData }
            }
        }
    }
}
