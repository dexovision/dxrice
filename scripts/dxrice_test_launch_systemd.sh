#!/usr/bin/env bash
# The real systemd behaviour behind scripts/dxrice_launch.sh, end to end,
# with an isolated stand-in for dxrice-quickshell.service.
#
# A transient user service with a unique name (dxrice-test-shell-*) plays
# the shell: Restart=on-failure like the real unit, and it launches two fake
# apps (copies of sleep) the way Quickshell does -- one detached directly
# (the old way), one through dxrice_launch.sh. The test then crashes that
# service, restarts it and stops it, and checks which app survived. Only
# units and processes this test created are ever touched, and all of them
# are removed on exit. Skips (exit 0) when no systemd user manager is
# reachable.
#
#   bash scripts/dxrice_test_launch_systemd.sh
set -uo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LAUNCH="$REPO_DIR/scripts/dxrice_launch.sh"

if ! command -v systemd-run >/dev/null 2>&1 || ! systemctl --user show-environment >/dev/null 2>&1; then
    echo "SKIP: no systemd user manager reachable"
    exit 0
fi

ID="$$-$RANDOM"
UNIT="dxrice-test-shell-$ID.service"
T="$(mktemp -d)"
cleanup() {
    systemctl --user stop "$UNIT" >/dev/null 2>&1
    systemctl --user reset-failed "$UNIT" >/dev/null 2>&1
    for f in "$T"/*.pid; do [ -f "$f" ] && kill "$(cat "$f")" 2>/dev/null; done
    rm -rf "$T"
}
trap cleanup EXIT

FAILED=0
assert() {
    if [ "$2" = "1" ]; then echo "  [PASS] $1"; else echo "  [FAIL] $1"; FAILED=1; fi
}
alive() { kill -0 "$(cat "$T/$1.pid")" 2>/dev/null; }
wait_for() {  # wait_for <seconds> <shell condition>
    local i=0
    while [ "$i" -lt $(( $1 * 10 )) ]; do eval "$2" && return 0; sleep 0.1; i=$((i + 1)); done
    return 1
}

cp "$(command -v sleep)" "$T/plain-app-$ID"
cp "$(command -v sleep)" "$T/scoped-app-$ID"
# The stand-in shell: launches both apps once (not again after a restart),
# then idles like a long-running shell.
cat > "$T/fake-shell.sh" <<EOF
#!/bin/sh
if [ ! -e "$T/launched" ]; then
    touch "$T/launched"
    setsid -f sh -c 'echo \$\$ > "$T/plain.pid"; exec "$T/plain-app-$ID" 300'
    setsid -f sh -c 'echo \$\$ > "$T/scoped.pid"; exec "$LAUNCH" test-app "$T/scoped-app-$ID" 300'
fi
exec sleep 300
EOF
chmod +x "$T/fake-shell.sh"

echo "=== a stand-in shell service launches two apps ==="
systemd-run --user --quiet --unit="$UNIT" -p Restart=on-failure -p RestartSec=1 "$T/fake-shell.sh"
wait_for 5 '[ -s "$T/plain.pid" ] && [ -s "$T/scoped.pid" ] && alive plain && alive scoped'
assert "both apps started" "$( (alive plain && alive scoped) && echo 1 || echo 0)"
wait_for 3 'grep -q "app-dxrice-test-app-" "/proc/$(cat "$T/scoped.pid")/cgroup"'
assert "the directly-detached app sits in the shell service's cgroup" \
    "$(grep -q "/$UNIT\$" "/proc/$(cat "$T/plain.pid")/cgroup" && echo 1 || echo 0)"
assert "the launched app has its own app-dxrice-*.scope in app.slice" \
    "$(grep -Eq '/app\.slice/app-dxrice-test-app-[0-9]+\.scope$' "/proc/$(cat "$T/scoped.pid")/cgroup" && echo 1 || echo 0)"

echo "=== the shell crashes and systemd restarts it ==="
main=$(systemctl --user show -p MainPID --value "$UNIT")
kill -KILL "$main"
wait_for 6 '[ "$(systemctl --user show -p NRestarts --value "$UNIT")" -ge 1 ] && [ "$(systemctl --user show -p ActiveState --value "$UNIT")" = active ]'
assert "the stand-in shell was restarted" \
    "$([ "$(systemctl --user show -p NRestarts --value "$UNIT")" -ge 1 ] && echo 1 || echo 0)"
wait_for 3 '! alive plain'
assert "the directly-detached app was killed with it (the old behaviour)" "$(alive plain && echo 0 || echo 1)"
assert "the launched app survived the crash and restart" "$(alive scoped && echo 1 || echo 0)"

echo "=== the shell is stopped ==="
systemctl --user stop "$UNIT"
sleep 0.3
assert "the launched app survived the stop as well" "$(alive scoped && echo 1 || echo 0)"
kill "$(cat "$T/scoped.pid")" 2>/dev/null
wait_for 3 '! alive scoped'
wait_for 3 '! systemctl --user list-units --all --plain --no-legend "app-dxrice-test-app-*" | grep -q .'
assert "its scope is cleaned up once the app exits" \
    "$(systemctl --user list-units --all --plain --no-legend "app-dxrice-test-app-*" | grep -q . && echo 0 || echo 1)"

echo ""
if [ "$FAILED" = "1" ]; then echo "FAILED"; exit 1; fi
echo "All assertions passed."
exit 0
