#!/usr/bin/env bash
# dxrice_session.sh: how it starts DXrice's parts with and without a systemd
# user manager, that it does nothing once DXrice is uninstalled, and the
# supervisor's restart policy, using real (tiny) processes.
#
#   bash scripts/dxrice_test_session.sh
set -uo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SESSION="$REPO_DIR/scripts/dxrice_session.sh"
SANDBOX="$(mktemp -d)"
trap 'pkill -f "$SANDBOX" 2>/dev/null; rm -rf "$SANDBOX"' EXIT

FAILED=0
assert() {
    if [ "$2" = "1" ]; then echo "  [PASS] $1"; else echo "  [FAIL] $1"; FAILED=1; fi
}
yes_if() { if eval "$1"; then echo 1; else echo 0; fi; }

H="$SANDBOX/home"
BIN="$SANDBOX/bin"
mkdir -p "$H/.local/state/dxrice" "$H/.config/systemd/user" "$BIN" "$SANDBOX/run"

run() {  # the session script, dry-run, with a fake PATH
    env -i HOME="$H" PATH="$BIN:/usr/bin:/bin" XDG_RUNTIME_DIR="$SANDBOX/run" \
        HYPRLAND_INSTANCE_SIGNATURE=test DXRICE_SESSION_DRY_RUN=1 sh "$SESSION"
}
fake() {  # fake NAME EXIT_STATUS
    printf '#!/bin/sh\n[ "$1 $2" = "--user show-environment" ] && exit %s\necho "$*" >> "%s/%s.log"\n' \
        "$2" "$SANDBOX" "$1" > "$BIN/$1"
    chmod +x "$BIN/$1"
}

echo "=== not installed: does nothing ==="
fake systemctl 0
out="$(run)"
assert "no recorded checkout -> no output, nothing started" "$(yes_if "[ -z '$out' ]")"

echo "=== systemd user manager with DXrice's units ==="
echo "$REPO_DIR" > "$H/.local/state/dxrice/repo_path"
for u in dxrice-quickshell.service dxrice-auto-place-window.service dxrice-infinite-desktop.service; do
    : > "$H/.config/systemd/user/$u"
done
out="$(run)"
assert "restarts the three units" \
    "$(yes_if "[ '$out' = 'systemctl --user restart dxrice-quickshell.service dxrice-auto-place-window.service dxrice-infinite-desktop.service' ]")"

echo "=== no systemd (OpenRC and friends) ==="
rm -f "$BIN/systemctl"
printf '#!/bin/sh\n' > "$BIN/qs"; chmod +x "$BIN/qs"
out="$(run)"
assert "supervises Quickshell" "$(yes_if "grep -q '^supervise quickshell: qs -p $REPO_DIR/quickshell/shell.qml' <<<'$out'")"
assert "supervises the placement daemon" "$(yes_if "grep -q '^supervise auto-place-window: python3 .*dxrice_auto_place_window.py' <<<'$out'")"
assert "supervises the panning daemon" "$(yes_if "grep -q '^supervise infinite-desktop: python3 .*dxrice_infinite_desktop_core.py 1.6' <<<'$out'")"

echo "=== systemd present but no units installed ==="
fake systemctl 0
rm -f "$H/.config/systemd/user/"*.service
out="$(run)"
assert "falls back to supervising" "$(yes_if "grep -q '^supervise quickshell' <<<'$out' && ! grep -q 'restart' <<<'$out'")"

echo "=== no Quickshell: the waybar bars ==="
rm -f "$BIN/qs"
out="$(run)"
assert "starts the four waybar bars" "$(yes_if "[ \$(grep -c '^waybar -c' <<<'$out') = 4 ]")"
assert "...and no Quickshell" "$(yes_if "! grep -q 'supervise quickshell' <<<'$out'")"

echo "=== the supervisor, for real ==="
# A copy of the script whose parts are tiny shell loops, so the real
# supervisor runs without Quickshell or Python daemons.
STUB="$SANDBOX/stubrepo"
mkdir -p "$STUB/scripts" "$STUB/quickshell"
sed -e 's#supervise quickshell qs -p "$REPO/quickshell/shell.qml"#supervise quickshell sh "$REPO/part.sh" quickshell#' \
    -e 's#supervise auto-place-window python3 "$REPO/scripts/dxrice_auto_place_window.py"#supervise auto-place-window sh "$REPO/part.sh" place#' \
    -e 's#supervise infinite-desktop python3 "$REPO/scripts/dxrice_infinite_desktop_core.py" 1.6#supervise infinite-desktop sh "$REPO/part.sh" pan#' \
    "$SESSION" > "$STUB/scripts/dxrice_session.sh"
