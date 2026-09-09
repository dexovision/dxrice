#!/usr/bin/env python3
"""Shared GTK4 widget helpers for DXrice's settings apps (theme editor,
taskbar manager, quick settings). Not runnable on its own -- imported by
each app so the `.dx-*` design system, the width-safe label helper, and
the debounce plumbing live in exactly one place instead of being
copy-pasted (and re-bugged) into every app.
"""
import json
import sys

from gi.repository import Adw, Gdk, GLib, Gtk, Pango


def read_anim_ms(live_theme_path, default=150):
    """Reads anim_duration_ms straight from the live theme.json (edited by
    the Theme app) so an app that doesn't otherwise load the full theme --
    Taskbar, Quick Settings -- still matches the animation speed the user
    picked, instead of a hardcoded constant. Safe before the live file
    exists yet (a fresh install that hasn't opened the Theme app once)."""
    try:
        with open(live_theme_path) as f:
            return json.load(f).get("anim_duration_ms", default)
    except (OSError, json.JSONDecodeError):
        return default


def load_css(css_path):
    """Loads a rendered gtk_style.css onto the default display. Safe to call
    even if the file doesn't exist yet (e.g. before the user's first
    `install.sh` run) -- prints a warning instead of crashing the app into a
    stock-Adwaita, un-themed window."""
    provider = Gtk.CssProvider()
    try:
        provider.load_from_path(css_path)
    except GLib.Error as e:
        print(f"Could not load {css_path}: {e}", file=sys.stderr)
        return
    Gtk.StyleContext.add_provider_for_display(
        Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )


def label(text, css_class=None, ellipsize=True, xalign=0.0, max_width_chars=28):
    """A Gtk.Label with ellipsizing done right.

    Pango's ellipsize mode alone only governs how willing a label is to
    shrink below its *natural* width -- it does NOT cap that natural width,
    so a long string still forces the whole window wider unless
    max_width_chars is also set. Any label whose text could plausibly be
    long (titles, subtitles, paths, descriptions) must go through here with
    ellipsize left on; only pass ellipsize=False for a string you are
    certain is always short (a single fixed word)."""
    lbl = Gtk.Label(label=text, xalign=xalign)
    if ellipsize:
        lbl.set_ellipsize(Pango.EllipsizeMode.END)
        lbl.set_hexpand(True)
        lbl.set_halign(Gtk.Align.FILL)
        lbl.set_max_width_chars(max_width_chars)
    if css_class:
        lbl.add_css_class(css_class)
    return lbl


def make_card():
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    box.add_css_class("dx-card")
    return box


def make_section_title(text):
    return label(text, "dx-section-title", ellipsize=False)


def make_row(title, subtitle=None, title_chars=22, subtitle_chars=30):
    row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    row.add_css_class("dx-row")
    text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0, hexpand=True)
    text_box.append(label(title, "dx-row-title", max_width_chars=title_chars))
    if subtitle:
        text_box.append(label(subtitle, "dx-row-subtitle", max_width_chars=subtitle_chars))
    row.append(text_box)
    return row, text_box


def make_debounced(fn, delay_ms=80):
    """Wraps fn so rapid repeated calls (e.g. every tick of a dragged
    slider) only actually invoke it once, ~delay_ms after the last call."""
    state = {"id": None}

    def wrapped(*args):
        if state["id"] is not None:
            GLib.source_remove(state["id"])

        def apply_call():
            fn(*args)
            state["id"] = None
            return False

        state["id"] = GLib.timeout_add(delay_ms, apply_call)

    return wrapped


def make_entry(initial="", placeholder=None):
    entry = Gtk.Entry()
    entry.add_css_class("dx-entry")
    if placeholder:
        entry.set_placeholder_text(placeholder)
    if initial:
        entry.set_text(initial)
    return entry


def animate_in(widget, anim_ms, distance=12):
    """Fades a just-presented root widget in (opacity 0->1) while it
    settles down from a small upward offset, via a real Adw.TimedAnimation
    driven by the widget's own frame clock -- not a plain instant
    appearance. Called once, right after a window is presented.

    Returns the Adw.Animation; the caller MUST keep a reference to it
    (e.g. as an attribute on the window) for as long as the window lives --
    letting it get garbage-collected stops the animation mid-flight, since
    nothing else holds it once this function returns."""
    widget.set_opacity(0)
    base_margin = widget.get_margin_top()

    def on_tick(value, *_args):
        widget.set_opacity(value)
        widget.set_margin_top(round(base_margin + distance * (1 - value)))

    target = Adw.CallbackAnimationTarget.new(on_tick)
    animation = Adw.TimedAnimation.new(widget, 0, 1, max(1, anim_ms * 3), target)
    animation.play()
    return animation


def make_segmented(labels, selected_index, on_select):
    """A small group of `.dx-toggle` buttons acting as a single-select
    control (e.g. an icon-mode picker) -- lighter and more on-theme than a
    stock Gtk.DropDown/Adw.ComboRow popover."""
    box = Gtk.Box(spacing=4)
    buttons = []

    def _paint(idx):
        for j, b in enumerate(buttons):
            if j == idx:
                b.add_css_class("active")
            else:
                b.remove_css_class("active")

    for i, text in enumerate(labels):
        btn = Gtk.Button(label=text)
        btn.add_css_class("dx-toggle")
        btn.connect("clicked", lambda _b, i=i: (_paint(i), on_select(i)))
        box.append(btn)
        buttons.append(btn)

    _paint(selected_index)
    box.set_selected = _paint
    return box
