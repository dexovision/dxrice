#!/usr/bin/env bash
# Installer lifecycle tests: the polkit-autostart migration and uninstall's
# service cleanup, against a throwaway HOME. Nothing here can touch the real
# system: systemctl and sudo are recording shims placed first on PATH (sudo
# never runs anything), every XDG directory points into the sandbox, and the
# real installer runs under `env -i` exactly as dxrice_test_legacy_rice_checkout.sh
# does.
#
#   bash scripts/dxrice_test_installer_lifecycle.sh
set -uo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SANDBOX="$(mktemp -d)"
trap 'rm -rf "$SANDBOX"' EXIT

FAILED=0
assert() {
    local desc="$1" ok="$2"
    if [ "$ok" = "1" ]; then
        echo "  [PASS] $desc"
    else
        echo "  [FAIL] $desc"
        FAILED=1
    fi
}
yes_if() { if eval "$1"; then echo 1; else echo 0; fi; }

BIN="$SANDBOX/bin"
LOG="$SANDBOX/log"
mkdir -p "$BIN" "$LOG"
cat > "$BIN/systemctl" <<EOF
#!/bin/sh
echo "\$*" >> "$LOG/systemctl.log"
exit 0
EOF
cat > "$BIN/sudo" <<EOF
#!/bin/sh
echo "\$*" >> "$LOG/sudo.log"
exit 0
EOF
# deploy_systemd_units only writes the Quickshell unit when `qs` resolves.
printf '#!/bin/sh\nexit 0\n' > "$BIN/qs"
chmod +x "$BIN"/*

new_home() {
    H="$SANDBOX/home-$1"
    mkdir -p "$H/.config/hypr" "$H/.config/systemd/user" "$H/.local/share" "$H/.local/state"
    : > "$LOG/systemctl.log"
    : > "$LOG/sudo.log"
}
run_env() {
    env -i HOME="$H" USER="${USER:-tester}" PATH="$BIN:/usr/bin:/bin" TERM=dumb \
        XDG_CONFIG_HOME="$H/.config" XDG_DATA_HOME="$H/.local/share" XDG_STATE_HOME="$H/.local/state" \
        DXRICE_LOCATION_CONFIRMED=1 "$@"
}
# Defines install.sh's functions without running it (see its source guard).
call() {
    run_env bash -c 'source "$1" >/dev/null; shift; "$@"' _ "$REPO_DIR/install.sh" "$@"
}

OLD_LINE='    hl.exec_cmd("/usr/lib/polkit-kde-agent-1")'
NEW_LINE='    hl.exec_cmd(repo .. "/scripts/dxrice_polkit_agent.sh")'

echo "=== polkit autostart migration ==="

new_home polkit
LUA="$H/.config/hypr/hyprland.lua"
# The pre-fix template, as installs deployed it.
git -C "$REPO_DIR" show 36ece7d:hypr/hyprland.lua > "$LUA" 2>/dev/null \
    || sed "s#hl.exec_cmd(repo .. \"/scripts/dxrice_polkit_agent.sh\")#hl.exec_cmd(\"/usr/lib/polkit-kde-agent-1\")#" \
        "$REPO_DIR/hypr/hyprland.lua" > "$LUA"
printf '\n-- my own keybind\nhl.bind("SUPER + Y", hl.dsp.exec_cmd("foot"))\n' >> "$LUA"
chmod 640 "$LUA"
grep -qF "$OLD_LINE" "$LUA"; assert "fixture has the old line" "$([ $? = 0 ] && echo 1 || echo 0)"
cp "$LUA" "$LOG/before.lua"
call migrate_polkit_agent_line > "$LOG/mig1.out" 2>&1
assert "old polkit path is gone" "$(yes_if "! grep -qF '/usr/lib/polkit-kde-agent-1' '$LUA'")"
assert "helper line is in its place" "$(yes_if "grep -qF '$NEW_LINE' '$LUA'")"
assert "nothing else in the file changed" "$(yes_if "diff <(grep -vF 'polkit' '$LOG/before.lua') <(grep -vF 'polkit' '$LUA') >/dev/null")"
assert "user's own keybind kept" "$(yes_if "grep -q 'SUPER + Y' '$LUA'")"
assert "permissions kept (640)" "$(yes_if "[ \"\$(stat -c %a '$LUA')\" = 640 ]")"
assert "no temp files left" "$(yes_if "[ -z \"\$(find '$H/.config/hypr' -name '*.tmp')\" ]")"
cp "$LUA" "$LOG/after1.lua"
call migrate_polkit_agent_line > "$LOG/mig2.out" 2>&1
assert "second run changes nothing" "$(yes_if "cmp -s '$LOG/after1.lua' '$LUA'")"

new_home polkit-custom
LUA="$H/.config/hypr/hyprland.lua"
sed "s#$NEW_LINE#    hl.exec_cmd(\"/usr/lib/my-own-agent\")#" "$REPO_DIR/hypr/hyprland.lua" > "$LUA"
cp "$LUA" "$LOG/custom.lua"
call migrate_polkit_agent_line > /dev/null 2>&1
assert "a polkit line the user changed is left alone" "$(yes_if "cmp -s '$LOG/custom.lua' '$LUA'")"

new_home polkit-norepo
LUA="$H/.config/hypr/hyprland.lua"
printf 'hl.on("hyprland.start", function()\n%s\nend)\n' "$OLD_LINE" > "$LUA"
cp "$LUA" "$LOG/norepo.lua"
call migrate_polkit_agent_line > "$LOG/norepo.out" 2>&1
assert "file without the repo variable is not edited" "$(yes_if "cmp -s '$LOG/norepo.lua' '$LUA'")"
assert "...and the user is told what to change" "$(yes_if "grep -q 'dxrice_polkit_agent.sh' '$LOG/norepo.out'")"

echo "=== uninstall removes DXrice's services ==="

new_home uninstall
UNITS="$H/.config/systemd/user"
call deploy_systemd_units > /dev/null 2>&1
for u in dxrice-quickshell.service dxrice-auto-place-window.service dxrice-infinite-desktop.service; do
    assert "fixture: deploy wrote $u" "$(yes_if "[ -f '$UNITS/$u' ]")"
done
printf '[Unit]\nDescription=My own sync job\n[Service]\nExecStart=/bin/true\n' > "$UNITS/my-sync.service"
mkdir -p "$H/.config/dxrice" "$H/.local/share/dxrice/backups/keep-me" "$H/.local/state/dxrice"
echo '{"schema_version": 1, "accent": "e67878"}' > "$H/.config/dxrice/theme.json"
echo "$REPO_DIR" > "$H/.local/state/dxrice/repo_path"
cp "$REPO_DIR/hypr/hyprland.lua" "$H/.config/hypr/hyprland.lua"
cp "$H/.config/hypr/hyprland.lua" "$LOG/lua-before-uninstall"
: > "$LOG/systemctl.log"

run_env bash "$REPO_DIR/install.sh" uninstall < /dev/null > "$LOG/uninstall.out" 2>&1
assert "uninstall exits 0" "$(yes_if "[ $? = 0 ]")"
for u in dxrice-quickshell.service dxrice-auto-place-window.service dxrice-infinite-desktop.service; do
    assert "$u stopped" "$(yes_if "grep -E '^--user stop .*$u' '$LOG/systemctl.log' >/dev/null")"
    assert "$u unit file removed" "$(yes_if "[ ! -e '$UNITS/$u' ]")"
done
assert "units reloaded afterwards" "$(yes_if "grep -q '^--user daemon-reload' '$LOG/systemctl.log'")"
assert "unrelated unit left in place" "$(yes_if "[ -f '$UNITS/my-sync.service' ]")"
assert "unrelated unit never passed to systemctl" "$(yes_if "! grep -q 'my-sync' '$LOG/systemctl.log'")"
assert "systemctl only ever called for DXrice units" \
    "$(yes_if "! grep -v -E '^--user (daemon-reload|(stop|disable|reset-failed)( dxrice-(quickshell|auto-place-window|infinite-desktop)\.service)+)\$' '$LOG/systemctl.log' | grep -q .")"
assert "theme.json kept" "$(yes_if "grep -q e67878 '$H/.config/dxrice/theme.json'")"
assert "data/backups kept" "$(yes_if "[ -d '$H/.local/share/dxrice/backups/keep-me' ]")"
assert "recorded repo path removed" "$(yes_if "[ ! -e '$H/.local/state/dxrice/repo_path' ]")"
assert "hyprland.lua untouched (deployed configs are the user's)" "$(yes_if "cmp -s '$LOG/lua-before-uninstall' '$H/.config/hypr/hyprland.lua'")"
assert "user told the remaining autostart lines are now inert" "$(yes_if "grep -q 'no longer start anything' '$LOG/uninstall.out'")"
# Nothing left for hyprland.lua's autostart to relaunch: every unit it
# restarts by name is gone from every user unit directory.
relaunchable=0
for u in $(grep -o 'dxrice-[a-z-]*\.service' "$H/.config/hypr/hyprland.lua" | sort -u); do
    for d in "$H/.config/systemd/user" "$H/.local/share/systemd/user"; do
        [ -e "$d/$u" ] && relaunchable=1
    done
done
assert "no unit left for hyprland.lua's autostart to relaunch" "$(yes_if "[ $relaunchable = 0 ]")"
assert "sudo shim only (never a real privileged command)" "$(yes_if "[ ! -s '$LOG/sudo.log' ] || ! grep -qv 'rm ' '$LOG/sudo.log'")"

echo "=== a same-named unit DXrice didn't write is not removed ==="

new_home foreign
UNITS="$H/.config/systemd/user"
printf '[Unit]\nDescription=Someone else\x27s quickshell\n[Service]\nExecStart=/bin/true\n' > "$UNITS/dxrice-quickshell.service"
run_env bash "$REPO_DIR/install.sh" uninstall < /dev/null > "$LOG/foreign.out" 2>&1
assert "foreign same-named unit kept" "$(yes_if "[ -f '$UNITS/dxrice-quickshell.service' ]")"
assert "foreign unit never stopped" "$(yes_if "! grep -q 'dxrice-quickshell' '$LOG/systemctl.log'")"
assert "...and the user is told why" "$(yes_if "grep -q \"wasn't written by DXrice\" '$LOG/foreign.out'")"

echo ""
if [ "$FAILED" = "1" ]; then
    echo "FAILED"
    echo "--- uninstall output:"; cat "$LOG/uninstall.out" 2>/dev/null
    echo "--- systemctl calls:"; cat "$LOG/systemctl.log" 2>/dev/null
    exit 1
fi
echo "All assertions passed."
exit 0
