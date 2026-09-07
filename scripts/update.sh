#!/usr/bin/env bash
set -e

# Always target the repository root (one level up from this script's location)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"

echo "==> Syncing local system configs to dotfiles repo..."
mkdir -p "$REPO_DIR"/{hypr,kitty,waybar,mako,scripts}

cp ~/.config/hypr/hyprland.lua "$REPO_DIR/hypr/" 2>/dev/null || true
cp ~/.config/kitty/kitty.conf "$REPO_DIR/kitty/" 2>/dev/null || true
cp ~/.config/waybar/config "$REPO_DIR/waybar/config" 2>/dev/null || true
cp ~/.config/waybar/style.css "$REPO_DIR/waybar/style.css" 2>/dev/null || true
cp ~/.config/mako/config "$REPO_DIR/mako/" 2>/dev/null || true

if [ -d "$HOME/scripts" ]; then
    cp ~/scripts/*.py ~/scripts/*.sh "$REPO_DIR/scripts/" 2>/dev/null || true
fi

echo "==> Checking for hardcoded user paths or usernames..."
HARDCODES=$(grep -rn "dexo\|DXpc\|/home/[a-z]" "$REPO_DIR/hypr" "$REPO_DIR/kitty" "$REPO_DIR/waybar" "$REPO_DIR/scripts" 2>/dev/null | grep -v "usuario" || true)

if [ -n "$HARDCODES" ]; then
    echo "[!] WARNING: Found hardcoded personal paths that need fixing before public release:"
    echo "$HARDCODES"
else
    echo "[✓] All configs scrubbed and verified generic!"
fi

echo ""
echo "==> Repo files updated. Run 'git status' or 'git diff' inside $REPO_DIR to review."
