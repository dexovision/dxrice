#!/bin/sh
# Starts DXrice's long-running parts for a Hyprland session: the Quickshell
# shell and the two daemons (new-window placement, infinite-desktop panning).
# hyprland.lua runs this once at startup. Living in the checkout means a fix
# here arrives with `git pull`; the deployed hyprland.lua never needs to
# change again.
#
# With a systemd user manager and DXrice's units installed, the units are
# (re)started, so systemd restarts a crashed part and stops one that keeps
# failing. Without one (OpenRC, runit, s6, or no units), each part runs under
# a small supervisor loop with the same policy: restart after a crash, give up
# after 5 crashes within 30 seconds. A part that exits cleanly isn't restarted.
#
# Without Quickshell, the waybar bars are started instead.
#
# Does nothing once DXrice is uninstalled (no recorded checkout), so the
# autostart line left in a user's hyprland.lua stays inert.
#
#   dxrice_session.sh            start everything (from hyprland.lua)
#   dxrice_session.sh status     print how each part is running
#
# Test hooks: DXRICE_SESSION_DRY_RUN=1 prints the commands instead of running
# them; DXRICE_SUPERVISE_* tune the restart policy.
set -u

STATE_HOME="${XDG_STATE_HOME:-$HOME/.local/state}"
CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
# Per Hyprland instance: a supervisor left over from an earlier Hyprland in
# the same login (its children die with that compositor) is never mistaken
# for this session's.
RUN_DIR="${XDG_RUNTIME_DIR:-/tmp/dxrice-$(id -u)}/dxrice/${HYPRLAND_INSTANCE_SIGNATURE:-session}"

UNITS="dxrice-quickshell.service dxrice-auto-place-window.service dxrice-infinite-desktop.service"
MAX_CRASHES="${DXRICE_SUPERVISE_MAX:-5}"
WINDOW_S="${DXRICE_SUPERVISE_WINDOW:-30}"
RESTART_DELAY_S="${DXRICE_SUPERVISE_DELAY:-1}"

run() {
    if [ "${DXRICE_SESSION_DRY_RUN:-0}" = 1 ]; then
        echo "$*"
    else
        "$@"
    fi
}

# run_detached CMD...: started in its own session, output discarded
run_detached() {
    if [ "${DXRICE_SESSION_DRY_RUN:-0}" = 1 ]; then
        echo "$*"
    else
        setsid "$@" >/dev/null 2>&1 &
    fi
}

have_systemd_user() {
    command -v systemctl >/dev/null 2>&1 && systemctl --user show-environment >/dev/null 2>&1
}

units_installed() {
    for u in $UNITS; do
        [ -f "$CONFIG_HOME/systemd/user/$u" ] || return 1
    done
}

# supervise NAME CMD...: runs CMD in the background, restarting it after a
# crash. One supervisor per NAME: a second start finds the live one's pid
# file and leaves it alone.
supervise() {
    name="$1"; shift
    mkdir -p "$RUN_DIR"
    pidfile="$RUN_DIR/$name.pid"
    if [ -f "$pidfile" ] && kill -0 "$(cat "$pidfile" 2>/dev/null)" 2>/dev/null; then
        return 0
    fi
    if [ "${DXRICE_SESSION_DRY_RUN:-0}" = 1 ]; then
        echo "supervise $name: $*"
        return 0
    fi
    (
        crashes=""
        while :; do
            "$@"
            status=$?
            [ "$status" = 0 ] && break
            now=$(date +%s)
            recent=""
            for t in $crashes; do
                [ $((now - t)) -lt "$WINDOW_S" ] && recent="$recent $t"
            done
            crashes="$recent $now"
            count=$(echo "$crashes" | wc -w)
            if [ "$count" -ge "$MAX_CRASHES" ]; then
                echo "dxrice: $name crashed $count times in ${WINDOW_S}s; not restarting it again." >&2
                break
            fi
            sleep "$RESTART_DELAY_S"
        done
        rm -f "$pidfile"
    ) >>"$RUN_DIR/$name.log" 2>&1 &
    echo $! > "$pidfile"
}

start_all() {
    [ -s "$STATE_HOME/dxrice/repo_path" ] || exit 0

    if have_systemd_user && units_installed; then
        # shellcheck disable=SC2086
        run systemctl --user restart $UNITS
        return
    fi

    if command -v qs >/dev/null 2>&1; then
        supervise quickshell qs -p "$REPO/quickshell/shell.qml"
    else
        for c in config config-left config-right config-dock; do
            run_detached waybar -c "$CONFIG_HOME/waybar/$c" -s "$CONFIG_HOME/waybar/style.css"
        done
    fi
    supervise auto-place-window python3 "$REPO/scripts/dxrice_auto_place_window.py"
    supervise infinite-desktop python3 "$REPO/scripts/dxrice_infinite_desktop_core.py" 1.6
}

status() {
    if have_systemd_user && units_installed; then
        echo "systemd user units:"
        # shellcheck disable=SC2086
        systemctl --user --no-pager --plain list-units $UNITS 2>/dev/null
        return
    fi
    for name in quickshell auto-place-window infinite-desktop; do
        pidfile="$RUN_DIR/$name.pid"
        if [ -f "$pidfile" ] && kill -0 "$(cat "$pidfile")" 2>/dev/null; then
            echo "$name: running (supervisor pid $(cat "$pidfile"), log $RUN_DIR/$name.log)"
        else
            echo "$name: not running"
        fi
    done
}

case "${1:-start}" in
    start) start_all ;;
    status) status ;;
    *) echo "usage: dxrice_session.sh [start|status]" >&2; exit 2 ;;
esac
