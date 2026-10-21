#!/bin/sh
# Screenshots and screen recordings for the bar's capture section.
#
#   dxrice_capture.sh shot region|screen     grim (+ slurp for a region): saved
#                                            to ~/Pictures/Screenshots/<date>.png
#                                            and copied to the clipboard, the
#                                            same as the PRINT keybinds
#   dxrice_capture.sh record region|screen   wf-recorder into
#                                            ~/Videos/Recordings/<date>.mp4, in
#                                            the foreground: it returns when
#                                            the recording ends
#   dxrice_capture.sh stop                   ends a recording (SIGINT, so
#                                            wf-recorder finishes the file;
#                                            SIGTERM after 3 s if it is still
#                                            running -- a background job of a
#                                            script starts with SIGINT ignored,
#                                            and only a program that installs
#                                            its own handler hears it)
#
# A cancelled region pick (Escape in slurp) does nothing and exits 1. Each
# finished capture sends a notification naming the file.
set -u

stamp() { date +%Y-%m-%d_%H-%M-%S; }
state_dir="${XDG_RUNTIME_DIR:-/tmp}/dxrice"
pid_file="$state_dir/recording.pid"

pick() {
    # a region from slurp, or nothing (cancelled)
    slurp 2>/dev/null
}

case "${1:-}" in
shot)
    dir="$HOME/Pictures/Screenshots"
    mkdir -p "$dir"
    file="$dir/$(stamp).png"
    if [ "${2:-region}" = "region" ]; then
        geom="$(pick)" || exit 1
        [ -n "$geom" ] || exit 1
        grim -g "$geom" "$file" || exit 1
    else
        grim "$file" || exit 1
    fi
    wl-copy < "$file" 2>/dev/null
    notify-send -a "Screenshot" "Screenshot saved" "$file" 2>/dev/null
    ;;
record)
    dir="$HOME/Videos/Recordings"
    mkdir -p "$dir" "$state_dir"
    file="$dir/$(stamp).mp4"
    if [ "${2:-screen}" = "region" ]; then
        geom="$(pick)" || exit 1
        [ -n "$geom" ] || exit 1
        wf-recorder -g "$geom" -f "$file" >/dev/null 2>&1 &
    else
        wf-recorder -f "$file" >/dev/null 2>&1 &
    fi
    rec=$!
    echo "$rec" > "$pid_file"
    wait "$rec"
    status=$?
    rm -f "$pid_file"
    if [ -s "$file" ]; then
        notify-send -a "Screen recording" "Recording saved" "$file" 2>/dev/null
    else
        rm -f "$file"
        notify-send -a "Screen recording" "Recording failed" "wf-recorder exited with $status" 2>/dev/null
        exit 1
    fi
    ;;
stop)
    [ -f "$pid_file" ] || exit 1
    rec="$(cat "$pid_file")"
    kill -INT "$rec" 2>/dev/null || exit 0
    i=0
    while kill -0 "$rec" 2>/dev/null && [ $i -lt 30 ]; do sleep 0.1; i=$((i + 1)); done
    kill -0 "$rec" 2>/dev/null && kill -TERM "$rec" 2>/dev/null
    exit 0
    ;;
*)
    echo "usage: $0 shot region|screen | record region|screen | stop" >&2
    exit 2
    ;;
esac
