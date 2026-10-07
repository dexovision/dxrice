import QtQuick
import QtQuick.Effects
import "BranchGeometry.js" as BranchGeometry

// The Theme editor's colour picker, as a child surface of the Theme panel.
//
// It replaced a QtQuick.Dialogs ColorDialog. Under Quickshell that dialog
// has no in-scene implementation to fall back on, so it opened as its own
// top-level window -- a separate Hyprland client, placed by the compositor
// wherever it liked, visible to SUPER+G and to new-window auto-placement,
// visually unrelated to the panel that opened it.
//
// This is an Item inside the Theme editor's own PanelWindow instead (which
// already spans the whole screen; its mask limits input to the panel plus
// the click-outside region -- see ThemeEditor.qml), the same pattern as
// the Taskbar's Add Shortcut branch inside the Dock's window. Not a
// PopupWindow: without grabFocus a Quickshell popup is a tooltip-type
// surface that never gets keyboard focus (the hex field needs it), and
// with grabFocus the compositor dismisses it on ANY outside click,
// including clicks on the Theme panel itself.
//
// Owns presentation only. ThemeEditor decides when it is open, where it is
// anchored, and what happens to the result:
//   accepted(hex)  Done / Enter -- hex is "rrggbb", no leading '#'
//   dismissed()    X / Cancel
// Escape and click-outside are ThemeEditor's (one Escape Shortcut per
// window), and both just close this first.
Item {
    id: root
    objectName: "colorPopover"

    property bool open: false
    property string title: ""
    property string initialHex: "ffffff"
    // Bumped by the owner on every (re)target, so picking a second swatch
    // while open reloads the draft without a close/open cycle.
    property int session: 0
    // Where it hangs from, in this item's parent's coordinates.
    property rect parentRect: Qt.rect(0, 0, 0, 0)
    property point anchorPoint: Qt.point(0, 0)
    property real screenWidth: 1920
    property real screenHeight: 1080
    property real edgeMargin: ShellSurface.gap

    signal accepted(string hex)
    signal dismissed()

    readonly property real gap: Theme.padMd
    readonly property real pad: Theme.padLg
    readonly property real wantW: 288
    readonly property real wantH: pad * 2 + header.height + svArea.height + hueBar.height + valueRow.height
        + buttonRow.height + Theme.padMd * 4

    // Placement only while visible or animating: a closed popover never
    // recomputes anything as the panel above it animates.
    property var _lastPlacement: ({ side: "right", x: 0, y: 0, w: 288, h: 0 })
    readonly property bool _placing: root.open || root.reveal > 0
    readonly property var placement: !root._placing ? root._lastPlacement : BranchGeometry.place(
        { x: parentRect.x, y: parentRect.y, w: parentRect.width, h: parentRect.height },
        anchorPoint,
        { w: wantW, h: wantH },
        { w: screenWidth, h: screenHeight },
        { margin: edgeMargin, gap: gap, minW: 260, minH: wantH, headerH: 56, footerH: 0,
          preferSide: "right", alignToAnchor: true })
    onPlacementChanged: if (root._placing) root._lastPlacement = root.placement
    readonly property string side: placement.side
    readonly property bool horizontal: side === "right" || side === "left"

    x: placement.x
    y: placement.y
    width: placement.w
    height: placement.h
    z: 20

    readonly property real anchorLocalX: Math.max(0, Math.min(width, anchorPoint.x - x))
    readonly property real anchorLocalY: Math.max(0, Math.min(height, anchorPoint.y - y))

    // ONE animated value drives the whole open/close, so an interrupted
    // close simply reverses from wherever it is -- nothing to cancel.
    property real reveal: root.open ? 1 : 0
    Behavior on reveal {
        NumberAnimation { duration: Theme.durationDefault; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveStandard }
    }
    function sub(p, from, to) { return Math.max(0, Math.min(1, (p - from) / (to - from))); }
    readonly property real pMain: sub(reveal, 0.0, 0.6)
    readonly property real pCross: sub(reveal, 0.2, 1.0)
    visible: reveal > 0.001

    // ---- draft colour (HSV, so dragging hue never collapses saturation) ----
    property real hue: 0
    property real sat: 0
    property real val: 1
    readonly property color draft: Qt.hsva(root.hue, root.sat, root.val, 1)
    function hexOf(c) {
        const h = (v) => Math.max(0, Math.min(255, Math.round(v * 255))).toString(16).padStart(2, "0");
        return h(c.r) + h(c.g) + h(c.b);
    }
    readonly property string draftHex: hexOf(draft)
    function load(hex) {
        const c = Qt.color("#" + hex);
        // Achromatic colours report hue -1; keep the current hue then, so
        // dragging saturation up from a grey starts from a sensible place.
        if (c.hsvHue >= 0) root.hue = c.hsvHue;
        root.sat = c.hsvSaturation;
        root.val = c.hsvValue;
        hexInput.text = hex;
    }
    function setFromHexText(t) {
        const m = /^#?([0-9a-fA-F]{6})$/.exec(t.trim());
        if (!m) return false;
        root.load(m[1].toLowerCase());
        return true;
    }
    function accept() {
        if (!hexInput.activeFocus || root.setFromHexText(hexInput.text)) root.accepted(root.draftHex);
    }
    onDraftHexChanged: if (!hexInput.activeFocus) hexInput.text = root.draftHex
    onSessionChanged: root.load(root.initialHex)
    onOpenChanged: {
        if (open) {
            root.load(root.initialHex);
        } else {
            // A closed picker must not keep keyboard focus in its hidden
            // field (typing would silently edit it).
            hexInput.focus = false;
        }
    }

    // ---- the surface: grows out of the swatch that opened it ----
    readonly property real seed: 28
    readonly property rect startRect: Qt.rect(
        Math.max(0, Math.min(width - seed, anchorLocalX - seed / 2)),
        Math.max(0, Math.min(height - seed, anchorLocalY - seed / 2)), seed, seed)

    // A short bridge across the gap to the panel edge, level with the
    // swatch -- only when beside/above/below the panel, not as an inset sheet.
    Rectangle {
        id: neck
        visible: root.side !== "sheet"
        readonly property real thickness: 16
        readonly property real grow: (root.gap + 2) * root.sub(root.reveal, 0, 0.25)
        // Grows out of the PANEL's edge toward the popover on every side.
        x: root.side === "right" ? -root.gap - 1
           : (root.side === "left" ? root.width + root.gap + 1 - grow : root.anchorLocalX - thickness / 2)
        y: root.horizontal ? root.anchorLocalY - thickness / 2
           : (root.side === "above" ? root.height + root.gap + 1 - grow : -root.gap - 1)
        width: root.horizontal ? grow : thickness
        height: root.horizontal ? thickness : grow
        color: Theme.bg
        opacity: root.sub(root.reveal, 0, 0.2)
    }

    RectangularShadow {
        anchors.fill: surface
        radius: surface.radius
        color: Theme.shadowColor
        blur: Theme.elevationBlur(2)
        spread: Theme.elevationSpread(2)
        offset.y: Theme.elevationOffsetY(2)
        opacity: root.pCross
    }

    Rectangle {
        id: surface
        x: root.startRect.x * (1 - pX)
        y: root.startRect.y * (1 - pY)
        width: root.startRect.width + (root.width - root.startRect.width) * pX
        height: root.startRect.height + (root.height - root.startRect.height) * pY
        readonly property real pX: root.horizontal ? root.pMain : root.pCross
        readonly property real pY: root.horizontal ? root.pCross : root.pMain
        radius: Math.min(Theme.roundingXl, width / 2, height / 2)
        color: root.side === "sheet" ? Theme.withAlpha(Theme.mix(Theme.panelTone, Theme.layer1Tone, 0.25), 0.98) : Theme.bg
        border.width: Theme.borderWidth
        border.color: root.side === "sheet" ? Theme.border : Theme.borderIdle
        clip: true

        Item {
            id: content
            x: -surface.x
            y: -surface.y
            width: root.width
            height: root.height
            opacity: root.sub(root.reveal, 0.55, 1.0)

            // Bare areas of the picker absorb clicks: they must never fall
            // through to the Theme editor's click-outside catcher.
            MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons }

            Column {
                x: root.pad
                y: root.pad
                width: parent.width - root.pad * 2
                spacing: Theme.padMd

                Item {
                    id: header
                    width: parent.width
                    height: 28
                    Text {
                        anchors.left: parent.left
                        anchors.right: closeBtn.left
                        anchors.rightMargin: Theme.padSm
                        anchors.verticalCenter: parent.verticalCenter
                        text: root.title
                        elide: Text.ElideRight
                        color: Theme.textActive
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSizeNormal
                        font.weight: Font.DemiBold
                    }
                    CloseButton {
                        id: closeBtn
                        objectName: "colorPopoverClose"
                        anchors.right: parent.right
                        anchors.verticalCenter: parent.verticalCenter
                        onClicked: root.dismissed()
                    }
                }

                // Saturation (x) / value (y) at the current hue.
                Rectangle {
                    id: svArea
                    objectName: "colorPopoverSV"
                    width: parent.width
                    height: 150
                    radius: Theme.roundingSm
                    color: Qt.hsva(root.hue, 1, 1, 1)
                    clip: true
                    Rectangle {
                        anchors.fill: parent
                        radius: parent.radius
                        gradient: Gradient {
                            orientation: Gradient.Horizontal
                            GradientStop { position: 0; color: "#ffffffff" }
                            GradientStop { position: 1; color: "#00ffffff" }
                        }
                    }
                    Rectangle {
                        anchors.fill: parent
                        radius: parent.radius
                        gradient: Gradient {
                            GradientStop { position: 0; color: "#00000000" }
                            GradientStop { position: 1; color: "#ff000000" }
                        }
                    }
                    Rectangle {
                        width: 14; height: 14; radius: 7
                        x: root.sat * parent.width - width / 2
                        y: (1 - root.val) * parent.height - height / 2
                        color: "transparent"
                        border.width: 2
                        border.color: root.val > 0.55 && root.sat < 0.45 ? "#202020" : "#ffffff"
                    }
                    MouseArea {
                        anchors.fill: parent
                        cursorShape: Qt.CrossCursor
                        function set(mx, my) {
                            hexInput.focus = false;
                            root.sat = Math.max(0, Math.min(1, mx / width));
                            root.val = Math.max(0, Math.min(1, 1 - my / height));
                        }
                        onPressed: (m) => set(m.x, m.y)
                        onPositionChanged: (m) => { if (pressed) set(m.x, m.y); }
                    }
                }

                Rectangle {
                    id: hueBar
                    objectName: "colorPopoverHue"
                    width: parent.width
                    height: 14
                    radius: height / 2
                    gradient: Gradient {
                        orientation: Gradient.Horizontal
                        GradientStop { position: 0 / 6; color: "#ff0000" }
                        GradientStop { position: 1 / 6; color: "#ffff00" }
                        GradientStop { position: 2 / 6; color: "#00ff00" }
                        GradientStop { position: 3 / 6; color: "#00ffff" }
                        GradientStop { position: 4 / 6; color: "#0000ff" }
                        GradientStop { position: 5 / 6; color: "#ff00ff" }
                        GradientStop { position: 6 / 6; color: "#ff0000" }
                    }
                    Rectangle {
                        width: 6; height: parent.height + 6; radius: 3
                        anchors.verticalCenter: parent.verticalCenter
                        x: root.hue * parent.width - width / 2
                        color: "transparent"
                        border.width: 2
                        border.color: "#ffffff"
                    }
                    MouseArea {
                        anchors.fill: parent
                        anchors.margins: -4
                        function set(mx) {
                            hexInput.focus = false;
                            root.hue = Math.max(0, Math.min(1, (mx - 4) / hueBar.width));
                        }
                        onPressed: (m) => set(m.x)
                        onPositionChanged: (m) => { if (pressed) set(m.x); }
                    }
                }

                // Before -> after, and the exact value.
                Row {
                    id: valueRow
                    width: parent.width
                    height: ShellSurface.rowHeight
                    spacing: Theme.padSm
                    Rectangle {
                        width: 52; height: parent.height
                        radius: Theme.roundingSm
                        clip: true
                        color: "transparent"
                        border.width: Theme.borderWidth
                        border.color: Theme.borderIdle
                        Row {
                            anchors.fill: parent
                            anchors.margins: 1
                            Rectangle { width: parent.width / 2; height: parent.height; color: "#" + root.initialHex; topLeftRadius: Theme.roundingSm - 1; bottomLeftRadius: Theme.roundingSm - 1 }
                            Rectangle { width: parent.width / 2; height: parent.height; color: root.draft; topRightRadius: Theme.roundingSm - 1; bottomRightRadius: Theme.roundingSm - 1 }
                        }
                    }
                    Rectangle {
                        width: parent.width - 52 - parent.spacing
                        height: parent.height
                        radius: Theme.roundingSm
                        color: Theme.inputFill
                        border.width: Theme.borderWidth
                        border.color: hexInput.activeFocus ? Theme.withAlpha(Theme.accent, 0.6) : Theme.borderIdle
                        Behavior on border.color { ColorAnimation { duration: Theme.durationFast } }
                        Text {
                            id: hashGlyph
                            anchors.left: parent.left
                            anchors.leftMargin: Theme.padMd
                            anchors.verticalCenter: parent.verticalCenter
                            text: "#"
                            color: Theme.text
                            opacity: Theme.opacityMuted
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSizeNormal
                        }
                        TextInput {
                            id: hexInput
                            objectName: "colorPopoverHex"
                            anchors.left: hashGlyph.right
                            anchors.leftMargin: Theme.padXs
                            anchors.right: parent.right
                            anchors.rightMargin: Theme.padMd
                            anchors.verticalCenter: parent.verticalCenter
                            color: Theme.textActive
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSizeNormal
                            maximumLength: 7
                            selectByMouse: true
                            validator: RegularExpressionValidator { regularExpression: /#?[0-9a-fA-F]{0,6}/ }
                            onTextEdited: root.setFromHexText(text)
                            onAccepted: root.accept()
                        }
                    }
                }

                Row {
                    id: buttonRow
                    anchors.right: parent.right
                    spacing: Theme.padSm
                    GlassButton { objectName: "colorPopoverCancel"; text: "Cancel"; variant: "secondary"; onClicked: root.dismissed() }
                    GlassButton { objectName: "colorPopoverDone"; text: "Done"; variant: "primary"; onClicked: root.accept() }
                }
            }
        }
    }
}
