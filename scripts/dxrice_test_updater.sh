#!/usr/bin/env bash
# `install.sh update` against a real git upstream in a sandbox: a bare repo
# made from this working tree plays the remote, a clone of it plays the
# user's checkout. Commands that could touch the system are recording fakes
# (sudo, systemctl, pacman says everything is installed). Covers: already up
# to date, a clean fast-forward, local edits that don't and do overlap the
# update, a diverged branch, an unreachable remote, a detached HEAD. The
# updater must never change the checkout when it refuses, and never lose a
# local edit.
#
#   bash scripts/dxrice_test_updater.sh
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
mkdir -p "$BIN" "$LOG"
for cmd in sudo systemctl usermod fc-cache curl wget; do
    printf '#!/bin/sh\necho "$*" >> "%s/%s.log"\nexit 0\n' "$LOG" "$cmd" > "$BIN/$cmd"
done
printf '#!/bin/sh\nexit 0\n' > "$BIN/pacman"
printf '#!/bin/sh\nexit 0\n' > "$BIN/qs"
printf '#!/bin/sh\nexit 1\n' > "$BIN/hyprctl"
printf '#!/bin/sh\nexit 1\n' > "$BIN/pgrep"
chmod +x "$BIN"/*

G() { git -c user.name=test -c user.email=test@example.invalid "$@"; }

# upstream: this working tree as one commit
SEED="$SANDBOX/seed"
cp -a "$SRC" "$SEED"
rm -rf "$SEED/.git"
G -C "$SEED" init -q -b main
G -C "$SEED" add -A
G -C "$SEED" commit -q -m "seed"
G clone -q --bare "$SEED" "$SANDBOX/origin.git"

# upstream_commit FILE TEXT: a new commit on the remote changing FILE
upstream_commit() {
    local work="$SANDBOX/upstream-work"
    [ -d "$work" ] || G clone -q "$SANDBOX/origin.git" "$work"
    G -C "$work" pull -q --ff-only
    printf '%s\n' "$2" >> "$work/$1"
    G -C "$work" commit -q -am "upstream: $1"
    G -C "$work" push -q origin main
}

H="$SANDBOX/home"
CO="$H/dxrice"
mkdir -p "$H"
G clone -q "$SANDBOX/origin.git" "$CO"

run_update() {
    env -i HOME="$H" USER="${USER:-tester}" PATH="$BIN:/usr/bin:/bin" TERM=dumb SHELL=/bin/bash \
        XDG_CONFIG_HOME="$H/.config" XDG_DATA_HOME="$H/.local/share" XDG_STATE_HOME="$H/.local/state" \
        GIT_CONFIG_GLOBAL=/dev/null DXRICE_LOCATION_CONFIRMED=1 \
        bash "$CO/install.sh" update < /dev/null > "$LOG/update.out" 2>&1
}
head_of() { git -C "$CO" rev-parse HEAD; }

echo "=== already up to date ==="
run_update; rc=$?
assert "exits 0 (rc=$rc)" "$(yes_if "[ $rc = 0 ]")"
assert "says it's up to date" "$(yes_if "grep -q 'Already up to date' '$LOG/update.out'")"
assert "summary reported at the end" "$(yes_if "grep -q 'Already up to date: main at' '$LOG/update.out'")"

echo "=== a clean fast-forward ==="
before="$(head_of)"
upstream_commit README.md "upstream line 1"
run_update; rc=$?
assert "exits 0 (rc=$rc)" "$(yes_if "[ $rc = 0 ]")"
assert "the incoming commit was listed before applying" "$(yes_if "grep -q 'upstream: README.md' '$LOG/update.out'")"
assert "checkout now at upstream" "$(yes_if "[ \"\$(head_of)\" = \"\$(git -C '$SANDBOX/origin.git' rev-parse main)\" ]")"
assert "old -> new reported" "$(yes_if "grep -q 'Updated main from ${before:0:7} to' '$LOG/update.out'")"
assert "...with the way back" "$(yes_if "grep -q 'To go back: git -C .* checkout ${before:0:7}' '$LOG/update.out'")"
assert "update history recorded" "$(yes_if "grep -q '${before:0:7} -> ' '$H/.local/state/dxrice/update-history'")"
assert "nothing restarted" "$(yes_if "! grep -q 'restart' '$LOG/systemctl.log' 2>/dev/null")"

echo "=== a local edit the update doesn't touch ==="
printf 'my tweak\n' >> "$CO/wofi/config"
cp "$CO/wofi/config" "$LOG/my-wofi"
upstream_commit README.md "upstream line 2"
run_update; rc=$?
assert "exits 0 (rc=$rc)" "$(yes_if "[ $rc = 0 ]")"
assert "update applied" "$(yes_if "grep -q 'upstream line 2' '$CO/README.md'")"
assert "local edit kept byte for byte" "$(yes_if "cmp -s '$LOG/my-wofi' '$CO/wofi/config'")"
assert "no stash was created" "$(yes_if "[ -z \"\$(git -C '$CO' stash list)\" ]")"

echo "=== a local edit the update also changes ==="
printf 'my readme note\n' >> "$CO/README.md"
cp "$CO/README.md" "$LOG/my-readme"
before="$(head_of)"
upstream_commit README.md "upstream line 3"
run_update; rc=$?
assert "refuses (rc=$rc)" "$(yes_if "[ $rc != 0 ]")"
assert "names the file" "$(yes_if "grep -q '    README.md' '$LOG/update.out'")"
assert "explains how to resolve it" "$(yes_if "grep -q 'stash push -- README.md' '$LOG/update.out'")"
assert "checkout unchanged" "$(yes_if "[ \"\$(head_of)\" = '$before' ]")"
assert "local edit untouched" "$(yes_if "cmp -s '$LOG/my-readme' '$CO/README.md'")"
git -C "$CO" checkout -q -- README.md
run_update
assert "after discarding the edit, it updates" "$(yes_if "grep -q 'upstream line 3' '$CO/README.md'")"

echo "=== a branch with its own commits ==="
printf 'local commit\n' >> "$CO/kitty/kitty.conf"
G -C "$CO" commit -q -am "my own commit"
before="$(head_of)"
upstream_commit README.md "upstream line 4"
run_update; rc=$?
assert "refuses (rc=$rc)" "$(yes_if "[ $rc != 0 ]")"
assert "suggests pull --rebase" "$(yes_if "grep -q 'pull --rebase' '$LOG/update.out'")"
assert "checkout unchanged" "$(yes_if "[ \"\$(head_of)\" = '$before' ]")"
G -C "$CO" reset -q --hard origin/main~1 2>/dev/null; G -C "$CO" pull -q --ff-only

echo "=== the remote can't be reached ==="
before="$(head_of)"
mv "$SANDBOX/origin.git" "$SANDBOX/origin.gone"
run_update; rc=$?
mv "$SANDBOX/origin.gone" "$SANDBOX/origin.git"
assert "fails (rc=$rc)" "$(yes_if "[ $rc != 0 ]")"
assert "says it couldn't fetch, nothing changed" "$(yes_if "grep -q \"Couldn't fetch updates\" '$LOG/update.out' && grep -q 'Nothing was changed' '$LOG/update.out'")"
assert "checkout unchanged" "$(yes_if "[ \"\$(head_of)\" = '$before' ]")"

echo "=== a detached HEAD ==="
git -C "$CO" checkout -q --detach
before="$(head_of)"
run_update; rc=$?
assert "exits 0 without updating (rc=$rc)" "$(yes_if "[ $rc = 0 ] && [ \"\$(head_of)\" = '$before' ]")"
assert "says why" "$(yes_if "grep -q 'detached commit' '$LOG/update.out'")"

echo ""
if [ "$FAILED" = 0 ]; then echo "All assertions passed."; else echo "FAILED"; tail -40 "$LOG/update.out"; exit 1; fi
