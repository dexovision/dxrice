import QtQuick
import Quickshell.Services.Mpris

// Native MPRIS binding -- no playerctl subprocess, no polling. Tracks
// whichever player is currently active; good enough for the common
// single-player case this panel is meant for.
Item {
    id: root
    readonly property var player: Mpris.players.values.length > 0 ? Mpris.players.values[0] : null
    readonly property bool available: player !== null
    readonly property string title: available ? (player.trackTitle || "Unknown") : ""
    readonly property string artist: available ? player.trackArtist : ""
    readonly property bool playing: available ? player.isPlaying : false

    function playPause() { if (root.player) root.player.togglePlaying(); }
    function next() { if (root.player) root.player.next(); }
    function previous() { if (root.player) root.player.previous(); }
}
