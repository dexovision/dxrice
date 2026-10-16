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
# \`show -p PROP --value UNIT\` answers from \$LOG/show-PROP when present.
if [ "\$2" = show ] && [ -f "$LOG/show-\$4" ]; then cat "$LOG/show-\$4"; fi
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
    rm -f "$LOG"/show-*
}
run_env() {
    env -i HOME="$H" USER="${USER:-tester}" PATH="$BIN:/usr/bin:/bin" TERM=dumb \
        XDG_CONFIG_HOME="$H/.config" XDG_DATA_HOME="$H/.local/share" XDG_STATE_HOME="$H/.local/state" \
        DXRICE_ASSUME_YES="${DXRICE_ASSUME_YES:-0}" DXRICE_LOCATION_CONFIRMED=1 DXRICE_CGROUP_ROOT="$SANDBOX/cg" DXRICE_PROC_ROOT="$SANDBOX/proc" "$@"
}
# Defines install.sh's functions without running it (see its source guard).
call() {
    run_env bash -c 'source "$1" >/dev/null; shift; "$@"' _ "$REPO_DIR/install.sh" "$@"
}

OLD_LINE='    hl.exec_cmd("/usr/lib/polkit-kde-agent-1")'
NEW_LINE='    hl.exec_cmd(repo .. "/scripts/dxrice_polkit_agent.sh")'

echo "=== hyprland.lua migrations ==="

# The pre-fix template, as installs deployed it: an old polkit path, the
# autostart before dxrice_session.sh, and no layer-fade lines.
old_template() {
    git -C "$REPO_DIR" show 36ece7d:hypr/hyprland.lua 2>/dev/null \
        || sed "s#hl.exec_cmd(repo .. \"/scripts/dxrice_polkit_agent.sh\")#hl.exec_cmd(\"/usr/lib/polkit-kde-agent-1\")#" \
            "$REPO_DIR/hypr/hyprland.lua"
}

new_home migrate
LUA="$H/.config/hypr/hyprland.lua"
old_template > "$LUA"
printf '\n-- my own keybind\nhl.bind("SUPER + Y", hl.dsp.exec_cmd("foot"))\n' >> "$LUA"
chmod 640 "$LUA"
grep -qF "$OLD_LINE" "$LUA"; assert "fixture has the old line" "$([ $? = 0 ] && echo 1 || echo 0)"
cp "$LUA" "$LOG/before.lua"

call migrate_hyprland_lua < /dev/null > "$LOG/mig0.out" 2>&1
assert "unattended without --yes: file untouched" "$(yes_if "cmp -s '$LOG/before.lua' '$LUA'")"
assert "...and the pending fixes were listed" "$(yes_if "grep -q 'polkit agent' '$LOG/mig0.out'")"

DXRICE_ASSUME_YES=1 call migrate_hyprland_lua > "$LOG/mig1.out" 2>&1
assert "old polkit path is gone" "$(yes_if "! grep -qF '/usr/lib/polkit-kde-agent-1' '$LUA'")"
assert "helper line is in its place" "$(yes_if "grep -qF '$NEW_LINE' '$LUA'")"
assert "layer fades turned off" "$(yes_if "grep -q 'leaf = \"fadeLayersIn\",  enabled = false' '$LUA'")"
assert "the result is exactly the migration of the old file" \
    "$(yes_if "python3 -c 'import sys; sys.path.insert(0, \"$REPO_DIR/scripts\"); import dxrice_hypr_migrate as m; sys.exit(m.migrate(open(\"$LOG/before.lua\").read()) != open(\"$LUA\").read())'")"
assert "user's own keybind kept" "$(yes_if "grep -q 'SUPER + Y' '$LUA'")"
assert "permissions kept (640)" "$(yes_if "[ \"\$(stat -c %a '$LUA')\" = 640 ]")"
assert "no temp files left" "$(yes_if "[ -z \"\$(find '$H/.config/hypr' -name '*.tmp')\" ]")"
backup="$(ls "$H/.local/state/dxrice/backups/"hyprland.lua.*.bak 2>/dev/null | head -1)"
assert "a backup of the original was made" "$(yes_if "[ -n '$backup' ] && cmp -s '$LOG/before.lua' '$backup'")"
assert "the backup is reported" "$(yes_if "grep -q 'backup:' '$LOG/mig1.out'")"
assert "migrated file is valid Lua" "$(yes_if "! command -v luac5.4 >/dev/null || luac5.4 -p '$LUA'")"
cp "$LUA" "$LOG/after1.lua"
DXRICE_ASSUME_YES=1 call migrate_hyprland_lua > "$LOG/mig2.out" 2>&1
assert "second run changes nothing" "$(yes_if "cmp -s '$LOG/after1.lua' '$LUA'")"
assert "...and makes no second backup" "$(yes_if "[ \"\$(ls '$H/.local/state/dxrice/backups/' | wc -l)\" = 1 ]")"

