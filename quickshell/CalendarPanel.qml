import QtQuick
import QtQuick.Effects
import Quickshell
import Quickshell.Wayland

// A real calendar, not just a bigger clock -- opened from the bar's clock
// module (waybar/config's on-click), same bar-attached drawer pattern as
// every other panel (WavyTopRect seam, bottom-only rounding, aboveWindows).
PanelWindow {
    id: root
    // See QuickSettings.qml's identical comment: shell.qml destroys this
    // panel the instant closeRequested() fires, so requestClose() plays
    // the reveal in reverse first and only then emits the real signal.
    signal closeRequested()
    property bool closing: false
    function requestClose() {
        if (root.closing) return;
        root.closing = true;
        closeTimer.start();
    }
    Timer { id: closeTimer; interval: Theme.durationEnter + 20; onTriggered: root.closeRequested() }

    implicitWidth: 320
    color: "transparent"
    anchors { top: true }
    margins {
        top: 52
        left: Math.round(((root.screen ? root.screen.width : 1920) - root.implicitWidth) / 2)
    }
    exclusionMode: ExclusionMode.Ignore
    aboveWindows: true
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.namespace: "dxrice-calendar"
    focusable: true

    implicitHeight: Math.min(500, drawer.contentImplicitHeight + 8)

    property var viewDate: new Date()
    readonly property var today: new Date()
    readonly property var dayNames: ["Su", "Mo", "Tu", "We", "Th", "Fr", "Sa"]
    readonly property var monthNames: ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]

    function isSameDay(a, b) {
        return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
    }

    readonly property var weeks: {
        const y = viewDate.getFullYear();
        const m = viewDate.getMonth();
        const firstOfMonth = new Date(y, m, 1);
        const startOffset = firstOfMonth.getDay();
        const daysInMonth = new Date(y, m + 1, 0).getDate();
        const cells = [];
        for (let i = 0; i < startOffset; i++) cells.push(null);
        for (let d = 1; d <= daysInMonth; d++) cells.push(new Date(y, m, d));
        while (cells.length % 7 !== 0) cells.push(null);
        const rows = [];
        for (let i = 0; i < cells.length; i += 7) rows.push(cells.slice(i, i + 7));
        return rows;
    }

    function prevMonth() { root.viewDate = new Date(viewDate.getFullYear(), viewDate.getMonth() - 1, 1); }
    function nextMonth() { root.viewDate = new Date(viewDate.getFullYear(), viewDate.getMonth() + 1, 1); }

    Item {
        id: drawer
        anchors.fill: parent
        clip: true

        readonly property real contentImplicitHeight: header.implicitHeight + body.implicitHeight + Theme.padLg * 2

        property real revealHeight: 0
        readonly property real revealProgress: root.implicitHeight > 0 ? Math.min(1, drawer.revealHeight / root.implicitHeight) : 0
        Behavior on revealHeight { NumberAnimation { duration: Theme.durationEnter; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveEmphasizedDecel } }
        Component.onCompleted: revealHeight = root.implicitHeight
        Connections {
            target: root
            function onImplicitHeightChanged() { if (!root.closing) drawer.revealHeight = root.implicitHeight; }
            function onClosingChanged() { drawer.revealHeight = root.closing ? 0 : root.implicitHeight; }
        }

        RectangularShadow {
            anchors.fill: panelSurface
            radius: 0
            bottomLeftRadius: Theme.roundingXl
            bottomRightRadius: Theme.roundingXl
            color: Theme.shadowColor
            blur: Theme.elevationBlur(3)
            spread: Theme.elevationSpread(3)
            offset.y: Theme.elevationOffsetY(3)
            opacity: drawer.revealProgress
        }

        Rectangle {
            id: panelSurface
            anchors.top: parent.top
            anchors.topMargin: (1 - drawer.revealProgress) * -10
            anchors.left: parent.left
            anchors.right: parent.right
            height: Math.max(0, drawer.revealHeight)
            opacity: drawer.revealProgress
            radius: 0
            bottomLeftRadius: Theme.roundingXl
            bottomRightRadius: Theme.roundingXl
            color: Theme.bg
            clip: true

            Column {
                anchors.fill: parent
                spacing: 0

                Item {
                    id: header
                    width: parent.width
                    implicitHeight: 52
                    height: implicitHeight

                    Text {
                        text: root.monthNames[root.viewDate.getMonth()] + " " + root.viewDate.getFullYear()
                        color: Theme.textActive
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSizeLarge
                        font.weight: Font.DemiBold
                        anchors.left: parent.left
                        anchors.leftMargin: Theme.padLg
                        anchors.verticalCenter: parent.verticalCenter
                    }
                    Row {
                        anchors.right: parent.right
                        anchors.rightMargin: Theme.padLg
                        anchors.verticalCenter: parent.verticalCenter
                        spacing: Theme.padSm
                        IconButton { glyph: ""; size: 28; onClicked: root.prevMonth() }
                        IconButton { glyph: ""; size: 28; onClicked: root.nextMonth() }
                        IconButton { glyph: "✕"; size: 28; onClicked: root.requestClose() }
                    }
                }

                Column {
                    id: body
                    x: Theme.padLg
                    width: parent.width - Theme.padLg * 2
                    spacing: Theme.padSm

                    Row {
                        width: parent.width
                        Repeater {
                            model: root.dayNames
                            delegate: Text {
                                width: parent.width / 7
                                horizontalAlignment: Text.AlignHCenter
                                text: modelData
                                color: Theme.text
                                opacity: 0.55
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSizeSmall
                                font.weight: Font.Medium
                            }
                        }
                    }

                    Repeater {
                        model: root.weeks
                        delegate: Row {
                            width: body.width
                            Repeater {
                                model: modelData
                                delegate: Item {
                                    width: body.width / 7
                                    height: 36
                                    readonly property bool isToday: modelData !== null && root.isSameDay(modelData, root.today)

                                    Rectangle {
                                        anchors.centerIn: parent
                                        width: 30
                                        height: 30
                                        radius: Theme.roundingFull
                                        visible: parent.isToday
                                        color: Theme.accent
                                    }
                                    Text {
                                        anchors.centerIn: parent
                                        visible: modelData !== null
                                        text: modelData ? modelData.getDate() : ""
                                        color: parent.isToday ? Theme.textActive : Theme.text
                                        font.family: Theme.fontFamily
                                        font.weight: parent.isToday ? Font.DemiBold : Font.Normal
                                        font.pixelSize: Theme.fontSizeNormal
                                    }
                                }
                            }
                        }
                    }

                    Item { width: 1; height: Theme.padLg }
                }
            }
        }
    }
}
