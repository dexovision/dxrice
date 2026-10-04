pragma Singleton
import QtQuick
import Quickshell

// XDG Base Directory resolution, shared by every QML file that needs
// dxrice's (or a third-party app's) config/data/state/cache location --
// mirrors scripts/dxrice_xdg.py exactly, so the Quickshell UI and the
// Python scripts always agree on where these live regardless of which one
// a user's $XDG_* overrides actually reach. See that file's own docstring
// for the full rationale (the four directories, what belongs in each).
QtObject {
    id: root

    readonly property string home: Quickshell.env("HOME")

    function _base(envVar, fallbackSuffix) {
        const override = Quickshell.env(envVar);
        return (override && override.length > 0) ? override : (root.home + fallbackSuffix);
    }

    readonly property string configHome: root._base("XDG_CONFIG_HOME", "/.config")
    readonly property string dataHome: root._base("XDG_DATA_HOME", "/.local/share")
    readonly property string stateHome: root._base("XDG_STATE_HOME", "/.local/state")
    readonly property string cacheHome: root._base("XDG_CACHE_HOME", "/.cache")

    readonly property string configDir: root.configHome + "/dxrice"
    readonly property string dataDir: root.dataHome + "/dxrice"
    readonly property string stateDir: root.stateHome + "/dxrice"
    readonly property string cacheDir: root.cacheHome + "/dxrice"
}
