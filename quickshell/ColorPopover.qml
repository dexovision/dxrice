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
// It is the Theme editor's counterpart of the Taskbar's Add Shortcut branch
// (AddShortcutBranch.qml) -- same material, same one-value reveal, same
// connector -- but it branches off ONE CONTROL, the swatch that opened it,
// rather than off the whole panel: BranchGeometry.attach() puts it `gap`
// from the swatch's own edge, centred on it (right of it, else left, below,
// above; squeezed onto the roomiest side, never over the swatch, if nothing
// fits), and the surface starts as the swatch's own footprint on that edge.
//
// Owns presentation only. ThemeEditor decides when it is open, which swatch
// it hangs off, and what happens to the result:
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
    // The swatch it grows out of, and where it may go -- both in this
    // item's parent's coordinates. targetRect is LIVE (the owner keeps it
    // on the swatch as the pane scrolls and the panel settles), so the
    // picker follows the control rather than a screen point.
    property rect targetRect: Qt.rect(0, 0, 0, 0)
    property rect bounds: Qt.rect(0, 0, 1920, 1080)
    // The panel it hangs from. Where the picker mostly sits ON it (a
    // narrow screen, where it branches left of the swatch over the
    // panel's own content), the panel's translucent material would let
    // that content show through -- blur only ever sees what is behind the
    // whole shell surface, not the panel drawn in it -- so it switches to
    // the same near-opaque fill the Add Shortcut branch uses for its own
    // inside-the-panel sheet.
    property rect occluder: Qt.rect(0, 0, 0, 0)
    readonly property bool overPanel: {
        const ox = Math.min(x + width, occluder.x + occluder.width) - Math.max(x, occluder.x);
        const oy = Math.min(y + height, occluder.y + occluder.height) - Math.max(y, occluder.y);
        return ox > 0 && oy > 0 && ox * oy > 0.25 * width * height;
    }

    signal accepted(string hex)
    signal dismissed()

    readonly property real gap: Theme.padMd
    readonly property real pad: Theme.padLg
    readonly property real wantW: 288
    readonly property real wantH: pad * 2 + header.height + svArea.height + hueBar.height + valueRow.height
        + buttonRow.height + Theme.padMd * 4

    // Placement only while visible or animating: a closed picker never
    // recomputes anything as the panel under it scrolls or animates.
    property var _lastPlacement: ({ side: "right", x: 0, y: 0, w: 288, h: 0, fallback: false })
    readonly property bool _placing: root.open || root.reveal > 0
    readonly property var placement: !root._placing ? root._lastPlacement : BranchGeometry.attach(
        { x: targetRect.x, y: targetRect.y, w: targetRect.width, h: targetRect.height },
        { w: wantW, h: wantH },
        { x: bounds.x, y: bounds.y, w: bounds.width, h: bounds.height },
        { gap: gap, minW: 260, minH: wantH })
    onPlacementChanged: if (root._placing) root._lastPlacement = root.placement
    readonly property string side: placement.side
    readonly property bool horizontal: side === "right" || side === "left"

    x: placement.x
    y: placement.y
    width: placement.w
    height: placement.h
    z: 20

    // The swatch's centre in this item's own coordinates (it sits just
    // outside it, `gap` away). Clamped into this item's span where the stem
    // and neck use it (_span), so they always meet the surface even when
    // the picker itself is clamped.
    readonly property real targetCX: targetRect.x + targetRect.width / 2 - x
    readonly property real targetCY: targetRect.y + targetRect.height / 2 - y

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
    // It starts as exactly the swatch's own footprint on the edge facing it
    // (the swatch's height for a side branch, its width for a stacked one),
    // so frame one reads as the swatch extending; then it stretches away
    // from the swatch along the branching axis and unfolds on the other --
    // the Add Shortcut branch's motion, from a control instead of a panel.
    readonly property real stemMain: Math.min(targetRect.width, targetRect.height)
    readonly property real stemCross: horizontal ? targetRect.height : targetRect.width
    function _span(c, size, extent) { return Math.max(0, Math.min(extent - size, c - size / 2)); }
    readonly property rect startRect: {
        switch (root.side) {
        case "right": return Qt.rect(0, _span(targetCY, stemCross, height), stemMain, stemCross);
        case "left": return Qt.rect(width - stemMain, _span(targetCY, stemCross, height), stemMain, stemCross);
        case "below": return Qt.rect(_span(targetCX, stemCross, width), 0, stemCross, stemMain);
        default: return Qt.rect(_span(targetCX, stemCross, width), height - stemMain, stemCross, stemMain);
        }
    }
    readonly property real pX: horizontal ? pMain : pCross
    readonly property real pY: horizontal ? pCross : pMain

    // The connector: grows out of the SWATCH's own edge across the gap
    // first, level with the swatch's centre, then the surface follows it.
    Rectangle {
        id: neck
        objectName: "colorPopoverNeck"
        readonly property real thickness: Math.max(8, Math.round(root.stemCross / 2))
        readonly property real grow: (root.gap + 2) * root.sub(root.reveal, 0, 0.2)
        x: root.side === "right" ? -root.gap - 1
           : (root.side === "left" ? root.width + root.gap + 1 - grow
              : root._span(root.targetCX, thickness, root.width))
        y: root.horizontal ? root._span(root.targetCY, thickness, root.height)
           : (root.side === "above" ? root.height + root.gap + 1 - grow : -root.gap - 1)
        width: root.horizontal ? grow : thickness
        height: root.horizontal ? thickness : grow
        radius: Math.min(width, height) / 2
        color: Theme.panel
        border.width: Theme.borderWidth
        border.color: Theme.borderIdle
        opacity: root.sub(root.reveal, 0, 0.15)
    }

    // Same material as the Add Shortcut branch: panel fill, idle hairline,
    // the shell's outer arc, one elevation step below a modal.
    RectangularShadow {
        anchors.fill: surface
        radius: surface.radius
        color: Theme.shadowColor
        blur: Theme.elevationBlur(1)
        spread: Theme.elevationSpread(1)
        offset.y: Theme.elevationOffsetY(1)
        opacity: root.pCross
    }

    Rectangle {
        id: surface
        x: root.startRect.x + (0 - root.startRect.x) * root.pX
        y: root.startRect.y + (0 - root.startRect.y) * root.pY
        width: root.startRect.width + (root.width - root.startRect.width) * root.pX
        height: root.startRect.height + (root.height - root.startRect.height) * root.pY
        radius: Math.min(ShellSurface.radius, width / 2, height / 2)
        color: root.overPanel ? Theme.withAlpha(Theme.mix(Theme.panelTone, Theme.layer1Tone, 0.25), 0.98) : Theme.panel
        border.width: Theme.borderWidth
        border.color: root.overPanel ? Theme.border : Theme.borderIdle
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
