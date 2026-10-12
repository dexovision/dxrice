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

# Test hooks (scripts/dxrice_test_polkit_agent.sh): both lists can be
# replaced so a test never sees, or starts, a real agent.
names="${DXRICE_POLKIT_AGENT_NAMES:-polkit-kde-authentication-agent-1 hyprpolkitagent
    polkit-gnome-authentication-agent-1 polkit-mate-authentication-agent-1
    lxpolkit lxqt-policykit-agent}"
# Unquoted on use, so the `*` (Debian/Ubuntu's per-architecture libexec)
# expands; a pattern matching nothing stays literal and fails -x.
candidates="${DXRICE_POLKIT_AGENT_CANDIDATES:-
    /usr/lib/polkit-kde-authentication-agent-1
    /usr/libexec/polkit-kde-authentication-agent-1
    /usr/libexec/kf6/polkit-kde-authentication-agent-1
    /usr/libexec/kf5/polkit-kde-authentication-agent-1
    /usr/lib/*-linux-gnu/libexec/polkit-kde-authentication-agent-1
    /usr/lib64/libexec/polkit-kde-authentication-agent-1
    /usr/lib/hyprpolkitagent/hyprpolkitagent
    /usr/libexec/hyprpolkitagent
    /usr/lib/polkit-gnome/polkit-gnome-authentication-agent-1
    /usr/libexec/polkit-gnome-authentication-agent-1
    /usr/lib/mate-polkit/polkit-mate-authentication-agent-1
    /usr/libexec/polkit-mate-authentication-agent-1
    /usr/bin/lxpolkit
    /usr/bin/lxqt-policykit-agent}"

# Matched on the command line's first word (the program, with or without
# its directory), not with `pgrep -x`: -x compares the kernel's process
# name, which is cut to 15 characters, so it could never match
# polkit-kde-authentication-agent-1 or three of the others -- an agent
# already running was not seen and a second one was started.
for running in $names; do
    if pgrep -u "$(id -u)" -f "^([^ ]*/)?$running( |\$)" >/dev/null 2>&1; then
        exit 0
    fi
done

for agent in $candidates; do
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
