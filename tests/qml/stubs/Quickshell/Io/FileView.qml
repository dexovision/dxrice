import QtQuick
import Harness
QtObject {
    id: root
    property string path: ""
    property bool watchChanges: false
    property bool blockLoading: false
    property bool printErrors: true
    property string _text: ""
    signal fileChanged()
    signal loaded()
    signal loadFailed(var error)
    function text() { return root._text; }
    function reload() { root._load(); }
    function setText(t) { Harness.writeFile(root.path, t); root._text = t; }
    function _load() {
        if (!root.path) return;
        const t = Harness.readFile(root.path);
        if (t === null || t === undefined) { root._text = ""; root.loadFailed("not found"); return; }
        root._text = t;
        root.loaded();
    }
    onPathChanged: root._load()
    Component.onCompleted: root._load()
}
