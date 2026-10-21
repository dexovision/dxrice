pragma Singleton
import QtQuick
import Quickshell.Services.Mpris

// Which MPRIS player the shell shows -- one choice for the desktop media
// widget, the Dashboard's Media tab and the bar's media section, so they
// can never be showing two different players. MediaBackend reads `player`
// from here; the players themselves are MPRIS's own objects.
//
// Automatic: one that is playing (a paused browser tab listed first must not
// hide the music that is actually on); else the one that played last, while
// it is still around; else the first. Picking one (choose) holds it until it
// goes away, the user picks again, or ANOTHER player starts playing -- what
// just started is what you want to see.
QtObject {
    id: root
    readonly property var players: Mpris.players.values
    property var chosen: null
    property var _lastPlaying: null
    // the last to start playing, while it is still around (and playing,
    // if any is); else any that is playing; else the first
    readonly property var _auto: {
        const all = root.players;
        const last = root._lastPlaying && all.indexOf(root._lastPlaying) >= 0 ? root._lastPlaying : null;
        if (last && last.isPlaying) return last;
        for (let i = 0; i < all.length; i++) if (all[i].isPlaying) return all[i];
        if (last) return last;
        return all.length > 0 ? all[0] : null;
    }
    readonly property var player: root.chosen && root.players.indexOf(root.chosen) >= 0 ? root.chosen : root._auto

    // the players playing now; one that wasn't before is the last to start,
    // and releases a choice of some other player
    readonly property var _playing: root.players.filter((p) => p.isPlaying)
    property var _wasPlaying: []
    on_PlayingChanged: {
        const started = root._playing.filter((p) => root._wasPlaying.indexOf(p) < 0);
        if (started.length > 0) {
            root._lastPlaying = started[started.length - 1];
            if (root.chosen && started.some((p) => p !== root.chosen)) root.chosen = null;
        }
        root._wasPlaying = root._playing;
    }

    function choose(p) { root.chosen = p; if (p && p.isPlaying) root._lastPlaying = p; }
    function nameOf(p) { return p ? String(p.identity || p.desktopEntry || "Player") : ""; }
}
