pragma Singleton
import QtQuick
QtObject {
    id: root
    property QtObject defaultAudioSink: QtObject {
        property string name: "alsa_output.speakers"
        property string description: "Built-in Speakers"
        property bool isSink: true
        property bool isStream: false
        property int type: 1
        property QtObject audio: QtObject { property real volume: 0.62; property bool muted: false }
    }
    property QtObject defaultAudioSource: QtObject {
        property string name: "alsa_input.mic"
        property string description: "Built-in Microphone"
        property bool isSink: false
        property bool isStream: false
        property int type: 1
        property QtObject audio: QtObject { property real volume: 0.4; property bool muted: false }
    }
    property var nodes: ({ values: [root.defaultAudioSink, root.defaultAudioSource] })
    property var preferredDefaultAudioSink: null
    property var preferredDefaultAudioSource: null
}
