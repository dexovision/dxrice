#!/usr/bin/env bash
# scripts/dxrice_launch.sh, against mocked systemd-run/systemctl: what it
# asks systemd for, that the app's arguments arrive intact, and that it
# falls back to running the app directly when there is no user manager.
# Nothing here talks to a real systemd (see
# dxrice_test_launch_systemd.sh for that).
#
#   bash scripts/dxrice_test_launch.sh
set -uo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LAUNCH="$REPO_DIR/scripts/dxrice_launch.sh"
SANDBOX="$(mktemp -d)"
trap 'rm -rf "$SANDBOX"' EXIT

FAILED=0
assert() {
    if [ "$2" = "1" ]; then echo "  [PASS] $1"; else echo "  [FAIL] $1"; FAILED=1; fi
}
yes_if() { if eval "$1"; then echo 1; else echo 0; fi; }

LOG="$SANDBOX/log"
mkdir -p "$LOG"
# A minimal PATH: only what the launcher needs, so "systemd-run is not
# installed" can be modelled by leaving it out.
base_bin() {
    local d="$SANDBOX/$1"
    mkdir -p "$d"
    for tool in sh tr cut; do ln -sf "$(command -v $tool)" "$d/$tool"; done
    # The "app": records its argv, one argument per line.
    cat > "$d/fake-app" <<EOF
#!/bin/sh
for a in "\$@"; do printf '%s\n' "\$a"; done > "$LOG/app-args"
EOF
    chmod +x "$d/fake-app"
    echo "$d"
}

WITH_SYSTEMD=$(base_bin with-systemd)
# systemd-run: records its own arguments, then (like the real --scope) runs
# the command after `--`.
cat > "$WITH_SYSTEMD/systemd-run" <<EOF
#!/bin/sh
printf '%s\n' "\$@" > "$LOG/systemd-run-args"
while [ "\$1" != "--" ]; do shift; done
shift
exec "\$@"
EOF
cat > "$WITH_SYSTEMD/systemctl" <<EOF
#!/bin/sh
read rc < "$LOG/systemctl-rc"
exit "\$rc"
EOF
chmod +x "$WITH_SYSTEMD/systemd-run" "$WITH_SYSTEMD/systemctl"
NO_SYSTEMD=$(base_bin no-systemd)

launch() {
    local bin="$1"; shift
    rm -f "$LOG/app-args" "$LOG/systemd-run-args"
    env -i PATH="$bin" "$bin/sh" "$LAUNCH" "$@" > "$LOG/out" 2>&1
    echo $? > "$LOG/rc"
}
ran_args() { cat "$LOG/app-args" 2>/dev/null; }

echo "=== with a systemd user manager: the app gets its own scope ==="

echo 0 > "$LOG/systemctl-rc"
launch "$WITH_SYSTEMD" dock fake-app --title='My Cool App' "two words" ""
assert "systemd-run was used" "$(yes_if "[ -s '$LOG/systemd-run-args' ]")"
assert "as a user scope, collected on exit, in app.slice" \
    "$(yes_if "grep -qx -- '--user' '$LOG/systemd-run-args' && grep -qx -- '--scope' '$LOG/systemd-run-args' && grep -qx -- '--collect' '$LOG/systemd-run-args' && grep -qx -- '--slice=app.slice' '$LOG/systemd-run-args'")"
assert "named app-dxrice-<name>-<pid>.scope (XDG launched-app naming)" \
    "$(yes_if "grep -Eqx -- '--unit=app-dxrice-dock-[0-9]+' '$LOG/systemd-run-args'")"
assert "every argument reaches the app intact (spaces, quotes, empty)" \
    "$(yes_if "[ \"\$(ran_args)\" = \"\$(printf '%s\n' '--title=My Cool App' 'two words' '')\" ]")"

launch "$WITH_SYSTEMD" 'my app/../x;rm' fake-app ok
assert "a label is reduced to characters valid in a unit name" \
    "$(yes_if "grep -Eqx -- '--unit=app-dxrice-my_app____x_rm-[0-9]+' '$LOG/systemd-run-args'")"

echo "=== no user manager: the app still starts, directly ==="

echo 1 > "$LOG/systemctl-rc"
launch "$WITH_SYSTEMD" dock fake-app hello
assert "user bus unreachable: systemd-run not used" "$(yes_if "[ ! -e '$LOG/systemd-run-args' ]")"
assert "...and the app ran with its arguments" "$(yes_if "[ \"\$(ran_args)\" = hello ]")"

launch "$NO_SYSTEMD" dock fake-app hello
assert "systemd-run not installed: the app ran directly" "$(yes_if "[ \"\$(ran_args)\" = hello ]")"

echo "=== misuse ==="

launch "$NO_SYSTEMD" dock
assert "a name without a command is refused (exit 2)" "$(yes_if "[ \$(cat '$LOG/rc') = 2 ]")"

echo ""
if [ "$FAILED" = "1" ]; then echo "FAILED"; exit 1; fi
echo "All assertions passed."
exit 0
