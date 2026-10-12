#!/bin/sh
# Starts a polkit authentication agent for the Hyprland session -- the thing
# that shows the "enter your password" dialog when an app asks for elevated
# rights (system-wide Wi-Fi profiles, pkexec, disk and package tools).
# Without one, those requests fail or hang with no prompt at all.
#
# hyprland.lua used to exec one hard-coded path, /usr/lib/polkit-kde-agent-1,
# which no package installs: Arch's polkit-kde-agent ships
# /usr/lib/polkit-kde-authentication-agent-1, and other distros and agents
# use other paths again. Probing a list of known locations instead keeps
# the right agent working on Arch and lets other setups find theirs.
#
# Never starts a second agent: if one is already running (another session
# component started it, or Hyprland was reloaded), this does nothing.

for running in polkit-kde-authentication-agent-1 hyprpolkitagent \
               polkit-gnome-authentication-agent-1 polkit-mate-authentication-agent-1 \
               lxpolkit lxqt-policykit-agent; do
    if pgrep -x -u "$(id -u)" "$running" >/dev/null 2>&1; then
        exit 0
    fi
done

for agent in \
    /usr/lib/polkit-kde-authentication-agent-1 \
    /usr/libexec/polkit-kde-authentication-agent-1 \
    /usr/lib/x86_64-linux-gnu/libexec/polkit-kde-authentication-agent-1 \
    /usr/lib/hyprpolkitagent/hyprpolkitagent \
    /usr/libexec/hyprpolkitagent \
    /usr/lib/polkit-gnome/polkit-gnome-authentication-agent-1 \
    /usr/libexec/polkit-gnome-authentication-agent-1 \
    /usr/lib/mate-polkit/polkit-mate-authentication-agent-1 \
    /usr/libexec/polkit-mate-authentication-agent-1 \
    /usr/bin/lxpolkit \
    /usr/bin/lxqt-policykit-agent; do
    if [ -x "$agent" ]; then
        exec "$agent"
    fi
done

msg="No polkit authentication agent found -- apps that need your password (pkexec, system Wi-Fi profiles, disk tools) cannot ask for it. Install polkit-kde-agent (or hyprpolkitagent)."
echo "dxrice: $msg" >&2
if command -v notify-send >/dev/null 2>&1; then
    notify-send -a DXrice -u critical "No polkit agent" "$msg"
fi
exit 1
