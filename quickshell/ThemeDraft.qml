pragma Singleton
import QtQuick

// The Theme editor's unapplied edits, kept across closing and reopening it.
//
// The editor's window is created on open and destroyed on close (shell.qml's
// LazyLoader), and its fields lived only in that window -- so every way of
// closing it (click outside, Escape, X, SUPER+C) silently threw away whatever
// hadn't been applied yet. This singleton outlives the window; it does not
// outlive the shell itself (a restart starts clean).
//
// `base` is the theme.json content (as Theme.data, serialised) the edits were
// made against. ThemeEditor only restores a draft whose base still matches
// the live theme: if theme.json changed in the meantime (applied from
// elsewhere, migrated, edited by hand), restoring stale edits on top of it
// would silently undo that change, so the draft is dropped instead and the
// editor says so.
QtObject {
    property var fields: null
    property string base: ""
    property string category: ""

    function save(newFields, newBase, newCategory) {
        fields = newFields;
        base = newBase;
        category = newCategory;
    }

    function clear() {
        fields = null;
        base = "";
        category = "";
    }
}
