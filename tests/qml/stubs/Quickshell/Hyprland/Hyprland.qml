pragma Singleton
import QtQuick
QtObject {
    property var workspaces: ({ values: [
        { id: 1, focused: true, activate: function() {} },
        { id: 2, focused: false, activate: function() {} },
        { id: 3, focused: false, activate: function() {} },
    ] })
    property var activeToplevel: null
}
