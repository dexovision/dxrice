import QtQuick

// A tap-to-expand section: a header row (title + optional trailing text)
// with a chevron that rotates and a body that grows/shrinks with a real
// animated height instead of snapping open -- this is what turns a plain
// "list that appears when a toggle is on" into an actual expanding panel.
// Content goes in `contentItem`'s default children; this measures them
// once via a hidden sizer so the open/close animation has a real target
// height to animate toward instead of guessing.
Column {
    id: root
    default property alias data: body.data
    property string title: ""
    property string trailingText: ""
    property bool expanded: false

    width: parent ? parent.width : implicitWidth
    spacing: 0

    Rectangle {
        width: parent.width
        height: 34
        radius: Theme.roundingSm
        color: headerArea.containsMouse ? Theme.layer2Hover : "transparent"

        Behavior on color {
            ColorAnimation { duration: Theme.durationFast; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveStandard }
        }

        Text {
            id: titleText
            anchors.verticalCenter: parent.verticalCenter
            anchors.left: parent.left
            anchors.leftMargin: Theme.padSm
            text: root.title
            color: Theme.textActive
            font.family: Theme.fontFamily
            font.pixelSize: 13
            font.weight: Font.Medium
        }
        Text {
            anchors.verticalCenter: parent.verticalCenter
            anchors.left: titleText.right
            anchors.leftMargin: Theme.padSm
            anchors.right: chevron.left
            anchors.rightMargin: Theme.padSm
            horizontalAlignment: Text.AlignRight
            elide: Text.ElideRight
            text: root.trailingText
            color: Theme.text
            opacity: 0.65
            font.family: Theme.fontFamily
            font.pixelSize: 12
        }
        Text {
            id: chevron
            anchors.verticalCenter: parent.verticalCenter
            anchors.right: parent.right
            anchors.rightMargin: Theme.padSm
            text: ""
            font.family: Theme.fontFamily
            font.pixelSize: 11
            color: Theme.text
            rotation: root.expanded ? 180 : 0
            Behavior on rotation {
                NumberAnimation { duration: Theme.durationDefault; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveExpressiveDefault }
            }
        }

        MouseArea {
            id: headerArea
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: root.expanded = !root.expanded
        }
    }

    Item {
        id: clip
        width: parent.width
        clip: true
        height: root.expanded ? body.implicitHeight : 0
        Behavior on height {
            NumberAnimation { duration: Theme.durationDefault; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveEmphasizedDecel }
        }

        Column {
            id: body
            y: Theme.padXs
            width: parent.width
            spacing: Theme.padXs
        }
    }
}
