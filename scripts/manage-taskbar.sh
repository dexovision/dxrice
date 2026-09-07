#!/usr/bin/env bash
set -euo pipefail

CONFIG="$HOME/.config/waybar/config"
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
    fi
}

show_modules() {
    python3 - "$CONFIG" << 'PYEOF'
import sys, json
with open(sys.argv[1]) as f:
    cfg = json.load(f)
mods = cfg.get("modules-left", [])
print("\nCurrent Taskbar Modules (modules-left):")
for i, m in enumerate(mods):
    label = m
    if m.startswith("custom/"):
        label = f"{m} -> {cfg.get(m, {}).get('format', '')}"
    print(f"  {i}: {label}")
print()
PYEOF
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
    echo "Added '$LABEL' successfully."
}

remove_app() {
    show_modules
    read -rp "Enter the index number to remove (or 'q' to cancel): " CHOICE
    [ "$CHOICE" = "q" ] && return
    if ! [[ "$CHOICE" =~ ^[0-9]+$ ]]; then
        echo "Invalid input."
        return
    fi

    python3 - "$CONFIG" "$CHOICE" << 'PYEOF'
import sys, json
config_path, idx = sys.argv[1], int(sys.argv[2])
with open(config_path) as f:
    cfg = json.load(f)
mods = cfg.get("modules-left", [])
if idx < 0 or idx >= len(mods):
    print("Index out of range.")
else:
    modid = mods[idx]
    mods.pop(idx)
    cfg["modules-left"] = mods
    if modid in cfg and modid.startswith("custom/"):
        del cfg[modid]
    with open(config_path, "w") as f:
        json.dump(cfg, f, indent=4)
    print(f"Removed {modid}.")
PYEOF

    sync_repo
    restart_waybar
}

reorder_app() {
    show_modules
    read -rp "Enter the index number of the module to move (or 'q' to cancel): " CHOICE
    [ "$CHOICE" = "q" ] && return
    if ! [[ "$CHOICE" =~ ^[0-9]+$ ]]; then
        echo "Invalid input."
        return
    fi

    read -rp "Move (u)p or (d)own? " DIR
    case "$DIR" in
        u|U) DIRECTION="up" ;;
        d|D) DIRECTION="down" ;;
        *) echo "Invalid direction."; return ;;
    esac

    python3 - "$CONFIG" "$CHOICE" "$DIRECTION" << 'PYEOF'
import sys, json
config_path, idx, direction = sys.argv[1], int(sys.argv[2]), sys.argv[3]
with open(config_path) as f:
    cfg = json.load(f)
mods = cfg.get("modules-left", [])
if idx < 0 or idx >= len(mods):
    print("Index out of range.")
else:
    if direction == "up" and idx > 0:
        mods[idx-1], mods[idx] = mods[idx], mods[idx-1]
    elif direction == "down" and idx < len(mods) - 1:
        mods[idx+1], mods[idx] = mods[idx], mods[idx+1]
    cfg["modules-left"] = mods
    with open(config_path, "w") as f:
        json.dump(cfg, f, indent=4)
    print("Reordered successfully.")
PYEOF

    sync_repo
    restart_waybar
}

while true; do
    echo ""
    echo "=== Universal Taskbar Manager ==="
    echo "1) View taskbar modules"
    echo "2) Add app shortcut"
    echo "3) Remove app shortcut"
    echo "4) Reorder modules (Up/Down)"
    echo "q) Quit"
    read -rp "Choice: " OPT

    case "$OPT" in
        1) show_modules ;;
        2) add_app ;;
        3) remove_app ;;
        4) reorder_app ;;
        q|Q) break ;;
        *) echo "Invalid option." ;;
    esac
done
