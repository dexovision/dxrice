#!/usr/bin/env bash
set -euo pipefail

CONFIG="$HOME/.config/waybar/config"

# Locate dotfiles path if running inside dotfiles repo
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_CONFIG="$REPO_DIR/waybar/config"

restart_waybar() {
    pkill -x waybar 2>/dev/null || true
    sleep 0.3
    setsid waybar >/dev/null 2>&1 < /dev/null &
    disown
}

sync_repo() {
    if [ -f "$REPO_CONFIG" ]; then
        cp "$CONFIG" "$REPO_CONFIG"
        echo "Synced changes to $REPO_CONFIG"
    fi
}

add_app() {
    read -rp "App name or Nerd Font Icon (e.g. 󰄛 or Kitty): " LABEL
    [ -z "$LABEL" ] && { echo "No name entered, cancelled."; return; }

    read -rp "Command to run (e.g. kitty, firefox): " CMD
    [ -z "$CMD" ] && { echo "No command entered, cancelled."; return; }

    SLUG=$(echo "$LABEL" | tr "[:upper:]" "[:lower:]" | tr -cd "a-zA-Z0-9")
    [ -z "$SLUG" ] && SLUG="app$(date +%s)"
    MODID="custom/$SLUG"

    python3 - "$CONFIG" "$MODID" "$LABEL" "$CMD" << 'PYEOF'
import sys, json

config_path, modid, label, cmd = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]

with open(config_path, "r") as f:
    cfg = json.load(f)

cfg[modid] = {
    "format": label,
    "on-click": f"sh -c '{cmd} >/dev/null 2>&1 &'",
    "tooltip": False
}

if "modules-left" not in cfg:
    cfg["modules-left"] = []

if modid not in cfg["modules-left"]:
    cfg["modules-left"].append(modid)

with open(config_path, "w") as f:
    json.dump(cfg, f, indent=4)
PYEOF

    sync_repo
    restart_waybar
    echo "Added '$LABEL' to your taskbar."
}

remove_app() {
    echo "Current taskbar apps:"
    python3 - "$CONFIG" << 'PYEOF'
import sys, json
config_path = sys.argv[1]
with open(config_path) as f:
    cfg = json.load(f)
for i, m in enumerate(cfg.get("modules-left", [])):
    if m.startswith("custom/"):
        fmt = cfg.get(m, {}).get("format", "")
        print(f"  {i}: {m}  ->  {fmt}")
PYEOF

    echo ""
    read -rp "Enter the number to remove (or 'q' to cancel): " CHOICE
    [ "$CHOICE" = "q" ] && return

    if ! [[ "$CHOICE" =~ ^[0-9]+$ ]]; then
        echo "Invalid input."
        return
    fi

    python3 - "$CONFIG" "$CHOICE" << 'PYEOF'
import sys, json
config_path = sys.argv[1]
idx = int(sys.argv[2])

with open(config_path) as f:
    cfg = json.load(f)

mods = cfg.get("modules-left", [])
if idx < 0 or idx >= len(mods):
    print("Index out of range, nothing removed.")
else:
    modid = mods[idx]
    if not modid.startswith("custom/"):
        print(f"'{modid}' is a built-in module, not removing it for safety.")
    else:
        mods.pop(idx)
        cfg["modules-left"] = mods
        if modid in cfg:
            del cfg[modid]
        with open(config_path, "w") as f:
            json.dump(cfg, f, indent=4)
        print(f"Removed {modid}.")
PYEOF

    sync_repo
    restart_waybar
}

while true; do
    echo ""
    echo "=== Taskbar Manager ==="
    echo "1) Add app"
    echo "2) Remove app"
    echo "q) Quit"
    read -rp "Choice: " OPT

    case "$OPT" in
        1) add_app ;;
        2) remove_app ;;
        q|Q) break ;;
        *) echo "Invalid choice." ;;
    esac
done
