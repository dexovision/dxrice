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

    LazyLoader {
        id: quickSettingsLoader
        source: "QuickSettings.qml"
    }
    // Each loaded panel calls its own closeRequested() (Escape, close
    // button, or a self-triggered action like screenshotting) to ask to be
    // torn down -- ignoreUnknownSignals covers the window between shell
    // startup and the first `active = true`, when .item is still null.
    Connections {
        target: quickSettingsLoader.item
        ignoreUnknownSignals: true
        function onCloseRequested() { quickSettingsLoader.active = false; }
    }
    IpcHandler {
        target: "quicksettings"
        function toggle(): void {
            quickSettingsLoader.active = !quickSettingsLoader.active;
        }
        function show(): void { quickSettingsLoader.active = true; }
        function hide(): void { quickSettingsLoader.active = false; }
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
        function toggle(): void {
            themeLoader.active = !themeLoader.active;
        }
        function show(): void { themeLoader.active = true; }
        function hide(): void { themeLoader.active = false; }
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
        function toggle(): void {
            taskbarLoader.active = !taskbarLoader.active;
        }
        function show(): void { taskbarLoader.active = true; }
        function hide(): void { taskbarLoader.active = false; }
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
}
