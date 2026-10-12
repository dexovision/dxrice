#!/bin/sh
# Starts an app the shell launches (a dock tile, the lock screen, a
# screenshot, the wallpaper after a theme Apply) in its own transient
# systemd user scope, so it is not tied to the shell's lifetime.
#
#   dxrice_launch.sh NAME COMMAND [ARG...]
#
# Quickshell runs as dxrice-quickshell.service, and everything it starts --
# even "detached" -- stays in that unit's cgroup. systemd kills a unit's
# whole cgroup when it stops, and before every Restart=on-failure restart,
# so one shell crash used to close every app opened from the dock (seen
# live: the browser, chat client, a game launcher and swaybg were all inside
# the unit). An app in its own app-dxrice-NAME-PID.scope (the XDG naming
# desktop environments use for launched apps) lives on its own instead.
#
# Falls back to running the command directly -- exactly the old behaviour --
# when there is no systemd user manager to ask (no systemd-run, or no user
# bus), so a launch never fails just because scopes aren't available.
# Short-lived helpers (nmcli, brightnessctl, ...) don't go through this:
# they end with the action anyway.

if [ "$#" -lt 2 ]; then
    echo "usage: dxrice_launch.sh NAME COMMAND [ARG...]" >&2
    exit 2
fi

# A unit name allows [A-Za-z0-9:_.\-]; anything else in the label becomes _.
name=$(printf '%s' "$1" | tr -c 'A-Za-z0-9_-' '_' | cut -c1-64)
shift

if command -v systemd-run >/dev/null 2>&1 \
    && systemctl --user show-environment >/dev/null 2>&1; then
    # --scope: systemd-run moves itself into the new scope and then execs
    # the command, so the app keeps this PID and the caller's environment.
    # --collect: the scope is cleaned up when the app exits, even with an
    # error, instead of lingering as a failed unit.
    exec systemd-run --user --scope --quiet --collect --slice=app.slice \
        --unit="app-dxrice-${name:-app}-$$" -- "$@"
fi

exec "$@"
