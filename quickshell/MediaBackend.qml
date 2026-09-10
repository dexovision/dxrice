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
    readonly property string artUrl: available ? player.trackArtUrl : ""
    readonly property bool playing: available ? player.isPlaying : false

    readonly property bool seekable: available && player.positionSupported && player.lengthSupported && player.length > 0
    readonly property real position: available ? player.position : 0
    readonly property real length: available ? player.length : 0

    readonly property bool shuffleSupported: available && player.shuffleSupported
    readonly property bool shuffle: available && player.shuffle
    readonly property bool loopSupported: available && player.loopSupported
    // 0 = None, 1 = Track, 2 = Playlist -- MprisLoopState's own ordering.
    readonly property int loopState: available ? player.loopState : 0

    function playPause() { if (root.player) root.player.togglePlaying(); }
    function next() { if (root.player) root.player.next(); }
    function previous() { if (root.player) root.player.previous(); }
    function seekTo(pos) { if (root.player && root.seekable) root.player.position = pos; }
    function toggleShuffle() { if (root.player && root.shuffleSupported) root.player.shuffle = !root.player.shuffle; }
    function cycleLoop() { if (root.player && root.loopSupported) root.player.loopState = (root.player.loopState + 1) % 3; }

    function formatTime(seconds) {
        if (!seconds || seconds < 0 || !isFinite(seconds)) return "0:00";
        const m = Math.floor(seconds / 60);
        const s = Math.floor(seconds % 60);
        return m + ":" + String(s).padStart(2, "0");
    }
}
