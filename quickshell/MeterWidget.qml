import QtQuick

// One reading as a shape filled to its level, like a liquid -- each metric
// its own shape, so three of them side by side read as different objects,
// not three copies of a card:
//
//   "cpu"     a rounded pentagon     processor use (PerformanceService), and
//                                    its temperature when there is a sensor
//   "memory"  a tall rounded tank    memory in use, used / total GiB
//   "disk"    a scalloped disc       the root filesystem's use, used / size
//
// Real samples only, taken while it is shown (it counts itself in to
// PerformanceService the way the system monitor does). The level rises and
// falls on a soft spring; the surface is a still wave, so nothing animates
// once the level has settled.
DesktopWidget {
    id: root
    property string metric: "cpu"
    name: root.metric
    defaultOn: false
    defaultCorner: "top-right"
    surface: "none"
    interactive: false
    pad: 0
    contentWidth: root.metric === "memory" ? 136 : 150
    contentHeight: root.metric === "memory" ? 168 : 150

    readonly property real value: root.metric === "cpu" ? PerformanceService.cpuPercent
        : (root.metric === "memory" ? PerformanceService.memPercent : PerformanceService.diskPercent)
    readonly property string title: root.metric === "cpu" ? "CPU" : (root.metric === "memory" ? "Memory" : "Disk")
    readonly property string detail: root.metric === "cpu" ? (PerformanceService.cpuTempC >= 0 ? Math.round(PerformanceService.cpuTempC) + "°C" : "")
        : (root.metric === "memory" ? PerformanceService.memUsedGiB.toFixed(1) + " / " + PerformanceService.memTotalGiB.toFixed(0) + " GiB"
           : PerformanceService.diskUsedLabel)

    // sampled only while shown
    property bool _counted: false
    onActiveChanged: root._count()
    function _count() {
        if (root.active && !root._counted) { PerformanceService.widgetUsers += 1; root._counted = true; }
        else if (!root.active && root._counted) { PerformanceService.widgetUsers -= 1; root._counted = false; }
    }
    Component.onCompleted: root._count()
    Component.onDestruction: if (root._counted) PerformanceService.widgetUsers -= 1

    property real level: Math.max(0, Math.min(1, root.value / 100))
    Behavior on level { enabled: !Theme.reduceMotion; NumberAnimation { duration: Theme.durationSpring; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveSettle } }

    Canvas {
        id: shape
        objectName: "meterShape:" + root.metric
        anchors.fill: parent
        onWidthChanged: requestPaint()
        onHeightChanged: requestPaint()
        onVisibleChanged: if (visible) requestPaint()
        onAvailableChanged: if (available) requestPaint()
        Connections { target: root; function onLevelChanged() { shape.requestPaint(); } }
        Connections { target: Theme; function onAccentChanged() { shape.requestPaint(); } function onPanelChanged() { shape.requestPaint(); } }
        function rgba(c, a) { return "rgba(" + Math.round(c.r * 255) + "," + Math.round(c.g * 255) + "," + Math.round(c.b * 255) + "," + (a === undefined ? c.a : a) + ")"; }
        function outline(ctx) {
            const w = width, h = height;
            ctx.beginPath();
            if (root.metric === "cpu") {
                // a pentagon with rounded corners
                const cx = w / 2, cy = h / 2 + 6, r = Math.min(w, h) / 2 - 2;
                const pts = [];
                for (let i = 0; i < 5; i++) {
                    const a = -Math.PI / 2 + i * 2 * Math.PI / 5;
                    pts.push([cx + r * Math.cos(a), cy + r * Math.sin(a)]);
                }
                const mid = (p, q) => [(p[0] + q[0]) / 2, (p[1] + q[1]) / 2];
                const start = mid(pts[4], pts[0]);
                ctx.moveTo(start[0], start[1]);
                for (let i = 0; i < 5; i++) {
                    const p = pts[i], q = pts[(i + 1) % 5], m = mid(p, q);
                    ctx.arcTo(p[0], p[1], m[0], m[1], 18);
                }
            } else if (root.metric === "memory") {
                const r = 30;
                ctx.moveTo(r, 0); ctx.lineTo(w - r, 0); ctx.arcTo(w, 0, w, r, r);
                ctx.lineTo(w, h - r); ctx.arcTo(w, h, w - r, h, r);
                ctx.lineTo(r, h); ctx.arcTo(0, h, 0, h - r, r);
                ctx.lineTo(0, r); ctx.arcTo(0, 0, r, 0, r);
            } else {
                // a scalloped disc: a circle with ten soft bumps
                const cx = w / 2, cy = h / 2, R = Math.min(w, h) / 2 - 6;
                for (let i = 0; i <= 160; i++) {
                    const t = i / 160 * Math.PI * 2;
                    const r = R * (1 + 0.055 * Math.cos(10 * t));
                    const x = cx + r * Math.cos(t), y = cy + r * Math.sin(t);
                    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
                }
            }
            ctx.closePath();
        }
        onPaint: {
            const ctx = getContext("2d");
            ctx.reset();
            const w = width, h = height;
            // the vessel
            outline(ctx);
            ctx.fillStyle = rgba(Theme.panelTone, 0.78);
            ctx.fill();
            ctx.lineWidth = 1;
            ctx.strokeStyle = rgba(Theme.borderTint, 0.14);
            ctx.stroke();
            // the liquid, inside it: a still wave at the level
            ctx.save();
            outline(ctx);
            ctx.clip();
            const top = h - root.level * h;
            ctx.beginPath();
            ctx.moveTo(0, h);
            for (let x = 0; x <= w; x += 4) ctx.lineTo(x, top + 3.5 * Math.sin(x / w * Math.PI * 3));
            ctx.lineTo(w, h);
            ctx.closePath();
            ctx.fillStyle = rgba(Theme.accent, 0.55);
            ctx.fill();
            ctx.restore();
        }
    }
    Column {
        anchors.centerIn: parent
        anchors.verticalCenterOffset: root.metric === "cpu" ? 8 : 0
        spacing: 0
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: root.title
            color: Theme.textActive; opacity: 0.8
            font.family: Theme.fontFamily; font.pixelSize: 12; font.weight: Font.DemiBold; font.letterSpacing: 1
        }
        Text {
            objectName: "meterValue:" + root.metric
            anchors.horizontalCenter: parent.horizontalCenter
            text: Math.round(root.value) + "%"
            color: Theme.textActive
            font.family: Theme.fontFamily; font.pixelSize: 30; font.weight: Font.Bold
            font.features: { "tnum": 1 }
        }
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            visible: text.length > 0
            text: root.detail
            color: Theme.textActive; opacity: 0.7
            font.family: Theme.fontMono; font.pixelSize: 10
        }
    }
}
