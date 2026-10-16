#!/usr/bin/env bash
# The real installer, end to end, against a throwaway HOME and a throwaway
# clone of this checkout: install -> update -> update -> uninstall ->
# uninstall --purge -> install again. Every command that could touch the
# system is a recording fake placed first on PATH: sudo runs nothing, the
# package managers report everything as already installed, systemctl only
# records, qs is a stub, hyprctl is absent (no running Hyprland). The
# clone has no upstream, so `update` never pulls.
#
# Checks what a user would care about: the install produces a working
# layout, a second update changes nothing, the user's own edits survive
# updates, uninstall removes only DXrice's integration and keeps their
# data, and a reinstall works.
#
#   bash scripts/dxrice_test_install_cycle.sh
set -uo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SANDBOX="$(mktemp -d)"
trap '[ -n "${KEEP:-}" ] || rm -rf "$SANDBOX"' EXIT

FAILED=0
assert() {
    if [ "$2" = "1" ]; then echo "  [PASS] $1"; else echo "  [FAIL] $1"; FAILED=1; fi
}
yes_if() { if eval "$1"; then echo 1; else echo 0; fi; }

BIN="$SANDBOX/bin"
LOG="$SANDBOX/log"
H="$SANDBOX/home"
mkdir -p "$BIN" "$LOG" "$H"
for cmd in sudo systemctl yay paru usermod fc-cache curl wget; do
    cat > "$BIN/$cmd" <<EOF
