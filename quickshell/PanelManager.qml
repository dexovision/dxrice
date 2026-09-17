pragma Singleton
import QtQuick

// The shell's single panel-exclusivity authority.
//
// Before this, "which panel is open" was split across two unrelated
// mechanisms: ShellSurface.openPanel (a bare string) coordinated the three
// island-hosted panels (Calendar/QuickSettings/Taskbar), while Theme used a
// completely different one (its own LazyLoader's `active` flag, toggled by
// ad hoc functions living on shell.qml's root). Anything that wanted to
// reason about "is a panel open" had to know which of the two mechanisms
// the panel in question happened to use. This collapses both into one
// singleton with one real API, so every panel -- island-hosted or not --
// is coordinated the same way.
QtObject {
    id: root

    // Empty string means nothing is open. Only one name at a time: opening
    // any panel implicitly closes whatever was open before it, matching the
    // shell's existing rule that only one branch is ever expanded at once.
    property string current: ""

    function isOpen(name) {
        return root.current === name;
    }

    function open(name) {
        root.current = name;
    }

    function close(name) {
        // Guarded on `name` so a stale/late close call for a panel that
        // isn't the current one can't accidentally clear a DIFFERENT panel
        // that opened in between -- e.g. panel A's own close animation
        // firing its close() after panel B has already become current.
        if (root.current === name) root.current = "";
    }

    function closeCurrent() {
        root.current = "";
    }

    function toggle(name) {
        if (root.current === name) root.close(name);
        else root.open(name);
    }
}
