import QtQuick

// The calendar's BODY -- deliberately not the whole panel.
//
// The clock itself is the calendar's header now (see ShellIsland.qml): it
// stays visible, unchanged, at the top of the surface for the entire time
// the panel is open, rather than fading out for a "September 2026" title
// that has no visual relationship to what was just clicked. This file lays
// out only the part that reveals below that persistent clock -- month
// navigation and the day grid -- in the space the island leaves for it.
Item {
    id: root
    // See the identical comment in QuickSettings.qml/TaskbarManager.qml: a
    // Loader with an explicit width/height does not resize its loaded item
    // to match on its own.
    anchors.fill: parent
    signal closeRequested()

    // The island reads this (see TopBar.qml) to size the space it leaves
    // below the persistent clock header -- this is body-only, not the whole
    // panel's height, since the clock above it is accounted for separately.
    readonly property real contentHeight: body.implicitHeight + Theme.padLg

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

    Column {
        id: body
        x: Theme.padLg
        y: Theme.padSm
        width: parent.width - Theme.padLg * 2
        spacing: Theme.padSm

        // Slim month nav -- a secondary, smaller line under the persistent
        // clock, not a second competing title. The prev/next controls sit in
        // a single quiet pill (ShellSurface.cardRadius, Theme.layer1) rather
        // than as two bare icon buttons floating on the panel background --
        // the same nav-as-integrated-surface language as Quick Settings'
        // tab strip, even though a calendar has no tabs to switch between.
        Item {
            width: parent.width
            height: ShellSurface.navHeight

            Text {
                text: root.monthNames[root.viewDate.getMonth()] + " " + root.viewDate.getFullYear()
                color: Theme.textActive
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSizeNormal
                font.weight: Font.DemiBold
                anchors.left: parent.left
                anchors.verticalCenter: parent.verticalCenter
            }
            Rectangle {
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                width: navRow.implicitWidth + Theme.padXs * 2
                height: parent.height
                radius: ShellSurface.cardRadius
                color: Theme.layer1
                Row {
                    id: navRow
                    anchors.centerIn: parent
                    spacing: Theme.padXs
                    IconButton { glyph: "‹"; size: 24; onClicked: root.prevMonth() }
                    IconButton { glyph: "›"; size: 24; onClicked: root.nextMonth() }
                }
            }
        }

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
                        height: 30
                        readonly property bool isToday: modelData !== null && root.isSameDay(modelData, root.today)

                        Rectangle {
                            anchors.centerIn: parent
                            width: 26
                            height: 26
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

        Item { width: 1; height: Theme.padSm }
    }
}
