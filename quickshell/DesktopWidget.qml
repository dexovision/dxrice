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
//   worldAttached  part of the infinite desktop: it travels with the windows
//                  when you pan (Viewport). theme.json "widgets_world"
//                  (default true) is the default for every widget, and
//                  "widget_<name>_world" overrides it for one
//   interactive    false for something only to look at (the clock): it then
//                  takes no input at all and the desktop under it stays
//                  clickable; true takes input over the card only
//
// Where it sits is the desktop's layout (WidgetStack: its corner, the ones
// before it there, the visualizer's band); when that place changes -- a
// neighbour comes or goes, the visualizer's band is taken or given back, the
// screen changes size -- it slides there. The pan is not part of that slide:
// it is added on top, from Viewport, which moves it exactly as the windows
// move.
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
    property string surface: "glass"
    property bool interactive: true
    // a widget you type into (reminders) takes the keyboard when clicked,
    // never otherwise
    property bool takesKeys: false
    readonly property bool worldAttached: Theme.widgetWorld(root.name)
    // the pan: Viewport already moves it the way the windows move, so it is
    // used as it is (a second animation here would trail the windows)
    // While arranging, it is drawn at home instead (eased there and back):
    // the layout is what is being arranged, and one panned away could
    // neither be reached nor dropped where it was meant to go.
    property real panWeight: WidgetStack.arranging ? 0 : 1
    Behavior on panWeight { NumberAnimation { duration: Theme.durationDefault; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveStandard } }
    readonly property real panX: root.worldAttached ? Viewport.x * root.panWeight : 0
    readonly property real panY: root.worldAttached ? Viewport.y * root.panWeight : 0
    default property alias content: holder.data
    readonly property alias card: surface
    readonly property alias hovered: hover.hovered

    // Shader effects (soft shadows, blur, masks) need the GPU scene graph;
    // under the software renderer they would draw nothing at all, so every
    // effect in a widget is gated on this and degrades to plain drawing.
    readonly property bool effects: surface.GraphicsInfo.api !== GraphicsInfo.Software
    readonly property bool on: Theme.widgetOn(root.name, root.defaultOn)
    // (a corner it was just dropped in counts at once, before theme.json
    // has been written and read back)
    property string _cornerOverride: ""
    readonly property string corner: root._cornerOverride || Theme.widgetCorner(root.name, root.defaultCorner)
    Connections {
        target: Theme
        function onDataChanged() { if (Theme.widgetCorner(root.name, root.defaultCorner) === root._cornerOverride) root._cornerOverride = ""; }
    }

    // ---- arranging (WidgetStack.arranging): drag it to any corner ----
    // Every widget takes the pointer then, even one that is only to look
    // at. Dropped, it joins the corner nearest its centre -- in its place in
    // that corner's order -- and theme.json "widget_<name>_pos" is saved.
    readonly property bool arranging: WidgetStack.arranging && root.active
    property real dragX: 0
    property real dragY: 0
    property point _grab: Qt.point(0, 0)
    function dropAt(cx, cy) {
        const corner = (cy < root.height / 2 ? "top" : "bottom") + "-" + (cx < root.width / 2 ? "left" : "right");
        const before = surface.mapToItem(null, 0, 0);
        if (corner !== root.corner) {
            root._cornerOverride = corner;
            Theme.setKeys({ ["widget_" + root.name + "_pos"]: corner });
        }
        root.dragX = 0; root.dragY = 0;
        const after = surface.mapToItem(null, 0, 0);
        root.dragX = before.x - after.x; root.dragY = before.y - after.y;
        settle.restart();
        return corner;
    }
    ParallelAnimation {
        id: settle
        NumberAnimation { target: root; property: "dragX"; to: 0; duration: Theme.durationDefault; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveSettle }
        NumberAnimation { target: root; property: "dragY"; to: 0; duration: Theme.durationDefault; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveSettle }
    }
    readonly property bool active: root.on && root.wanted
    property real shown: 0
    // its place in the desktop's layout (WidgetStack), eased when it changes
    // -- but taken at once the first time, so it doesn't fly in from 0,0
    readonly property var place: WidgetStack.placeOf(root.name)
    property real slotX: root.place.dx
    property real slotY: root.place.dy
    property real bottomClearance: WidgetStack.bottomClearance
    property bool _placed: false
    Behavior on slotX { enabled: root._placed; NumberAnimation { duration: Theme.durationDefault; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveSettle } }
    Behavior on slotY { enabled: root._placed; NumberAnimation { duration: Theme.durationDefault; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveSettle } }
    Behavior on bottomClearance { enabled: root._placed; NumberAnimation { duration: Theme.durationDefault; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveSettle } }
    // drawn at the desktop's scale (WidgetStack.scale), from its own corner
    // theme.json "widget_<name>_size": "s", "m" (default) or "l" -- the
    // arrange mode's size buttons; the layout makes room either way
    readonly property string sizeKey: "widget_" + root.name + "_size"
    readonly property string size: ["s", "l"].indexOf(String(Theme.data[root.sizeKey])) >= 0 ? String(Theme.data[root.sizeKey]) : "m"
    readonly property real sizeFactor: root.size === "s" ? 0.85 : (root.size === "l" ? 1.2 : 1)
    readonly property real uiScale: WidgetStack.scale * root.sizeFactor
    function _report() { WidgetStack.report(root.name, root.corner, surface.width * root.uiScale, surface.height * root.uiScale, root.active); }
    onUiScaleChanged: root._report()
    onCornerChanged: root._report()
    Component.onDestruction: WidgetStack.report(root.name, root.corner, 0, 0, false)
    onActiveChanged: { arrive.stop(); arrive.to = root.active ? 1 : 0; arrive.duration = root.active ? Theme.durationDefault : Theme.durationFast; arrive.start(); root._report(); }
    onHeightChanged: if (root.height > 0) WidgetStack.screenHeight = root.height
    onWidthChanged: if (root.width > 0) WidgetStack.screenWidth = root.width
    Component.onCompleted: {
        if (root.active) root.shown = 1;
        if (root.height > 0) WidgetStack.screenHeight = root.height;
        if (root.width > 0) WidgetStack.screenWidth = root.width;
        root._report();
        Qt.callLater(() => { root._placed = true; });
    }

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
    mask: root.interactive || root.arranging ? root._cardRegion : root._noRegion
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
        x: (atLeft ? WidgetStack.sideMargin + root.slotX : parent.width - width - WidgetStack.sideMargin - root.slotX) + root.panX + root.dragX
        // rises 12 px into place on arrival (falls 12 px when leaving)
        y: (atTop ? WidgetStack.topClearance + root.slotY : parent.height - height - root.bottomClearance - root.slotY) + root.panY
           + (1 - root.shown) * (atTop ? -12 : 12) + root.dragY
        onHeightChanged: root._report()
        onWidthChanged: root._report()
        // the hover lift is drawn, not a move: `y` has to follow a pan at once
        transform: Translate {
            y: root.interactive && hover.hovered ? -2 : 0
            Behavior on y { NumberAnimation { duration: Theme.durationFast; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveStandard } }
        }
        opacity: root.shown
        scale: root.uiScale * (0.97 + 0.03 * root.shown)
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
        // arranging: an outline, and the whole card is the handle
        Rectangle {
            objectName: "widgetArrange:" + root.name
            visible: root.arranging
            anchors.fill: parent
            anchors.margins: -6
            radius: Theme.radius + 6
            color: Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, arrangeArea.pressed ? 0.18 : 0.08)
            border.width: 2
            border.color: Theme.accentText
            MouseArea {
                id: arrangeArea
                anchors.fill: parent
                cursorShape: pressed ? Qt.ClosedHandCursor : Qt.OpenHandCursor
                onPressed: (m) => { settle.stop(); const p = mapToItem(null, m.x, m.y); root._grab = Qt.point(p.x - root.dragX, p.y - root.dragY); }
                onPositionChanged: (m) => { const p = mapToItem(null, m.x, m.y); root.dragX = p.x - root._grab.x; root.dragY = p.y - root._grab.y; }
                onReleased: { const c = surface.mapToItem(null, surface.width / 2, surface.height / 2); root.dropAt(c.x, c.y); }
            }
            // its size, and hiding it (saved at once; Settings brings a
            // hidden one back)
            Row {
                anchors.top: parent.top; anchors.right: parent.right
                anchors.margins: 12
                spacing: 4
                component ArrangeChip: Rectangle {
                    id: chip
                    property string label: ""
                    property bool selected: false
                    signal clicked()
                    width: Math.max(26, chipText.implicitWidth + 14); height: 24; radius: 12
                    color: chip.selected ? Theme.accent : (chipArea.containsMouse ? Theme.layer1Hover : Theme.panel)
                    border.width: 1; border.color: Theme.borderIdle
                    Text {
                        id: chipText
                        anchors.centerIn: parent
                        text: chip.label
                        color: chip.selected ? Theme.panelTone : Theme.textActive
                        font.family: Theme.fontFamily; font.pixelSize: 11; font.weight: Font.DemiBold
                    }
                    MouseArea { id: chipArea; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: chip.clicked() }
                }
                Repeater {
                    model: ["s", "m", "l"]
                    delegate: ArrangeChip {
                        required property string modelData
                        objectName: "widgetSize:" + root.name + ":" + modelData
                        label: modelData.toUpperCase()
                        selected: root.size === modelData
                        onClicked: Theme.setKeys({ [root.sizeKey]: modelData === "m" ? null : modelData })
                    }
                }
                ArrangeChip {
                    objectName: "widgetHide:" + root.name
                    label: "Hide"
                    onClicked: Theme.setKeys({ ["widget_" + root.name]: false })
                }
            }
        }
    }
}
