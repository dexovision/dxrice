pragma Singleton
import QtQuick
QtObject {
    property var workspaces: ({ values: [
        { id: 1, focused: true, activate: function() {} },
        { id: 2, focused: false, activate: function() {} },
        { id: 3, focused: false, activate: function() {} },
    ] })
    property var activeToplevel: null
    // Overview: the event-fed toplevel model (address + a fake Wayland
    // toplevel the ScreencopyView stub can paint), the Lua dispatch layer,
    // and the raw event stream. dispatch() only records -- nothing is real.
    property var toplevels: ({ values: [] })
    property bool usingLua: true
    property var focusedMonitor: ({ name: "DP-1" })
    property var dispatchLog: []
    signal rawEvent(var event)
    function dispatch(request) { dispatchLog = dispatchLog.concat([request]); }
    function refreshToplevels() {}
    function refreshMonitors() {}
    function refreshWorkspaces() {}
}
