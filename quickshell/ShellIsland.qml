import QtQuick
import QtQuick.Effects

// One section of the top bar, and the panel that hangs from it.
//
// The bar is one continuous strip (TopBar.qml draws it); a section is a
// transparent region of it -- the launcher and workspaces, the clock, the
// indicators -- holding its own controls (`controlContent`). Its panel is a
// body that grows DOWN out of the bar's lower edge, under that section: the
// same colour as the bar, square where it meets it, with a concave curve
// (a fillet) on each side joining the two, so bar and panel read as one
// shape branching, not a second surface placed near the first. Where the
// body reaches the end of the bar it runs flush with it instead
// (`flushLeft`/`flushRight`, which the bar reads to square off that corner).
//
// The section itself never moves or changes size: what opened a panel stays
// exactly under the pointer that opened it, and the rest of the bar is never
// covered (an earlier design grew each pill into its panel, which ran over
// its neighbours and had to fade them out).
//
// Motion (unchanged in spirit): `morph` owns the geometry -- the body drops
// out of the bar first (height leads) and widens from the section's width a
// beat later, overshooting a little on the opening spring -- and
// `contentFade` owns the content's visibility; each direction has its own
// curve (Theme's enter/exit), and both always start from where they are, so
// reversing mid-way never jumps.
//
// While it is open, a panel that changes size (a section with more or less
// in it, the Dashboard taking over from a section) eases to the new size
// (`shownWidth`/`shownHeight`) rather than snapping; a different panel
// taking over (`panel` changing) fades the old content out first, then
// fades the new in as the body reaches its size.
Item {
    id: root

    property bool expanded: false
    signal closeRequested()

    // the section in the bar
    property real collapsedWidth: 100
    property real collapsedHeight: 32
    // the panel: expandedHeight counts the section's row too (the body is
    // expandedHeight - collapsedHeight tall), as hosts have always sized it
    property real expandedWidth: 320
    property real expandedHeight: 360

    // which edge of the body lines up with the section as it widens
    property string pinX: "center"   // "center" | "left" | "right"
    // where the bar runs, in this item's parent's coordinates: the body stays
    // inside it, and is flush with an end it reaches
    property real barLeft: -1e9
    property real barRight: 1e9

    property real maxRadius: ShellSurface.radius
    readonly property real filletRadius: 14
    readonly property alias pointerInside: hover.inside
    // the host sets these from its own MouseArea: a section that opens a
    // panel lightens under the pointer, like every button
    property bool hovered: false
    property bool pressed: false
    property int elevation: 3

    // Constructed on first expand and torn down once fully collapsed again,
    // so an unopened panel costs nothing.
    property Component panel: null
    default property alias controlContent: controlHolder.data
    readonly property alias panelItem: panelLoader.item
    readonly property real contentOpacity: panelLoader.opacity
    // for the host's input mask
    readonly property alias bodyItem: body

    function sub(p, from, to) {
        return Math.max(0, Math.min(1, (p - from) / (to - from)));
    }

    property real morph: 0
    property real contentFade: 0
    Component.onCompleted: {
        root.morph = root.expanded ? 1 : 0;
        root.contentFade = root.expanded ? 1 : 0;
    }
    NumberAnimation {
        id: morphAnim
        target: root
        property: "morph"
        easing.type: Theme.easingType
    }
    NumberAnimation {
        id: fadeAnim
        target: root
        property: "contentFade"
        easing.type: Theme.easingType
        easing.bezierCurve: Theme.curveStandard
    }
    function _animateTo(open) {
        morphAnim.stop();
        fadeAnim.stop();
        morphAnim.from = root.morph;
        morphAnim.to = open ? 1 : 0;
        morphAnim.duration = open ? Theme.durationEnter : Theme.durationExit;
        morphAnim.easing.bezierCurve = open ? Theme.curveEnter : Theme.curveExit;
        fadeAnim.from = root.contentFade;
        fadeAnim.to = open ? 1 : 0;
        fadeAnim.duration = open ? Theme.durationFadeIn : Theme.durationFadeOut;
        morphAnim.start();
        fadeAnim.start();
    }
    readonly property real pV: morph
    // past 1 while the opening spring overshoots: both axes follow it
    readonly property real pH: morph > 1 ? morph : sub(morph, 0.18, 1.0)

    // ---- the size it opens to, eased while open ----
    // (snapped while opening or closing: the morph is what moves then)
    readonly property bool _easeSize: root.expanded && !morphAnim.running && !Theme.reduceMotion
    property real shownWidth: root.expandedWidth
    property real shownHeight: root.expandedHeight
    Behavior on shownWidth { enabled: root._easeSize; NumberAnimation { duration: Theme.durationDefault; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveStandard } }
    Behavior on shownHeight { enabled: root._easeSize; NumberAnimation { duration: Theme.durationDefault; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveStandard } }

    // ---- the body's live geometry (x in this item's coordinates) ----
    readonly property real bodyWidth: Math.max(root.collapsedWidth, Math.min(root.barRight - root.barLeft,
        root.collapsedWidth + (root.shownWidth - root.collapsedWidth) * root.pH))
    readonly property real bodyHeight: Math.max(0, (root.shownHeight - root.collapsedHeight) * root.pV)
    readonly property real _pinnedX: root.pinX === "left" ? 0
        : (root.pinX === "right" ? root.collapsedWidth - root.bodyWidth : (root.collapsedWidth - root.bodyWidth) / 2)
    readonly property real bodyX: Math.max(root.barLeft - root.x, Math.min(root.barRight - root.x - root.bodyWidth, root._pinnedX))
    readonly property bool flushLeft: root.x + root.bodyX <= root.barLeft + 0.5
    readonly property bool flushRight: root.x + root.bodyX + root.bodyWidth >= root.barRight - 0.5

    width: collapsedWidth
    height: collapsedHeight

    // ---- another panel taking over while open: out, swap, in ----
    property Component _component: root.panel
    property real swapFade: 1
    property real _frozenWidth: -1      // the outgoing content keeps its layout while it fades
    onPanelChanged: {
        if (!panelLoader.item || root.contentFade < 0.01 || Theme.reduceMotion) {
            swapAnim.stop();
            root._frozenWidth = -1;
            root.swapFade = 1;
            root._component = root.panel;
            return;
        }
        if (!swapAnim.running) root._frozenWidth = panelLoader.width;
        swapAnim.restart();
    }
    SequentialAnimation {
        id: swapAnim
        NumberAnimation { target: root; property: "swapFade"; to: 0; duration: Theme.durationFadeOut; easing.type: Easing.InQuad }
        ScriptAction { script: { root._frozenWidth = -1; root._component = root.panel; } }
        NumberAnimation { target: root; property: "swapFade"; to: 1; duration: Theme.durationFadeIn; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveStandard }
    }

    property bool _keepAlive: false
    onExpandedChanged: {
        root._animateTo(expanded);
        if (expanded) {
            collapseTimer.stop();
            root._keepAlive = true;
        } else {
            collapseTimer.start();
        }
    }
    Timer {
        id: collapseTimer
        interval: Math.max(Theme.durationExit, Theme.durationFadeOut) + 40
        onTriggered: root._keepAlive = false
    }

    // the pointer is over the section or its panel (a HoverHandler only sees
    // its own item's bounds, and the body hangs outside the section's)
    QtObject {
        id: hover
        readonly property bool inside: sectionHover.hovered || bodyHover.hovered
    }
    HoverHandler { id: sectionHover }

    // the section's own state layer under the pointer
    Rectangle {
        objectName: (root.objectName || "island") + "Hover"
        anchors.fill: parent
        anchors.margins: 3
        radius: height / 2
        color: Theme.stateFill(Theme.panel, true, root.pressed)
        opacity: (root.hovered || root.pressed) && !root.expanded ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: Theme.durationFast; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveStandard } }
    }
    Item {
        id: controlHolder
        anchors.fill: parent
    }

    // ---- the panel body ----
    // its shadow falls below the bar only (through the translucent bar it
    // would show as a dark band)
    Item {
        x: body.x - 60; y: root.collapsedHeight
        width: body.width + 120; height: body.height + 80
        clip: true
        visible: body.visible
        RectangularShadow {
            x: 60; y: 0
            width: body.width; height: body.height
            radius: body.bottomLeftRadius
            color: Theme.shadowColor
            blur: Theme.elevationBlur(root.elevation)
            spread: Theme.elevationSpread(root.elevation)
            offset.y: Theme.elevationOffsetY(root.elevation)
        }
    }
    Rectangle {
        id: body
        objectName: (root.objectName || "island") + "Body"
        x: root.bodyX
        y: root.collapsedHeight
        width: root.bodyWidth
        height: root.bodyHeight
        visible: height > 0.5
        readonly property real cornerR: Math.min(root.maxRadius, height / 2, width / 2)
        topLeftRadius: 0
        topRightRadius: 0
        bottomLeftRadius: cornerR
        bottomRightRadius: cornerR
        color: Theme.panel
        clip: true
        HoverHandler { id: bodyHover }
        // eats clicks on the body's bare areas: the host's click-outside
        // catcher sits under it while a panel is open
        MouseArea {
            anchors.fill: parent
            acceptedButtons: Qt.AllButtons
        }
        // a faint line where the bar ends and the panel begins
        Rectangle {
            x: ShellSurface.pad; width: parent.width - ShellSurface.pad * 2
            height: 1
            color: Theme.seam
            opacity: Math.min(root.contentFade, root.sub(root.morph, 0.5, 0.85))
        }
        Loader {
            id: panelLoader
            objectName: (root.objectName || "island") + "Content"
            opacity: Math.min(root.contentFade, root.swapFade, root.sub(Math.min(root.pH, root.pV), 0.85, 1.0))
            enabled: root.expanded && !swapAnim.running
            active: root.expanded || root._keepAlive
            width: root._frozenWidth >= 0 ? root._frozenWidth : root.expandedWidth
            height: root.expandedHeight - root.collapsedHeight
            x: root.pinX === "left" ? 0 : (root.pinX === "right" ? body.width - width : (body.width - width) / 2)
            sourceComponent: root._component
        }
    }

    // the joints: a concave curve on each side where the body leaves the
    // bar, unless that side runs flush with the bar's end
    component Fillet: Canvas {
        id: fillet
        property bool leftSide: true
        property color fill: Theme.panel
        width: root.filletRadius
        height: Math.min(root.filletRadius, body.height)
        y: root.collapsedHeight
        visible: body.visible && height > 0.5
        // (a request made while it is hidden or not yet ready is dropped)
        onFillChanged: requestPaint()
        onHeightChanged: requestPaint()
        onVisibleChanged: if (visible) requestPaint()
        onAvailableChanged: if (available) requestPaint()
        onPaint: {
            const ctx = getContext("2d");
            const r = root.filletRadius;
            ctx.reset();
            // spelled out: a translucent colour handed over as-is becomes
            // Qt's "#aarrggbb", which the canvas reads as something else
            const c = fillet.fill;
            ctx.fillStyle = "rgba(" + Math.round(c.r * 255) + "," + Math.round(c.g * 255) + "," + Math.round(c.b * 255) + "," + c.a + ")";
            ctx.beginPath();
            // the square outside the body's corner, minus a quarter circle
            // centred away from the body
            if (fillet.leftSide) {
                ctx.moveTo(r, 0);
                ctx.lineTo(r, r);
                ctx.arc(0, r, r, 0, -Math.PI / 2, true);
            } else {
                ctx.moveTo(0, 0);
                ctx.lineTo(0, r);
                ctx.arc(r, r, r, Math.PI, Math.PI * 1.5, false);
            }
            ctx.closePath();
            ctx.fill();
        }
    }
    Fillet {
        objectName: (root.objectName || "island") + "FilletLeft"
        leftSide: true
        x: body.x - width
        visible: body.visible && height > 0.5 && !root.flushLeft
    }
    Fillet {
        objectName: (root.objectName || "island") + "FilletRight"
        leftSide: false
        x: body.x + body.width
        visible: body.visible && height > 0.5 && !root.flushRight
    }
}
