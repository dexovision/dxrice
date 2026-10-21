import QtQuick

// The desktop clock. No card: the time itself is the shape, in one of two
// styles (theme.json "clock_style"):
//
//   "type"    (default) the hours in the accent and the minutes in the text
//             colour, both heavy, a light colon raised between them; a thin
//             accent bar, then the month, the day and the weekday stacked
//   "blocks"  tty-clock's block digits, drawn as cells in the accent
//   "stacked" the hours over the minutes, both large, with a thin accent
//             hand crossing them at the minute's angle and the date beside
//   "analog"  a round face: hour ticks, the hands, a second hand in the
//             accent when seconds are on, and the date under it
//
// "clock_24h" (default true) and "clock_seconds" (false) apply to both. It is
// only to look at: it takes no input, so the desktop under it stays
// clickable.
DesktopWidget {
    id: root
    name: "clock"
    defaultCorner: "top-left"
    defaultOn: true
    surface: "none"
    interactive: false
    contentWidth: root.analog ? analogFace.width : (root.blocks ? blockFace.implicitWidth : (root.stacked ? stackFace.implicitWidth : typeFace.implicitWidth))
    contentHeight: root.analog ? analogFace.height : (root.blocks ? blockFace.implicitHeight : (root.stacked ? stackFace.implicitHeight : typeFace.implicitHeight))

    readonly property bool h24: Theme.data.clock_24h !== false
    readonly property bool seconds: Theme.data.clock_seconds === true
    readonly property bool blocks: Theme.data.clock_style === "blocks"
    readonly property bool analog: Theme.data.clock_style === "analog"
    readonly property bool stacked: Theme.data.clock_style === "stacked"
    property date now: new Date()
    readonly property real dayFraction: (now.getHours() * 3600 + now.getMinutes() * 60 + now.getSeconds()) / 86400
    readonly property string hours: Qt.formatDateTime(root.now, root.h24 ? "HH" : "h")
    readonly property string minutes: Qt.formatDateTime(root.now, "mm")
    readonly property string timeText: root.hours + ":" + root.minutes
    readonly property string meridiem: Qt.formatDateTime(root.now, "AP")
    // (sized to the screen with every other widget: DesktopWidget draws it at
    // WidgetStack.scale; k is kept for the proportions inside the faces)
    readonly property real k: 1
    // a new minute (or hour) rises into place; seconds just change
    component Roll: Text {
        id: roll
        property real lift: 0
        transform: Translate { y: roll.lift }
        onTextChanged: if (root.active && !Theme.reduceMotion) rollIn.restart()
        ParallelAnimation {
            id: rollIn
            NumberAnimation { target: roll; property: "lift"; from: 14 * root.k; to: 0; duration: Theme.durationSpring; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveSettle }
            NumberAnimation { target: roll; property: "opacity"; from: 0.15; to: 1; duration: Theme.durationDefault; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveStandard }
        }
    }

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

    // ---- "type" ----
    Row {
        id: typeFace
        objectName: "clockTypeFace"
        visible: !root.blocks && !root.analog && !root.stacked
        spacing: Math.round(22 * root.k)
        Row {
            id: digits
            spacing: 2
            Roll {
                objectName: "clockHours"
                text: root.hours
                color: Theme.accent
                font.family: Theme.fontFamily; font.pixelSize: Math.round(96 * root.k); font.weight: Font.Bold
                font.letterSpacing: -2
            }
            Text {
                text: ":"
                anchors.top: parent.top; anchors.topMargin: -8 * root.k
                color: Theme.textActive; opacity: 0.45
                font.family: Theme.fontFamily; font.pixelSize: Math.round(96 * root.k); font.weight: Font.Light
            }
            Roll {
                objectName: "clockMinutes"
                text: root.minutes
                color: Theme.textActive
                font.family: Theme.fontFamily; font.pixelSize: Math.round(96 * root.k); font.weight: Font.Bold
                font.letterSpacing: -2
            }
            Column {
                anchors.top: parent.top; anchors.topMargin: 22 * root.k
                spacing: 2
                leftPadding: 6
                Text {
                    objectName: "clockSeconds"
                    visible: root.seconds
                    text: Qt.formatDateTime(root.now, "ss")
                    color: Theme.accentText
                    font.family: Theme.fontMono; font.pixelSize: Math.round(18 * root.k); font.weight: Font.Medium
                }
                Text {
                    objectName: "clockMeridiem"
                    visible: !root.h24
                    text: root.meridiem
                    color: Theme.textActive; opacity: 0.7
                    font.family: Theme.fontFamily; font.pixelSize: Math.round(16 * root.k); font.weight: Font.DemiBold
                    font.letterSpacing: 1
                }
            }
        }
        Rectangle {
            width: 3; radius: 1.5
            height: digits.height - 34 * root.k
            anchors.verticalCenter: digits.verticalCenter
            color: Theme.accent; opacity: 0.85
        }
        Column {
            anchors.verticalCenter: digits.verticalCenter
            spacing: 0
            Text {
                objectName: "clockMonth"
                text: Qt.formatDateTime(root.now, "MMMM").toUpperCase()
                color: Theme.accentText
                font.family: Theme.fontFamily; font.pixelSize: Math.round(15 * root.k); font.weight: Font.Bold; font.letterSpacing: 4
            }
            Text {
                objectName: "clockDate"
                text: Qt.formatDateTime(root.now, "dd")
                color: Theme.textActive
                font.family: Theme.fontFamily; font.pixelSize: Math.round(40 * root.k); font.weight: Font.Medium; font.letterSpacing: 1
            }
            Text {
                objectName: "clockWeekday"
                text: Qt.formatDateTime(root.now, "dddd")
                color: Theme.textActive; opacity: 0.75
                font.family: Theme.fontFamily; font.pixelSize: Math.round(15 * root.k); font.letterSpacing: 2
            }
        }
    }

    // ---- "stacked" ----
    Row {
        id: stackFace
        objectName: "clockStackedFace"
        visible: root.stacked
        spacing: 20
        Item {
            id: stackDigits
            width: Math.max(stackH.implicitWidth, stackM.implicitWidth)
            height: stackH.implicitHeight + stackM.implicitHeight - 40
            Roll {
                id: stackH
                objectName: "clockStackedHours"
                anchors.horizontalCenter: parent.horizontalCenter
                text: root.hours.length < 2 ? "0" + root.hours : root.hours
                color: Theme.accent
                font.family: Theme.fontFamily; font.pixelSize: 110; font.weight: Font.Black
                font.letterSpacing: -4
            }
            Roll {
                id: stackM
                objectName: "clockStackedMinutes"
                anchors.horizontalCenter: parent.horizontalCenter
                y: stackH.implicitHeight - 40
                text: root.minutes
                color: Theme.textActive
                font.family: Theme.fontFamily; font.pixelSize: 110; font.weight: Font.Black
                font.letterSpacing: -4
            }
            // a thin hand through both, pointing where the minute hand would
            Item {
                objectName: "clockStackedHand"
                anchors.centerIn: parent
                width: 4; height: parent.height * 0.92
                rotation: root.now.getMinutes() * 6 + root.now.getSeconds() * 0.1
                Behavior on rotation { enabled: !Theme.reduceMotion; RotationAnimation { direction: RotationAnimation.Clockwise; duration: 260; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveSpringFast } }
                Rectangle { width: 3; radius: 1.5; height: parent.height / 2; x: 0.5; color: Theme.accentText; opacity: 0.9 }
                Rectangle { width: 9; height: 9; radius: 4.5; anchors.centerIn: parent; color: Theme.accentText }
            }
        }
        Column {
            anchors.verticalCenter: stackDigits.verticalCenter
            spacing: 2
            Eyebrow { text: Qt.formatDateTime(root.now, "ddd") }
            Text {
                text: Qt.formatDateTime(root.now, "d")
                color: Theme.textActive
                font.family: Theme.fontFamily; font.pixelSize: 34; font.weight: Font.Bold
            }
            Text {
                text: Qt.formatDateTime(root.now, "MMM")
                color: Theme.text
                font.family: Theme.fontFamily; font.pixelSize: 14; font.letterSpacing: 1
            }
            Text {
                visible: root.seconds
                text: Qt.formatDateTime(root.now, "ss")
                color: Theme.accentText
                font.family: Theme.fontMono; font.pixelSize: 14
            }
        }
    }

    // ---- "blocks": tty-clock's 3x5 digits ----
    readonly property var glyphs: ({
        "0": "111101101101111", "1": "001001001001001", "2": "111001111100111", "3": "111001111001111",
        "4": "101101111001001", "5": "111100111001111", "6": "111100111101111", "7": "111001001001001",
        "8": "111101111101111", "9": "111101111001111", " ": "000000000000000"
    })
    readonly property int cell: Math.round(17 * root.k)
    component BlockGlyph: Grid {
        id: g
        property string ch: "0"
        readonly property bool colon: g.ch === ":"
        columns: g.colon ? 1 : 3
        rows: 5
        Repeater {
            model: g.colon ? 5 : 15
            delegate: Rectangle {
                required property int index
                width: root.cell * (g.colon ? 1 : 1.3); height: root.cell
                readonly property bool lit: g.colon ? (index === 1 || index === 3) : root.glyphs[g.ch].charAt(index) === "1"
                color: Theme.accent
                opacity: lit ? 1 : 0
                Behavior on opacity { NumberAnimation { duration: Theme.durationFast; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveStandard } }
            }
        }
    }
    Column {
        id: blockFace
        objectName: "clockBlockFace"
        visible: root.blocks && !root.analog
        spacing: 12
        Row {
            spacing: root.cell
            Repeater {
                model: ((root.hours.length < 2 ? " " + root.hours : root.hours) + ":" + root.minutes
                        + (root.seconds ? ":" + Qt.formatDateTime(root.now, "ss") : "")).split("")
                delegate: BlockGlyph { required property string modelData; ch: modelData }
            }
        }
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: Qt.formatDateTime(root.now, "ddd MMM d") + (root.h24 ? "" : "  " + root.meridiem)
            color: Theme.textActive; opacity: 0.8
            font.family: Theme.fontMono; font.pixelSize: 13; font.letterSpacing: 1
        }
    }

    // ---- "analog" ----
    Column {
        id: analogFace
        objectName: "clockAnalogFace"
        visible: root.analog
        spacing: Math.round(10 * root.k)
        readonly property real size: Math.round(190 * root.k)
        width: size
        Item {
            id: dial
            width: analogFace.size; height: width
            Rectangle {
                anchors.fill: parent
                radius: width / 2
                color: Qt.rgba(Theme.panel.r, Theme.panel.g, Theme.panel.b, 0.55)
                border.width: 1
                border.color: Theme.mix(Theme.borderIdle, Theme.accent, 0.3)
            }
            // theme.json "clock_face": "numerals" (default) sets 12, 3, 6 and
            // 9 large in place of the quarter ticks; "ticks" keeps all twelve
            // as marks
            readonly property bool numerals: Theme.data.clock_face !== "ticks"
            Repeater {
                model: dial.numerals ? [12, 3, 6, 9] : []
                delegate: Text {
                    required property int modelData
                    required property int index
                    objectName: "clockNumeral:" + modelData
                    readonly property real a: index * Math.PI / 2
                    readonly property real r: dial.width * 0.34
                    x: dial.width / 2 + r * Math.sin(a) - width / 2
                    y: dial.width / 2 - r * Math.cos(a) - height / 2
                    text: modelData
                    color: Theme.textActive; opacity: 0.85
                    font.family: Theme.fontFamily; font.pixelSize: Math.round(dial.width * 0.17); font.weight: Font.DemiBold
                }
            }
            Repeater {      // twelve ticks, the quarters longer (or numerals)
                model: 12
                delegate: Item {
                    required property int index
                    anchors.fill: parent
                    rotation: index * 30
                    visible: !(dial.numerals && index % 3 === 0)
                    Rectangle {
                        readonly property bool quarter: index % 3 === 0
                        width: quarter ? 3 : 2
                        height: quarter ? dial.width * 0.09 : dial.width * 0.05
                        radius: width / 2
                        x: (dial.width - width) / 2
                        y: dial.width * 0.05
                        color: quarter ? Theme.textActive : Theme.text
                        opacity: quarter ? 0.9 : 0.5
                    }
                }
            }
            component Hand: Item {
                id: hand
                property real angle: 0
                property real length: 0.3
                property real thickness: 4
                property color tint: Theme.textActive
                anchors.fill: parent
                rotation: hand.angle
                Behavior on rotation { enabled: !Theme.reduceMotion; RotationAnimation { direction: RotationAnimation.Clockwise; duration: 260; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveSpringFast } }
                Rectangle {
                    width: hand.thickness
                    height: dial.width * hand.length
                    radius: width / 2
                    x: (dial.width - width) / 2
                    y: dial.width / 2 - height + width / 2
                    color: hand.tint
                    antialiasing: true
                }
            }
            Hand {
                objectName: "clockHourHand"
                angle: (root.now.getHours() % 12) * 30 + root.now.getMinutes() * 0.5
                length: 0.28; thickness: Math.max(4, dial.width * 0.03)
            }
            Hand {
                objectName: "clockMinuteHand"
                angle: root.now.getMinutes() * 6 + root.now.getSeconds() * 0.1
                length: 0.4; thickness: Math.max(3, dial.width * 0.02)
            }
            Hand {
                objectName: "clockSecondHand"
                visible: root.seconds
                angle: root.now.getSeconds() * 6
                length: 0.44; thickness: 2; tint: Theme.accent
            }
            Rectangle {
                width: Math.max(8, dial.width * 0.05); height: width; radius: width / 2
                anchors.centerIn: parent
                color: Theme.accent
            }
        }
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: Qt.formatDateTime(root.now, "dddd d MMMM")
            color: Theme.textActive; opacity: 0.85
            font.family: Theme.fontFamily; font.pixelSize: Math.round(14 * root.k); font.letterSpacing: 1
        }
    }
}
