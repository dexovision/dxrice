#!/usr/bin/env python3
"""Derives a full DXrice glass/border color palette from the current
wallpaper -- the "theme actually matches the wallpaper" trick real end-4/
caelestia-style rices do with their own Material You wallpaper picker.

No PIL/numpy/ImageMagick needed: ffmpeg (already a DXrice dependency via
grim/slurp-adjacent tooling on most of these systems, and pulled in by
plenty of desktop stacks already) can scale any image down to a small grid
and dump it as raw pixels on its own, which is all the sampling this needs.

Algorithm:
  1. Downscale the wallpaper to a small grid (area-averaging, so it's a
     real content-aware downsample, not a nearest-neighbor guess) and read
     the raw RGB bytes back.
  2. The overall average of that grid becomes the base hue/lightness for
     the background tones (kept dark and desaturated -- this rice stays a
     dark glass theme; only the accent gets to be vivid).
  3. The single sampled pixel with the highest saturation (excluding
     near-black/near-white noise) becomes the accent -- a wallpaper is
     rarely uniformly saturated (a lantern, a sky, a character's jacket),
     and the average alone would just wash that out into gray.

Usage: dxrice_wallpaper_theme.py [--print-only] [path/to/wallpaper]
  With no path, uses whatever wallpaper is already set in the live
  theme.json. --print-only (what the Theme editor uses) only prints the
  palette: the editor puts it in its unapplied draft, like a preset, and
  nothing is written until Apply. Without it, writes only the color fields into
  ~/.config/dxrice/theme.json -- radius, blur, animation speed, fonts, etc.
  are left exactly as they were. Run dxrice_apply_theme.py afterward (the
  Theme app's "Generate from Wallpaper" button does this automatically) to
  actually render/reload every app with the new colors.
"""
import colorsys
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dxrice_manifest
import dxrice_xdg

LIVE_THEME_JSON = os.path.join(dxrice_xdg.config_dir(), "theme.json")
SAMPLE_GRID = 24


def clamp01(x):
    return max(0.0, min(1.0, x))


def hexc(rgb):
    return "".join(f"{max(0, min(255, round(c))):02x}" for c in rgb)


def hls_hex(h, l, s):
    r, g, b = colorsys.hls_to_rgb(h % 1.0, clamp01(l), clamp01(s))
    return hexc((r * 255, g * 255, b * 255))


SAMPLE_TIMEOUT = 30


def sample_pixels(image_path):
    proc = subprocess.run(
        [
            "ffmpeg", "-y", "-i", image_path,
            "-vf", f"scale={SAMPLE_GRID}:{SAMPLE_GRID}:flags=area",
            "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
        ],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=True,
        # A hung decoder must not leave the Theme editor on "Generating..."
        # forever; the sample is a 24x24 thumbnail, seconds at most.
        timeout=SAMPLE_TIMEOUT,
    )
    data = proc.stdout
    return [(data[i], data[i + 1], data[i + 2]) for i in range(0, len(data), 3)]