new_home polkit-custom
LUA="$H/.config/hypr/hyprland.lua"
sed "s#$NEW_LINE#    hl.exec_cmd(\"/usr/lib/my-own-agent\")#" "$REPO_DIR/hypr/hyprland.lua" > "$LUA"
cp "$LUA" "$LOG/custom.lua"
DXRICE_ASSUME_YES=1 call migrate_hyprland_lua > /dev/null 2>&1
assert "a polkit line the user changed is left alone" "$(yes_if "cmp -s '$LOG/custom.lua' '$LUA'")"

new_home polkit-norepo
LUA="$H/.config/hypr/hyprland.lua"
printf 'hl.on("hyprland.start", function()\n%s\nend)\n' "$OLD_LINE" > "$LUA"
cp "$LUA" "$LOG/norepo.lua"
DXRICE_ASSUME_YES=1 call migrate_hyprland_lua > "$LOG/norepo.out" 2>&1
assert "file without the repo variable is not edited" "$(yes_if "cmp -s '$LOG/norepo.lua' '$LUA'")"
assert "...and the user is told what to change" "$(yes_if "grep -q 'dxrice_polkit_agent.sh' '$LOG/norepo.out'")"

echo "=== dotfiles managed through symlinks ==="

new_home symlinks
mkdir -p "$H/dotfiles"
old_template > "$H/dotfiles/hyprland.lua"
ln -sf "$H/dotfiles/hyprland.lua" "$H/.config/hypr/hyprland.lua"
printf 'export EDITOR=vim\n' > "$H/dotfiles/bashrc"
ln -s "$H/dotfiles/bashrc" "$H/.bashrc"
DXRICE_ASSUME_YES=1 call migrate_hyprland_lua > "$LOG/sym.out" 2>&1
call install_shell_alias >> "$LOG/sym.out" 2>&1
call install_shell_alias >> "$LOG/sym.out" 2>&1
assert "hyprland.lua is still a symlink after a migration" "$(yes_if "[ -L '$H/.config/hypr/hyprland.lua' ]")"
assert "...and the dotfiles copy got the fix" "$(yes_if "grep -q 'fadeLayersIn' '$H/dotfiles/hyprland.lua'")"
assert ".bashrc is still a symlink after installing the dx functions twice" "$(yes_if "[ -L '$H/.bashrc' ]")"
assert "...with exactly one dx block in the dotfiles copy" \
    "$(yes_if "[ \"\$(grep -c 'BEGIN dxrice shell functions' '$H/dotfiles/bashrc')\" = 1 ]")"
assert "...and the user's own line kept" "$(yes_if "grep -q 'EDITOR=vim' '$H/dotfiles/bashrc'")"

echo "=== a checkout path hyprland.lua can't use ==="

SPACED="$SANDBOX/my stuff/dxrice"
mkdir -p "$SANDBOX/my stuff"
cp -a "$REPO_DIR" "$SPACED"
new_home spaced
env -i HOME="$H" USER="${USER:-tester}" PATH="$BIN:/usr/bin:/bin" TERM=dumb \
    XDG_CONFIG_HOME="$H/.config" XDG_DATA_HOME="$H/.local/share" XDG_STATE_HOME="$H/.local/state" \
    bash "$SPACED/install.sh" < /dev/null > "$LOG/spaced.out" 2>&1
rc=$?
assert "install refuses a checkout path with a space (rc=$rc)" "$(yes_if "[ $rc != 0 ]")"
assert "...says why and what to use" "$(yes_if "grep -q 'contains spaces or shell characters' '$LOG/spaced.out'")"
assert "...before deploying anything" "$(yes_if "[ ! -e '$H/.config/hypr/hyprland.lua' ]")"
assert "plain paths are accepted" "$(yes_if "call path_is_plain /home/me/dxrice-2.0_x+y@z")"

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
for u in dxrice-auto-place-window.service dxrice-infinite-desktop.service; do
    assert "$u stopped" "$(yes_if "grep -E '^--user stop .*$u' '$LOG/systemctl.log' >/dev/null")"
