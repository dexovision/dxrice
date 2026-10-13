import QtQuick

// The shell's one text field: a soft filled box, a quiet leading glyph if
// it has one, a placeholder, and the accent edge only while it has focus.
// The caller supplies the TextInput as a child (so it keeps its own id,
// echo mode and handlers) and points `input` at it. Before this, fields
// came in three unrelated styles -- bordered boxes, a bare underline, a
// search box drawn by hand -- for the same job. (The lock screen's
// password pill is the one deliberate exception: it is the screen.)
Rectangle {
    id: field
    property string glyph: ""
    property string placeholder: ""
    property Item input: null
    // 30px instead of a full row, for fields that sit inside a list row.
    property bool compact: false
    default property alias inner: inputHolder.data
    readonly property bool focused: field.input !== null && field.input.activeFocus

    width: parent ? parent.width : 0
    height: compact ? 30 : ShellSurface.rowHeight
    radius: Theme.roundingMd
    color: Theme.stateFill(Theme.inputFill, hover.hovered && !field.focused, false)
    border.width: Theme.borderWidth
    border.color: field.focused ? Theme.withAlpha(Theme.accent, 0.7) : Theme.borderIdle
    Behavior on border.color { ColorAnimation { duration: Theme.durationFast; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveStandard } }
    Behavior on color { ColorAnimation { duration: Theme.durationFast; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveStandard } }

    HoverHandler { id: hover; cursorShape: Qt.IBeamCursor }

    Text {
        id: glyphText
        visible: field.glyph.length > 0
        anchors.left: parent.left
        anchors.leftMargin: Theme.padMd
        anchors.verticalCenter: parent.verticalCenter
        text: field.glyph
        color: field.focused ? Theme.textActive : Theme.text
        opacity: field.focused ? Theme.opacitySecondary : Theme.opacityMuted
        font.family: Theme.iconFamily
        font.pixelSize: Theme.fontSizeSmaller
    }
    Item {
        id: inputHolder
        anchors.fill: parent
        anchors.leftMargin: glyphText.visible ? Theme.padMd + glyphText.width + Theme.padSm : Theme.padMd
        anchors.rightMargin: Theme.padMd
    }
    Text {
        anchors.fill: inputHolder
        verticalAlignment: Text.AlignVCenter
        text: field.placeholder
        visible: !field.input || field.input.text.length === 0
        color: Theme.text
        opacity: Theme.opacityMuted
        font.family: Theme.fontFamily
        font.pixelSize: field.compact ? Theme.fontSizeSmaller : Theme.fontSizeNormal
        elide: Text.ElideRight
    }
}
