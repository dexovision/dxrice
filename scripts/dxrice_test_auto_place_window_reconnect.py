#!/usr/bin/env python3
"""Regression test for dxrice_auto_place_window.py's socket2 reconnect
handling.

Found during a full-codebase audit: `buf` (the partial-line accumulator)
and `_deferred` (windows seen fullscreen/tiled, awaiting a later state
change) were both initialized ONCE, outside main()'s reconnect loop,
instead of being reset on every fresh connection.

socket2 only ever drops when Hyprland itself restarts or crashes -- at
that point every window address this listener previously knew about is
gone. The consequence of not resetting: the first fullscreen>>/
changefloatingmode>> event after reconnecting would replay EVERY stale
deferred entry through place_new_window, which polls hyprctl for up to a
full 2 seconds per address before concluding "gone" -- stalling this
single-threaded listener for several seconds total, right when the user's
freshly-restarted desktop needs new-window placement working. A stale buf
fragment could also corrupt the parse of the first real event after
reconnecting.

This test drives the REAL main() against a local fake Hyprland socket (no
mocking of the parsing/event logic itself), with only place_new_window and
the live-gap/hyprctl dependencies it would need a real compositor for
stubbed out, and asserts on observable behavior: after a reconnect, a
window address deferred before the drop must NOT be retried.
"""
import os
import socket
import sys
import tempfile
import threading
import time
import unittest
import unittest.mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dxrice_auto_place_window as apw


class FakeHyprlandSocket2:
    """A disposable local Unix socket standing in for Hyprland's own
    socket2 event stream. accept()s one connection at a time; the test
    drives exactly when it sends data and when it closes/reopens."""

    def __init__(self):
        self.dir = tempfile.mkdtemp(prefix="dxrice-fake-hypr-")
        self.path = os.path.join(self.dir, "socket2.sock")
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server.bind(self.path)
        self.server.listen(1)
        self.conn = None

    def accept(self, timeout=5):
        self.server.settimeout(timeout)
        self.conn, _ = self.server.accept()

    def send(self, line):
        self.conn.sendall((line + "\n").encode())

    def send_partial(self, fragment):
        # No trailing newline -- simulates a line cut off mid-event right
        # as the connection drops.
        self.conn.sendall(fragment.encode())

    def drop(self):
        self.conn.close()
        self.conn = None

    def close(self):
        if self.conn:
            self.conn.close()
        self.server.close()
        import shutil
        shutil.rmtree(self.dir, ignore_errors=True)


class TestReconnectResetsState(unittest.TestCase):
    def setUp(self):
        self.fake = FakeHyprlandSocket2()
        self.place_calls = []

        def fake_place_new_window(address, workspace_id, gap):
            self.place_calls.append(address)
            # First window (deferred, never retried after reconnect in the
            # fixed version) always reports "fullscreen" (not placeable
            # yet). A second, genuinely new window after reconnect reports
            # "placed" so the test can tell the two apart.
            if address == "0xSTALE":
                return "fullscreen"
            return "placed"

        self._patches = [
            unittest.mock.patch.object(apw, "socket2_path", return_value=self.fake.path),
            unittest.mock.patch.object(apw, "live_gap", return_value=5),
            unittest.mock.patch.object(apw, "place_new_window", side_effect=fake_place_new_window),
            unittest.mock.patch.object(apw.dxrice_singleton, "claim_single_instance",
                                        return_value=unittest.mock.MagicMock()),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self.fake.close()

    def test_stale_deferred_window_is_not_retried_after_reconnect(self):
        main_thread = threading.Thread(target=apw.main, daemon=True)
        main_thread.start()

        # First connection: a window opens fullscreen (deferred), then the
        # connection drops (simulating Hyprland restarting) mid-fragment.
        self.fake.accept()
        self.fake.send("openwindow>>STALE,1,firefox,Firefox")
        time.sleep(0.3)
        self.assertIn("0xSTALE", self.place_calls, "the real event must still have been processed normally")
        self.fake.send_partial("fullscreen>>tru")  # cut off mid-line, no trailing \n
        self.fake.drop()

        # main()'s reconnect loop should notice the drop (recv() returns
        # b"") and reconnect within ~1s (its own retry sleep).
        self.fake.accept(timeout=5)

        calls_before = list(self.place_calls)
        # A fullscreen>> event for a DIFFERENT, brand-new window after
        # reconnecting. If _deferred survived the reconnect, this would
        # ALSO replay 0xSTALE through place_new_window (and block for up
        # to 2s doing it). If buf survived, the leftover "fullscreen>>tru"
        # fragment would corrupt this line's own parse.
        self.fake.send("openwindow>>NEW1,1,kitty,Kitty")
        time.sleep(0.3)

        self.assertIn("0xNEW1", self.place_calls, "the new window after reconnect must still be processed")
        stale_retries_after_reconnect = [a for a in self.place_calls[len(calls_before):] if a == "0xSTALE"]
        self.assertEqual(stale_retries_after_reconnect, [],
                          "a window deferred before a reconnect must never be replayed afterward -- "
                          "_deferred was not reset on reconnect")


if __name__ == "__main__":
    unittest.main(verbosity=2)
