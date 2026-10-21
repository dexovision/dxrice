pragma Singleton
import QtQuick
import Quickshell.Io

// Owns the Performance tab's expensive polling (CPU/mem/disk sampling),
// decoupled from QuickSettings.qml's own lifetime.
//
// Before this, the 1.5s CPU/mem Timer and 30s disk Timer lived directly on
// QuickSettings.qml's root and ran unconditionally for as long as the WHOLE
// panel was open -- regardless of which of the 3 tabs (Overview/Media/
// Performance) was actually selected. Confirmed empirically in the Phase 4
// baseline: switching from Performance to Media kept producing sample ticks
// tagged "tab=media" instead of stopping. This service is the fix: sampling
// only runs while `active` is true, and QuickSettings.qml is the only thing
// that sets it, tying it directly to "the Performance tab is the one
// currently selected AND the panel itself still exists" -- never just "the
// panel is open."
QtObject {
    id: root

    // The single on/off switch. Whoever wants this data sets this true
    // while the Performance view is actually visible and false the instant
    // it stops being visible -- QuickSettings.qml does this from its own
    // `currentTab` and `Component.onDestruction`, so switching tabs OR
    // closing the panel while still on Performance both reliably release
    // it. There is deliberately no ref-counting here: exactly one consumer
    // (Quick Settings' Performance tab) will ever set this, so a ref-count
    // would just be unused machinery -- see the plan's explicit
    // "don't overengineer" guidance.
    property bool active: false
    // The desktop system widget is a second, independent consumer: it counts
    // itself in and out here (it must not flip `active`, which Quick Settings
    // owns), and sampling runs while either wants it.
    property int widgetUsers: 0
    readonly property bool sampling: root.active || root.widgetUsers > 0
    // once per sample, after every reading above is updated (a history that
    // only grew when a value changed would never draw a steady reading)
    signal sampled()
    // The last minute or so of each reading (one entry per sample, oldest
    // first), for graphs; kept here so a graph that appears later still has
    // what was sampled before it was shown. Real samples only: a reading
    // with no source (no GPU) gets no entries.
    readonly property int historyLength: 40
    property var cpuHistory: []
    property var gpuHistory: []
    property var memHistory: []
    property var netDownHistory: []
    property var netUpHistory: []
    function _keep(list, v) { const a = list.slice(-(root.historyLength - 1)); a.push(v); return a; }
    function _record() {
        root.cpuHistory = root._keep(root.cpuHistory, root._cpuPercent);
        root.memHistory = root._keep(root.memHistory, root._memPercent);
        if (root._gpuAvailable) root.gpuHistory = root._keep(root.gpuHistory, root._gpuPercent);
        root.netDownHistory = root._keep(root.netDownHistory, root._netDownKBs);
        root.netUpHistory = root._keep(root.netUpHistory, root._netUpKBs);
    }

    readonly property real cpuPercent: _cpuPercent
    readonly property real memPercent: _memPercent
    readonly property real diskPercent: _diskPercent
    readonly property string diskUsedLabel: _diskUsedLabel
    readonly property real networkRateKBs: _networkRateKBs
    readonly property real netDownKBs: _netDownKBs
    readonly property real netUpKBs: _netUpKBs
    readonly property real memUsedGiB: _memUsedGiB
    readonly property real memTotalGiB: _memTotalGiB

    // Sensors and system facts, all plain sysfs/procfs reads. Each is -1 /
    // "" until a real source is found (sensorsProc, once per session); the
    // UI shows that as missing, never as a made-up reading.
    readonly property real cpuTempC: _cpuTempC
    readonly property real gpuTempC: _gpuTempC
    readonly property real diskTempC: _diskTempC
    readonly property int batteryPercent: _batteryPercent
    readonly property string batteryStatus: _batteryStatus
    readonly property real uptimeS: _uptimeS
    readonly property real load1: _load1
    readonly property string hostName: hostFile.text().trim()
    readonly property string kernel: kernelFile.text().trim()

    // GPU: no single cross-vendor interface exists (AMD publishes a sysfs
    // busy-percent file; NVIDIA requires nvidia-smi; Intel has neither in
    // any common form). Detected once, lazily, the first time Performance
    // is actually opened -- not at process startup, so a machine that never
    // opens this tab never pays even the one-time detection cost.
    // `gpuAvailable` stays false (not a fabricated 0%) until a real source
    // is found, so the UI can show a genuine "unavailable" state instead of
    // a fake reading.
    readonly property bool gpuAvailable: _gpuAvailable
    readonly property real gpuPercent: _gpuPercent
    property bool _gpuDetected: false
    property bool _gpuAvailable: false
    property real _gpuPercent: 0
    property string _gpuSysfsPath: ""

    property real _cpuPercent: 0
    property real _memPercent: 0
    property real _diskPercent: 0
    property string _diskUsedLabel: ""
    property var _prevCpuTimes: null
    property real _networkRateKBs: 0
    property real _netDownKBs: 0
    property real _netUpKBs: 0
    property var _prevNetSplit: null
    property real _memUsedGiB: 0
    property real _memTotalGiB: 0
    property real _cpuTempC: -1
    property real _gpuTempC: -1
    property real _diskTempC: -1
    property int _batteryPercent: -1
    property string _batteryStatus: ""
    property real _uptimeS: 0
    property real _load1: 0
    property var _sensorPaths: ({})
    property var _prevNetBytes: null
    property var _prevNetTime: null

    // QtObject (unlike Item) has no default property, so every child object
    // has to be assigned to an explicitly declared property of its own type
    // -- same pattern Theme.qml already uses for its own FileView.
    property FileView statFile: FileView { path: "/proc/stat" }
    property FileView memFile: FileView { path: "/proc/meminfo" }
    property FileView netFile: FileView { path: "/proc/net/dev" }
    // Path is empty until GPU detection (below) finds a real sysfs file;
    // an empty path just means "nothing loaded yet," not an error.
    property FileView gpuFile: FileView { path: root._gpuSysfsPath }
    property FileView cpuTempFile: FileView { path: root._sensorPaths.cpu || "" }
    property FileView gpuTempFile: FileView { path: root._sensorPaths.gputemp || "" }
    property FileView diskTempFile: FileView { path: root._sensorPaths.disk || "" }
    property FileView batCapFile: FileView { path: root._sensorPaths.bat ? root._sensorPaths.bat + "/capacity" : "" }
    property FileView batStatusFile: FileView { path: root._sensorPaths.bat ? root._sensorPaths.bat + "/status" : "" }
    property FileView uptimeFile: FileView { path: "/proc/uptime" }
    property FileView loadFile: FileView { path: "/proc/loadavg" }
    property FileView hostFile: FileView { path: "/proc/sys/kernel/hostname" }
    property FileView kernelFile: FileView { path: "/proc/sys/kernel/osrelease" }

    function _sampleCpu() {
        const line = statFile.text().split("\n")[0];
        const fields = line.trim().split(/\s+/).slice(1).map(Number);
        if (root._prevCpuTimes) {
            const prev = root._prevCpuTimes;
            const prevIdle = prev[3] + prev[4];
            const curIdle = fields[3] + fields[4];
            const prevTotal = prev.reduce((a, b) => a + b, 0);
            const curTotal = fields.reduce((a, b) => a + b, 0);
            const totalDelta = curTotal - prevTotal;
            const idleDelta = curIdle - prevIdle;
            root._cpuPercent = totalDelta > 0 ? Math.max(0, Math.min(100, (totalDelta - idleDelta) / totalDelta * 100)) : 0;
        }
        root._prevCpuTimes = fields;
    }

    function _sampleMem() {
        const info = {};
        for (const line of memFile.text().split("\n")) {
            const m = line.match(/^(\w+):\s*(\d+)/);
            if (m) info[m[1]] = Number(m[2]);
        }
        const total = info.MemTotal || 1;
        const avail = info.MemAvailable !== undefined ? info.MemAvailable : total;
        root._memPercent = Math.max(0, Math.min(100, (total - avail) / total * 100));
        root._memUsedGiB = (total - avail) / 1048576;
        root._memTotalGiB = total / 1048576;
    }

    // ---- network: total rx+tx bytes across every non-loopback interface,
    // sampled at the same 1.5s cadence as CPU/mem so the rate reads live. ----
    function _sampleNetwork() {
        const now = Date.now();
        let total = 0, rx = 0, tx = 0;
        const lines = netFile.text().split("\n").slice(2);
        for (const line of lines) {
            const parts = line.trim().split(":");
            if (parts.length < 2) continue;
            const iface = parts[0].trim();
            if (iface === "lo" || iface.length === 0) continue;
            const fields = parts[1].trim().split(/\s+/).map(Number);
            // rx bytes is field 0, tx bytes is field 8 (per /proc/net/dev's
            // documented column layout).
            total += fields[0] + fields[8];
            rx += fields[0];
            tx += fields[8];
        }
        if (root._prevNetBytes !== null && root._prevNetTime !== null) {
            const elapsedS = (now - root._prevNetTime) / 1000;
            const deltaBytes = total - root._prevNetBytes;
            root._networkRateKBs = elapsedS > 0 ? Math.max(0, deltaBytes / elapsedS / 1024) : 0;
            if (root._prevNetSplit && elapsedS > 0) {
                root._netDownKBs = Math.max(0, (rx - root._prevNetSplit[0]) / elapsedS / 1024);
                root._netUpKBs = Math.max(0, (tx - root._prevNetSplit[1]) / elapsedS / 1024);
            }
        }
        root._prevNetSplit = [rx, tx];
        root._prevNetBytes = total;
        root._prevNetTime = now;
    }

    // ---- GPU: detected once, lazily, on first activation. Tries AMD's
    // sysfs busy-percent file first (a plain synchronous file read, no
    // subprocess needed for ongoing sampling -- cheap enough to poll at the
    // same cadence as CPU/mem); NVIDIA would need nvidia-smi shelled out on
    // every sample instead, so it's only used to confirm a working NVIDIA
    // GPU exists at all, not for ongoing polling in this pass. Neither
    // found -> gpuAvailable stays false permanently for this session
    // (detection is not retried every tick against a GPU that isn't there). ----
    function _detectGpu() {
        if (root._gpuDetected) return;
        root._gpuDetected = true;
        gpuDetectProc.running = true;
        sensorsProc.running = true;
    }
    // ---- sensors: found once (hwmon names, the GPU's own hwmon, the
    // system battery -- not a mouse's, whose scope is "Device"), then read
    // as files on every tick like everything else ----
    property Process sensorsProc: Process {
        command: ["sh", "-c",
            "for h in /sys/class/hwmon/hwmon*; do case \"$(cat $h/name 2>/dev/null)\" in "
            + "k10temp|coretemp|zenpower|cpu_thermal) echo cpu=$h/temp1_input;; nvme) echo disk=$h/temp1_input;; esac; done; "
            + "g=$(ls /sys/class/drm/card*/device/gpu_busy_percent 2>/dev/null | head -1); "
            + "[ -n \"$g\" ] && for h in $(dirname $g)/hwmon/hwmon*; do [ -f $h/temp1_input ] && echo gputemp=$h/temp1_input; done; "
            + "for b in /sys/class/power_supply/*; do [ \"$(cat $b/type 2>/dev/null)\" = Battery ] && [ \"$(cat $b/scope 2>/dev/null)\" != Device ] "
            + "&& [ -f $b/capacity ] && echo bat=$b; done; true"]
        stdout: StdioCollector {
            onStreamFinished: {
                const found = {};
                for (const line of this.text.split("\n")) {
                    const i = line.indexOf("=");
                    if (i > 0 && found[line.slice(0, i)] === undefined) found[line.slice(0, i)] = line.slice(i + 1).trim();
                }
                root._sensorPaths = found;
            }
        }
    }
    function _readTemp(file, has) {
        if (!has) return -1;
        file.reload();
        const v = Number(file.text().trim());
        return isNaN(v) || v <= 0 ? -1 : v / 1000;
    }
    function _sampleSensors() {
        const p = root._sensorPaths;
        root._cpuTempC = root._readTemp(cpuTempFile, !!p.cpu);
        root._gpuTempC = root._readTemp(gpuTempFile, !!p.gputemp);
        root._diskTempC = root._readTemp(diskTempFile, !!p.disk);
        if (p.bat) {
            batCapFile.reload(); batStatusFile.reload();
            const c = parseInt(batCapFile.text().trim());
            root._batteryPercent = isNaN(c) ? -1 : Math.max(0, Math.min(100, c));
            root._batteryStatus = batStatusFile.text().trim();
        }
        uptimeFile.reload(); loadFile.reload();
        root._uptimeS = Number(uptimeFile.text().split(" ")[0]) || 0;
        root._load1 = Number(loadFile.text().split(" ")[0]) || 0;
    }
    property Process gpuDetectProc: Process {
        // Finds the first AMD-style busy-percent sysfs file, if any.
        command: ["sh", "-c", "ls /sys/class/drm/card*/device/gpu_busy_percent 2>/dev/null | head -1"]
        stdout: StdioCollector {
            onStreamFinished: {
                const path = this.text.trim();
                if (path.length > 0) {
                    root._gpuSysfsPath = path;
                    root._gpuAvailable = true;
                } else {
                    nvidiaCheckProc.running = true;
                }
            }
        }
    }
    property Process nvidiaCheckProc: Process {
        command: ["nvidia-smi", "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"]
        stdout: StdioCollector {
            onStreamFinished: {
                const value = Number(this.text.trim());
                if (!isNaN(value)) {
                    root._gpuAvailable = true;
                    root._gpuPercent = value;
                }
                // A failed/non-numeric result means no working NVIDIA GPU
                // either -- gpuAvailable stays false, genuinely, rather
                // than showing a fabricated reading.
            }
        }
    }
    function _sampleGpu() {
        if (!root._gpuAvailable || root._gpuSysfsPath.length === 0) return;
        gpuFile.reload();
        const value = Number(gpuFile.text().trim());
        if (!isNaN(value)) root._gpuPercent = value;
    }

    // ---- disk usage (statvfs via df, sampled far less often -- it never
    // changes fast enough to justify /proc-speed polling) ----
    property Process diskProc: Process {
        command: ["df", "-B1", "--output=used,size", "/"]
        stdout: StdioCollector {
            onStreamFinished: {
                const lines = this.text.trim().split("\n");
                if (lines.length < 2) return;
                const parts = lines[1].trim().split(/\s+/).map(Number);
                if (parts.length < 2 || !parts[1]) return;
                root._diskPercent = Math.max(0, Math.min(100, (parts[0] / parts[1]) * 100));
                root._diskUsedLabel = (parts[0] / 1e9).toFixed(0) + " / " + (parts[1] / 1e9).toFixed(0) + " GB";
            }
        }
    }

    property Timer sampleTimer: Timer {
        interval: 1500
        running: root.sampling
        repeat: true
        triggeredOnStart: true
        onTriggered: {
            root.statFile.reload(); root.memFile.reload(); root.netFile.reload();
            root._sampleCpu(); root._sampleMem(); root._sampleNetwork(); root._sampleGpu(); root._sampleSensors();
            root._record();
            root.sampled();
        }
    }
    property Timer diskTimer: Timer {
        interval: 30000
        running: root.sampling
        repeat: true
        triggeredOnStart: true
        onTriggered: root.diskProc.running = true
    }
    // GPU detection is one-shot per session, triggered the first time this
    // service is actually activated (never at process startup) -- exactly
    // the same lazy-cost principle as the disk/CPU/mem timers above.
    onSamplingChanged: if (sampling) root._detectGpu()
}
