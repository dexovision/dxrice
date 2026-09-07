#!/usr/bin/env bash
set -euo pipefail

CONFIG=~/.config/waybar/config

while true; do
    echo ""
    echo "Current taskbar order (modules-left):"
    python3 -c "
import json
with open('$CONFIG') as f:
    cfg = json.load(f)
for i, m in enumerate(cfg.get('modules-left', [])):
    print(f'  {i}: {m}')
"
    echo ""
    read -rp "Enter the number of the app to move (or 'q' to quit): " CHOICE

    [ "$CHOICE" = "q" ] && break

    if ! [[ "$CHOICE" =~ ^[0-9]+$ ]]; then
        echo "Invalid input, enter a number or 'q'."
        continue
    fi

    read -rp "Move it (u)p or (d)own? " DIR

    case "$DIR" in
        u|U) DIRECTION="up" ;;
        d|D) DIRECTION="down" ;;
        *) echo "Invalid direction, enter u or d."; continue ;;
    esac

    python3 << PYEOF
import json

with open("$CONFIG") as f:
    cfg = json.load(f)

mods = cfg.get("modules-left", [])
idx = $CHOICE
direction = "$DIRECTION"

if idx < 0 or idx >= len(mods):
    print("Index out of range, nothing changed.")
else:
    if direction == "up" and idx > 0:
        mods[idx-1], mods[idx] = mods[idx], mods[idx-1]
    elif direction == "down" and idx < len(mods) - 1:
        mods[idx+1], mods[idx] = mods[idx], mods[idx+1]
    cfg["modules-left"] = mods
    with open("$CONFIG", "w") as f:
        json.dump(cfg, f, indent=4)
    print("Moved.")
PYEOF

    pkill waybar 2>/dev/null || true
    sleep 0.3
    setsid waybar >/dev/null 2>&1 < /dev/null &
    disown
done

echo "Done — taskbar order saved."
