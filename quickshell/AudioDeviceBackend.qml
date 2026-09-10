import QtQuick
import Quickshell.Services.Pipewire

// Lists real physical/virtual audio output and input devices (excluding
// per-app streams) via Pipewire.nodes, and lets Quick Settings switch which
// one is the system default -- the one genuinely new capability neither
// the old GTK app nor the first Quickshell pass had.
//
// PwNodeType is a bitflag; "Audio" is set on every real audio node
// (device or stream) but not on unrelated nodes like a webcam's v4l2
// capture node, so `type & PwNodeType.Audio` is what actually separates
// "a mic" from "a camera" -- isSink/isStream alone don't.
Item {
    id: root

    function isRealAudioDevice(n) {
        return !n.isStream && (n.type & PwNodeType.Audio) !== 0;
    }

    readonly property var outputs: {
        const list = [];
        for (const n of Pipewire.nodes.values) {
            if (root.isRealAudioDevice(n) && n.isSink) list.push(n);
        }
        return list;
    }
    readonly property var inputs: {
        const list = [];
        for (const n of Pipewire.nodes.values) {
            if (root.isRealAudioDevice(n) && !n.isSink) list.push(n);
        }
        return list;
    }

    function label(node) {
        return node.description && node.description.length > 0 ? node.description : node.name;
    }

    function setOutput(node) { Pipewire.preferredDefaultAudioSink = node; }
    function setInput(node) { Pipewire.preferredDefaultAudioSource = node; }
}
