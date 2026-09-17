import QtQuick

// A thin, self-hiding scroll indicator for a Flickable -- the shell's answer
// to "the content scrolls but nothing on screen says so." A bare Flickable
// with no ScrollBar looks IDENTICAL whether its content fits or there's a
// whole screen's worth hidden below the fold; a screenshot (or a user who
// never happens to scroll-wheel over it) can't tell the difference, which is
// exactly what read as "content randomly cut off" rather than "content you
// have to scroll to see."
//
// Deliberately not QtQuick.Controls' ScrollBar: everything else in this
// shell is a hand-built Rectangle in Theme's own palette, and a stock
// Controls scrollbar carries its own style that doesn't match. This is the
// same idea reduced to what the shell actually needs: a track-less thumb
// that fades in only when there is something to scroll to.
//
// Usage: anchor a Flickable, then add `ScrollHint { flickable: thatFlickable }`
// as a sibling (not a child) positioned along its trailing edge.
Item {
    id: root
    property Flickable flickable: null
    readonly property bool scrollable: flickable && flickable.visibleArea.heightRatio < 0.999
    width: 3
    opacity: scrollable ? 0.5 : 0
    visible: opacity > 0.01
    Behavior on opacity { NumberAnimation { duration: Theme.durationFast } }

    Rectangle {
        width: parent.width
        radius: width / 2
        color: Theme.text
        y: root.flickable ? root.flickable.visibleArea.yPosition * root.height : 0
        height: root.flickable ? Math.max(20, root.flickable.visibleArea.heightRatio * root.height) : 0
    }
}
