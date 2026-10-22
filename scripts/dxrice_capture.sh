#!/bin/sh
# Screenshots and screen recordings for the bar's capture section.
#
#   dxrice_capture.sh shot region|screen     grim (+ slurp for a region): saved
#                                            to ~/Pictures/Screenshots/<date>.png
#                                            and copied to the clipboard, the
#                                            same as the PRINT keybinds
#   dxrice_capture.sh record region|screen [none|desktop|mic]
#                                            wf-recorder into
#                                            ~/Videos/Recordings/<date>.mp4, in
#                                            the foreground: it returns when
#                                            the recording ends. The sound, if
#                                            any: what is playing (the default
#                                            output's monitor) or the default
#                                            microphone, as PipeWire's pulse
#                                            server names them. It is chosen
#                                            before recording: wf-recorder
#                                            can't add or drop it midway
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
    # a region from slurp, or nothing (cancelled). Its stdin must not be a
    # pipe: slurp reads predefined boxes from a stdin that isn't a terminal
    # and shows nothing until that ends -- run from the shell (a Process with
    # its stdin held open) it waited there forever, invisible. With a file
    # given ($1), slurp's own pid goes in it, so `stop` can cancel the pick.
    slurp < /dev/null 2>/dev/null &
    picker=$!
    [ -n "${1:-}" ] && echo "$picker" > "$1"
    wait "$picker"
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
    pick_file="$state_dir/recording.pick"
    audio=""
    case "${3:-none}" in
    desktop) dev="$(pactl get-default-sink 2>/dev/null)" && [ -n "$dev" ] && audio="--audio=$dev.monitor" ;;
    mic) dev="$(pactl get-default-source 2>/dev/null)" && [ -n "$dev" ] && audio="--audio=$dev" ;;
    esac
    if [ "${2:-screen}" = "region" ]; then
        # while the region is being picked, `stop` cancels the pick
        geom="$(pick "$pick_file")"
        ok=$?
        rm -f "$pick_file"
        [ $ok -eq 0 ] && [ -n "$geom" ] || exit 1
        wf-recorder $audio -g "$geom" -f "$file" >/dev/null 2>&1 &
    else
        wf-recorder $audio -f "$file" >/dev/null 2>&1 &
    fi
    rec=$!
    echo "$rec" > "$pid_file"
    # the shell's cue that the recording itself has begun (its timer starts here)
    echo started
    # Whatever stops this script (the shell going away mid-recording) stops
    # the recording with it, so the file is finished rather than the
    # recorder left running unseen; TERM after 3 s, as `stop` does.
    trap 'kill -INT "$rec" 2>/dev/null; ( sleep 3; kill -TERM "$rec" 2>/dev/null ) &' TERM HUP INT
    wait "$rec"
    status=$?
    # (a trapped signal returns from `wait` early: wait for the file to close)
    while kill -0 "$rec" 2>/dev/null; do wait "$rec"; status=$?; done
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
    # still picking a region: cancel the pick (the script then ends, recording nothing)
    if [ ! -f "$pid_file" ] && [ -f "$state_dir/recording.pick" ]; then
        kill -TERM "$(cat "$state_dir/recording.pick")" 2>/dev/null
        exit 0
    fi
    [ -f "$pid_file" ] || exit 1
    rec="$(cat "$pid_file")"
    kill -INT "$rec" 2>/dev/null || exit 0
    i=0
    while kill -0 "$rec" 2>/dev/null && [ $i -lt 30 ]; do sleep 0.1; i=$((i + 1)); done
    kill -0 "$rec" 2>/dev/null && kill -TERM "$rec" 2>/dev/null
    exit 0
    ;;
*)
    echo "usage: $0 shot region|screen | record region|screen [none|desktop|mic] | stop" >&2
    exit 2
    ;;
esac
