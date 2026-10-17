#!/usr/bin/env python3
"""Measure whether the desktop overview's surface is being faded by the
compositor, from a screen recording of SUPER+Tab.

Why it can be told from a recording: the overview covers the top bar with
the wallpaper. If the overview takes the screen over in one frame, the bar
is gone in one or two frames. If Hyprland fades the overlay surface in or
out (animation leaves fadeLayersIn / fadeLayersOut, inherited from `fade`),
the bar and the real windows show through it for ~300 ms -- the doubled
windows seen on a real desktop.

The probe takes the clock in the middle of the bar and, for every frame, its
Pearson correlation with the same box in the first frame (the plain
desktop). A uniform dim doesn't change that correlation, so it follows the
bar being replaced, not the overview's darkening. Each time it goes from
"the bar" to "not the bar" (or back), the frames in between are the
transition; a clean handover is 1-2 frames, a compositor fade is 3 or more
(on a measured real desktop: 9 frames opening, 4 closing).

    python3 scripts/dxrice_overview_probe.py RECORDING.mp4 [--box X0,Y0,X1,Y1]

After each close it also measures how long the desktop keeps sliding once
the overlay has gone (a phase-correlation estimate of how far the whole
picture moves from frame to frame, the top bar left out): windows the
compositor is still moving into place after a panning click -- what showed
as a ghost sliding in from the side after picking another window.

Exit 0 when every transition is a clean handover and nothing slides after
a close, 3 when one is a compositor fade, 4 when the desktop keeps sliding
after a close, 1 when no transition was found. The desktop at the start of the recording must
show the bar's clock, and nothing else may cover it during a transition (a
window over the clock reads as a slow "transition" that isn't one).

The box is in source pixels (default: the clock in the middle of the top bar,
x 870..1050, y 2..46 of a 1080p recording, scaled to the video; give --box
if your bar is laid out differently). Needs ffmpeg and numpy.
"""
import subprocess
import sys

DEFAULT_BOX = (870, 2, 1050, 46)
HIGH, LOW = 0.80, 0.50      # correlation: the bar there / the bar gone
CLEAN_MAX_FRAMES = 2        # a transition longer than this is a fade


def correlations(strips):
    """Pearson r of every strip (array [T, h, w]) with the first one."""
    import numpy as np
    flat = strips.reshape(len(strips), -1).astype(float)
    flat = flat - flat.mean(axis=1, keepdims=True)
    ref = flat[0]
    den = np.sqrt((flat * flat).sum(axis=1) * (ref * ref).sum())
    den[den == 0] = 1e-9
    return (flat @ ref) / den


MIN_RUN = 3                 # frames a state must hold to count (screen-recording noise)


def transitions(r, times):
    """[(kind, first_frame, last_frame, frames, ms)]: every time r goes from
    one steady state ("bar" r >= HIGH, "gone" r <= LOW, each held for MIN_RUN
    frames) to the other, and the number of frames it took. kind is "covers"
    (bar -> gone) or "uncovers"."""
    runs = []                       # (state, first, last)
    for i, v in enumerate(r):
        state = "bar" if v >= HIGH else ("gone" if v <= LOW else None)
        if runs and state is not None and runs[-1][0] == state and runs[-1][2] == i - 1:
            runs[-1] = (state, runs[-1][1], i)
        elif state is not None:
            runs.append((state, i, i))
    steady = [x for x in runs if x[2] - x[1] + 1 >= MIN_RUN]
    out = []
    for prev, nxt in zip(steady, steady[1:]):
        if prev[0] != nxt[0]:
            a, b = prev[2], nxt[1]
            out.append(("covers" if nxt[0] == "gone" else "uncovers", a, b, b - a, (times[b] - times[a]) * 1000))
    return out


SLIDE_SCALE = 4             # frames are compared at 1/4 size: shifts in 4 px steps
SETTLED_PAIRS = 3           # this many still frame pairs in a row: it has settled
SLIDE_MAX_FRAMES = 2        # sliding longer than this after the overlay went is the ghost
SLIDE_LOOK = 60             # frames examined after each close


def global_shift(f0, f1):
    """(dx, dy) in full-size px by which the picture moved from f0 to f1, by
    phase correlation (a uniform fade or changing content inside a window
    doesn't read as a shift), and how clear the peak is (0..1)."""
    import numpy as np
    a, b = np.fft.fft2(f0 - f0.mean()), np.fft.fft2(f1 - f1.mean())
    r = a * np.conj(b)
    r /= np.abs(r) + 1e-9
    c = np.fft.ifft2(r).real
    y, x = np.unravel_index(np.argmax(c), c.shape)
    h, w = c.shape
    if y > h // 2:
        y -= h
    if x > w // 2:
        x -= w
    return -x * SLIDE_SCALE, -y * SLIDE_SCALE, float(c.max())


