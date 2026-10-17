#!/usr/bin/env bash
# The installer on a Gentoo-shaped system, in a sandbox: emerge, portageq and
# Hyprland are fakes, the installed-package database is a temporary
# directory, there is no systemd, and sudo only records. Checks that the
# emerge backend reads deps/emerge.list, never installs anything without
# consent, installs only with `emerge --ask`, explains the overlays when
# Hyprland or Quickshell aren't visible, and refuses a Hyprland too old for
# hyprland.lua.
#
#   bash scripts/dxrice_test_gentoo.sh
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
VDB="$SANDBOX/vdb"
mkdir -p "$BIN" "$LOG" "$VDB"
for cmd in sudo systemctl usermod fc-cache curl wget emerge; do
    printf '#!/bin/sh\necho "$*" >> "%s/%s.log"\nexit 0\n' "$LOG" "$cmd" > "$BIN/$cmd"
done
# portageq best_visible: answers only for atoms listed in $LOG/visible
cat > "$BIN/portageq" <<EOF
#!/bin/sh
grep -qx "\$3" "$LOG/visible" 2>/dev/null && echo "\$3-9.9"
exit 0
EOF
printf '#!/bin/sh\nexit 1\n' > "$BIN/hyprctl"
printf '#!/bin/sh\nexit 1\n' > "$BIN/pgrep"
chmod +x "$BIN"/*
: > "$LOG/visible"

# every core package installed except two
while read -r group atom _; do
    [ "$group" = core ] || continue
    case "$atom" in gui-apps/wofi|app-misc/jq) continue ;; esac
    mkdir -p "$VDB/$atom-1.0"
done < "$SRC/deps/emerge.list"

cp -a "$SRC" "$SANDBOX/repo"
H="$SANDBOX/home"
mkdir -p "$H"

# The system's commands minus the other distributions' package managers,
# Quickshell, Hyprland and the "manual" packages (all faked here or meant to
# be absent), so the installer finds the fake emerge and sees what's missing
# even on a machine that has pacman (it takes the first one it finds) or
# Quickshell installed.
SYS="$SANDBOX/sysbin"
mkdir -p "$SYS"
for d in /usr/local/bin /usr/bin /bin; do
    [ -d "$d" ] || continue
    for f in "$d"/*; do
        n="${f##*/}"
        case "$n" in pacman|dnf|apt|apt-get|zypper|emerge|portageq|sudo|hyprctl|pgrep|qs|quickshell|Hyprland|hyprland|cliphist|nwg-look) continue ;; esac
        [ -e "$SYS/$n" ] || ln -s "$f" "$SYS/$n"
    done
done

run() {  # run ARGS... -- the real installer
    : > "$LOG/emerge.log"; : > "$LOG/sudo.log"
    env -i HOME="$H" USER="${USER:-tester}" PATH="$BIN:$SYS" TERM=dumb SHELL=/bin/bash \
        XDG_CONFIG_HOME="$H/.config" XDG_DATA_HOME="$H/.local/share" XDG_STATE_HOME="$H/.local/state" \
        DXRICE_VDB="$VDB" DXRICE_LOCATION_CONFIRMED=1 \
        bash "$SANDBOX/repo/install.sh" "$@" < /dev/null > "$LOG/out" 2>&1
}

echo "=== dry run ==="
run install --dry-run; rc=$?
assert "exits 0 (rc=$rc)" "$(yes_if "[ $rc = 0 ]")"
assert "uses emerge's list" "$(yes_if "grep -q 'Detected: emerge (package list: deps/emerge.list)' '$LOG/out'")"
assert "names exactly the two missing atoms" "$(yes_if "grep -q 'Would offer to install (needs sudo): gui-apps/wofi app-misc/jq' '$LOG/out'")"
assert "nothing run through sudo" "$(yes_if "[ ! -s '$LOG/sudo.log' ]")"

echo "=== unattended install without --yes ==="
run install; rc=$?
assert "exits 0 (rc=$rc)" "$(yes_if "[ $rc = 0 ]")"
assert "detects no systemd and says what runs the shell instead" "$(yes_if "grep -q 'init: ' '$LOG/out' && grep -q 'dxrice_session.sh' '$LOG/out'")"
assert "asked, and skipped without a terminal" "$(yes_if "grep -q 'Install them now with emerge.*skipping' '$LOG/out'")"
assert "no package installed" "$(yes_if "! grep -q 'emerge' '$LOG/sudo.log'")"
assert "Hyprland not visible: overlay explained" "$(yes_if "grep -q 'hyproverlay' '$LOG/out'")"
assert "Quickshell not visible: GURU explained" "$(yes_if "grep -q 'GURU' '$LOG/out'")"
assert "overlay-only packages named, not installed" "$(yes_if "grep -q 'Optional, not installed automatically: cliphist' '$LOG/out'")"

echo "=== install with --yes ==="
printf 'gui-wm/hyprland\ngui-apps/quickshell\n' > "$LOG/visible"
run install --yes; rc=$?
assert "exits 0 (rc=$rc)" "$(yes_if "[ $rc = 0 ]")"
assert "core atoms installed with emerge --ask --noreplace" \
    "$(yes_if "grep -qx 'emerge --ask --noreplace gui-apps/wofi app-misc/jq' '$LOG/sudo.log'")"
assert "visible Hyprland offered through emerge --ask" "$(yes_if "grep -q '^emerge --ask --noreplace gui-wm/hyprland' '$LOG/sudo.log'")"
assert "visible Quickshell offered through emerge --ask" "$(yes_if "grep -qx 'emerge --ask --noreplace gui-apps/quickshell' '$LOG/sudo.log'")"
assert "only emerge and usermod ever ran under sudo" "$(yes_if "! grep -vE '^(emerge --ask --noreplace |usermod -aG input )' '$LOG/sudo.log' | grep -q .")"

echo "=== a Hyprland too old for hyprland.lua ==="
printf '#!/bin/sh\necho "Hyprland 0.54.3 built from branch main"\n' > "$BIN/Hyprland"
chmod +x "$BIN/Hyprland"
run install --dry-run
assert "warned that 0.55 is needed" "$(yes_if "grep -q 'Hyprland 0.54.3 is installed, but DXrice.s config (hyprland.lua) needs 0.55' '$LOG/out'")"
printf '#!/bin/sh\necho "Hyprland 0.56.2 built from branch main"\n' > "$BIN/Hyprland"
run install --dry-run
assert "a new enough one is accepted" "$(yes_if "grep -q 'Hyprland 0.56.2 (needs 0.55 or newer)' '$LOG/out'")"

echo ""
if [ "$FAILED" = 0 ]; then echo "All assertions passed."; else echo "FAILED"; tail -60 "$LOG/out"; exit 1; fi
