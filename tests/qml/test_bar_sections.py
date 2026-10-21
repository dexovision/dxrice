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
        self.s.wait(1300)
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
            "slurp": f'[ -n "{slurp_out}" ] && echo "{slurp_out}" || exit 1',
            "wl-copy": 'cat > /dev/null; echo wl-copy >> "$LOG"',
            "notify-send": 'echo "notify-send $*" >> "$LOG"',
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

    def test_a_cancelled_region_does_nothing(self):
        tmp, r, log = self.run_script("shot", "region", slurp_out="")
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse(log.exists() and "grim" in log.read_text())

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
