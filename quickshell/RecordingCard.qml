import QtQuick

// What hangs from the bar's capture indicator while a screen recording runs
// (TopBar's recording branch): a red mark, the time, the sound it takes, and
// Stop. Pause and a mid-recording mic toggle are not offered: wf-recorder
// can do neither, and a button that did nothing would be a lie.
Item {
    id: root
    objectName: "recordingCard"
    readonly property real contentHeight: 52
    implicitWidth: row.implicitWidth + Theme.padLg * 2

    Row {
        id: row
        anchors.centerIn: parent
        spacing: Theme.padMd
        Rectangle {
            id: dot
            anchors.verticalCenter: parent.verticalCenter
            width: 10; height: 10; radius: 5
            color: "#e5534b"
            SequentialAnimation on opacity {
                running: CaptureService.recording && !Theme.reduceMotion
                loops: Animation.Infinite
                NumberAnimation { to: 0.35; duration: 700; easing.type: Easing.InOutSine }
                NumberAnimation { to: 1; duration: 700; easing.type: Easing.InOutSine }
            }
        }
        Column {
            anchors.verticalCenter: parent.verticalCenter
            spacing: 0
            Text {
                objectName: "recordingTime"
                text: CaptureService.clock(CaptureService.elapsed)
                color: Theme.textActive
                font.family: Theme.fontMono; font.pixelSize: Theme.fontSizeNormal; font.weight: Font.DemiBold
                font.features: { "tnum": 1 }
            }
            Text {
                objectName: "recordingSound"
                text: CaptureService.recordingAudio === "desktop" ? "with desktop sound"
                    : (CaptureService.recordingAudio === "mic" ? "with microphone" : "no sound")
                color: Theme.text; opacity: Theme.opacityMuted
                font.family: Theme.fontFamily; font.pixelSize: 10
            }
        }
        CompactChip {
            objectName: "recordingStop"
            anchors.verticalCenter: parent.verticalCenter
            text: "Stop"
            onClicked: CaptureService.stop()
        }
    }
}