# each part records its start, then crashes (or exits cleanly for "pan")
cat > "$STUB/part.sh" <<EOF
#!/bin/sh
echo start >> "$SANDBOX/\$1.starts"
[ "\$1" = pan ] && exit 0
sleep 0.05
exit 3
EOF
printf '#!/bin/sh\n' > "$BIN/qs"; chmod +x "$BIN/qs"
rm -f "$BIN/systemctl"
mkdir -p "$SANDBOX/run/hypr/real" "$SANDBOX/run/hypr/gone"
env -i HOME="$H" PATH="$BIN:/usr/bin:/bin" XDG_RUNTIME_DIR="$SANDBOX/run" HYPRLAND_INSTANCE_SIGNATURE=real \
    DXRICE_SUPERVISE_DELAY=0.05 DXRICE_SUPERVISE_MAX=3 sh "$STUB/scripts/dxrice_session.sh"
sleep 2
assert "a crashing part is restarted, then given up on after 3 crashes" \
    "$(yes_if "[ \$(wc -l < '$SANDBOX/quickshell.starts') = 3 ]")"
assert "...each part independently" "$(yes_if "[ \$(wc -l < '$SANDBOX/place.starts') = 3 ]")"
assert "a part that exits cleanly is not restarted" "$(yes_if "[ \$(wc -l < '$SANDBOX/pan.starts') = 1 ]")"
assert "giving up is logged" "$(yes_if "grep -q 'not restarting it again' '$SANDBOX/run/dxrice/real/quickshell.log'")"
assert "pid files cleaned up once a supervisor ends" "$(yes_if "[ -z \"\$(ls '$SANDBOX/run/dxrice/real/'*.pid 2>/dev/null)\" ]")"

# a second start while a supervisor is alive leaves it alone
cat > "$STUB/part.sh" <<EOF
#!/bin/sh
echo start >> "$SANDBOX/\$1.starts2"
sleep 30
EOF
for _ in 1 2; do
    env -i HOME="$H" PATH="$BIN:/usr/bin:/bin" XDG_RUNTIME_DIR="$SANDBOX/run" HYPRLAND_INSTANCE_SIGNATURE=real \
        sh "$STUB/scripts/dxrice_session.sh"
done
sleep 0.5
assert "starting twice runs one copy of each part" "$(yes_if "[ \$(wc -l < '$SANDBOX/quickshell.starts2') = 1 ]")"

# its Hyprland goes away: a crashed part isn't restarted
pkill -f "$STUB/scripts/dxrice_session.sh" 2>/dev/null   # earlier supervisors first,
pkill -f "$STUB/part.sh" 2>/dev/null; sleep 0.3            # so nothing restarts these
cat > "$STUB/part.sh" <<EOF
#!/bin/sh
echo start >> "$SANDBOX/\$1.starts3"
sleep 0.3
exit 3
EOF
env -i HOME="$H" PATH="$BIN:/usr/bin:/bin" XDG_RUNTIME_DIR="$SANDBOX/run" HYPRLAND_INSTANCE_SIGNATURE=gone \
    DXRICE_SUPERVISE_DELAY=0.05 DXRICE_SUPERVISE_MAX=5 sh "$STUB/scripts/dxrice_session.sh"
sleep 0.1
rmdir "$SANDBOX/run/hypr/gone"
sleep 1.5
assert "once its Hyprland is gone, a crashed part is not restarted" \
    "$(yes_if "[ \$(wc -l < '$SANDBOX/quickshell.starts3') = 1 ]")"
assert "...and its supervisor has ended" "$(yes_if "[ -z \"\$(ls '$SANDBOX/run/dxrice/gone/'*.pid 2>/dev/null)\" ]")"

echo ""
if [ "$FAILED" = 0 ]; then echo "All assertions passed."; else echo "FAILED"; exit 1; fi
