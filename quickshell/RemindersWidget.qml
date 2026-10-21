import QtQuick

// Today's date over what is coming up -- the reminders kept on this
// machine (ReminderStore, the same list as the calendar's agenda) -- with a
// line to add one for today. A card of its own shape: a date block on the
// left, the list beside it. Click the line to type; Enter adds.
DesktopWidget {
    id: root
    name: "reminders"
    defaultCorner: "top-left"
    defaultOn: false
    surface: "glass"
    takesKeys: true
    contentWidth: 330
    contentHeight: Math.max(dateBlock.height, list.implicitHeight)

    property date now: new Date()
    Timer {
        // the date turns over at midnight
        running: root.active
        interval: 60000; repeat: true
        onTriggered: root.now = new Date()
    }
    readonly property var coming: ReminderStore.items.length >= 0 ? ReminderStore.upcoming(root.now, 4) : []
    function when(d) {
        const today = ReminderStore.key(root.now);
        if (d === today) return "Today";
        const t = new Date(root.now.getFullYear(), root.now.getMonth(), root.now.getDate() + 1);
        if (d === ReminderStore.key(t)) return "Tomorrow";
        const p = d.split("-");
        return Qt.formatDate(new Date(Number(p[0]), Number(p[1]) - 1, Number(p[2])), "ddd d MMM");
    }

    // the date block
    Rectangle {
        id: dateBlock
        width: 88; height: 108
        radius: 18
        color: Theme.mix(Theme.layer1, Theme.accent, 0.22)
        Column {
            anchors.centerIn: parent
            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                text: Qt.formatDate(root.now, "MMM").toUpperCase()
                color: Theme.accent
                font.family: Theme.fontFamily; font.pixelSize: 12; font.weight: Font.Bold; font.letterSpacing: 2
            }
            Text {
                objectName: "remindersDay"
                anchors.horizontalCenter: parent.horizontalCenter
                text: root.now.getDate()
                color: Theme.textActive
                font.family: Theme.fontFamily; font.pixelSize: 40; font.weight: Font.Bold
            }
            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                text: Qt.formatDate(root.now, "dddd")
                color: Theme.text
                font.family: Theme.fontFamily; font.pixelSize: 11
            }
        }
    }
    Column {
        id: list
        x: dateBlock.width + Theme.padLg
        width: root.contentWidth - x
        spacing: 4
        Repeater {
            model: root.coming
            delegate: Row {
                id: line
                required property var modelData
                objectName: "reminderLine:" + modelData.id
                width: list.width
                spacing: Theme.padSm
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    text: ReminderStore.kindOf(line.modelData.kind).glyph
                    color: Theme.accent
                    font.family: Theme.iconFamily; font.pixelSize: 11
                }
                Column {
                    width: parent.width - 20
                    Text { width: parent.width; text: line.modelData.text; elide: Text.ElideRight; color: Theme.textActive; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSmall }
                    Text { text: root.when(line.modelData.date); color: Theme.text; opacity: Theme.opacityMuted; font.family: Theme.fontFamily; font.pixelSize: 10 }
                }
            }
        }
        Text {
            visible: root.coming.length === 0
            width: parent.width
            text: "Nothing coming up."
            color: Theme.text; opacity: Theme.opacityMuted
            font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSmall
        }
        Item { width: 1; height: 2 }
        Rectangle {
            width: parent.width; height: 28; radius: 14
            color: Theme.layer1
            border.width: 1
            border.color: addInput.activeFocus ? Theme.mix(Theme.borderIdle, Theme.accent, 0.6) : Theme.borderIdle
            TextInput {
                id: addInput
                objectName: "remindersInput"
                anchors.fill: parent; anchors.leftMargin: 12; anchors.rightMargin: 12
                verticalAlignment: TextInput.AlignVCenter
                clip: true
                color: Theme.textActive
                selectionColor: Theme.accent
                font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSmaller
                onAccepted: if (ReminderStore.add(root.now, text, "reminder")) text = ""
                Text {
                    visible: addInput.text.length === 0
                    anchors.verticalCenter: parent.verticalCenter
                    text: "Add a reminder for today…"
                    color: Theme.text; opacity: Theme.opacityFaint
                    font: addInput.font
                }
            }
        }
    }
}
