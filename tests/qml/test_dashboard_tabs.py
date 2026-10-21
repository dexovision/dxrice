#!/usr/bin/env python3
"""Quick Settings' Performance and Media tabs: real readings with their
real history, honest missing states, and media controls that drive the
player.

    python3 tests/qml/test_dashboard_tabs.py
"""
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

PLAYER = """({ trackTitle: 'Blue in Green', trackArtist: 'Miles Davis', trackArtUrl: '', isPlaying: true,
    identity: 'Spotify', metadata: { 'xesam:album': 'Kind of Blue' }, volumeSupported: true, volume: 0.7,
    positionSupported: true, lengthSupported: true, length: 337, position: 112,
    shuffleSupported: true, shuffle: false, loopSupported: true, loopState: 0, calls: [],
    togglePlaying: function() { this.calls.push('toggle'); }, next: function() {}, previous: function() {},
    positionChanged: function() {} })"""


def inside(name, child):
    """The first descendant of findNamed(name) whose objectName is `child`."""
    return (f"(function(){{ const st = [findNamed('{name}')]; while (st.length) {{ const it = st.pop(); if (!it) continue;"
            f" if (it.objectName === '{child}') return it; for (let k = 0; k < it.children.length; k++) st.push(it.children[k]); }}"
            f" return null; }})()")


class PerformanceTabTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.s = Scene(width=1920, height=1080)
        cls.s.ev("panels.open('quicksettings')")
        cls.s.wait(900)
        cls.s.ev("findPanel('currentTab').currentTab = 'performance'")
        cls.s.wait(5000)          # a few real samples

    @classmethod
    def tearDownClass(cls):
        cls.s.close()

    def test_four_readings_and_the_footer(self):
        for tile in ("cpu", "gpu", "mem", "net"):
            self.assertIsNotNone(self.s.ev(f"findNamed('perf:{tile}')"), tile)
        self.assertRegex(self.s.ev("findNamed('perfStorage').text"), r"GB")
        self.assertRegex(self.s.ev("findNamed('perfUptime').text"), r"^up .*load \d+\.\d\d$")

    def test_history_is_the_samples_taken_nothing_more(self):
        n = self.s.ev("perf.cpuHistory.length")
        self.assertGreaterEqual(n, 3)
        bars = self.s.ev(f"(function(){{ const g = {inside('perf:cpu', 'perfGraph')}; let k = 0;"
                         " for (let i = 0; i < g.children.length; i++) if (g.children[i].has) k++; return k; })()")
        self.assertEqual(bars, n)

    def test_a_gpu_without_a_source_says_so_and_draws_no_graph(self):
        if self.s.ev("perf.gpuAvailable"):
            self.skipTest("the harness found a GPU source")
        self.assertEqual(self.s.ev(f"{inside('perf:gpu', 'perfValue')}.text"), "n/a")
        self.assertFalse(self.s.ev(f"{inside('perf:gpu', 'perfGraph')}.visible"))
        self.assertEqual(self.s.ev("perf.gpuHistory.length"), 0)

    def test_a_temperature_shows_where_there_is_a_sensor_and_heat_is_accented(self):
        t = inside("perf:cpu", "perfTemp")
        self.s.ev("perf._cpuTempC = 61")
        self.assertTrue(self.s.ev(f"{t}.visible"))
        self.assertEqual(self.s.ev(f"{t}.text"), "61°C")
        self.s.ev("perf._cpuTempC = 92")
        self.assertEqual(self.s.ev(f"{t}.color.toString()"), self.s.ev("theme.accent.toString()"))
        self.s.ev("perf._cpuTempC = -1")
        self.assertFalse(self.s.ev(f"{t}.visible"))


