#!/usr/bin/env bash
set -euo pipefail

CONFIG="$HOME/.config/waybar/config"
# Hardcoded rather than derived from this script's own location: this script
# gets deployed to ~/scripts/manage-taskbar.sh, and deriving the repo path
# from there (../..) used to silently resolve to $HOME and make sync_repo a
# no-op -- your taskbar edits never made it back into git.
REPO_CONFIG="$HOME/dotfiles-rice/waybar/config"
SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

restart_waybar() {
    pkill -x waybar 2>/dev/null || true
    sleep 0.3
    setsid waybar >/dev/null 2>&1 < /dev/null &
    disown
}

sync_repo() {
    mkdir -p "$(dirname "$REPO_CONFIG")"
    cp "$CONFIG" "$REPO_CONFIG"
}

icon_for() {
    python3 "$SCRIPTS_DIR/rice_icons.py" "$@" 2>/dev/null || echo ""
}

show_modules() {
    python3 - "$CONFIG" << 'PYEOF'
import sys, json
with open(sys.argv[1]) as f:
    cfg = json.load(f)
mods = cfg.get("modules-left", [])
print("\nCurrent Taskbar Modules (modules-left):")
for i, m in enumerate(mods):
    entry = cfg.get(m, {}) if m.startswith("custom/") else {}
    label = m
    if m.startswith("custom/"):
        name = entry.get("tooltip-format") or entry.get("format", "")
        label = f"{m}  [{entry.get('format','')}]  {name}"
    print(f"  {i}: {label}")
print()
PYEOF
}

# List installed .desktop apps and let the user pick one by number.
# Sets PICKED_NAME / PICKED_CMD / PICKED_ICON_HINT on success.
pick_installed_app() {
    local list
    list=$(python3 - << 'PYEOF'
import glob, os, re

dirs = ["/usr/share/applications", os.path.expanduser("~/.local/share/applications")]
seen = set()
entries = []
for d in dirs:
    for path in sorted(glob.glob(os.path.join(d, "*.desktop"))):
        try:
            text = open(path, encoding="utf-8", errors="ignore").read()
        except OSError:
            continue
        if "NoDisplay=true" in text:
            continue
        name_m = re.search(r"^Name=(.+)$", text, re.MULTILINE)
        exec_m = re.search(r"^Exec=(.+)$", text, re.MULTILINE)
        icon_m = re.search(r"^Icon=(.+)$", text, re.MULTILINE)
        if not name_m or not exec_m:
            continue
        name = name_m.group(1).strip()
        if name in seen:
            continue
        seen.add(name)
        cmd = re.sub(r"%[a-zA-Z]", "", exec_m.group(1)).strip()
        icon = icon_m.group(1).strip() if icon_m else ""
        entries.append((name, cmd, icon))

entries.sort(key=lambda e: e[0].lower())
for name, cmd, icon in entries:
    print(f"{name}\t{cmd}\t{icon}")
PYEOF
    )

    if [ -z "$list" ]; then
        echo "No installed .desktop applications found."
        return 1
    fi

    local i=0
    local names=()
    while IFS=$'\t' read -r name cmd icon; do
        names+=("$name"$'\t'"$cmd"$'\t'"$icon")
        printf "  %3d) %s\n" "$i" "$name"
        i=$((i + 1))
    done <<< "$list"

    read -rp "Pick a number (or 'q' to cancel, or type to search by name): " CHOICE
    if [ "$CHOICE" = "q" ]; then
        return 1
    fi
    if ! [[ "$CHOICE" =~ ^[0-9]+$ ]]; then
        local matches=()
        local idx=0
        for entry in "${names[@]}"; do
            local nm="${entry%%$'\t'*}"
            if [[ "${nm,,}" == *"${CHOICE,,}"* ]]; then
                matches+=("$idx")
            fi
            idx=$((idx + 1))
        done
        if [ "${#matches[@]}" -eq 0 ]; then
            echo "No match for '$CHOICE'."
            return 1
        elif [ "${#matches[@]}" -eq 1 ]; then
            CHOICE="${matches[0]}"
        else
            echo "Multiple matches:"
            for m in "${matches[@]}"; do
                local nm="${names[$m]%%$'\t'*}"
                echo "  $m) $nm"
            done
            read -rp "Pick a number: " CHOICE
        fi
    fi
    if [ -z "${names[$CHOICE]:-}" ]; then
        echo "Invalid choice."
        return 1
    fi

    PICKED_NAME="${names[$CHOICE]%%$'\t'*}"
    local rest="${names[$CHOICE]#*$'\t'}"
    PICKED_CMD="${rest%%$'\t'*}"
    PICKED_ICON_HINT="${rest#*$'\t'}"
    return 0
}

