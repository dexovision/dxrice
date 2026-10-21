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
//   surface        what it sits on, chosen per widget so they don't all look
//                  alike: "none" (bare, with a soft shadow for legibility on
//                  any wallpaper), "glass" (the shell's panel glass) or
//                  "terminal" (a dark, square-edged plate with a hairline)
//   worldAttached  theme.json "widget_<name>_world": true makes it part of the
//                  infinite desktop -- it travels with the windows when you
//                  pan (Viewport); false (default) keeps it on the screen
//   interactive    false for something only to look at (the clock): it then
//                  takes no input at all and the desktop under it stays
//                  clickable; true takes input over the card only
//
// It arrives by rising a little as it fades in and leaves the same way. An
// interactive one warms its edge and lifts 2 px under the pointer. Reduced
// motion makes all of it instant.
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
    property real bottomClearance: 28   // the screen's edge (there is no dock)
    property string surface: "glass"
    property bool interactive: true
    // a widget you type into (reminders) takes the keyboard when clicked,
    // never otherwise
    property bool takesKeys: false
    readonly property bool worldAttached: Theme.data["widget_" + root.name + "_world"] === true
    // the pan, smoothed between the daemon's ~30 updates a second
    property real panX: root.worldAttached ? Viewport.x : 0
    property real panY: root.worldAttached ? Viewport.y : 0
    Behavior on panX { NumberAnimation { duration: 45; easing.type: Easing.Linear } }
    Behavior on panY { NumberAnimation { duration: 45; easing.type: Easing.Linear } }
    default property alias content: holder.data
    readonly property alias card: surface
    readonly property alias hovered: hover.hovered

    // Shader effects (soft shadows, blur, masks) need the GPU scene graph;
    // under the software renderer they would draw nothing at all, so every
    // effect in a widget is gated on this and degrades to plain drawing.
    readonly property bool effects: surface.GraphicsInfo.api !== GraphicsInfo.Software
    readonly property bool on: Theme.widgetOn(root.name, root.defaultOn)
    readonly property string corner: Theme.widgetCorner(root.name, root.defaultCorner)
    readonly property bool active: root.on && root.wanted
    property real shown: 0
    // others in the same corner come first (WidgetStack); this one sits past them
    readonly property real stackOffset: WidgetStack.offsetOf(root.name)
    function _report() { WidgetStack.report(root.name, root.corner, surface.height, root.active); }
    onCornerChanged: root._report()
    Component.onDestruction: WidgetStack.report(root.name, root.corner, 0, false)
    onActiveChanged: { arrive.stop(); arrive.to = root.active ? 1 : 0; arrive.duration = root.active ? Theme.durationDefault : Theme.durationFast; arrive.start(); root._report(); }
    Component.onCompleted: { if (root.active) root.shown = 1; root._report(); }

    visible: root.shown > 0
    color: "transparent"
    exclusionMode: ExclusionMode.Ignore
    aboveWindows: false
    WlrLayershell.layer: WlrLayer.Bottom
    WlrLayershell.namespace: "dxrice-widget-" + root.name
    WlrLayershell.keyboardFocus: root.takesKeys ? WlrKeyboardFocus.OnDemand : WlrKeyboardFocus.None
    anchors { top: true; left: true; right: true; bottom: true }
    implicitWidth: root.screen && root.screen.width ? root.screen.width : 1920
    implicitHeight: root.screen && root.screen.height ? root.screen.height : 1080
    // input only over the card, or none at all
    mask: root.interactive ? root._cardRegion : root._noRegion
    property Region _cardRegion: Region { item: surface }
    property Region _noRegion: Region {}

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
        x: (atLeft ? root.cornerMargin : parent.width - width - root.cornerMargin) + root.panX
        // rises 12 px into place on arrival (falls 12 px when leaving)
        y: (atTop ? root.topClearance + root.stackOffset : parent.height - height - root.bottomClearance - root.stackOffset) + root.panY
           + (1 - root.shown) * (atTop ? -12 : 12)
        onHeightChanged: root._report()
        // the hover lift is drawn, not a move: `y` has to follow a pan at once
        transform: Translate {
            y: root.interactive && hover.hovered ? -2 : 0
            Behavior on y { NumberAnimation { duration: Theme.durationFast; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveStandard } }
        }
        opacity: root.shown
        scale: 0.97 + 0.03 * root.shown
        transformOrigin: surface.atTop ? (surface.atLeft ? Item.TopLeft : Item.TopRight) : (surface.atLeft ? Item.BottomLeft : Item.BottomRight)

        RectangularShadow {
            visible: root.surface === "glass"
            anchors.fill: glass
            radius: glass.radius
            color: Theme.shadowColor
            blur: Theme.elevationBlur(2)
            spread: Theme.elevationSpread(2)
            offset.y: Theme.elevationOffsetY(2)
        }
        Rectangle {
            id: glass
            visible: root.surface === "glass"
            anchors.fill: parent
            anchors.margins: 0
            radius: Theme.radius
            color: Qt.rgba(Theme.panel.r, Theme.panel.g, Theme.panel.b, 0.72)
            border.width: 1
            border.color: hover.hovered ? Theme.mix(Theme.borderIdle, Theme.accent, 0.5) : Theme.borderIdle
            Behavior on border.color { ColorAnimation { duration: Theme.durationFast; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveStandard } }
        }
        // the terminal plate: square-edged, darker, a hairline and a lit top edge
        Rectangle {
            objectName: "widgetPlate:" + root.name
            visible: root.surface === "terminal"
            anchors.fill: parent
            radius: 4
            color: Qt.rgba(Theme.panel.r * 0.6, Theme.panel.g * 0.6, Theme.panel.b * 0.6, 0.78)
            border.width: 1
            border.color: root.interactive && hover.hovered ? Theme.mix(Theme.borderIdle, Theme.accent, 0.5) : Theme.borderIdle
            Behavior on border.color { ColorAnimation { duration: Theme.durationFast; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveStandard } }
            Rectangle { x: 1; y: 1; width: parent.width - 2; height: 1; color: Theme.accent; opacity: 0.55 }
        }
        HoverHandler { id: hover; enabled: root.interactive }
        Item {
            id: holder
            x: root.pad; y: root.pad
            width: root.contentWidth; height: root.contentHeight
            // bare widgets carry their own soft shadow so they read on any wallpaper
            layer.enabled: root.surface === "none" && root.effects
            layer.effect: MultiEffect {
                shadowEnabled: true
                shadowColor: "#000000"
                shadowOpacity: 0.55
                shadowBlur: 0.6
                shadowVerticalOffset: 2
            }
        }
    }
}
