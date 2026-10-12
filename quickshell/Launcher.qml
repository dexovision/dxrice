pragma Singleton
import QtQuick
import Quickshell

// Starts apps the user launches from the shell (dock tiles, the lock
// screen, screenshots) through scripts/dxrice_launch.sh, which gives each
// one its own systemd scope. Started with a bare execDetached they stayed
// inside dxrice-quickshell.service's cgroup, and systemd kills that whole
// cgroup on every stop or crash-restart of the shell -- taking the user's
// open apps with it. Short-lived helpers (nmcli, brightnessctl, ...) don't
// need this and still use execDetached directly.
QtObject {
    readonly property string script: Quickshell.shellDir + "/../scripts/dxrice_launch.sh"

    function launch(name, argv) {
        Quickshell.execDetached([script, name].concat(argv));
    }
}