def derive_palette(pixels):
    avg = tuple(sum(p[i] for p in pixels) / len(pixels) for i in range(3))
    avg_h, avg_l, avg_s = colorsys.rgb_to_hls(avg[0] / 255, avg[1] / 255, avg[2] / 255)

    # The accent hue is a saturation-weighted circular mean over every
    # sampled pixel (skipping near-black/near-white noise), not the single
    # most-saturated pixel -- a single outlier pixel (a stray colored
    # highlight, a UI element caught in the wallpaper) can easily have
    # higher saturation than the image's actual dominant color while being
    # wildly unrepresentative of it. Weighting by saturation still lets
    # genuinely colorful regions dominate the average far more than gray/
    # near-neutral ones, without a single pixel being able to hijack the
    # whole result.
    import math
    sum_x = sum_y = weight_total = 0.0
    for p in pixels:
        h, l, s = colorsys.rgb_to_hls(p[0] / 255, p[1] / 255, p[2] / 255)
        if 0.08 < l < 0.92:
            sum_x += math.cos(2 * math.pi * h) * s
            sum_y += math.sin(2 * math.pi * h) * s
            weight_total += s
    if weight_total > 0.05 * len(pixels):
        accent_h = (math.atan2(sum_y, sum_x) / (2 * math.pi)) % 1.0
        accent_s = min(1.0, weight_total / len(pixels))
    else:
        accent_h, accent_s = avg_h, avg_s

    # Backgrounds stay genuinely neutral -- zero saturation, independent of
    # the wallpaper's own hue -- so the shell always reads as black/
    # charcoal/off-white no matter what color the wallpaper is. Only the
    # accent is allowed to carry any of the wallpaper's identity; a shell
    # whose *surfaces* pick up wallpaper hue reads as "green UI," not
    # "neutral UI with a green accent."
    return {
        "glass_bg": hls_hex(0, 0.05, 0),
        "glass_bg_active": hls_hex(0, 0.12, 0),
        "glass_text": "d8d8d8",
        "glass_text_active": "ffffff",
        "glass_border": "ffffff",
        # A restrained, "sophisticated" accent: capped well short of a
        # vivid/neon saturation and held at a mid lightness so it stays
        # legible without dominating -- this is meant to read as one small
        # indicator's worth of color, not a wash. Earlier versions of this
        # script boosted saturation aggressively (accent_s * 1.6 + 0.35),
        # which turned a muted wallpaper teal into a garish neon cyan --
        # the fix is restraint here, not hiding the result behind smaller
        # UI elements.
        "accent": hls_hex(accent_h, 0.58, min(0.42, max(0.22, accent_s * 0.6))),
        "hypr_active_border_1": hls_hex(accent_h, 0.55, min(0.35, accent_s * 0.5)),
        "hypr_active_border_2": hls_hex(accent_h + 0.04, 0.45, min(0.3, accent_s * 0.45)),
        "hypr_inactive_border": hls_hex(0, 0.10, 0),
    }


def write_palette(path, palette):
    """Merges `palette` into the theme.json at `path` -- every other key,
    unknown ones and schema_version included, kept -- atomically (temp file
    in the same directory, fsync, rename, original mode kept): a crash or
    full disk mid-write can no longer leave an empty or half-written theme."""
    with open(path) as f:
        theme = json.load(f)
    theme.update(palette)
    dxrice_manifest.atomic_write_json(path, theme)


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    print_only = "--print-only" in args
    args = [a for a in args if a != "--print-only"]
    if args:
        wallpaper = os.path.expanduser(args[0])
    else:
        if not os.path.exists(LIVE_THEME_JSON):
            print("No live theme.json found -- run install.sh first.", file=sys.stderr)
            return 1
        with open(LIVE_THEME_JSON) as f:
            wallpaper = os.path.expanduser(json.load(f).get("wallpaper", ""))

    if not wallpaper or not os.path.isfile(wallpaper):
        print(f"Wallpaper not found: {wallpaper!r}", file=sys.stderr)
        return 1

    # Messages are shown as-is in the Theme editor, so they say what to do.
    try:
        pixels = sample_pixels(wallpaper)
    except FileNotFoundError:
        print("Generating a palette needs ffmpeg, which isn't installed -- install it with your "
              "package manager and try again.", file=sys.stderr)
        return 1
    except subprocess.TimeoutExpired:
        print(f"ffmpeg took over {SAMPLE_TIMEOUT}s to read the wallpaper -- try a smaller image.", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError:
        print(f"ffmpeg couldn't read {os.path.basename(wallpaper)} as an image.", file=sys.stderr)
        return 1
    if not pixels:
        print(f"ffmpeg returned no pixel data for {wallpaper}", file=sys.stderr)
        return 1

    palette = derive_palette(pixels)

    # The Theme editor passes --print-only: writing the live theme.json here
    # recoloured the running shell before Apply, made Revert "restore" the
    # generated colours (it reloads from theme.json), and made the editor
    # drop its own unapplied draft as "changed outside the editor".
    if not print_only:
        write_palette(LIVE_THEME_JSON, palette)

    # Plain JSON on stdout, nothing else -- the Theme app parses this
    # directly to update its draft fields (matching a preset button).
    print(json.dumps(palette))
    return 0


if __name__ == "__main__":
    sys.exit(main())
