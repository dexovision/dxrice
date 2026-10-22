#!/usr/bin/env python3
"""The bar's newer sections, through the real shell QML offscreen: what is
playing (and which player), screenshots and recordings, performance, the
power actions that ask first, sound inputs, and notifications (dismissable
when on screen, an unread count in the bar).

    python3 tests/qml/test_bar_sections.py
"""
import json
import sys
import unittest
from pathlib import Path

try:
    import PySide6  # noqa: F401
except ImportError:  # pragma: no cover
    print("SKIP: PySide6 not installed")
    sys.exit(0)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import Scene  # noqa: E402

PLAYER = """({
    trackTitle: 'Who Can It Be Now?', trackArtist: 'Men at Work', trackArtUrl: '', isPlaying: true,
    identity: 'Spotify', metadata: {}, volumeSupported: true, volume: 0.6,
    positionSupported: true, lengthSupported: true, length: 200, position: 50,
    shuffleSupported: false, shuffle: false, loopSupported: false, loopState: 0,
    calls: [],
    togglePlaying: function() { this.calls.push('toggle'); },
    next: function() { this.calls.push('next'); },
    previous: function() { this.calls.push('previous'); },
    positionChanged: function() { this.calls.push('poll'); }
})"""


class SectionsTest(unittest.TestCase):
    def setUp(self):
        self.s = Scene(width=1920, height=1080)
        self.s.wait(500)

    def tearDown(self):
        self.s.close()

    def centre(self, name):
        return json.loads(self.s.ev(f"(function(){{ const b = findNamed('{name}'); const p = b.mapToItem(null, b.width/2, b.height/2);"
                                    " return JSON.stringify([Math.round(p.x), Math.round(p.y)]); })()"))

    def open(self, section):
        self.s.ev(f"panels.open('status:{section}', 'click')")
        self.s.wait(900)

    def click(self, name):
        self.s.click(*self.centre(name))
        self.s.wait(60)

    def execs(self, prog):
        return [e for e in self.s.bridge.exec_log if e and e[0] == prog]

    # ---- media ----
    def test_the_media_indicator_is_there_only_with_a_player_and_names_the_track(self):
        self.assertFalse(self.s.ev("findNamed('barIndicator:media').visible"))
        self.s.ev(f"mpris.players = {{ values: [{PLAYER}] }}")
        self.s.wait(300)
        self.assertTrue(self.s.ev("findNamed('barIndicator:media').visible"))
        self.assertEqual(self.s.ev("findNamed('barIndicator:media').label"), "Who Can It Be Now?")

    def test_the_media_section_drives_the_shells_one_player(self):
        other = PLAYER.replace("'Who Can It Be Now?'", "'A Paused Tab'").replace("isPlaying: true", "isPlaying: false").replace("'Spotify'", "'Brave'")
        self.s.ev(f"mpris.players = {{ values: [{PLAYER}, {other}] }}")
        self.open("media")
        self.assertEqual(self.s.ev("findNamed('statusMediaTitle').text"), "Who Can It Be Now?")
        for name in ("statusMediaPlay", "statusMediaNext", "statusMediaPrev"):
            self.click(name)
        self.assertEqual(self.s.ev("mpris.players.values[0].calls.filter(c => c !== 'poll').join(',')"), "toggle,next,previous")
        # two players: choosing one here is the choice for the whole shell
        self.assertTrue(self.s.ev("findNamed('statusMediaPlayers').visible"))
        self.click("statusMediaPlayer:1")
        self.s.wait(200)
        self.assertEqual(self.s.ev("findNamed('statusMediaTitle').text"), "A Paused Tab")
        self.assertEqual(self.s.ev("media.player.trackTitle"), "A Paused Tab")

    def test_with_no_player_the_media_section_says_so(self):
        self.open("media")
        self.assertEqual(self.s.ev("findNamed('statusMediaTitle').text"), "Nothing playing")
        self.assertFalse(self.s.ev("findNamed('statusMediaSeek').visible"))

    # ---- capture ----
    def test_a_screenshot_closes_the_panel_first_then_runs_the_capture_script(self):
        self.open("capture")
        self.s.bridge.exec_log.clear()
        self.click("statusShotRegion")
        self.assertEqual(self.s.ev("panels.current"), "", "the panel would be in the shot")
        self.assertEqual(self.execs("sh"), [], "the shot ran before the panel was gone")
        self.s.wait(400)
        shots = [e for e in self.execs("sh") if e[1].endswith("dxrice_capture.sh")]
        self.assertEqual(len(shots), 1)
        self.assertEqual(shots[0][2:], ["shot", "region"])

    def test_a_recording_shows_in_the_bar_and_stops_from_there(self):
        self.s.set_command("dxrice_capture.sh record", "__HANG__")      # wf-recorder runs until stopped
        self.open("capture")
        self.click("statusRecordScreen")
        self.s.wait(400)
        self.s.ev("capture.recorder.stdout.read('started')")     # wf-recorder is up (the script says so)
        self.s.wait(1300)                                        # the timer counts from here
        self.assertTrue(self.s.ev("capture.recording"))
        self.assertGreaterEqual(self.s.ev("capture.elapsed"), 1)
        self.assertEqual(self.s.ev("findNamed('barIndicator:capture').label"), self.s.ev("capture.clock(capture.elapsed)"))
        self.open("capture")
        self.assertTrue(self.s.ev("findNamed('statusRecordStop').visible"))
        self.s.bridge.exec_log.clear()
        self.click("statusRecordStop")
        stops = [e for e in self.execs("sh") if e[1].endswith("dxrice_capture.sh")]
        self.assertEqual([e[2:] for e in stops], [["stop"]])

    # ---- performance ----
    def test_performance_samples_only_while_its_section_shows(self):
        self.assertEqual(self.s.ev("perf.widgetUsers"), 0)
        self.open("performance")
        self.assertEqual(self.s.ev("perf.widgetUsers"), 1)
        self.assertIsNotNone(self.s.ev("findNamed('statusGaugeCpu')"))
        self.s.ev("panels.open('status:network', 'click')")
        self.s.wait(600)
        self.assertEqual(self.s.ev("perf.widgetUsers"), 0, "still sampling with another section showing")
        self.open("performance")
        self.s.ev("panels.closeCurrent()")
        self.s.wait(900)
        self.assertEqual(self.s.ev("perf.widgetUsers"), 0, "still sampling after the panel closed")

    def test_a_missing_gpu_reading_is_said_not_drawn_as_zero(self):
        self.open("performance")
        if self.s.ev("perf.gpuAvailable"):
            self.skipTest("this fixture has a GPU reading")
        gauge = "findNamed('statusGaugeGpu')"
        self.assertFalse(self.s.ev(f"{gauge}.available"))
        self.assertEqual(self.s.ev(f"{gauge}.extra"), "no reading")

    def test_the_graphs_link_opens_the_dashboard_on_performance(self):
        self.open("performance")
        self.click("statusOpenGraphs")
        self.s.wait(900)
        self.assertEqual(self.s.ev("panels.current"), "quicksettings")
        self.assertEqual(self.s.ev("findPanel('currentTab').currentTab"), "performance")

    # ---- power ----
    def test_ending_the_session_takes_a_second_click(self):
        self.open("power")
        self.s.bridge.exec_log.clear()
        self.click("statusPoweroff")
        self.assertEqual(self.execs("sh"), [], "one click shut the machine down")
        self.assertEqual(self.s.ev("findNamed('statusPoweroff').text"), "Shut down now?")
        self.click("statusPoweroff")
        self.assertEqual([e[2:] for e in self.execs("sh")], [["poweroff"]])

    def test_an_unanswered_question_goes_away(self):
        self.open("power")
        self.click("statusReboot")
        self.assertEqual(self.s.ev("findNamed('statusReboot').text"), "Restart now?")
        self.s.wait(4300)
        self.assertEqual(self.s.ev("findNamed('statusReboot').text"), "Restart")
        self.s.bridge.exec_log.clear()
        self.click("statusReboot")
        self.assertEqual(self.execs("sh"), [], "a stale question still counted as the first click")

    # ---- sound ----
    def test_the_sound_section_picks_the_input_too(self):
        self.s.ev("addAudioDevices()")
        self.open("audio")
        name = "statusInput:HyperX Virtual Surround Sound Mic"
        self.assertIsNotNone(self.s.ev(f"findNamed('{name}')"))
        self.click(name)
        self.assertEqual(self.s.ev("pipewire.preferredDefaultAudioSource.description"), "HyperX Virtual Surround Sound Mic")

    # ---- notifications ----
    def test_on_screen_notifications_can_be_dismissed_and_new_ones_counted(self):
        def fixtures(bridge):
            bridge.commands.insert(0, ("makoctl list -j", json.dumps([{"id": 7, "app_name": "Discord", "summary": "ping"}])))
            bridge.commands.insert(0, ("makoctl history -j", json.dumps([{"id": 3, "app_name": "kitty", "summary": "done"}])))
        self.s.close()
        self.s = Scene(width=1920, height=1080, setup=fixtures)
        self.s.wait(500)
        # what was in the history at start isn't unread; what is on screen is
        self.assertEqual(self.s.ev("notifications.unread"), 1)
        self.assertEqual(self.s.ev("findNamed('barIndicator:notifications').badge"), 1)
        self.s.set_command("makoctl history -j", json.dumps([{"id": 9, "app_name": "Steam", "summary": "update"},
                                                             {"id": 3, "app_name": "kitty", "summary": "done"}]))
        self.s.ev("notifications.refresh()")
        self.s.wait(300)
        self.assertEqual(self.s.ev("notifications.unread"), 2)
        self.open("notifications")
        self.s.bridge.exec_log.clear()
        self.click("statusDismiss:7")
        self.assertIn(["makoctl", "dismiss", "-n", "7"], self.s.bridge.exec_log)
        self.click("statusClearAll")
        self.assertIn(["makoctl", "dismiss", "--all"], self.s.bridge.exec_log)
        # looking at them read the history (what is still on screen stays counted)
        self.assertEqual(self.s.ev("notifications.history.filter(n => n.id > notifications.seenId).length"), 0)

    # ---- the recording's sound, and its card hanging from the bar ----
    def test_the_recording_sound_is_chosen_first_and_a_card_hangs_while_it_runs(self):
        self.s.set_command("dxrice_capture.sh record", "__HANG__")
        self.open("capture")
        self.click("recordSound:desktop")
        self.assertEqual(self.s.ev("capture.audio"), "desktop")
        self.click("statusRecordScreen")
        self.s.wait(400)
        self.s.ev("capture.recorder.stdout.read('started')")     # wf-recorder is up (the script says so)
        self.s.wait(1300)                                        # the timer counts from here
        self.assertTrue(self.s.ev("capture.recording"))
        cmd = json.loads(self.s.ev("JSON.stringify(capture.recorder.command)"))
        self.assertEqual(cmd[2:], ["record", "screen", "desktop"])
        # the panel closed for the recording: the card has grown out of the capture mark
        self.assertTrue(self.s.ev("findNamed('recordIsland').expanded"))
        self.assertGreater(self.s.ev("findNamed('recordIsland').bodyHeight"), 40)
        self.assertEqual(self.s.ev("findNamed('recordingSound').text"), "with desktop sound")
        ind = self.centre("barIndicator:capture")
        body = json.loads(self.s.ev("(function(){ const b = findNamed('recordIslandBody'); const p = b.mapToItem(null, b.width/2, 0);"
                                    " return JSON.stringify([p.x, p.y]); })()"))
        self.assertLess(abs(body[0] - ind[0]), 60, "the card doesn't hang from the capture mark")
        self.assertEqual(self.s.input_owner(*self.centre("recordingStop")), "TopBar", "Stop takes no clicks")
        # the right section's panel opening tucks it away
        self.open("network")
        self.assertFalse(self.s.ev("findNamed('recordIsland').expanded"))
        self.s.ev("panels.closeCurrent()")
        self.s.wait(900)
        self.s.bridge.exec_log.clear()
        self.click("recordingStop")
        stops = [e for e in self.execs("sh") if e[1].endswith("dxrice_capture.sh")]
        self.assertEqual([e[2:] for e in stops], [["stop"]])

    def test_choosing_a_region_is_not_recording_yet_and_can_be_cancelled(self):
        # (live: the region picker never showed, the bar counted a recording
        # that hadn't started, and Stop did nothing)
        self.s.set_command("dxrice_capture.sh record", "__HANG__")
        self.s.ev("capture.record('region')")
        self.s.wait(500)
        self.assertTrue(self.s.ev("capture.picking"))
        self.assertFalse(self.s.ev("capture.recording"), "counted as recording while the region is still being picked")
        self.assertFalse(self.s.ev("findNamed('recordIsland').expanded"))
        self.open("capture")
        self.assertTrue(self.s.ev("findNamed('statusRecordCancel').visible"))
        self.assertFalse(self.s.ev("findNamed('statusRecordRegion').visible"))
        self.s.bridge.exec_log.clear()
        self.click("statusRecordCancel")
        stops = [e for e in self.execs("sh") if e[1].endswith("dxrice_capture.sh")]
        self.assertEqual([e[2:] for e in stops], [["stop"]])

    def test_no_card_without_a_recording(self):
        self.assertFalse(self.s.ev("findNamed('recordIsland').expanded"))
        self.assertLess(self.s.ev("findNamed('recordIsland').bodyHeight"), 0.5)

    # ---- a muted microphone shows from anywhere ----
    def test_a_muted_microphone_shows_in_the_bar(self):
        extra = "findNamed('barIndicator:audio').extraGlyph"
        self.assertEqual(self.s.ev(extra), "")
        self.s.ev("pipewire.defaultAudioSource.audio.muted = true")
        self.s.wait(50)
        self.assertNotEqual(self.s.ev(extra), "")

    # ---- bluetooth: nearby devices and pairing ----
    def bt(self, pair_out="Attempting to pair\nPairing successful\n", agent="4242\n"):
        c = self.s.bridge.commands
        c.insert(0, ("bluetoothctl devices", "Device AA:BB:CC:DD:EE:01 WH-1000XM4\nDevice AA:BB:CC:DD:EE:09 Buds Pro\n"))
        c.insert(0, ("bluetoothctl info AA:BB:CC:DD:EE:09", "Name: Buds Pro\nPaired: no\nConnected: no\n"))
        c.insert(0, ("bluetoothctl info AA:BB:CC:DD:EE:01", "Paired: yes\nConnected: yes\n"))
        c.insert(0, ("&& bluetoothctl --timeout 10 connect", pair_out))
        c.insert(0, ("pgrep -x blueman-applet", agent))
        self.open("bluetooth")
        self.s.wait(400)

    def test_bluetooth_lists_paired_and_nearby_apart(self):
        self.bt()
        self.assertIsNotNone(self.s.ev("findNamed('btPaired:AA:BB:CC:DD:EE:01')"))
        self.assertIsNone(self.s.ev("findNamed('btPaired:AA:BB:CC:DD:EE:09')"), "an unpaired device listed as paired")
        self.assertIsNotNone(self.s.ev("findNamed('btNearby:AA:BB:CC:DD:EE:09')"))

    def test_bluetooth_searches_for_a_while_then_pairs_trusts_and_connects(self):
        self.bt()
        self.s.bridge.run_log.clear()
        self.click("btScan")
        self.s.wait(200)
        self.assertIn(["bluetoothctl", "--timeout", "12", "scan", "on"], self.s.bridge.run_log)
        self.s.ev("findNamed('btNearby:AA:BB:CC:DD:EE:09').actionClicked()")
        self.s.wait(300)
        pairs = [r for r in self.s.bridge.run_log if r[:2] == ["sh", "-c"] and "pair" in r[2]]
        self.assertEqual(len(pairs), 1)
        self.assertIn("trust", pairs[0][2])
        self.assertIn("connect", pairs[0][2])
        self.assertEqual(pairs[0][-1], "AA:BB:CC:DD:EE:09")
        self.assertFalse(self.s.ev("findNamed('btNote').visible && findNamed('btNote').text.indexOf('PIN') >= 0"))

    def test_a_pairing_that_needs_a_pin_without_an_agent_says_so(self):
        self.bt(pair_out="Attempting to pair\nFailed to pair: org.bluez.Error.AuthenticationFailed\n", agent="")
        self.s.ev("findNamed('btNearby:AA:BB:CC:DD:EE:09').actionClicked()")
        self.s.wait(300)
        note = self.s.ev("findNamed('btNote').text")
        self.assertTrue(self.s.ev("findNamed('btNote').visible"))
        self.assertIn("blueman-applet", note)

    # ---- performance: the GPU's own readings and a ping ----
    def test_performance_shows_vram_gpu_power_and_ping(self):
        c = self.s.bridge.commands
        c.insert(0, ("for h in /sys/class/hwmon", "vram=/fake/gpu\ngpupower=/fake/hwmon/power1_average\ngpuclock=/fake/hwmon/freq1_input\n"))
        c.insert(0, ("ping -n -c 1 -W 2 1.1.1.1", "64 bytes from 1.1.1.1: icmp_seq=1 ttl=57 time=38.6 ms\n"))
        f = self.s.bridge.files
        f["/fake/gpu/mem_info_vram_used"] = "1073741824\n"
        f["/fake/gpu/mem_info_vram_total"] = "4294967296\n"
        f["/fake/hwmon/power1_average"] = "4000000\n"
        f["/fake/hwmon/freq1_input"] = "1500000000\n"
        self.open("performance")
        self.s.wait(2500)
        self.assertEqual(self.s.ev("findNamed('statusVram').value"), "1.0 / 4.0 GiB")
        self.assertEqual(self.s.ev("findNamed('statusGpuPower').value"), "4 W · 1500 MHz")
        self.assertEqual(self.s.ev("findNamed('statusPing').value"), "39 ms  1.1.1.1")
        # a ping host of "" turns it off
        self.s.ev("theme.data = Object.assign({}, theme.data, { ping_host: '' })")
        self.s.wait(100)
        self.assertFalse(self.s.ev("findNamed('statusPing').visible"))

    def test_without_those_sources_nothing_is_made_up(self):
        self.open("performance")
        self.s.wait(1500)
        self.assertFalse(self.s.ev("findNamed('statusVram').visible"))
        self.assertFalse(self.s.ev("findNamed('statusGpuPower').visible"))
        self.assertIn(self.s.ev("findNamed('statusPing').value").split()[0], ("no", "…"))


    # ---- the battery's state, named plainly ----
    def test_a_charger_holding_the_battery_reads_plugged_in(self):
        # (live: plugged in at 97% with a charge limit, the kernel says "Not
        # charging", and the bar and widgets said "not charging" as if unplugged)
        self.s.ev("battery.path = '/sys/class/power_supply/BAT1'; battery.percent = 97; battery.status = 'Not charging'")
        self.s.wait(50)
        self.assertEqual(self.s.ev("battery.label"), "plugged in")
        self.assertEqual(self.s.ev("findNamed('barIndicator:power').glyph"), "\U000f0084", "no plug on the bar's battery")
        for status, label in (("Charging", "charging"), ("Full", "full"), ("Discharging", "on battery")):
            self.s.ev(f"battery.status = '{status}'")
            self.assertEqual(self.s.ev("battery.label"), label)
        self.assertEqual(self.s.ev("findNamed('barIndicator:power').glyph"), "\U000f0079")

    # ---- which indicators the bar shows (Settings > Top bar) ----
    def test_indicators_can_be_hidden_but_a_recording_still_shows(self):
        vis = lambda n: self.s.ev(f"findNamed('barIndicator:{n}').visible")  # noqa: E731
        self.assertTrue(vis("bluetooth"))
        self.s.ev("theme.data = Object.assign({}, theme.data, { bar_show_bluetooth: false, bar_show_capture: false })")
        self.s.wait(100)
        self.assertFalse(vis("bluetooth"))
        self.assertFalse(vis("capture"))
        self.assertEqual(self.s.ev("findNamed('barIndicator:bluetooth').width"), 0)
        self.assertTrue(vis("dashboard"), "the Dashboard can't be hidden: it leads to everything")
        self.s.set_command("dxrice_capture.sh record", "__HANG__")
        self.s.ev("capture.record('screen')")
        self.s.wait(400)
        self.s.ev("capture.recorder.stdout.read('started')")
        self.s.wait(200)
        self.assertTrue(vis("capture"), "a running recording must show its time even when capture is hidden")

    def test_the_choice_is_in_settings(self):
        self.s.ev("panels.open('theme')")
        self.s.wait(800)
        te = "surfaces().filter(w => _name(w).indexOf('ThemeEditor') === 0)[0]"
        self.s.ev(f"{te}.currentCategory = 'experience'")
        self.s.wait(600)
        self.assertIsNotNone(self.s.ev("findNamed('toggleChip:bar_show_bluetooth')"))
        self.assertIsNotNone(self.s.ev("findNamed('barHoverOpenSwitch')"))
        self.assertIn("bar_show_bluetooth", self.s.ev(f"{te}.allKeys().join(',')").split(","))


