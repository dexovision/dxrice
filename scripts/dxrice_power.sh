#!/bin/sh
# Power actions for the Quick Settings panel (Quickshell and GTK), on
# systemd-logind or elogind.
#
#   dxrice_power.sh reboot | poweroff
#   dxrice_power.sh inhibit      hold an idle/sleep inhibitor until killed
#
# With systemd as init, systemctl does it. Otherwise (e.g. OpenRC with
# elogind, Gentoo's default desktop setup) elogind's loginctl offers the
# same reboot/poweroff verbs, and elogind-inhibit replaces systemd-inhibit.
# `inhibit` execs the inhibitor, so killing this process releases it.
set -u

case "${1:-}" in
    reboot|poweroff)
        if [ -d /run/systemd/system ] && command -v systemctl >/dev/null 2>&1; then
            exec systemctl "$1"
        fi
        exec loginctl "$1"
        ;;
    inhibit)
        for tool in systemd-inhibit elogind-inhibit; do
            if command -v "$tool" >/dev/null 2>&1; then
                exec "$tool" --what=idle:sleep --who=DXrice --why="Quick Settings Keep Awake" sleep infinity
            fi
        done
        echo "dxrice_power.sh: neither systemd-inhibit nor elogind-inhibit is installed" >&2
        exit 1
        ;;
    *)
        echo "usage: dxrice_power.sh reboot|poweroff|inhibit" >&2
        exit 2
        ;;
esac
