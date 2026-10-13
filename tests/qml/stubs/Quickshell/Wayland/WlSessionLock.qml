import QtQuick
// Creates the lock surface while locked (one, for a single fake screen) so
// the lock UI's own logic can be driven in tests; `surfaceItem` is it.
QtObject {
    id: root
    property bool locked: false
    default property var surface
    property var surfaceItem: null
    onLockedChanged: {
        if (locked && surface && !surfaceItem) surfaceItem = surface.createObject(null, {});
        else if (!locked && surfaceItem) { surfaceItem.destroy(); surfaceItem = null; }
    }
}
