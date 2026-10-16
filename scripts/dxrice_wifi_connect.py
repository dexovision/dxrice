#!/usr/bin/env python3
"""Joins a secured Wi-Fi network without putting the password on any
command line.

  printf '%s\\n' "$PASSWORD" | dxrice_wifi_connect.py SSID SECURITY

`nmcli device wifi connect SSID password SECRET` puts the secret in nmcli's
argv, which every local user can read in `ps` or /proc/PID/cmdline for as
long as nmcli runs (seconds, while it associates). nmcli's `--ask` is an
interactive prompt and doesn't take a piped password reliably. The supported
non-interactive way is a password file on `nmcli connection up`
(`passwd-file`, see nmcli(1)), so:

  1. the password arrives on this script's stdin, never in its own argv;
  2. a profile named after the network is created with no secret in it
     (or the existing one with that name is reused);
  3. it's brought up with `passwd-file` pointing at a 0600 file in the
     user's private runtime directory, removed as soon as nmcli exits.

NetworkManager keeps the secret in the profile, as `device wifi connect`
would, so later connections need no password. If activation fails, a
profile this script created is deleted again, so the next attempt asks for
the password afresh.

SECURITY is nmcli's SECURITY column ("WPA2", "WPA1 WPA2", "WPA3", "WEP",
"WPA2 802.1X", ...). Enterprise (802.1X) networks need more than a
password and are refused, as before.

Exit status: 0 connected, 1 failed, 2 usage or unsupported network.
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dxrice_xdg  # noqa: E402

# Seconds. Activation (associating, getting an address) takes the longest;
# the GTK app waits for this script on its UI thread, so keep the total short.
ACTIVATE_TIMEOUT = 25
QUERY_TIMEOUT = 5


def key_mgmt(security):
    """(key-mgmt, secret property) for nmcli's SECURITY column, or None."""
    words = security.upper().split()
    if "802.1X" in words:
        return None
    if "WEP" in words:
        return "none", "wep-key0"
    if words == ["WPA3"]:  # WPA3-only; a WPA2/WPA3 network also takes wpa-psk
        return "sae", "psk"
    if any(w.startswith("WPA") for w in words):
        return "wpa-psk", "psk"
    return None


def nmcli(*args, timeout=QUERY_TIMEOUT):
    return subprocess.run(["nmcli", *args], capture_output=True, text=True, timeout=timeout, check=False)


def profile_exists(name):
    r = nmcli("-t", "-f", "NAME", "connection", "show")
    return r.returncode == 0 and name in r.stdout.splitlines()


def write_passwd_file(prop, password):
    """The secret in a new 0600 file only this user can read; its path."""
    path = os.path.join(dxrice_xdg.runtime_dir(), f"wifi-secret.{os.getpid()}")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(f"802-11-wireless-security.{prop}:{password}\n")
    return path


def connect(ssid, security, password):
    mgmt = key_mgmt(security)
    if mgmt is None:
        print(f"dxrice_wifi_connect: {security or 'this'} network needs more than a password "
              "(e.g. 802.1X); set it up in nm-connection-editor.", file=sys.stderr)
        return 2
    key_mgmt_value, prop = mgmt

    created = False
    if not profile_exists(ssid):
        r = nmcli("connection", "add", "type", "wifi", "con-name", ssid, "ssid", ssid,
                  "wifi-sec.key-mgmt", key_mgmt_value)
        if r.returncode != 0:
            print(f"dxrice_wifi_connect: couldn't create a profile for {ssid}: {r.stderr.strip()}", file=sys.stderr)
            return 1
        created = True

    path = write_passwd_file(prop, password)
    try:
        r = nmcli("connection", "up", "id", ssid, "passwd-file", path, timeout=ACTIVATE_TIMEOUT)
    except subprocess.TimeoutExpired:
        r = None
    finally:
        os.unlink(path)

    if r is not None and r.returncode == 0:
        return 0
    reason = r.stderr.strip() if r is not None else "timed out"
    print(f"dxrice_wifi_connect: couldn't connect to {ssid}: {reason}", file=sys.stderr)
    if created:
        nmcli("connection", "delete", "id", ssid)
    return 1


def main(argv):
    if len(argv) != 3 or not argv[1]:
        print("usage: printf '%s\\n' PASSWORD | dxrice_wifi_connect.py SSID SECURITY", file=sys.stderr)
        return 2
    password = sys.stdin.readline().rstrip("\n")
    if not password:
        print("dxrice_wifi_connect: no password on stdin", file=sys.stderr)
        return 2
    try:
        return connect(argv[1], argv[2], password)
    except (OSError, subprocess.SubprocessError) as e:
        print(f"dxrice_wifi_connect: {type(e).__name__}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
