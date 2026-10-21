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
    // tall enough for the pill under the bar (it sits below the bar's strip)
    implicitHeight: ShellSurface.topEdgeHeight + 56
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
                text: "Drag a widget to any corner, or size or hide it"
                color: Theme.textActive
                font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSmall
            }
            CompactChip {
                objectName: "arrangeReset"
                anchors.verticalCenter: parent.verticalCenter
                text: "Reset layout"
                // every widget back to its own corner and size (which are on
                // stays as it is)
                onClicked: {
                    const out = {};
                    for (const k in Theme.data) if (/^widget_.+_(pos|size)$/.test(k)) out[k] = null;
                    Theme.setKeys(out);
                }
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