class ToggleStateTest(unittest.TestCase):
    def scene(self, bt="Controller AA:BB:CC:DD:EE:00 (public)\n\tPowered: yes\n"):
        def setup(bridge):
            bridge.commands.insert(0, ("bluetoothctl show", bt))
        s = Scene(width=1920, height=1080, setup=setup)
        s.ev("panels.open('quicksettings')")
        s.wait(900)
        return s

    def test_a_toggle_is_pending_until_the_system_says_so(self):
        s = self.scene()
        try:
            qs = "findPanel('currentTab')"
            s.set_command("nmcli radio wifi", "disabled\n")      # the radio really turns off
            s.ev(f"{qs}.setWifi(false)")
            self.assertTrue(s.ev("findNamed('toggle:wifi').pending"))
            self.assertFalse(s.ev("findNamed('toggle:wifi').active"))
            s.wait(1200)                                             # the read-back
            self.assertFalse(s.ev("findNamed('toggle:wifi').pending"))
            self.assertFalse(s.ev(f"{qs}.wifiEnabled"))
            self.assertIn(["nmcli", "radio", "wifi", "off"], s.bridge.exec_log)
        finally:
            s.close()

    def test_a_switch_the_system_refused_shows_the_real_state(self):
        s = self.scene()
        try:
            qs = "findPanel('currentTab')"
            s.set_command("nmcli radio wifi", "enabled\n")       # it stayed on (e.g. rfkill)
            s.ev(f"{qs}.setWifi(false)")
            s.wait(1200)
            self.assertTrue(s.ev(f"{qs}.wifiEnabled"))
            self.assertTrue(s.ev("findNamed('toggle:wifi').active"))
        finally:
            s.close()

    def test_pending_never_sticks_when_the_read_back_never_comes(self):
        s = self.scene()
        try:
            s.set_command("nmcli radio wifi", "__NOSTART__")
            s.ev("findPanel('currentTab').setWifi(false)")
            self.assertTrue(s.ev("findNamed('toggle:wifi').pending"))
            s.wait(3400)
            self.assertFalse(s.ev("findNamed('toggle:wifi').pending"), "still pulsing after the timeout")
        finally:
            s.close()

    def test_no_bluetooth_adapter_dims_the_tile_and_it_switches_nothing(self):
        s = self.scene(bt="No default controller available\n")
        try:
            t = "findNamed('toggle:bluetooth')"
            self.assertFalse(s.ev(f"{t}.available"))
            self.assertLess(s.ev(f"{t}.opacity"), 0.6)
            self.assertEqual(s.ev(f"{t}.label"), "No Bluetooth")
            s.bridge.exec_log.clear()
            s.ev("findPanel('currentTab').setBluetooth(true)")
            self.assertEqual([c for c in s.bridge.exec_log if c and c[0] == "bluetoothctl"], [])
        finally:
            s.close()


class TabMotionTest(unittest.TestCase):
    def test_a_tab_change_slides_in_from_the_side_it_was_picked_on(self):
        s = Scene(width=1920, height=1080)
        try:
            s.ev("panels.open('quicksettings')")
            s.wait(900)
            qs = "findPanel('currentTab')"
            rise = f"(function(){{ const l = {inside('statusIsland', 'qsPaneLoader')}; return l ? l.transform[0].x : null; }})()"
            for tab, sign in (("performance", 1), ("media", -1), ("overview", -1), ("media", 1)):
                s.ev(f"{qs}.currentTab = '{tab}'")
                s.wait(25)
                x = s.ev(rise)
                self.assertIsNotNone(x)
                self.assertGreater(x * sign, 4, f"to {tab}: started at {x}")
                s.wait(700)
                self.assertAlmostEqual(s.ev(rise), 0, delta=0.01)
        finally:
            s.close()


class MediaTabTest(unittest.TestCase):
    def setUp(self):
        self.s = Scene(width=1920, height=1080)
        self.s.ev(f"mpris.players = {{ values: [{PLAYER}] }}")
        self.s.ev("panels.open('quicksettings')")
        self.s.wait(900)
        self.s.ev("findPanel('currentTab').currentTab = 'media'")
        self.s.wait(900)

    def tearDown(self):
        self.s.close()

    def test_the_player_is_shown_with_its_source_title_and_album(self):
        self.assertEqual(self.s.ev("findNamed('mediaSource').text"), "SPOTIFY")
        self.assertEqual(self.s.ev("findNamed('mediaTitle').text"), "Blue in Green")
        self.assertTrue(self.s.ev("findNamed('mediaGround').visible"))

    def test_the_play_button_drives_the_player(self):
        import json
        pos = json.loads(self.s.ev("(function(){ const b = findNamed('mediaPlay'); const p = b.mapToItem(null, b.width/2, b.height/2); return JSON.stringify([p.x, p.y]); })()"))
        self.s.click(int(pos[0]), int(pos[1]))
        self.s.wait(100)
        self.assertEqual(self.s.ev("mpris.players.values[0].calls.join(',')"), "toggle")

    def test_a_new_track_slides_its_words_in(self):
        self.s.ev(f"mpris.players = {{ values: [Object.assign({PLAYER}, {{ trackTitle: 'So What' }})] }}")
        self.s.wait(30)
        mid = self.s.ev("findNamed('mediaTitle').parent.slide")
        self.s.wait(800)
        self.assertGreater(mid, 0, "no slide on a track change")
        self.assertEqual(self.s.ev("findNamed('mediaTitle').parent.slide"), 0)
        self.assertEqual(self.s.ev("findNamed('mediaTitle').text"), "So What")

    def test_with_no_player_the_ground_is_gone(self):
        self.s.ev("mpris.players = { values: [] }")
        self.s.wait(400)
        self.assertFalse(self.s.ev("findNamed('mediaGround').visible"))


if __name__ == "__main__":
    unittest.main()
