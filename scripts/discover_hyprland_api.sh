#!/usr/bin/env bash
set -uo pipefail

echo "== Hyprland version =="
hyprctl version | head -3
echo

echo "== Methods available in hl.dsp.window.* =="
hyprctl repl 'local t={} for k,v in pairs(hl.dsp.window) do table.insert(t,k) end table.sort(t) return table.concat(t, ", ")'
echo "   (if 'resize' does not appear in this list, moveactive/resizewindowpixel"
echo "    may live under a different sub-namespace, or 'move' may handle both)"
echo

ADDR=$(hyprctl activewindow -j 2>/dev/null | python3 -c 'import json,sys
try:
    print(json.load(sys.stdin)["address"])
except Exception:
    print("")' )

if [ -z "$ADDR" ]; then
    echo "No active window detected. Open/focus a floating window and run this again."
    exit 1
fi

echo "== Active window: $ADDR =="
echo

echo "== Testing move to (100, 100) with the syntax hypr_ipc.py uses =="
OUT=$(hyprctl dispatch "hl.dsp.window.move({ window = \"address:$ADDR\", coords = { 100, 100 }, mode = \"exact\" })" 2>&1)
echo "$OUT"
if echo "$OUT" | grep -qi "error"; then
    echo
    echo "-> Failed. Try these variants by hand and see which one doesn't error:"
    echo "   hyprctl dispatch 'hl.dsp.window.move({ window = \"address:$ADDR\", x = 100, y = 100 })'"
    echo "   hyprctl dispatch 'hl.dsp.window.move({ window = \"address:$ADDR\", coords = {x=100, y=100} })'"
    echo "   hyprctl dispatch 'hl.dsp.window.move({ window = \"address:$ADDR\", position = {100, 100} })'"
else
    echo "-> OK. Visually confirm the window moved to (100,100)."
    echo "   If it did NOT move but no error was returned (this happened before with"
    echo "   resizewindowpixel on older versions), the field is being accepted but"
    echo "   ignored: try the variants above anyway."
fi
echo

echo "== Testing resize to 800x600 =="
OUT=$(hyprctl dispatch "hl.dsp.window.resize({ window = \"address:$ADDR\", size = { 800, 600 }, mode = \"exact\" })" 2>&1)
echo "$OUT"
if echo "$OUT" | grep -qi "error"; then
    echo
    echo "-> Failed. 'resize' may not exist as a separate dispatcher. Check the"
    echo "   list above (hl.dsp.window.*) and try whether 'move' accepts a"
    echo "   'size' field in the same call, e.g.:"
    echo "   hyprctl dispatch 'hl.dsp.window.move({ window = \"address:$ADDR\", size = {800,600} })'"
else
    echo "-> OK. Visually confirm the window is now 800x600."
fi

echo
echo "== Once you confirm the correct field names, edit ONLY these two functions"
echo "   in hypr_ipc.py: move_window_exact_lua() and resize_window_exact_lua()"
