#!/usr/bin/env python3
"""Measures what the desktop costs while idle. Read-only: it only reads /proc.

  python3 scripts/dxrice_idle_probe.py [SECONDS] [--json]

Leave the desktop alone for the whole sample (default 60 s): no input, no
animations, no media. Run it twice, before and after a change, under the
same conditions (same windows open, same monitor, no updates running).

For each group of this user's processes:
  pss_mib     proportional set size (shared pages split between the processes
              sharing them), from /proc/PID/smaps_rollup, at the end
  cpu_pct     CPU time used during the sample, as % of one core
  wakeups_s   context switches per second, voluntary + involuntary, over all
              threads: how often the group gets scheduled at all
  spawned     processes started during the sample whose parent is in the
              group (each a fork+exec: hyprctl, sh, python3 ...)

Groups: hyprland (the compositor), quickshell (qs), dxrice-daemons (any
python process running a dxrice_*.py script), other (everything else of
yours). Kernel threads and other users' processes are left out.
"""
import json
import os
import sys
import time

CLK_TCK = os.sysconf("SC_CLK_TCK")
UID = os.getuid()


def _read(path):
    try:
        with open(path, "rb") as f:
            return f.read().decode(errors="replace")
    except OSError:
        return None


def _pids():
    out = []
    for name in os.listdir("/proc"):
        if not name.isdigit():
            continue
        try:
            if os.stat(f"/proc/{name}").st_uid == UID:
                out.append(int(name))
        except OSError:
            pass
    return out


def group_of(pid):
    cmd = _read(f"/proc/{pid}/cmdline")
    if not cmd:
        return None  # kernel thread or gone
    argv = [a for a in cmd.split("\0") if a]
    exe = os.path.basename(argv[0]) if argv else ""
    if exe in ("Hyprland", "hyprland", ".Hyprland-wrapped"):
        return "hyprland"
    if exe in ("qs", "quickshell"):
        return "quickshell"
    if exe.startswith("python") and any(os.path.basename(a).startswith("dxrice_") for a in argv[1:2]):
        return "dxrice-daemons"
    return "other"


def cpu_ticks(pid):
    stat = _read(f"/proc/{pid}/stat")
    if not stat:
        return 0
    fields = stat[stat.rfind(")") + 2:].split()
    return int(fields[11]) + int(fields[12])  # utime + stime


def ppid(pid):
    stat = _read(f"/proc/{pid}/stat")
    if not stat:
        return None
    return int(stat[stat.rfind(")") + 2:].split()[1])


def switches(pid):
    total = 0
    try:
        tids = os.listdir(f"/proc/{pid}/task")
    except OSError:
        return 0
    for tid in tids:
        status = _read(f"/proc/{pid}/task/{tid}/status") or ""
        for line in status.splitlines():
            if line.startswith(("voluntary_ctxt_switches", "nonvoluntary_ctxt_switches")):
                total += int(line.split()[1])
    return total


def pss_kib(pid):
    rollup = _read(f"/proc/{pid}/smaps_rollup") or ""
    for line in rollup.splitlines():
        if line.startswith("Pss:"):
            return int(line.split()[1])
    return 0


def snapshot():
    snap = {}
    for pid in _pids():
        g = group_of(pid)
        if g:
            snap[pid] = (g, cpu_ticks(pid), switches(pid))
    return snap


def measure(seconds):
    before = snapshot()
    groups_at_start = {pid: g for pid, (g, _, _) in before.items()}
    spawned = {}
    seen = set(before)
    t0 = time.monotonic()
    # poll for new processes often enough to catch short-lived ones
    while time.monotonic() - t0 < seconds:
        for pid in _pids():
            if pid in seen:
                continue
            seen.add(pid)
            parent = ppid(pid)
            g = groups_at_start.get(parent)
            if g:
                spawned[g] = spawned.get(g, 0) + 1
        time.sleep(0.02)
    elapsed = time.monotonic() - t0
    after = snapshot()

    result = {}
    for pid, (g, ticks, sw) in after.items():
        r = result.setdefault(g, {"processes": 0, "pss_mib": 0.0, "cpu_pct": 0.0, "wakeups_s": 0.0, "spawned": 0})
        r["processes"] += 1
        r["pss_mib"] += pss_kib(pid) / 1024
        if pid in before and before[pid][0] == g:
            r["cpu_pct"] += (ticks - before[pid][1]) / CLK_TCK / elapsed * 100
            r["wakeups_s"] += (sw - before[pid][2]) / elapsed
    for g, n in spawned.items():
        result.setdefault(g, {"processes": 0, "pss_mib": 0.0, "cpu_pct": 0.0, "wakeups_s": 0.0, "spawned": 0})
        result[g]["spawned"] = n
    for r in result.values():
        for k in ("pss_mib", "cpu_pct", "wakeups_s"):
            r[k] = round(r[k], 2)
    return {"seconds": round(elapsed, 1), "groups": result}


def main(argv):
    seconds = float(next((a for a in argv[1:] if not a.startswith("-")), 60))
    res = measure(seconds)
    if "--json" in argv:
        print(json.dumps(res, indent=2, sort_keys=True))
        return 0
    print(f"idle sample: {res['seconds']} s")
    print(f"{'group':<16}{'procs':>6}{'PSS MiB':>10}{'CPU %':>8}{'wakeups/s':>11}{'spawned':>9}")
    for g in ("hyprland", "quickshell", "dxrice-daemons", "other"):
        r = res["groups"].get(g)
        if r:
            print(f"{g:<16}{r['processes']:>6}{r['pss_mib']:>10.1f}{r['cpu_pct']:>8.2f}"
                  f"{r['wakeups_s']:>11.1f}{r['spawned']:>9}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
