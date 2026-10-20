pragma Singleton
import QtQuick
import Harness

// Test stub: the subset of Quickshell's global object the shell uses.
QtObject {
    readonly property string shellDir: Harness.shellDir
    readonly property var screens: []
    function env(name) { return Harness.env(name); }
    function execDetached(argv) { Harness.exec(argv); }
    // icons: none are installed in the harness, so the launcher shows its lettered tiles
    function iconPath(name, check) { return ""; }
}
