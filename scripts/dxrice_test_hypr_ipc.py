#!/usr/bin/env python3
"""Regression suite for dxrice_hypr_ipc.py's failure handling.

This module's entire contract is "never raise, fail quietly and let the
caller treat a failure the same as an empty/unavailable response" -- it's
called up to ~144 times/sec from the pan/drag loops in
dxrice_infinite_desktop_core.py, and a raised exception there would kill
the whole daemon mid-pan. Found during a full-codebase audit: _send's own
socket.socket() construction sat outside its try/except, so a transient
OSError there (e.g. file-descriptor exhaustion) could still escape the
"never raise" contract despite every other failure path in the function
being guarded.
"""
import os
import socket
import unittest
import unittest.mock

import dxrice_hypr_ipc as ipc


class TestSocketPathResolution(unittest.TestCase):
    def test_missing_env_vars_returns_none(self):
        with unittest.mock.patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(ipc._socket_path())

    def test_present_env_vars_builds_expected_path(self):
        with unittest.mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": "/run/user/1000",
                                                     "HYPRLAND_INSTANCE_SIGNATURE": "abc123"}):
            self.assertEqual(ipc._socket_path(), "/run/user/1000/hypr/abc123/.socket.sock")


class TestSendNeverRaises(unittest.TestCase):
    """The core contract: no matter what goes wrong, _send (and everything
    built on it) returns a quiet failure value instead of propagating."""

    def test_no_hyprland_env_returns_empty_bytes(self):
        with unittest.mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(ipc._send("j/clients"), b"")

    def test_socket_construction_failure_does_not_raise(self):
        # The exact bug: socket.socket() itself used to sit outside the
        # try/except, so a transient OSError (e.g. fd exhaustion) escaped
        # this function's "never raise" contract.
        with unittest.mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": "/run/user/1000",
                                                     "HYPRLAND_INSTANCE_SIGNATURE": "abc123"}):
            with unittest.mock.patch.object(socket, "socket", side_effect=OSError("simulated fd exhaustion")):
                try:
                    result = ipc._send("j/clients")
                except OSError:
                    self.fail("_send must never raise OSError, even when socket() itself fails")
                self.assertEqual(result, b"")

    def test_connect_failure_does_not_raise(self):
        # No Hyprland running / stale socket path -- a real, common case
        # (e.g. right after a Hyprland crash, before the session fully
        # tears down the stale socket file).
        with unittest.mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": "/tmp",
                                                     "HYPRLAND_INSTANCE_SIGNATURE": "nonexistent-socket-xyz"}):
            try:
                result = ipc._send("j/clients", timeout=0.2)
            except OSError:
                self.fail("_send must never raise OSError on a connect failure")
            self.assertEqual(result, b"")

    def test_hyprctl_json_with_no_hyprland_returns_none(self):
        with unittest.mock.patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(ipc.hyprctl_json(["clients"]))

    def test_hyprctl_json_malformed_response_returns_none(self):
        with unittest.mock.patch.object(ipc, "_send", return_value=b"not valid json {{{"):
            self.assertIsNone(ipc.hyprctl_json(["clients"]))

    def test_hyprctl_json_empty_response_returns_none(self):
        with unittest.mock.patch.object(ipc, "_send", return_value=b""):
            self.assertIsNone(ipc.hyprctl_json(["clients"]))

    def test_batch_async_with_no_exprs_is_a_safe_noop(self):
        with unittest.mock.patch.object(ipc, "_send") as mock_send:
            ipc.batch_async([])
            mock_send.assert_not_called()

    def test_dispatch_async_never_raises_without_hyprland(self):
        with unittest.mock.patch.dict(os.environ, {}, clear=True):
            try:
                ipc.dispatch_async('hl.dsp.exec_cmd("echo hi")')
            except Exception as e:
                self.fail(f"dispatch_async must never raise, got {type(e).__name__}: {e}")


class TestLuaExpressionBuilders(unittest.TestCase):
    """These build literal Lua source handed to Hyprland's IPC -- a
    malformed address/path must not break the expression's syntax."""

    def test_exec_cmd_escapes_embedded_quotes(self):
        expr = ipc.exec_cmd_lua('echo "hello"')
        self.assertEqual(expr, 'hl.dsp.exec_cmd("echo \\"hello\\"")')

    def test_exec_cmd_escapes_backslashes(self):
        expr = ipc.exec_cmd_lua('C:\\path')
        self.assertIn('\\\\', expr)

    def test_move_window_exact_coerces_to_int(self):
        expr = ipc.move_window_exact_lua(10.7, 20.3, "0x123")
        self.assertIn("x = 10", expr)
        self.assertIn("y = 20", expr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
