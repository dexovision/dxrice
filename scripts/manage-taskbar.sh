#!/usr/bin/env bash
set -euo pipefail

CONFIG=~/.config/waybar/config
CSS=~/.config/waybar/style.css

restart_waybar() {
    pkill -9 waybar 2>/dev/null || true
    sleep 0.5
    setsid waybar >/dev/null 2>&1 < /dev/null &
    disown
}

add_app() {
    read -rp "App name (shown on the bar): " LABEL
    [ -z "$LABEL" ] && { echo "No name entered, cancelled."; return; }

    read -rp "Command to run (e.g. firefox, discord, spotify): " CMD
    [ -z "$CMD" ] && { echo "No command entered, cancelled."; return; }

    SLUG=$(echo "$LABEL" | tr '[:upper:]' '[:lower:]' | tr -d ' ')
    MODID="custom/$SLUG"
    CSSID="custom-$SLUG"

    python3 << PYEOF
import json
with open("$CONFIG") as f:
    cfg = json.load(f)
modid = "$MODID"
cfg[modid] = {
    "format": "$LABEL",
    "on-click": "sh -c '$CMD >/dev/null 2>&1 &'",
    "tooltip": False
}
if modid not in cfg["modules-left"]:
    cfg["modules-left"].append(modid)
with open("$CONFIG", "w") as f:
    json.dump(cfg, f, indent=4)
PYEOF

    cat >> "$CSS" << CSSEOF

#$CSSID {
    background: rgba(18, 20, 26, 0.55);
    color: #e6e6e6;
    padding: 4px 12px;
    margin: 2px 0;
    border-radius: 12px;
    border: 1px solid rgba(255, 255, 255, 0.08);
}
#$CSSID:hover {
    background: rgba(255, 255, 255, 0.12);
    color: #ffffff;
}
CSSEOF

    restart_waybar
    echo "Added '$LABEL' to your taskbar."
}

remove_app() {
    echo "Current taskbar apps:"
    python3 -c "
import json
with open('$CONFIG') as f:
    cfg = json.load(f)
for i, m in enumerate(cfg.get('modules-left', [])):
    if m.startswith('custom/'):
        print(f'  {i}: {m}  ->  {cfg.get(m, {}).get(\"format\", \"\")}')"

    echo ""
    read -rp "Enter the number to remove (or 'q' to cancel): " CHOICE
    [ "$CHOICE" = "q" ] && return

    if ! [[ "$CHOICE" =~ ^[0-9]+$ ]]; then
        echo "Invalid input."
        return
    fi

    python3 << PYEOF
import json
with open("$CONFIG") as f:
    cfg = json.load(f)
mods = cfg.get("modules-left", [])
idx = $CHOICE
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
        with open("$CONFIG", "w") as f:
            json.dump(cfg, f, indent=4)
        print(f"Removed {modid}.")
PYEOF

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
