import QtQuick
import Quickshell
import Quickshell.Wayland

// Shown while the desktop's widgets are being arranged (WidgetStack.
// arranging): what to do, and Done. Escape is Done too. It sits just under
// the bar, above everything, and takes input only over itself.
PanelWindow {
    id: root
    objectName: "arrangeBar"
    visible: WidgetStack.arranging
    color: "transparent"
    anchors { top: true; left: true; right: true }
    implicitHeight: 64
    exclusionMode: ExclusionMode.Ignore
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.namespace: "dxrice-arrange"
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.OnDemand
    mask: Region { item: pill }

    Shortcut { sequence: "Escape"; enabled: root.visible; onActivated: WidgetStack.arranging = false }

    Rectangle {
        id: pill
        anchors.horizontalCenter: parent.horizontalCenter
        y: ShellSurface.topEdgeHeight
        width: row.implicitWidth + Theme.padLg * 2
        height: 40
        radius: 20
        color: Theme.panel
        border.width: 1; border.color: Theme.borderIdle
        Row {
            id: row
            anchors.centerIn: parent
            spacing: Theme.padMd
            Text {
                anchors.verticalCenter: parent.verticalCenter
                text: "Drag a widget to any corner"
                color: Theme.textActive
                font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSmall
            }
            CompactChip {
                objectName: "arrangeDone"
                anchors.verticalCenter: parent.verticalCenter
                text: "Done"
                onClicked: WidgetStack.arranging = false
            }
        }
    }
}
