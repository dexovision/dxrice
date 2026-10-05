import QtQuick
import Harness
// Test stub: output comes from the harness's fixture table, never a real
// subprocess, so tests are hermetic and the real parsing code still runs.
QtObject {
    id: root
    property var command: []
    property bool running: false
    property var stdout: null
    property var stderr: null
    property var environment: ({})
    property string workingDirectory: ""
    property bool stdinEnabled: false
    signal exited(int exitCode, int exitStatus)
    signal started()
    function write(data) {}
    function signal(sig) {}
    onRunningChanged: if (running) Qt.callLater(root._finish)
    function _finish() {
        if (!root.running) return;
        const out = Harness.run(root.command || []);
        if (root.stdout) { root.stdout.text = out; root.stdout.streamFinished(); }
        root.running = false;
        root.exited(0, 0);
    }
}
