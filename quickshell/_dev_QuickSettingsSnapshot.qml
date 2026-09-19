import QtQuick
import Quickshell

// Throwaway visual-QA rig -- NOT part of the shell, never wired into
// shell.qml. Loads the REAL QuickSettings.qml component (same file the live
// shell uses) inside its own isolated, offscreen-rendered window so its
// actual proportions/alignment/spacing can be inspected from a real
// grabToImage render, without touching the live production shell or
// capturing anything on the real desktop. Run with: qs -p
// _dev_QuickSettingsSnapshot.qml -- renders to
// /tmp/qs_snapshot_overview.png / _media.png / _performance.png and quits.
FloatingWindow {
    id: win
    implicitWidth: 720
    implicitHeight: 460
    title: "QuickSettings Snapshot"
    color: "#202020"

    // Matches the real panel backdrop ShellIsland.qml actually draws behind
    // this content in production (Theme.panel fill, ShellSurface.radius
    // corners) -- without this, QuickSettings.qml's own root Item has no
    // fill of its own (ShellIsland owns that layer), so grabToImage would
    // capture transparent pixels there instead of the real panel tone,
    // making light text falsely read as low-contrast/illegible.
    Rectangle {
        id: backdrop
        anchors.centerIn: parent
        width: 680 + Theme.padLg * 2
        height: 420 + Theme.padLg * 2
        radius: ShellSurface.radius
        color: Theme.panel
        border.width: 1
        border.color: Theme.borderIdle

        QuickSettings {
            id: qsPanel
            anchors.centerIn: parent
            width: 680   // ShellSurface.panelWidthWide, the real production width
            height: 420  // preferredPaneHeight + header, the real production height
        }
    }

    property int tabIndex: 0
    property var tabNames: ["overview", "media", "performance"]

    Timer {
        id: settleTimer
        interval: 900
        onTriggered: {
            backdrop.grabToImage((result) => {
                result.saveToFile("/tmp/qs_snapshot_" + win.tabNames[win.tabIndex] + ".png");
                if (win.tabIndex < win.tabNames.length - 1) {
                    win.tabIndex += 1;
                    qsPanel.currentTab = win.tabNames[win.tabIndex];
                    restart();
                } else {
                    Qt.quit();
                }
            });
        }
    }
    Component.onCompleted: settleTimer.start()
}
