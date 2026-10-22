#!/usr/bin/env python3
"""The desktop audio visualizer: cava runs only while something plays and the
setting is on, its frames become the bars, it never takes input, and a
machine without cava shows nothing.

    python3 tests/qml/test_visualizer.py
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
from test_customization import with_theme  # noqa: E402

V = "findNamed('visualizer')"
FRAME = ";".join(str(v) for v in [0, 250, 500, 1000] + [100] * 44) + ";"


def cava_runs(s):
    # cava itself, or cava started by the small shell step that writes a
    # chosen source's config first
    return [r for r in s.bridge.run_log if r and (r[0] == "cava" or (r[0] == "sh" and "exec cava -p" in " ".join(r)))]


class VisualizerTest(unittest.TestCase):
    def scene(self, frames=FRAME, **theme):
        s = Scene(width=1920, height=1080, setup=with_theme(**theme))
        s.set_command("cava -p", frames)
        return s

    def play(self, s, playing=True):
        s.ev(f"setPlayer({{ trackTitle: 'x', isPlaying: {str(playing).lower()} }})")
        s.wait(500)

    def test_nothing_runs_while_nothing_plays(self):
        s = self.scene()
        try:
            s.wait(500)
            self.assertFalse(s.ev(f"{V}.active"))
            self.assertFalse(s.ev(f"{V}.visible"))
            self.assertEqual(cava_runs(s), [])
            self.play(s, playing=False)
            self.assertEqual(cava_runs(s), [], "a paused player must not start cava")
        finally:
            s.close()

    def test_playing_starts_cava_with_the_shells_own_config(self):
        s = self.scene()
        try:
            self.play(s)
            runs = cava_runs(s)
            self.assertGreaterEqual(len(runs), 1)
            # automatic runs on the shipped config itself
            self.assertEqual(runs[0][1], "-p")
            self.assertTrue(runs[0][2].endswith("/shell/cava.conf") or runs[0][2].endswith("/cava.conf"), runs[0])
            self.assertTrue(s.ev(f"{V}.active"))
        finally:
            s.close()

    def test_a_frame_becomes_the_bars(self):
        s = self.scene()
        try:
            self.play(s)
            s.wait(300)
            # one frame (of 60 a second) takes a bar halfway up: a quick rise
            vals = json.loads(s.ev(f"JSON.stringify({V}.values.slice(0, 4))"))
            for got, want in zip(vals, [0, 0.25, 0.5, 1]):
                self.assertAlmostEqual(got, want * 0.5, places=6)
            self.assertEqual(s.ev(f"{V}.values.length"), 48)
            h = [s.ev(f"findNamed('visualizerBars').children[{i}].height") for i in (2, 3)]
            self.assertAlmostEqual(h[1] / h[0], 2.0, delta=0.1)   # 1000 is twice 500
            # drawn as it comes: no animation between cava's frames (that kept
            # the strip redrawing at the screen's rate)
            self.assertFalse(s.ev("findNamed('visualizerBars').children[3].height !== Math.max(3, findNamed('visualizer').values[3] * (findNamed('visualizer').barHeight - 8))"))
        finally:
            s.close()

    def test_lines_that_are_not_frames_are_ignored_and_values_clamped(self):
        s = self.scene()
        try:
            self.play(s)
            before = s.ev(f"{V}.values[3]")
            s.ev(f"{V}.feed('cava: warning, something')")
            self.assertEqual(s.ev(f"{V}.values[3]"), before)
            s.ev(f"{V}.values = []")
            s.ev(f"{V}.feed('2000;-5;500;')")
            self.assertEqual(json.loads(s.ev(f"JSON.stringify({V}.values)")), [0.5, 0, 0.25])
        finally:
            s.close()

    def test_a_bar_rises_quickly_and_falls_slowly(self):
        s = self.scene()
        try:
            self.play(s)
            s.ev(f"{V}.values = []")
            s.ev(f"{V}.feed('1000;')")
            up = s.ev(f"{V}.values[0]")
            s.ev(f"{V}.feed('0;')")
            down = s.ev(f"{V}.values[0]")
            self.assertAlmostEqual(up, 0.5, places=6)
            self.assertGreater(down, 0.4, "it dropped as fast as it rose")
        finally:
            s.close()

    def test_mirrored_puts_the_low_notes_in_the_middle(self):
        s = self.scene(visualizer_style="mirror")
        try:
            self.play(s)
            bars = "findNamed('visualizerBars')"
            self.assertTrue(s.ev(f"{bars}.visible"))
            n = s.ev(f"{bars}.children.length") - 1          # (the Repeater)
            self.assertEqual(s.ev(f"{bars}.children[0].band"), s.ev(f"{bars}.children[{n - 1}].band"), "not symmetrical")
            self.assertLessEqual(s.ev(f"{bars}.children[{n // 2}].band"), 1, "the middle should be the lowest band")
        finally:
            s.close()

    def test_switched_off_it_never_runs(self):
        s = self.scene(widget_visualizer=False)
        try:
            self.play(s)
            self.assertFalse(s.ev(f"{V}.active"))
            self.assertEqual(cava_runs(s), [])
        finally:
            s.close()

    def test_pausing_stops_cava_and_clears_the_bars(self):
        s = self.scene()
        try:
            self.play(s)
            s.ev("setPlayer({ trackTitle: 'x', isPlaying: false })")
            s.wait(600)
            self.assertFalse(s.ev(f"{V}.active"))
            self.assertEqual(s.ev(f"{V}.values.length"), 0)
            self.assertFalse(s.ev("findNamed('visualizerCava').running"))
        finally:
            s.close()

    def test_without_cava_it_stays_hidden(self):
        s = self.scene(frames="__NOSTART__")
        try:
            self.play(s)
            s.wait(300)
            self.assertFalse(s.ev(f"{V}.available"))
            self.assertFalse(s.ev(f"{V}.active"))
            s.wait(2500)
            self.assertEqual(len(cava_runs(s)), 1, "a missing cava must not be retried")
        finally:
            s.close()

    def test_a_cava_that_exits_after_drawing_is_started_again(self):
        s = self.scene()
        try:
            self.play(s)
            n = len(cava_runs(s))
            s.wait(2600)
            self.assertGreater(len(cava_runs(s)), n)
            self.assertTrue(s.ev(f"{V}.available"))
        finally:
            s.close()

    def test_it_is_a_strip_not_a_whole_screen_surface(self):
        s = self.scene()
        try:
            self.play(s)
            self.assertEqual(s.ev(f"{V}.implicitHeight"), s.ev(f"{V}.barHeight"))
            self.assertLess(s.ev(f"{V}.height"), 200)
        finally:
            s.close()

    def test_it_never_takes_input(self):
        s = self.scene()
        try:
            self.play(s)
            self.assertIsNone(s.input_owner(300, 1060))
        finally:
            s.close()

    def test_the_blocks_style_prints_the_spectrum(self):
        s = self.scene(visualizer_style="blocks")
        try:
            self.play(s)
            s.wait(300)
            self.assertTrue(s.ev("findNamed('visualizerBlocks').visible"))
            self.assertFalse(s.ev("findNamed('visualizerBars').visible"))
            # one frame in, halfway up (0, 0.25, 0.5, 1 -> 0, 0.125, 0.25, 0.5)
            self.assertTrue(s.ev("findNamed('visualizerBlocks').text").startswith("  ▁ ▂ ▄"))
        finally:
            s.close()


SINKS = json.dumps([{"name": "alsa_output.usb-headset", "description": "USB Headset"},
                    {"name": "alsa_output.pci-speakers", "description": "Speakers"}])
STREAMS = json.dumps([{"index": 51, "corked": False, "properties": {"application.name": "Brave", "object.serial": "1582"}},
                      {"index": 52, "corked": False, "properties": {"node.name": "java", "object.serial": "1708"}}])


class SourceTest(unittest.TestCase):
    """What the visualizer listens to, chosen in the bar's Sound section:
    automatic, one output's monitor, or one application's stream -- a real
    change of what cava reads, never a microphone."""

    def scene(self, frames=FRAME, **theme):
        themed = with_theme(**theme)

        def setup(bridge):
            themed(bridge)
            # in place before the shell loads (it looks at once)
            bridge.commands.insert(0, ("cava -p", frames))
            bridge.commands.insert(0, ("pactl -f json list sinks", SINKS))
            bridge.commands.insert(0, ("pactl -f json list sink-inputs", STREAMS))
        return Scene(width=1920, height=1080, setup=setup)

    def config(self, s):
        return s.ev(f"{V}.lastConfig")

    def saved(self, s):
        return json.loads((Path(s.bridge.config_home) / "dxrice" / "theme.json").read_text()).get("visualizer_source")

    def open_sound(self, s):
        s.ev("panels.open('status:audio', 'click')")
        s.wait(900)

    def test_the_sound_section_offers_outputs_and_apps_but_never_a_microphone(self):
        s = self.scene()
        try:
            self.open_sound(s)
            names = s.ev("(function(){ const out = []; const st = [findNamed('statusPanel')]; while (st.length) { const it = st.pop();"
                         " if (String(it.objectName).indexOf('vizSource:') === 0 && it.visible) out.push(it.objectName);"
                         " for (let k = 0; k < it.children.length; k++) st.push(it.children[k]); } return out.sort().join(','); })()").split(",")
            self.assertEqual(names, sorted(["vizSource:auto", "vizSource:monitor:alsa_output.usb-headset", "vizSource:monitor:alsa_output.pci-speakers",
                                            "vizSource:app:Brave", "vizSource:app:java"]))
            self.assertFalse(any("input" in n or "mic" in n.lower() for n in names))
            self.assertTrue(s.ev("findNamed('vizSource:auto').selected"))
        finally:
            s.close()

    def test_choosing_an_output_restarts_cava_on_its_monitor_and_is_saved(self):
        s = self.scene()
        try:
            s.ev("setPlayer({ trackTitle: 'x', isPlaying: true })")
            s.wait(500)
            self.assertIn("method = pipewire", self.config(s))
            self.assertIn("source = auto", self.config(s))
            runs = len(cava_runs(s))
            self.open_sound(s)
            s.ev("findNamed('vizSource:monitor:alsa_output.usb-headset').picked()")
            s.wait(400)
            self.assertEqual(self.saved(s), "monitor:alsa_output.usb-headset")
            self.assertIn("method = pulse", self.config(s))
            self.assertIn("source = alsa_output.usb-headset.monitor", self.config(s))
            last = cava_runs(s)[-1]
            self.assertEqual(last[:2], ["sh", "-c"], "a chosen source is started by the step that writes its config")
            self.assertIn('mkdir -p "$1"', last[2], "the directory must be made first (a fresh boot has none)")
            self.assertIn("source = alsa_output.usb-headset.monitor", last[-1])
            self.assertGreater(len(cava_runs(s)), runs, "cava wasn't restarted on the new source")
        finally:
            s.close()

    def test_an_app_is_found_by_its_stream_and_runs_without_a_media_player(self):
        s = self.scene(visualizer_source="app:java")
        try:
            s.wait(500)
            self.assertTrue(s.ev(f"{V}.active"), "a chosen app must not wait for a media player (a game has none)")
            self.assertIn("method = pipewire", self.config(s))
            self.assertIn("source = 1708", self.config(s))
            self.assertEqual(s.ev("widgetStack.visualizerState"), "ok")
        finally:
            s.close()

    def test_an_app_that_is_not_playing_is_said_and_waited_for(self):
        s = self.scene(visualizer_source="app:Spotify")
        try:
            s.wait(500)
            self.assertEqual(s.ev(f"{V}.sourceState"), "missing")
            self.assertEqual(cava_runs(s), [], "cava ran on some other source")
            self.open_sound(s)
            self.assertTrue(s.ev("findNamed('vizSource:app:Spotify').selected"), "the chosen app should stay listed")
            self.assertTrue(s.ev("findNamed('vizSourceNote').visible"))
            self.assertIn("Spotify", s.ev("findNamed('vizSourceNote').text"))
            # it starts playing: picked up on the next look
            s.set_command("pactl -f json list sink-inputs", json.dumps([{"index": 9, "corked": False,
                          "properties": {"application.name": "Spotify", "object.serial": "77"}}]))
            s.wait(3400)
            self.assertEqual(s.ev(f"{V}.sourceState"), "ok")
            self.assertIn("source = 77", self.config(s))
        finally:
            s.close()

    def test_a_source_cava_cannot_use_is_said_and_does_not_disable_the_visualizer(self):
        s = self.scene(frames="", visualizer_source="monitor:alsa_output.gone")     # cava starts, never a frame
        try:
            s.wait(800)
            self.assertEqual(s.ev(f"{V}.sourceState"), "failed")
            self.assertTrue(s.ev(f"{V}.available"), "a bad choice must not switch the visualizer off for good")
            s.ev("theme.setKeys({ visualizer_source: 'auto' })")
            s.wait(300)
            self.assertEqual(s.ev(f"{V}.sourceState"), "ok")
        finally:
            s.close()


if __name__ == "__main__":
    unittest.main()
