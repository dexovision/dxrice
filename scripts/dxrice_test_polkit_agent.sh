#!/usr/bin/env bash
# scripts/dxrice_polkit_agent.sh: sees an agent that is already running
# (whatever the length of its name), starts the first one installed
# otherwise, and says so when there is none. Only fake agents are involved:
# both of the helper's lists are replaced through its test hooks, the
# "running agents" are copies of sleep under made-up names, and
# notify-send is a recording shim -- no real agent is ever seen or started.
#
#   bash scripts/dxrice_test_polkit_agent.sh
set -uo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HELPER="$REPO_DIR/scripts/dxrice_polkit_agent.sh"
SANDBOX="$(mktemp -d)"
PIDS=()
cleanup() {
    for p in "${PIDS[@]}"; do kill "$p" 2>/dev/null; done
    rm -rf "$SANDBOX"
}
trap cleanup EXIT

FAILED=0
assert() {
    if [ "$2" = "1" ]; then echo "  [PASS] $1"; else echo "  [FAIL] $1"; FAILED=1; fi
}
yes_if() { if eval "$1"; then echo 1; else echo 0; fi; }

BIN="$SANDBOX/bin"
LOG="$SANDBOX/log"
mkdir -p "$BIN" "$LOG"
cat > "$BIN/notify-send" <<EOF
#!/bin/sh
echo "\$*" >> "$LOG/notify.log"
EOF
# The candidate agent: records that it was started, then exits.
cat > "$SANDBOX/fake-agent" <<EOF
#!/bin/sh
echo started >> "$LOG/started.log"
EOF
chmod +x "$BIN/notify-send" "$SANDBOX/fake-agent"

# Unique per run, so no real process can match them. LONG is over the
# kernel's 15-character process-name limit, like
# polkit-kde-authentication-agent-1; SHORT fits, like hyprpolkitagent.
LONG="dxrice-test-authentication-agent-$$"
SHORT="dxpk$$"
NAMES="$LONG $SHORT"

# A process whose command line starts with <path>, kept running.
run_as() {
    cp /usr/bin/sleep "$SANDBOX/$1"
    "$SANDBOX/$1" 60 &
    PIDS+=($!)
    sleep 0.2
}
stop_all() {
    for p in "${PIDS[@]}"; do kill "$p" 2>/dev/null; wait "$p" 2>/dev/null; done
    PIDS=()
}
helper() {
    : > "$LOG/started.log"; : > "$LOG/notify.log"
    env PATH="$BIN:/usr/bin:/bin" DXRICE_POLKIT_AGENT_NAMES="$NAMES" \
        DXRICE_POLKIT_AGENT_CANDIDATES="$1" sh "$HELPER" > "$LOG/out" 2>&1
    echo $? > "$LOG/rc"
}
started() { [ -s "$LOG/started.log" ]; }

echo "=== an agent that is already running is seen ==="

run_as "$LONG"
helper "$SANDBOX/fake-agent"
assert "long-named agent (comm cut to 15 chars) is seen" "$(yes_if "! started")"
assert "...and the helper exits 0" "$(yes_if "[ \$(cat '$LOG/rc') = 0 ]")"
stop_all

run_as "$SHORT"
helper "$SANDBOX/fake-agent"
assert "short-named agent is seen" "$(yes_if "! started")"
stop_all

echo "=== only the program counts, not an argument ==="

python3 -c 'import time; time.sleep(60)' "$SANDBOX/$LONG" &
PIDS+=($!)
sleep 0.2
helper "$SANDBOX/fake-agent"
assert "the name as an argument to another program is not an agent" "$(yes_if "started")"
stop_all

echo "=== nothing running: the first installed agent is started ==="

helper "$SANDBOX/missing-agent $SANDBOX/fake-agent"
assert "skips a missing candidate and starts the installed one" "$(yes_if "started")"
assert "...exiting with the agent's status" "$(yes_if "[ \$(cat '$LOG/rc') = 0 ]")"

mkdir -p "$SANDBOX/lib/aarch64-linux-gnu/libexec"
cp "$SANDBOX/fake-agent" "$SANDBOX/lib/aarch64-linux-gnu/libexec/agent"
helper "$SANDBOX/lib/*-linux-gnu/libexec/agent"
assert "per-architecture (globbed) candidate path is found" "$(yes_if "started")"

echo "=== no agent at all ==="

helper "$SANDBOX/missing-agent $SANDBOX/lib/*-nothing/agent"
assert "exits non-zero" "$(yes_if "[ \$(cat '$LOG/rc') != 0 ]")"
assert "says so on stderr" "$(yes_if "grep -q 'No polkit authentication agent' '$LOG/out'")"
assert "and as a critical notification" "$(yes_if "grep -q -- '-u critical' '$LOG/notify.log'")"

echo ""
if [ "$FAILED" = "1" ]; then
    echo "FAILED"
    exit 1
fi
echo "All assertions passed."
exit 0
