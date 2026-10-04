#!/usr/bin/env bash
# Regression test for check_legacy_rice_checkout's line-removal step.
#
# Found during a release-candidate review: the removal step used to run
# `grep -vE "$names_re"` against the WHOLE rc file -- an unanchored
# substring match with no "must be an alias" requirement, completely
# independent of the narrow, provable condition that gated detection.
# Confirmed live: it silently deleted an unrelated comment and an
# unrelated echo string that merely mentioned "theme_gui.py" in passing,
# and it deleted a line from the dx() function install_shell_alias had
# just written in the SAME install run, because "theme_gui.py" is a
# substring of "dxrice_theme_gui.py". Fixed by removing exactly the
# lines recorded during detection (by exact string match), never a fresh
# broad regex pass, and by making the write atomic + permission-
# preserving like every other write in this codebase.
#
# This test builds a disposable sandbox (never the real $HOME), seeds a
# genuine legacy-checkout alias alongside two adversarial lines designed
# to trigger the old bug, runs the real install.sh against it with
# sudo/systemctl/waybar/swaybg/hyprctl-mutations stubbed out, and asserts
# every expected outcome.
#
# Run: bash scripts/dxrice_test_legacy_rice_checkout.sh
# Exit code: 0 = all assertions passed, 1 = a regression was detected.
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

mkdir -p "$SANDBOX/home/hyprland-rice-main/scripts" "$SANDBOX/bin" "$SANDBOX/log"
touch "$SANDBOX/home/hyprland-rice-main/scripts/theme_gui.py"

for b in sudo systemctl waybar swaybg; do
    cat > "$SANDBOX/bin/$b" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
done
cat > "$SANDBOX/bin/hyprctl" <<'EOF'
#!/usr/bin/env bash
if [ "$1" = "monitors" ]; then exec /usr/bin/hyprctl "$@"; fi
exit 0
EOF
chmod +x "$SANDBOX"/bin/*

cat > "$SANDBOX/home/.bashrc" <<EOF
# my own bashrc
alias managetaskbar='$SANDBOX/home/hyprland-rice-main/scripts/manage-taskbar.sh'
export EDITOR=vim

# Note to self: finally stopped using that old theme_gui.py script, glad it's gone
echo "unrelated line that happens to mention theme_gui.py in a comment, not an alias"
EOF
chmod 644 "$SANDBOX/home/.bashrc"

env -i \
    HOME="$SANDBOX/home" USER="$USER" PATH="$SANDBOX/bin:/usr/bin:/bin" \
    XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-}" HYPRLAND_INSTANCE_SIGNATURE="${HYPRLAND_INSTANCE_SIGNATURE:-}" \
    DXRICE_LOCATION_CONFIRMED=1 TERM="${TERM:-dumb}" \
    bash "$REPO_DIR/install.sh" install < /dev/null > "$SANDBOX/log/install.out" 2>&1
install_exit=$?

RC="$SANDBOX/home/.bashrc"

echo "=== dxrice_test_legacy_rice_checkout.sh ==="
assert "install exits 0" "$([ "$install_exit" = "0" ] && echo 1 || echo 0)"
assert "genuine legacy alias IS removed" \
    "$(grep -q 'alias managetaskbar' "$RC" && echo 0 || echo 1)"
assert "unrelated comment line survives (not an alias, never confirmed)" \
    "$(grep -q 'finally stopped using' "$RC" && echo 1 || echo 0)"
assert "unrelated echo line survives (not an alias, never confirmed)" \
    "$(grep -q 'unrelated line that happens' "$RC" && echo 1 || echo 0)"
assert "DXrice's own dx() dxrice_theme_gui.py line survives" \
    "$(grep -q 'dxrice_theme_gui.py' "$RC" && echo 1 || echo 0)"
assert "dx()/dxrice-update block was added exactly once" \
    "$([ "$(grep -c 'BEGIN dxrice shell functions' "$RC")" = "1" ] && echo 1 || echo 0)"
assert "permissions preserved (0644)" \
    "$([ "$(stat -c %a "$RC")" = "644" ] && echo 1 || echo 0)"
assert "no leftover temp files" \
    "$([ -z "$(find "$SANDBOX/home" -name '.*.bashrc.*' ! -name "$(basename "$RC")" 2>/dev/null)" ] && echo 1 || echo 0)"

if [ "$FAILED" = "1" ]; then
    echo ""
    echo "FAILED -- install output:"
    cat "$SANDBOX/log/install.out"
    exit 1
fi
echo ""
echo "All assertions passed."
exit 0
