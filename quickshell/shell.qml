//@ pragma ShellId dxrice
import QtQuick
import Quickshell
import Quickshell.Io

// Entry point for DXrice's Quickshell-based shell.
//
// Quick Settings, Calendar and Taskbar are hosted inside TopBar's and Dock's
// own ShellIslands (see ShellIsland.qml), because a control and the panel it
// summons have to share one item tree to visually morph from one into the
// other. Theme has no originating bar/dock control, so it stays what it
// always was: a LazyLoader'd window toggled by name, torn down when not in
// use. Both kinds of panel are coordinated through ONE singleton --
// PanelManager.qml -- instead of the island panels sharing a bare
// ShellSurface.openPanel string while Theme cross-closed it through a
// second, separate LazyLoader-active mechanism of its own. See
// PanelManager.qml for why that split existed and why nothing here needs to
// know the difference between the two kinds of panel any more.
//
// Toggle from outside (a Hyprland keybind, a terminal):
//   qs -p <repo>/quickshell/shell.qml ipc call quicksettings toggle
//   qs -p <repo>/quickshell/shell.qml ipc call theme toggle
//   qs -p <repo>/quickshell/shell.qml ipc call taskbar toggle
//   qs -p <repo>/quickshell/shell.qml ipc call calendar toggle
ShellRoot {
    id: root

    LazyLoader {
        id: themeLoader
        source: "ThemeEditor.qml"
    }
    // Theme's window is constructed/destroyed by this Loader, not directly
    // by PanelManager: opening is a plain `active = true`, but closing has
    // to go through the loaded item's own requestClose() so its
    // reveal-in-reverse animation gets to play before the loader tears it
    // down (see ThemeEditor.qml's requestClose()/closing/closeTimer).
    // Slamming `active = false` the instant PanelManager.current changes
    // away from "theme" would destroy it mid-frame with no chance for that
    // animation to play -- exactly the bug this reactive close (rather than
    // a plain property binding) exists to avoid.
    Connections {
        target: PanelManager
        function onCurrentChanged() {
            if (PanelManager.current === "theme") {
                themeLoader.active = true;
            } else if (themeLoader.active) {
                if (themeLoader.item) themeLoader.item.requestClose();
                else themeLoader.active = false;
            }
        }
    }
    // The loaded panel calls its own closeRequested() (after its close
    // animation finishes) to ask to be torn down for real --
    // ignoreUnknownSignals covers the window between shell startup and
    // the first `active = true`, when .item is still null.
    Connections {
        target: themeLoader.item
        ignoreUnknownSignals: true
        function onCloseRequested() { themeLoader.active = false; }
    }
    IpcHandler {
        target: "theme"
        function toggle(): void { PanelManager.toggle("theme"); }
        function show(): void { PanelManager.open("theme"); }
        function hide(): void { PanelManager.close("theme"); }
    }

    IpcHandler {
        target: "quicksettings"
        function toggle(): void { PanelManager.toggle("quicksettings"); }
        function show(): void { PanelManager.open("quicksettings"); }
        function hide(): void { PanelManager.close("quicksettings"); }
    }
    IpcHandler {
        target: "calendar"
        function toggle(): void { PanelManager.toggle("calendar"); }
        function show(): void { PanelManager.open("calendar"); }
        function hide(): void { PanelManager.close("calendar"); }
    }
    IpcHandler {
        target: "taskbar"
        function toggle(): void { PanelManager.toggle("taskbar"); }
        function show(): void { PanelManager.open("taskbar"); }
        function hide(): void { PanelManager.close("taskbar"); }
    }

    // Opt-in, not wired to SUPER+L: see LockScreen.qml's own comment for
    // why a real Wayland session lock is a fundamentally higher-stakes
    // thing to trust than any of the panels above (fail-secure by design --
    // a bug here can't be fixed by killing the process the way a broken
    // panel can). `dx lock` triggers it explicitly; SUPER+L stays on the
    // already-proven hyprlock until you've tried this yourself and are
    // comfortable making it the default.
    LockScreen {
        id: lockScreen
    }
    IpcHandler {
        target: "lock"
        function engage(): void { lockScreen.locked = true; }
    }

    // Always constructed, never lazy -- an OSD has to already be watching
    // Pipewire/backlight state before the first volume/brightness keypress,
    // not spun up on first use like the toggleable panels above.
    OSD {
        id: osd
    }

    // The shell's top and bottom edges -- each an always-on window hosting
    // its own islands (see TopBar.qml/Dock.qml/ShellIsland.qml). Their
    // "requested" signals toggle the same shared PanelManager.current every
    // IPC handler above uses, so a click and a keybind take the exact same
    // path.
    TopBar {
        id: topBar
        onCalendarRequested: PanelManager.toggle("calendar")
        onQuickSettingsRequested: PanelManager.toggle("quicksettings")
    }
    Dock {
        id: dock
        onTaskbarRequested: PanelManager.toggle("taskbar")
    }
}
