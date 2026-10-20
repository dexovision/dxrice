import QtQuick
import QtQuick.Effects
import Quickshell
import Quickshell.Wayland

// The frame every desktop widget (clock, music, system) shares: its own
// window on the Bottom layer (above the wallpaper, under every window), a
// glass card in the corner theme.json says, and the same motion.
//
//   name           "clock", "music", ... -- theme.json "widget_<name>" turns
//                  it on or off, "widget_<name>_pos" picks the corner
//   defaultOn / defaultCorner   what a theme.json without those keys means
//   wanted         the widget's own reason to be shown (music: a player exists)
//   content        the card's contents, sized by contentWidth / contentHeight
//
// The window spans the monitor but takes input only over the card, so the
// desktop underneath stays clickable. It arrives by rising a little as it
// fades in, leaves the same way, and a hover warms the card's edge and
// lifts it 2 px. Reduced motion makes all of it instant.
PanelWindow {
    id: root
    property string name: ""
    property string defaultCorner: "top-left"
    property bool defaultOn: true
    property bool wanted: true
    property real contentWidth: 320
    property real contentHeight: 140
    property real pad: Theme.padLg
    property real cornerMargin: 28
    property real topClearance: 76      // the bar
    property real bottomClearance: 96   // the dock
    default property alias content: holder.data
    readonly property alias card: surface
    readonly property alias hovered: hover.hovered

    readonly property bool on: Theme.widgetOn(root.name, root.defaultOn)
    readonly property string corner: Theme.widgetCorner(root.name, root.defaultCorner)
    readonly property bool active: root.on && root.wanted
    property real shown: 0
    onActiveChanged: { arrive.stop(); arrive.to = root.active ? 1 : 0; arrive.duration = root.active ? Theme.durationDefault : Theme.durationFast; arrive.start(); }
    Component.onCompleted: if (root.active) root.shown = 1

    visible: root.shown > 0
    color: "transparent"
    exclusionMode: ExclusionMode.Ignore
    aboveWindows: false
    WlrLayershell.layer: WlrLayer.Bottom
    WlrLayershell.namespace: "dxrice-widget-" + root.name
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.None
    anchors { top: true; left: true; right: true; bottom: true }
    implicitWidth: root.screen && root.screen.width ? root.screen.width : 1920
    implicitHeight: root.screen && root.screen.height ? root.screen.height : 1080
    // input only over the card
    mask: Region { item: surface }

    NumberAnimation {
        id: arrive
        target: root; property: "shown"
        easing.type: Theme.easingType; easing.bezierCurve: Theme.curveEmphasizedDecel
    }

    Item {
        id: surface
        objectName: "widgetCard:" + root.name
        width: root.contentWidth + 2 * root.pad
        height: root.contentHeight + 2 * root.pad
        readonly property bool atTop: root.corner.indexOf("top") === 0
        readonly property bool atLeft: root.corner.endsWith("left")
        x: atLeft ? root.cornerMargin : parent.width - width - root.cornerMargin
        // rises 12 px into place on arrival (falls 12 px when leaving)
        y: (atTop ? root.topClearance : parent.height - height - root.bottomClearance)
           + (1 - root.shown) * (atTop ? -12 : 12) - (hover.hovered ? 2 : 0)
        Behavior on y { enabled: !arrive.running; NumberAnimation { duration: Theme.durationFast; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveStandard } }
        opacity: root.shown
        scale: 0.97 + 0.03 * root.shown
        transformOrigin: surface.atTop ? (surface.atLeft ? Item.TopLeft : Item.TopRight) : (surface.atLeft ? Item.BottomLeft : Item.BottomRight)

        RectangularShadow {
            anchors.fill: glass
            radius: glass.radius
            color: Theme.shadowColor
            blur: Theme.elevationBlur(2)
            spread: Theme.elevationSpread(2)
            offset.y: Theme.elevationOffsetY(2)
        }
        Rectangle {
            id: glass
            anchors.fill: parent
            anchors.margins: 0
            radius: Theme.radius
            color: Qt.rgba(Theme.panel.r, Theme.panel.g, Theme.panel.b, 0.72)
            border.width: 1
            border.color: hover.hovered ? Theme.mix(Theme.borderIdle, Theme.accent, 0.5) : Theme.borderIdle
            Behavior on border.color { ColorAnimation { duration: Theme.durationFast; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveStandard } }
        }
        HoverHandler { id: hover }
        Item {
            id: holder
            x: root.pad; y: root.pad
            width: root.contentWidth; height: root.contentHeight
        }
    }
}
