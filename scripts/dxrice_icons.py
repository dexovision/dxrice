#!/usr/bin/env python3
"""Nerd Font glyph lookup for common desktop apps, used by dxrice_taskbar_gui.py
to show real icons on taskbar shortcuts instead of plain text labels."""

ICON_TABLE = [
    (("firefox",), ""),
    (("chromium", "chrome"), ""),
    (("brave",), ""),
    (("discord",), "󰙯"),
    (("telegram",), ""),
    (("slack",), ""),
    (("spotify",), ""),
    (("steam",), ""),
    (("sober", "roblox"), ""),
    (("nautilus", "files", "thunar", "nemo", "dolphin", "pcmanfm"), ""),
    (("kitty", "terminal", "alacritty", "konsole", "foot", "wezterm"), ""),
    (("code", "vscode", "codium"), ""),
    (("gimp",), ""),
    (("blender",), ""),
    (("obs",), ""),
    (("vlc", "mpv"), ""),
    (("thunderbird", "mail"), ""),
    (("git",), ""),
    (("pavucontrol", "volume", "audio"), ""),
    (("bluetooth", "blueman"), ""),
    (("nm-connection", "network"), ""),
    (("nwg-look", "qt6ct", "qt5ct", "settings", "control"), ""),
    (("yazi", "ranger", "nnn"), ""),
    (("cava",), ""),
]

DEFAULT_ICON = ""  # generic window, used when nothing matches


def icon_for(*texts: str) -> str:
    haystack = " ".join(t.lower() for t in texts if t)
    for keywords, glyph in ICON_TABLE:
        if any(k in haystack for k in keywords):
            return glyph
    return DEFAULT_ICON


if __name__ == "__main__":
    import sys
    print(icon_for(*sys.argv[1:]))
