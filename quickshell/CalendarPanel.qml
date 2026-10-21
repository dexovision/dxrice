import QtQuick

// The calendar: the panel that hangs from the bar's clock. Month navigation,
// the day grid (today in the accent, a dot under a day with reminders), and
// the selected day's agenda -- the reminders you keep on this machine
// (ReminderStore, shared with the desktop reminders widget): add one with a
// kind and a line of text, remove one with its ×. Nothing is synced with an
// online calendar, and the agenda says so.
Item {
    id: root
    objectName: "calendarPanel"
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
    // the day the agenda shows: today, until another is clicked
    property var selectedDate: new Date()
    property string newKind: "reminder"
    function select(d) { root.selectedDate = d; }
    function addReminder() {
        if (ReminderStore.add(root.selectedDate, reminderInput.text, root.newKind)) reminderInput.text = "";
    }
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

    // Changing month: the label and the grid slide out the way you're going,
    // the month swaps while they're invisible, and they slide in from the
    // other side. `shift` is that one number (-1 out to the left ... 1 in from
    // the right); clicking again mid-way just moves the month it lands on.
    property real shift: 0
    readonly property alias monthGrid: grid
    property int direction: 1
    property var pendingDate: root.viewDate
    function go(delta) {
        const base = monthChange.running ? root.pendingDate : root.viewDate;
        root.pendingDate = new Date(base.getFullYear(), base.getMonth() + delta, 1);
        if (monthChange.running) return;
        root.direction = delta;
        monthChange.restart();
    }
    function prevMonth() { root.go(-1); }
    function nextMonth() { root.go(1); }
    SequentialAnimation {
        id: monthChange
        NumberAnimation { target: root; property: "shift"; to: -root.direction; duration: Math.round(Theme.durationFast * 0.6); easing.type: Easing.InQuad }
        ScriptAction { script: { root.viewDate = root.pendingDate; root.shift = root.direction; } }
        NumberAnimation { target: root; property: "shift"; to: 0; duration: Theme.durationFast; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveEmphasizedDecel }
        // a click that came in after the swap: land on it now
        ScriptAction { script: if (root.viewDate.getTime() !== root.pendingDate.getTime()) root.viewDate = root.pendingDate }
    }

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
                objectName: "calendarMonth"
                x: root.shift * 14
                opacity: 1 - Math.abs(root.shift)
                text: root.monthNames[root.viewDate.getMonth()] + " " + root.viewDate.getFullYear()
                color: Theme.textActive
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSizeNormal
                font.weight: Font.DemiBold
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

        Column {
            id: grid
            objectName: "calendarGrid"
            width: parent.width
            spacing: body.spacing
            x: root.shift * 14
            opacity: 1 - Math.abs(root.shift)
            Repeater {
                model: root.weeks
                delegate: Row {
                    width: body.width
                    Repeater {
                        model: modelData
                        delegate: Item {
                            id: day
                            width: body.width / 7
                            height: 30
                            objectName: modelData ? "calendarDay:" + modelData.getDate() : ""
                            readonly property bool isToday: modelData !== null && root.isSameDay(modelData, root.today)
                            readonly property bool isSelected: modelData !== null && root.isSameDay(modelData, root.selectedDate)
                            readonly property bool hasReminders: modelData !== null && ReminderStore.items.length >= 0 && ReminderStore.has(modelData)

                            Rectangle {
                                anchors.centerIn: parent
                                width: 26
                                height: 26
                                radius: Theme.roundingFull
                                visible: day.isToday || day.isSelected || dayArea.containsMouse
                                color: day.isToday ? Theme.accent : (day.isSelected ? Theme.mix(Theme.layer1, Theme.accent, 0.25) : Theme.layer1Hover)
                            }
                            Text {
                                anchors.centerIn: parent
                                visible: modelData !== null
                                text: modelData ? modelData.getDate() : ""
                                color: day.isToday || day.isSelected ? Theme.textActive : Theme.text
                                font.family: Theme.fontFamily
                                font.weight: day.isToday || day.isSelected ? Font.DemiBold : Font.Normal
                                font.pixelSize: Theme.fontSizeNormal
                            }
                            // a day with reminders
                            Rectangle {
                                visible: day.hasReminders
                                anchors.horizontalCenter: parent.horizontalCenter
                                anchors.bottom: parent.bottom; anchors.bottomMargin: -1
                                width: 4; height: 4; radius: 2
                                color: day.isToday ? Theme.textActive : Theme.accent
                            }
                            MouseArea {
                                id: dayArea
                                anchors.fill: parent
                                enabled: modelData !== null
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: root.select(modelData)
                            }
                        }
                    }
                }
            }

        }

        // ---- the selected day's agenda ----
        Rectangle { width: parent.width; height: 1; color: Theme.seam }
        Item {
            width: parent.width; height: 22
            Text {
                objectName: "agendaDay"
                anchors.verticalCenter: parent.verticalCenter
                text: root.isSameDay(root.selectedDate, root.today) ? "Today" : Qt.formatDate(root.selectedDate, "dddd d MMMM")
                color: Theme.textActive
                font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSmall; font.weight: Font.DemiBold
            }
            Text {
                anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
                text: "On this machine"
                color: Theme.text; opacity: Theme.opacityMuted
                font.family: Theme.fontFamily; font.pixelSize: 10
            }
        }
        Repeater {
            model: ReminderStore.on(root.selectedDate)
            delegate: Item {
                id: entry
                required property var modelData
                objectName: "agendaItem:" + modelData.id
                width: body.width; height: 28
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    text: ReminderStore.kindOf(entry.modelData.kind).glyph
                    color: Theme.accent
                    font.family: Theme.iconFamily; font.pixelSize: Theme.fontSizeSmall
                }
                Text {
                    x: 22; width: parent.width - 22 - 28
                    anchors.verticalCenter: parent.verticalCenter
                    text: entry.modelData.text
                    elide: Text.ElideRight
                    color: Theme.textActive
                    font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSmall
                }
                IconButton {
                    objectName: "agendaRemove:" + entry.modelData.id
                    anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
                    glyph: "\uf00d"; size: 24
                    onClicked: ReminderStore.remove(entry.modelData.id)
                }
            }
        }
        Text {
            visible: ReminderStore.on(root.selectedDate).length === 0
            text: "Nothing on this day yet."
            color: Theme.text; opacity: Theme.opacityMuted
            font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSmaller
        }
        // add one: its kind, and a line of text (Enter adds)
        Flow {
            width: parent.width
            spacing: Theme.padXs
            Repeater {
                model: ReminderStore.kinds
                delegate: Rectangle {
                    id: kindChip
                    required property var modelData
                    objectName: "agendaKind:" + modelData.id
                    readonly property bool current: root.newKind === modelData.id
                    width: kindRow.implicitWidth + Theme.padMd * 2; height: 24; radius: 12
                    color: kindChip.current ? Theme.mix(Theme.layer1, Theme.accent, 0.3) : (kindArea.containsMouse ? Theme.layer1Hover : Theme.layer1)
                    Row {
                        id: kindRow
                        anchors.centerIn: parent
                        spacing: 4
                        Text { text: kindChip.modelData.glyph; color: kindChip.current ? Theme.accent : Theme.text; font.family: Theme.iconFamily; font.pixelSize: 10; anchors.verticalCenter: parent.verticalCenter }
                        Text { text: kindChip.modelData.label; color: kindChip.current ? Theme.textActive : Theme.text; font.family: Theme.fontFamily; font.pixelSize: 11; anchors.verticalCenter: parent.verticalCenter }
                    }
                    MouseArea { id: kindArea; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: root.newKind = kindChip.modelData.id }
                }
            }
        }
        Row {
            width: parent.width
            spacing: Theme.padSm
            Rectangle {
                width: parent.width - addButton.width - parent.spacing
                height: 30; radius: 15
                color: Theme.layer1
                border.width: 1
                border.color: reminderInput.activeFocus ? Theme.mix(Theme.borderIdle, Theme.accent, 0.6) : Theme.borderIdle
                TextInput {
                    id: reminderInput
                    objectName: "agendaInput"
                    anchors.fill: parent
                    anchors.leftMargin: 12; anchors.rightMargin: 12
                    verticalAlignment: TextInput.AlignVCenter
                    clip: true
                    color: Theme.textActive
                    selectionColor: Theme.accent
                    font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSmall
                    onAccepted: root.addReminder()
                    Text {
                        visible: reminderInput.text.length === 0
                        anchors.verticalCenter: parent.verticalCenter
                        text: "Add a " + ReminderStore.kindOf(root.newKind).label.toLowerCase() + "\u2026"
                        color: Theme.text; opacity: Theme.opacityFaint
                        font: reminderInput.font
                    }
                }
            }
            Rectangle {
                id: addButton
                objectName: "agendaAdd"
                width: 30; height: 30; radius: 15
                color: reminderInput.text.trim().length > 0 ? Theme.accent : Theme.layer1
                Text { anchors.centerIn: parent; text: "+"; color: reminderInput.text.trim().length > 0 ? Theme.panelTone : Theme.text; font.family: Theme.fontFamily; font.pixelSize: 18; font.weight: Font.DemiBold }
                MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: root.addReminder() }
            }
        }

        Item { width: 1; height: Theme.padSm }
    }
}
