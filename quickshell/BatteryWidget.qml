import QtQuick

// The battery as a ring: the arc is the charge (drawn, not a bar in a box),
// the percentage sits in the middle, and a bolt says when it is charging.
// Only on a machine with a battery (BatteryService); low charge turns the
// arc the accent. It is the system's own reading, refreshed every 20 s.
DesktopWidget {
    id: root
    name: "battery"
    defaultCorner: "top-right"
    defaultOn: false
    wanted: BatteryService.available
    surface: "none"
    interactive: false
    contentWidth: ring.width
    contentHeight: ring.height + label.implicitHeight + 6

    readonly property real level: Math.max(0, Math.min(100, BatteryService.percent)) / 100
    readonly property bool low: BatteryService.percent >= 0 && BatteryService.percent <= 20 && !BatteryService.charging

    Item {
        id: ring
        width: 112; height: 112
        Canvas {
            id: arc
            objectName: "batteryArc"
            anchors.fill: parent
            property real shownLevel: root.level
            Behavior on shownLevel { NumberAnimation { duration: Theme.durationSpring; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveSettle } }
            onShownLevelChanged: requestPaint()
            property color track: Theme.withAlpha(Theme.borderTint, 0.18)
            property color fill: root.low ? Theme.accent : Theme.textActive
            onFillChanged: requestPaint()
            onPaint: {
                const ctx = getContext("2d");
                ctx.reset();
                const r = width / 2 - 7;
                ctx.lineWidth = 8;
                ctx.lineCap = "round";
                ctx.strokeStyle = arc.track;
                ctx.beginPath(); ctx.arc(width / 2, height / 2, r, 0, Math.PI * 2); ctx.stroke();
                if (arc.shownLevel > 0) {
                    ctx.strokeStyle = arc.fill;
                    ctx.beginPath();
                    ctx.arc(width / 2, height / 2, r, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * arc.shownLevel);
                    ctx.stroke();
                }
            }
        }
        Column {
            anchors.centerIn: parent
            spacing: -2
            Text {
                objectName: "batteryPercent"
                anchors.horizontalCenter: parent.horizontalCenter
                text: BatteryService.percent >= 0 ? BatteryService.percent + "%" : ""
                color: Theme.textActive
                font.family: Theme.fontFamily; font.pixelSize: 26; font.weight: Font.Light
            }
            Text {
                objectName: "batteryBolt"
                anchors.horizontalCenter: parent.horizontalCenter
                visible: BatteryService.plugged
                text: "\u{f0e7}"
                color: Theme.accentText
                font.family: Theme.iconFamily; font.pixelSize: 14
            }
        }
    }
    Text {
        id: label
        y: ring.height + 6
        width: ring.width
        horizontalAlignment: Text.AlignHCenter
        text: BatteryService.label
        color: Theme.textActive; opacity: 0.7
        font.family: Theme.fontFamily; font.pixelSize: 12; font.letterSpacing: 1
    }
}
