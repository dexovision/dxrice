import QtQuick
import Quickshell.Io

// A handful of fixed-timezone clocks, resolved locally via the system's
// own `date` (which already carries the full IANA tzdata) -- no network
// API needed, unlike a weather widget.
Item {
    id: root
    readonly property var zones: [
        { label: "New York", tz: "America/New_York" },
        { label: "London", tz: "Europe/London" },
        { label: "Tokyo", tz: "Asia/Tokyo" },
        { label: "Sydney", tz: "Australia/Sydney" },
    ]
    property var cities: []

    Process {
        id: proc
        command: ["sh", "-c", "for z in " + root.zones.map((z) => z.tz).join(" ") + "; do echo \"$z:$(TZ=$z date +%H:%M)\"; done"]
        stdout: StdioCollector {
            onStreamFinished: {
                const times = {};
                for (const line of this.text.trim().split("\n")) {
                    const idx = line.lastIndexOf(":");
                    if (idx < 0) continue;
                    times[line.substring(0, idx - 3)] = line.substring(idx - 2);
                }
                root.cities = root.zones.map((z) => ({ label: z.label, time: times[z.tz] || "--:--" }));
            }
        }
    }

    Timer {
        interval: 30000
        running: true
        repeat: true
        triggeredOnStart: true
        onTriggered: proc.running = true
    }
}