#!/bin/sh
echo "\$*" >> "$LOG/$cmd.log"
exit 0
EOF
done
# pacman: every query says "installed"; anything else is recorded only.
cat > "$BIN/pacman" <<EOF
#!/bin/sh
echo "\$*" >> "$LOG/pacman.log"
case "\$1" in -Q*) exit 0 ;; esac
exit 0
EOF
printf '#!/bin/sh\nexit 0\n' > "$BIN/qs"
# No Hyprland here: hyprctl must never reach a real instance (with no
# signature it would pick whichever Hyprland is running), nor pgrep find one.
printf '#!/bin/sh\necho "HYPRLAND_INSTANCE_SIGNATURE not set!" >&2\nexit 1\n' > "$BIN/hyprctl"
printf '#!/bin/sh\nexit 1\n' > "$BIN/pgrep"
chmod +x "$BIN"/*

# the working tree as it is on disk, uncommitted changes included
cp -a "$SRC" "$SANDBOX/repo"
git -C "$SANDBOX/repo" branch -q --unset-upstream 2>/dev/null || true
REPO="$SANDBOX/repo"

run() {  # run MODE [ARGS...] -- the real installer, in the sandbox
    env -i HOME="$H" USER="${USER:-tester}" PATH="$BIN:/usr/bin:/bin" TERM=dumb SHELL=/bin/bash \
        XDG_CONFIG_HOME="$H/.config" XDG_DATA_HOME="$H/.local/share" XDG_STATE_HOME="$H/.local/state" \
        DXRICE_LOCATION_CONFIRMED=1 bash "$REPO/install.sh" "$@" < /dev/null > "$LOG/out-$1-$RANDOM" 2>&1
}
snapshot() {  # every file under HOME with its content hash, sorted
    (cd "$H" && find . -type f ! -path './.cache/*' ! -name '*.log' -print0 | sort -z | xargs -0 sha256sum)
}

echo "=== install into an empty home ==="
run install; rc=$?
assert "install exits 0 (rc=$rc)" "$(yes_if "[ $rc = 0 ]")"
assert "hyprland.lua deployed" "$(yes_if "[ -s '$H/.config/hypr/hyprland.lua' ]")"
assert "theme.json created" "$(yes_if "[ -s '$H/.config/dxrice/theme.json' ]")"
assert "repo path recorded" "$(yes_if "grep -qx '$REPO' '$H/.local/state/dxrice/repo_path'")"
assert "systemd units written" "$(yes_if "[ -f '$H/.config/systemd/user/dxrice-quickshell.service' ]")"
assert "with every package present, the package manager was only queried" \
    "$(yes_if "! grep -qv '^-Q' '$LOG/pacman.log'")"

echo "=== a second update changes nothing ==="
run update; rc=$?
assert "first update exits 0 (rc=$rc)" "$(yes_if "[ $rc = 0 ]")"
snapshot > "$LOG/after-update-1"
run update
snapshot > "$LOG/after-update-2"
assert "second update left every file identical" "$(yes_if "diff -q '$LOG/after-update-1' '$LOG/after-update-2' >/dev/null")"
diff "$LOG/after-update-1" "$LOG/after-update-2" | head -5

echo "=== the user's own edits survive an update ==="
printf '\n-- my own bind\nhl.bind("SUPER + Y", hl.dsp.exec_cmd("foot"))\n' >> "$H/.config/hypr/hyprland.lua"
python3 - "$H/.config/dxrice/theme.json" <<'EOF'
import json, sys
p = sys.argv[1]; d = json.load(open(p)); d["my_custom_key"] = [1, 2]; d["accent"] = "a1b2c3"
json.dump(d, open(p, "w"), indent=4)
EOF
run update
assert "hand-added keybind kept" "$(yes_if "grep -q 'SUPER + Y' '$H/.config/hypr/hyprland.lua'")"
assert "custom theme key kept" "$(yes_if "grep -q my_custom_key '$H/.config/dxrice/theme.json'")"
assert "custom accent kept" "$(yes_if "grep -q a1b2c3 '$H/.config/dxrice/theme.json'")"

echo "=== uninstall keeps the user's data ==="
run uninstall; rc=$?
assert "uninstall exits 0 (rc=$rc)" "$(yes_if "[ $rc = 0 ]")"
assert "DXrice units removed" "$(yes_if "[ ! -e '$H/.config/systemd/user/dxrice-quickshell.service' ]")"
assert "repo path record removed" "$(yes_if "[ ! -e '$H/.local/state/dxrice/repo_path' ]")"
assert "theme.json kept" "$(yes_if "grep -q a1b2c3 '$H/.config/dxrice/theme.json'")"
assert "hyprland.lua kept" "$(yes_if "grep -q 'SUPER + Y' '$H/.config/hypr/hyprland.lua'")"

echo "=== uninstall --purge without confirmation deletes nothing ==="
snapshot > "$LOG/before-purge"
run uninstall --purge; rc=$?
assert "purge exits cleanly (rc=$rc)" "$(yes_if "[ $rc = 0 ] || [ $rc = 1 ]")"
assert "unconfirmed purge kept theme.json" "$(yes_if "[ -f '$H/.config/dxrice/theme.json' ]")"

echo "=== reinstall over the leftovers ==="
run install; rc=$?
assert "reinstall exits 0 (rc=$rc)" "$(yes_if "[ $rc = 0 ]")"
assert "reinstall kept the custom accent" "$(yes_if "grep -q a1b2c3 '$H/.config/dxrice/theme.json'")"
assert "units back" "$(yes_if "[ -f '$H/.config/systemd/user/dxrice-quickshell.service' ]")"
# Root is only ever asked for the login-screen theme: syncing it, and
# removing it (and its drop-in) on uninstall. Anything else needing root
# would be a new, unreviewed privileged action.
assert "sudo used only for the SDDM theme" \
    "$(yes_if "! grep -vE '^(python3 [^ ]*/scripts/dxrice_sync_sddm_theme\.py|rm -rf /usr/share/sddm/themes/dxrice|rm -f /etc/sddm\.conf\.d/dxrice\.conf)\$' '$LOG/sudo.log' | grep -q .")"

echo ""
if [ "$FAILED" = "1" ]; then
    echo "FAILED"
    for f in "$LOG"/out-*; do echo "--- $f"; tail -15 "$f"; done
    exit 1
fi
echo "All assertions passed."
exit 0
