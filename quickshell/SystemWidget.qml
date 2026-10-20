import QtQuick

// CPU, memory, GPU and network at a glance, each with the last minute as a
// strip of bars. Numbers come from PerformanceService (/proc and sysfs), and
// only while this card is shown: hidden, it samples nothing. A reading the
// machine can't give (no readable GPU) says "n/a" -- never a made-up zero.
DesktopWidget {
    id: root
    name: "system"
    defaultCorner: "top-right"
    defaultOn: false
    contentWidth: 232
    contentHeight: 164

    readonly property int history: 36
    property var cpu: []
    property var mem: []
    property var gpu: []
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
        function onCpuPercentChanged() { root.cpu = root._push(root.cpu, PerformanceService.cpuPercent); }
        function onMemPercentChanged() { root.mem = root._push(root.mem, PerformanceService.memPercent); }
        function onGpuPercentChanged() { if (PerformanceService.gpuAvailable) root.gpu = root._push(root.gpu, PerformanceService.gpuPercent); }
        function onNetworkRateKBsChanged() { root.net = root._push(root.net, Math.min(100, PerformanceService.networkRateKBs / 50)); }
    }

    function rateLabel(kbs) { return kbs >= 1024 ? (kbs / 1024).toFixed(1) + " MB/s" : Math.round(kbs) + " KB/s"; }

    Column {
        anchors.fill: parent
        spacing: 12
        Repeater {
            model: [
                { id: "cpu", label: "CPU" },
                { id: "mem", label: "MEMORY" },
                { id: "gpu", label: "GPU" },
                { id: "net", label: "NETWORK" },
            ]
            delegate: Item {
                id: row
                required property var modelData
                objectName: "systemRow:" + row.modelData.id
                width: parent.width; height: 32
                readonly property var samples: root[row.modelData.id]
                readonly property bool missing: row.modelData.id === "gpu" && !PerformanceService.gpuAvailable
                readonly property string value: {
                    if (row.missing) return "n/a";
                    switch (row.modelData.id) {
                    case "cpu": return Math.round(PerformanceService.cpuPercent) + "%";
                    case "mem": return Math.round(PerformanceService.memPercent) + "%";
                    case "gpu": return Math.round(PerformanceService.gpuPercent) + "%";
                    default: return root.rateLabel(PerformanceService.networkRateKBs);
                    }
                }
                Text {
                    text: row.modelData.label
                    color: Theme.text; opacity: Theme.opacityMuted
                    font.family: Theme.fontFamily; font.pixelSize: 9; font.weight: Font.DemiBold; font.letterSpacing: 2
                }
                Text {
                    objectName: "systemValue:" + row.modelData.id
                    anchors.right: parent.right
                    text: row.value
                    color: row.missing ? Theme.text : Theme.textActive
                    opacity: row.missing ? Theme.opacityFaint : 1
                    font.family: Theme.fontFamily; font.pixelSize: 13; font.weight: Font.Medium
                }
                // the last minute as bars; each is its own height, easing to it
                Row {
                    anchors.bottom: parent.bottom
                    width: parent.width; height: 16
                    spacing: 2
                    visible: !row.missing
                    Repeater {
                        model: root.history
                        delegate: Rectangle {
                            required property int index
                            readonly property real v: row.samples.length > (root.history - 1 - index) && root.history - 1 - index >= 0
                                ? (row.samples[row.samples.length - 1 - (root.history - 1 - index)] || 0) : 0
                            width: (parent.width - 2 * (root.history - 1)) / root.history
                            height: Math.max(2, parent.height * Math.min(100, v) / 100)
                            anchors.bottom: parent.bottom
                            radius: 1
                            color: index === root.history - 1 ? Theme.accent : Theme.mix(Theme.borderIdle, Theme.accent, 0.45)
                            Behavior on height { NumberAnimation { duration: Theme.durationDefault; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveStandard } }
                        }
                    }
                }
            }
        }
    }
}