def slide_after(frames, start, stop=None):
    """How many frames after `start` (the first frame without the overlay)
    the desktop keeps sliding, and the total distance (px): windows still
    being moved by the compositor after the overview let go. Ends at the
    first SETTLED_PAIRS still pairs in a row, or at `stop` (the next
    transition: an overview opening again isn't a slide)."""
    still, moving, last_moving, dist = 0, 0, start, 0.0
    end = min(start + SLIDE_LOOK, len(frames) - 1, stop if stop is not None else len(frames))
    for i in range(start, end):
        dx, dy, _peak = global_shift(frames[i], frames[i + 1])
        if dx or dy:
            moving += 1
            last_moving = i + 1
            dist += (dx * dx + dy * dy) ** 0.5
            still = 0
        else:
            still += 1
            if still >= SETTLED_PAIRS:
                break
    return (last_moving - start if moving else 0), dist


def slid_during(frames, a, b):
    """Frame pairs in which the whole picture shifted between frames a-2 and
    b+3. The overview takes the screen over and gives it back in place; a
    "transition" during which everything slides is a window or the desktop
    moving under the clock (a SUPER+arrow pan, a window dragged over it)."""
    n = 0
    for i in range(max(0, a - 2), min(b + 3, len(frames) - 1)):
        dx, dy, _peak = global_shift(frames[i], frames[i + 1])
        n += bool(dx or dy)
    return n


def load_frames(path, skip_top=56):
    """Every frame, grey, at 1/SLIDE_SCALE size, without the top bar (its
    clock changes on its own)."""
    import numpy as np
    w, h = 1920 // SLIDE_SCALE, 1080 // SLIDE_SCALE
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-fps_mode", "passthrough", "-vf", f"scale={w}:{h}",
                          "-pix_fmt", "gray", "-f", "rawvideo", "-"], capture_output=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, h, w)[:, skip_top // SLIDE_SCALE:, :].astype(float)


def load(path, box):
    import numpy as np
    p = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=width,height", "-of", "csv=p=0", path], capture_output=True, text=True)
    w, h = (int(v) for v in p.stdout.strip().strip(",").split(",")[:2])
    sx, sy = w / 1920.0, h / 1080.0
    x0, y0, x1, y1 = box
    x0, x1, y0, y1 = int(x0 * sx), int(x1 * sx), int(y0 * sy), int(y1 * sy)
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-fps_mode", "passthrough",
                          "-vf", f"crop={x1 - x0}:{y1 - y0}:{x0}:{y0}", "-pix_fmt", "gray", "-f", "rawvideo", "-"],
                         capture_output=True).stdout
    strips = np.frombuffer(raw, np.uint8).reshape(-1, y1 - y0, x1 - x0)
    t = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "frame=pts_time",
                        "-of", "csv=p=0", path], capture_output=True, text=True).stdout.split()
    times = [float(v.strip(",")) for v in t][:len(strips)]
    return strips, times


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    box = DEFAULT_BOX
    if "--box" in argv:
        box = tuple(int(v) for v in argv[argv.index("--box") + 1].split(","))
    strips, times = load(argv[1], box)
    r = correlations(strips)
    found = transitions(r, times)
    if not found:
        print("no overview transition found (the bar strip never left the desktop's look).")
        return 1
    worst, worst_slide = 0, 0
    frames_all = load_frames(argv[1])
    for k, (kind, a, b, frames, ms) in enumerate(found):
        if slid_during(frames_all, a, b) >= 3:
            print(f"{'(slide)':9s} t={times[a]:6.3f}s  something slid over the clock -- a pan or a window, "
                  f"not the overview; not judged")
            continue
        verdict = "clean handover" if frames <= CLEAN_MAX_FRAMES else "COMPOSITOR FADE (two copies on screen)"
        worst = max(worst, frames)
        print(f"{kind:9s} t={times[a]:6.3f}s  {frames:3d} frames  {ms:6.0f} ms   {verdict}")
        if kind == "uncovers":
            nxt = found[k + 1][1] if k + 1 < len(found) else None
            n, dist = slide_after(frames_all, b, nxt)
            end = min(b + n, len(times) - 1)
            worst_slide = max(worst_slide, n)
            what = ("settled" if n <= SLIDE_MAX_FRAMES else
                    "WINDOWS STILL SLIDING after the overview closed (the ghost)")
            print(f"          then {n:3d} frames {(times[end] - times[b]) * 1000:6.0f} ms of sliding, "
                  f"{dist:5.0f} px   {what}")
    if worst > CLEAN_MAX_FRAMES:
        return 3
    return 4 if worst_slide > SLIDE_MAX_FRAMES else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