done
for u in dxrice-quickshell.service dxrice-auto-place-window.service dxrice-infinite-desktop.service; do
    assert "$u unit file removed" "$(yes_if "[ ! -e '$UNITS/$u' ]")"
done
# Stopping a unit kills its whole cgroup, and an app opened from an older
# shell may still be in the Quickshell unit's -- when what's in there can't
# be inspected, an uninstall must not take the user's browser (or its own
# terminal) down with the bar.
assert "Quickshell unit not stopped when its cgroup can't be inspected" \
    "$(yes_if "! grep -E '^--user (stop|restart|kill|try-restart|reload-or-restart) .*dxrice-quickshell' '$LOG/systemctl.log' >/dev/null")"
assert "...and the user is told the bar ends at logout" "$(yes_if "grep -q 'keeps running until you log out' '$LOG/uninstall.out'")"
assert "units reloaded afterwards" "$(yes_if "grep -q '^--user daemon-reload' '$LOG/systemctl.log'")"
assert "unrelated unit left in place" "$(yes_if "[ -f '$UNITS/my-sync.service' ]")"
assert "unrelated unit never passed to systemctl" "$(yes_if "! grep -q 'my-sync' '$LOG/systemctl.log'")"
assert "systemctl only ever called for DXrice units" \
    "$(yes_if "! grep -v -E '^--user (daemon-reload|show -p (ControlGroup|MainPID) --value dxrice-quickshell\.service|(stop|disable|reset-failed)( dxrice-(quickshell|auto-place-window|infinite-desktop)\.service)+)\$' '$LOG/systemctl.log' | grep -q .")"
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

echo "=== the Quickshell unit is stopped only when nothing else lives in it ==="

# A fake cgroup tree and /proc: the unit's cgroup lists PIDs, and each PID's
# status names its parent. MainPID 100 is Quickshell.
fake_cgroup() {  # fake_cgroup "pid:ppid" ...
    local cg="$SANDBOX/cg/user.slice/app.slice/dxrice-quickshell.service" entry
    rm -rf "$SANDBOX/cg" "$SANDBOX/proc"
    mkdir -p "$cg"
    : > "$cg/cgroup.procs"
    for entry in "$@"; do
        echo "${entry%%:*}" >> "$cg/cgroup.procs"
        mkdir -p "$SANDBOX/proc/${entry%%:*}"
        printf 'Name:\tx\nPPid:\t%s\n' "${entry##*:}" > "$SANDBOX/proc/${entry%%:*}/status"
    done
    echo "/user.slice/app.slice/dxrice-quickshell.service" > "$LOG/show-ControlGroup"
    echo "${MAIN_PID:-100}" > "$LOG/show-MainPID"
}
uninstall_with_cgroup() {
    new_home "cg-$1"; shift
    call deploy_systemd_units > /dev/null 2>&1
    fake_cgroup "$@"
    : > "$LOG/systemctl.log"
    run_env bash "$REPO_DIR/install.sh" uninstall < /dev/null > "$LOG/cg.out" 2>&1
}
qs_stopped() { grep -E '^--user stop .*dxrice-quickshell' "$LOG/systemctl.log" >/dev/null; }

uninstall_with_cgroup own 100:1 101:100 102:101
assert "only Quickshell and its own helpers inside: the unit is stopped" "$(yes_if "qs_stopped")"
assert "...and not reported as left running" "$(yes_if "! grep -q 'keeps running until you log out' '$LOG/cg.out'")"

uninstall_with_cgroup foreign 100:1 101:100 200:1
assert "an app detached from an older shell inside: the unit is not stopped" "$(yes_if "! qs_stopped")"
assert "...and the user is told the bar ends at logout" "$(yes_if "grep -q 'keeps running until you log out' '$LOG/cg.out'")"

uninstall_with_cgroup vanished 100:1 300:999
assert "a process whose parent chain can't be read: not stopped" "$(yes_if "! qs_stopped")"

MAIN_PID=0 uninstall_with_cgroup notrunning 100:1
assert "fixture: the unit file was there to remove" "$(yes_if "grep -q 'Removed DXrice.s services: .*dxrice-quickshell' '$LOG/cg.out'")"
assert "unit not running (MainPID 0): nothing to stop, not stopped" "$(yes_if "! qs_stopped")"

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