class CaptureScriptTest(unittest.TestCase):
    """scripts/dxrice_capture.sh against fake grim/slurp/wf-recorder/wl-copy/
    notify-send: the files land where the keybinds put them, a cancelled
    region does nothing, and `stop` ends a recording so the file is kept."""

    def run_script(self, *args, slurp_out="10,20 300x200", env_extra=None, wait=True):
        import os
        import subprocess
        import tempfile
        tmp = Path(tempfile.mkdtemp())
        bin_ = tmp / "bin"
        bin_.mkdir()
        log = tmp / "calls"
        fakes = {
            "grim": 'echo "grim $*" >> "$LOG"; for a; do last="$a"; done; echo png > "$last"',
            "slurp": ('trap "exit 1" TERM; while :; do sleep 0.05; done' if slurp_out == "__WAIT__"
                      else f'[ -n "{slurp_out}" ] && echo "{slurp_out}" || exit 1'),
            "wl-copy": 'cat > /dev/null; echo wl-copy >> "$LOG"',
            "notify-send": 'echo "notify-send $*" >> "$LOG"',
            "pactl": '[ "$1" = get-default-sink ] && echo alsa_output.hdmi; [ "$1" = get-default-source ] && echo alsa_input.mic; true',
            "wf-recorder": 'echo "wf-recorder $*" >> "$LOG"; f=""; while [ $# -gt 0 ]; do [ "$1" = -f ] && f="$2"; shift; done;'
                           ' trap \'echo video > "$f"; exit 0\' INT TERM; while :; do sleep 0.05; done',
        }
        for name, body in fakes.items():
            p = bin_ / name
            p.write_text("#!/bin/sh\n" + body + "\n")
            p.chmod(0o755)
        env = {**os.environ, "HOME": str(tmp / "home"), "XDG_RUNTIME_DIR": str(tmp / "run"),
               "PATH": f"{bin_}:/usr/bin:/bin", "LOG": str(log)}
        (tmp / "run").mkdir()
        env.update(env_extra or {})
        script = Path(__file__).resolve().parents[2] / "scripts" / "dxrice_capture.sh"
        if wait:
            r = subprocess.run(["sh", str(script), *args], env=env, capture_output=True, text=True, timeout=20)
            return tmp, r, log
        return tmp, subprocess.Popen(["sh", str(script), *args], env=env), log, env, script

    def test_a_region_screenshot_is_saved_and_copied(self):
        tmp, r, log = self.run_script("shot", "region")
        self.assertEqual(r.returncode, 0, r.stderr)
        shots = list((tmp / "home" / "Pictures" / "Screenshots").glob("*.png"))
        self.assertEqual(len(shots), 1)
        calls = log.read_text()
        self.assertIn("grim -g 10,20 300x200", calls)
        self.assertIn("wl-copy", calls)
        self.assertIn("Screenshot saved", calls)

    def test_slurp_never_waits_on_a_pipe(self):
        # slurp reads preset boxes from a stdin that isn't a terminal and shows
        # nothing until it ends; from the shell that stdin was an open pipe
        src = (Path(__file__).resolve().parents[2] / "scripts" / "dxrice_capture.sh").read_text()
        self.assertIn("slurp < /dev/null", src)

    def test_stop_cancels_a_region_still_being_picked(self):
        import time
        tmp, proc, log, env, script = self.run_script("record", "region", wait=False,
                                                      slurp_out="__WAIT__")
        pick = tmp / "run" / "dxrice" / "recording.pick"
        for _ in range(100):
            if pick.exists():
                break
            time.sleep(0.05)
        self.assertTrue(pick.exists(), "the pick wasn't recorded")
        import subprocess
        subprocess.run(["sh", str(script), "stop"], env=env, timeout=10)
        self.assertNotEqual(proc.wait(timeout=10), 0, "a cancelled pick must record nothing")
        self.assertFalse((log.exists() and "wf-recorder" in log.read_text()))

    def test_a_cancelled_region_does_nothing(self):
        tmp, r, log = self.run_script("shot", "region", slurp_out="")
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse(log.exists() and "grim" in log.read_text())

    def test_the_script_going_away_ends_its_recording_too(self):
        # the shell restarting mid-recording: no recorder left running unseen
        import signal
        import time
        tmp, proc, log, env, script = self.run_script("record", "screen", wait=False)
        pid_file = tmp / "run" / "dxrice" / "recording.pid"
        for _ in range(100):
            if pid_file.exists():
                break
            time.sleep(0.05)
        rec = int(pid_file.read_text())
        time.sleep(0.2)
        proc.send_signal(signal.SIGTERM)
        proc.wait(timeout=10)
        time.sleep(0.3)
        self.assertFalse(Path(f"/proc/{rec}").exists() and "wf-recorder" in Path(f"/proc/{rec}/cmdline").read_text(errors="ignore"),
                         "the recorder outlived the script")
        self.assertEqual(len(list((tmp / "home" / "Videos" / "Recordings").glob("*.mp4"))), 1, "the file was not finished")

    def test_a_recording_with_desktop_sound_records_the_outputs_monitor(self):
        import time
        tmp, proc, log, env, script = self.run_script("record", "screen", "desktop", wait=False)
        for _ in range(100):
            if log.exists() and "wf-recorder" in log.read_text():
                break
            time.sleep(0.05)
        proc.terminate()
        proc.wait(timeout=10)
        self.assertIn("--audio=alsa_output.hdmi.monitor", log.read_text())

    def test_stop_ends_a_recording_and_keeps_the_file(self):
        import subprocess
        import time
        tmp, proc, log, env, script = self.run_script("record", "screen", wait=False)
        pid_file = tmp / "run" / "dxrice" / "recording.pid"
        for _ in range(100):
            if pid_file.exists():
                break
            time.sleep(0.05)
        self.assertTrue(pid_file.exists(), "no recording started")
        time.sleep(0.2)
        subprocess.run(["sh", str(script), "stop"], env=env, timeout=10)
        self.assertEqual(proc.wait(timeout=10), 0)
        videos = list((tmp / "home" / "Videos" / "Recordings").glob("*.mp4"))
        self.assertEqual(len(videos), 1)
        self.assertIn("Recording saved", log.read_text())
        self.assertFalse(pid_file.exists())


if __name__ == "__main__":
    unittest.main(verbosity=1)
