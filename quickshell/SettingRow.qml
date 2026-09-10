import QtQuick

// A titled row inside a Card -- the QML equivalent of dxrice_gtk_widgets.
// make_row(). Extra content (a slider, switch, button...) goes in `data`
// and is placed after the text block since Row lays children out
// left-to-right.
Row {
    id: root
    property string title: ""
    property string subtitle: ""
    default property alias extra: extraRow.data

    width: parent ? parent.width : implicitWidth
    spacing: Theme.padMd

    Column {
        width: root.width - extraRow.implicitWidth - root.spacing
        anchors.verticalCenter: parent.verticalCenter
        spacing: 0

        Text {
            text: root.title
            color: Theme.textActive
            font.family: Theme.fontFamily
            font.pixelSize: 13
            font.weight: Font.Medium
            elide: Text.ElideRight
            width: parent.width
        }
        Text {
            visible: root.subtitle.length > 0
            text: root.subtitle
            color: Theme.text
            opacity: 0.65
            font.family: Theme.fontFamily
            font.pixelSize: 11
            elide: Text.ElideRight
            width: parent.width
        }
    }

    Row {
        id: extraRow
        spacing: Theme.padSm
        anchors.verticalCenter: parent.verticalCenter
    }
}
