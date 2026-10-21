import QtQuick
import Quickshell.Services.Mpris

// Native MPRIS binding -- no playerctl subprocess, no polling. Tracks
// whichever player is currently active; good enough for the common
// single-player case this panel is meant for.
Item {
    id: root
    // The player to show: one that is playing (a paused browser tab listed
    // first must not hide the music that is actually on); else the one that
    // played last, while it is still around; else the first.
    property var _lastPlaying: null
    readonly property var player: {
        const all = Mpris.players.values;
        for (let i = 0; i < all.length; i++) if (all[i].isPlaying) return all[i];
        if (root._lastPlaying && all.indexOf(root._lastPlaying) >= 0) return root._lastPlaying;
        return all.length > 0 ? all[0] : null;
    }
    onPlayerChanged: if (root.player && root.player.isPlaying) root._lastPlaying = root.player
    readonly property bool available: player !== null
    readonly property string title: available ? (player.trackTitle || "Unknown") : ""
    readonly property string artist: available ? player.trackArtist : ""
    readonly property string artUrl: available ? player.trackArtUrl : ""
    readonly property bool playing: available ? player.isPlaying : false

    // Secondary info for the Media pane's right column -- there is no
    // lyrics source in this codebase, so rather than leave that column
    // empty this exposes what MPRIS actually offers beyond title/artist:
    // which app is actually playing, the album (when the player publishes
    // one), and a real per-player volume control (most players -- browser
    // tabs especially -- support this even when they don't support seeking).
    readonly property string source: available ? (player.identity || "") : ""
    readonly property string album: available && player.metadata ? (player.metadata["xesam:album"] || "") : ""
    readonly property bool volumeSupported: available && player.volumeSupported
    readonly property real volume: available ? player.volume : 0
    function setVolume(v) { if (root.player && root.volumeSupported) root.player.volume = v; }

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
