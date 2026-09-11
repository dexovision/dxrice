//@ pragma ShellId dxrice
import QtQuick
import Quickshell
import Quickshell.Io

// Entry point for DXrice's Quickshell-based shell -- replaces the old
// per-invocation GTK4 apps (Theme, Taskbar, Quick Settings) with one
// persistent process, autostarted alongside waybar, with each panel
// toggled on demand via IPC instead of being spawned fresh every time.
//
// Toggle from outside (waybar on-click, a Hyprland keybind, a terminal):
//   qs -p <repo>/quickshell/shell.qml ipc call quicksettings toggle
//   qs -p <repo>/quickshell/shell.qml ipc call theme toggle
//   qs -p <repo>/quickshell/shell.qml ipc call taskbar toggle
//
// Each panel is a LazyLoader: nothing is constructed (no window, no
// backend Process objects) until the first toggle, and `active: false`
// fully tears it down again rather than just hiding it -- so an idle
// DXrice shell costs next to nothing beyond Theme.qml's live file watch.
ShellRoot {
    id: root

    // Closing a loaded panel from OUTSIDE it (an IPC hide/toggle -- the
    // far more common path in practice, since that's what every waybar
    // on-click and keybind actually calls) used to just slam
    // `loader.active = false` straight away, destroying the panel mid-
    // frame with no chance for its own close animation to play; only the
    // panel's own internal close button/Escape went through
    // requestClose(). Routing every close through the same
    // requestClose() (when the panel exists to ask) means external and
    // internal close paths now always play the same reveal-in-reverse
    // before the loader actually tears it down.
    function closeLoader(loader) {
        if (loader.item) loader.item.requestClose();
        else loader.active = false;
    }
    function toggleLoader(loader) {
        if (loader.active) root.closeLoader(loader);
        else loader.active = true;
    }

    LazyLoader {
        id: quickSettingsLoader
        source: "QuickSettings.qml"
    }
    // Each loaded panel calls its own closeRequested() (after its close
    // animation finishes) to ask to be torn down for real --
    // ignoreUnknownSignals covers the window between shell startup and
    // the first `active = true`, when .item is still null.
    Connections {
        target: quickSettingsLoader.item
        ignoreUnknownSignals: true
        function onCloseRequested() { quickSettingsLoader.active = false; }
    }
    IpcHandler {
        target: "quicksettings"
        function toggle(): void { root.toggleLoader(quickSettingsLoader); }
        function show(): void { quickSettingsLoader.active = true; }
        function hide(): void { root.closeLoader(quickSettingsLoader); }
    }

    LazyLoader {
        id: themeLoader
        source: "ThemeEditor.qml"
    }
    Connections {
        target: themeLoader.item
        ignoreUnknownSignals: true
        function onCloseRequested() { themeLoader.active = false; }
    }
    IpcHandler {
        target: "theme"
        function toggle(): void { root.toggleLoader(themeLoader); }
        function show(): void { themeLoader.active = true; }
        function hide(): void { root.closeLoader(themeLoader); }
    }

    LazyLoader {
        id: taskbarLoader
        source: "TaskbarManager.qml"
    }
    Connections {
        target: taskbarLoader.item
        ignoreUnknownSignals: true
        function onCloseRequested() { taskbarLoader.active = false; }
    }
    IpcHandler {
        target: "taskbar"
        function toggle(): void { root.toggleLoader(taskbarLoader); }
        function show(): void { taskbarLoader.active = true; }
        function hide(): void { root.closeLoader(taskbarLoader); }
    }

    LazyLoader {
        id: calendarLoader
        source: "CalendarPanel.qml"
    }
    Connections {
        target: calendarLoader.item
        ignoreUnknownSignals: true
        function onCloseRequested() { calendarLoader.active = false; }
    }
    IpcHandler {
        target: "calendar"
        function toggle(): void { root.toggleLoader(calendarLoader); }
        function show(): void { calendarLoader.active = true; }
        function hide(): void { root.closeLoader(calendarLoader); }
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
}
