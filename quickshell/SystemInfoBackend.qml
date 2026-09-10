import QtQuick
import Quickshell
import Quickshell.Io

// Fetch-style system info (OS/kernel/host/uptime/user) -- the same kind of
// card every rice screenshot in this whole session has had somewhere.
// Everything here is a static one-time file read (os-release, /proc/sys
// kernel hostname -- the plain `hostname` binary isn't installed by
// default on Arch anymore, this file always is) or a cheap /proc read for
// uptime; no fastfetch/neofetch dependency needed for five fields.
Item {
    id: root
    property string osName: ""
    property string kernel: ""
    property string hostname: ""
    property string uptime: ""
    readonly property string user: Quickshell.env("USER") || ""

    // blockLoading is required here, not optional: without it text() at
    // Component.onCompleted below can read before the async load finishes
    // and silently fall back to "Linux"/"" (this exact bug shipped once
    // already -- see Theme.qml's own comment on the same gotcha).
    FileView { id: osRelease; path: "/etc/os-release"; blockLoading: true }
    FileView { id: hostnameFile; path: "/proc/sys/kernel/hostname"; blockLoading: true }
    FileView { id: kernelFile; path: "/proc/sys/kernel/osrelease"; blockLoading: true }
    FileView { id: uptimeFile; path: "/proc/uptime" }

    Component.onCompleted: {
        const m = osRelease.text().match(/^PRETTY_NAME="?([^"\n]+)"?/m);
        root.osName = m ? m[1] : "Linux";
        root.hostname = hostnameFile.text().trim();
        root.kernel = kernelFile.text().trim();
    }

    function formatUptime(totalSeconds) {
        const days = Math.floor(totalSeconds / 86400);
        const hours = Math.floor((totalSeconds % 86400) / 3600);
        const mins = Math.floor((totalSeconds % 3600) / 60);
        if (days > 0) return days + "d " + hours + "h";
        if (hours > 0) return hours + "h " + mins + "m";
        return mins + "m";
    }

    Timer {
        interval: 30000
        running: true
        repeat: true
        triggeredOnStart: true
        onTriggered: {
            uptimeFile.reload();
            const seconds = Number(uptimeFile.text().split(" ")[0]) || 0;
            root.uptime = root.formatUptime(seconds);
        }
    }
}
