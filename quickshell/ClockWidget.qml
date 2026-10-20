import QtQuick

// The desktop clock: the time large and light, the weekday in the accent,
// the date under it, and a thin line along the bottom that fills as the day
// goes. theme.json: "clock_24h" (default true) and "clock_seconds" (false).
DesktopWidget {
    id: root
    name: "clock"
    defaultCorner: "top-left"
    defaultOn: true
    contentWidth: 292
    contentHeight: 134

    readonly property bool h24: Theme.data.clock_24h !== false
    readonly property bool seconds: Theme.data.clock_seconds === true
    property date now: new Date()
    readonly property real dayFraction: (now.getHours() * 3600 + now.getMinutes() * 60 + now.getSeconds()) / 86400

    Timer {
        // ticks each second with seconds shown, else just after each minute
        running: root.active
        repeat: false
        interval: 1
        onTriggered: {
            root.now = new Date();
            interval = root.seconds ? 1000 - root.now.getMilliseconds() + 20
                                    : 60000 - (root.now.getSeconds() * 1000 + root.now.getMilliseconds()) + 50;
            restart();
        }
    }

    Column {
        anchors.fill: parent
        spacing: 2
        Text {
            objectName: "clockWeekday"
            text: Qt.formatDateTime(root.now, "dddd").toUpperCase()
            color: Theme.accent
            font.family: Theme.fontFamily; font.pixelSize: 12; font.weight: Font.DemiBold
            font.letterSpacing: 3
        }
        Row {
            spacing: 6
            Text {
                objectName: "clockTime"
                text: Qt.formatDateTime(root.now, root.h24 ? "HH:mm" : "h:mm")
                color: Theme.textActive
                font.family: Theme.fontFamily; font.pixelSize: 62; font.weight: Font.Light
            }
            Column {
                anchors.bottom: parent.bottom; anchors.bottomMargin: 10
                visible: root.seconds || !root.h24
                spacing: 0
                Text {
                    objectName: "clockSeconds"
                    visible: root.seconds
                    text: Qt.formatDateTime(root.now, "ss")
                    color: Theme.text; opacity: Theme.opacityMuted
                    font.family: Theme.fontFamily; font.pixelSize: 20; font.weight: Font.Light
                }
                Text {
                    objectName: "clockMeridiem"
                    visible: !root.h24
                    text: Qt.formatDateTime(root.now, "AP")
                    color: Theme.text; opacity: Theme.opacityMuted
                    font.family: Theme.fontFamily; font.pixelSize: 14; font.weight: Font.Medium
                }
            }
        }
        Text {
            objectName: "clockDate"
            text: Qt.formatDateTime(root.now, "d MMMM yyyy")
            color: Theme.text; opacity: Theme.opacityMuted
            font.family: Theme.fontFamily; font.pixelSize: 14
        }
    }
    Rectangle {
        anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom
        height: 2; radius: 1
        color: Theme.borderIdle
        Rectangle {
            objectName: "clockDayBar"
            height: parent.height; radius: 1
            width: parent.width * root.dayFraction
            color: Theme.accent
            Behavior on width { NumberAnimation { duration: Theme.durationDefault; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveStandard } }
        }
    }
}
