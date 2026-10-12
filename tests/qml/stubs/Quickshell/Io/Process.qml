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
    // Mirrors quickshell src/io/process.cpp: a start request made while a
    // process is live is remembered (targetRunning) and honoured once it
    // exits; on exit `running` is ALREADY false when the stdout parser's
    // streamFinished fires, so handlers may set `running = true` to chain
    // the next command (BluetoothBackend does exactly that).
    property bool _live: false
    property bool _target: false
    onRunningChanged: {
        if (root.running && !root._live) { root._live = true; Qt.callLater(root._finish); }
        else if (root.running && root._live) root._target = true;
    }
    function _finish() {
        const out = Harness.run(root.command || []);
        // Fixture sentinel for "still loading": the process never finishes.
        if (out === "__HANG__") return;
        root._live = false;
        // "__NOSTART__": the binary could not be started. Quickshell emits
        // no `exited` then -- only `running` drops (process.cpp
        // onErrorOccurred(FailedToStart)).
        if (out === "__NOSTART__") { root.running = false; return; }
        // "__EXIT__<code>\n<stderr...>": a run that fails with that exit code
        // and stderr. Streams end before `exited`, as in process.cpp.
        let code = 0, stdoutText = out, stderrText = "";
        const m = /^__EXIT__(\d+)\n?([\s\S]*)$/.exec(out);
        if (m) { code = Number(m[1]); stdoutText = ""; stderrText = m[2]; }
        root.running = false;
        if (root.stdout) { root.stdout.text = stdoutText; root.stdout.streamFinished(); }
        if (root.stderr) { root.stderr.text = stderrText; root.stderr.streamFinished(); }
        root.exited(code, 0);
        if (root._target && !root.running) { root._target = false; root.running = true; }
    }
}
