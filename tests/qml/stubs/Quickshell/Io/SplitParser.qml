import QtQuick
// Test stub: Process hands it the fixture's output and it emits one `read`
// per line, as Quickshell's SplitParser does for a streaming process.
QtObject {
    property string splitMarker: "\n"
    signal read(string data)
    function feedAll(text) {
        for (const line of String(text).split(splitMarker)) if (line.length > 0) read(line);
    }
}