add_module() {
    local label="$1" cmd="$2" icon_hint="$3"
    local slug modid glyph
    slug=$(echo "$label" | tr "[:upper:]" "[:lower:]" | tr -cd "a-zA-Z0-9")
    [ -z "$slug" ] && slug="app$(date +%s)"
    modid="custom/$slug"
    glyph=$(icon_for "$label" "$cmd" "$icon_hint")

    python3 - "$CONFIG" "$modid" "$label" "$cmd" "$glyph" << 'PYEOF'
import sys, json
config_path, modid, label, cmd, glyph = sys.argv[1:6]
with open(config_path) as f:
    cfg = json.load(f)
cfg[modid] = {
    "format": glyph,
    "on-click": f"sh -c '{cmd} >/dev/null 2>&1 &'",
    "tooltip": True,
    "tooltip-format": label,
}
cfg.setdefault("modules-left", [])
if modid not in cfg["modules-left"]:
    cfg["modules-left"].append(modid)
with open(config_path, "w") as f:
    json.dump(cfg, f, indent=4)
PYEOF

    sync_repo
    restart_waybar
    echo "Added '$label' ($cmd) with icon '$glyph'."
}

add_app_browse() {
    if pick_installed_app; then
        add_module "$PICKED_NAME" "$PICKED_CMD" "$PICKED_ICON_HINT"
    fi
}

add_app_manual() {
    read -rp "Display name (used for the hover tooltip, e.g. Firefox): " LABEL
    [ -z "$LABEL" ] && { echo "No name entered, cancelled."; return; }
    read -rp "Command to run (e.g. firefox): " CMD
    [ -z "$CMD" ] && { echo "No command entered, cancelled."; return; }
    add_module "$LABEL" "$CMD" ""
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

fix_icons() {
    echo "Re-deriving icons for every existing shortcut from its command..."
    python3 - "$CONFIG" "$SCRIPTS_DIR" << 'PYEOF'
import json, sys
sys.path.insert(0, sys.argv[2])
from rice_icons import icon_for

config_path = sys.argv[1]
with open(config_path) as f:
    cfg = json.load(f)

changed = []
for modid in cfg.get("modules-left", []):
    if not modid.startswith("custom/") or modid == "custom/launcher":
        continue
    entry = cfg.get(modid)
    if not entry:
        continue
    old_format = entry.get("format", "")
    name = entry.get("tooltip-format") or old_format
    glyph = icon_for(name, entry.get("on-click", ""))
    entry["format"] = glyph
    entry["tooltip"] = True
    entry["tooltip-format"] = name
    changed.append((modid, name, glyph))

with open(config_path, "w") as f:
    json.dump(cfg, f, indent=4)

for modid, name, glyph in changed:
    print(f"  {modid}: '{name}' -> {glyph}")
PYEOF
    sync_repo
    restart_waybar
    echo "Done."
}

while true; do
    echo ""
    echo "=== Universal Taskbar Manager ==="
    echo "1) View taskbar modules"
    echo "2) Add app shortcut (browse installed apps)"
    echo "3) Add custom shortcut (type name + command)"
    echo "4) Remove app shortcut"
    echo "5) Reorder modules (Up/Down)"
    echo "6) Fix icons on existing shortcuts"
    echo "q) Quit"
    read -rp "Choice: " OPT

    case "$OPT" in
        1) show_modules ;;
        2) add_app_browse ;;
        3) add_app_manual ;;
        4) remove_app ;;
        5) reorder_app ;;
        6) fix_icons ;;
        q|Q) break ;;
        *) echo "Invalid option." ;;
    esac
done
