import QtQuick

// A fake monitor: wallpaper, an ordinary application window underneath the
// shell (the "Discord" from the dead-zone report), and the REAL shell.qml
// on top. inputOwner() models the compositor: a point belongs to the
// top-most shell surface whose input mask contains it, else it falls
// through to the application below.
Item {
    id: root
    width: 1920
    height: 1080

    property bool desktopBlocked: false
    property int appClicks: 0
    property var lastAppClick: null

    Rectangle {
        anchors.fill: parent
        gradient: Gradient {
            GradientStop { position: 0.0; color: "#2b3a4a" }
            GradientStop { position: 0.55; color: "#4a3b52" }
            GradientStop { position: 1.0; color: "#1d2630" }
        }
    }
    // The application underneath -- deliberately covers the lower half of
    // the screen, where the dock and its Add Shortcut branch live.
    Rectangle {
        id: app
        x: root.width * 0.135; y: root.height * 0.28; width: root.width * 0.73; height: root.height * 0.70
        radius: 10
        color: "#313338"
        border.color: "#1e1f22"
        Rectangle { width: 72; height: parent.height; radius: 10; color: "#1e1f22" }
        Rectangle { x: 72; width: 240; height: parent.height; color: "#2b2d31" }
        Repeater {
            model: 14
            delegate: Column {
                x: 340; y: 30 + index * 50
                spacing: 4
                Rectangle { width: 120 + (index * 37) % 140; height: 10; radius: 5; color: "#5865f2"; opacity: 0.8 }
                Rectangle { width: 400 + (index * 91) % 600; height: 8; radius: 4; color: "#949ba4"; opacity: 0.6 }
            }
        }
    }

    Loader { id: shellLoader; anchors.fill: parent; source: "shell.qml" }

    readonly property QtObject panels: PanelManager
    readonly property QtObject theme: Theme
    // The hosted panel Item whose type exposes `prop` (QuickSettings has
    // currentTab, TaskbarManager has addPanelOpen, CalendarPanel viewDate).
    function findPanel(prop) {
        const stack = [shellLoader];
        while (stack.length) {
            const it = stack.pop();
            if (it.panelItem && it.panelItem[prop] !== undefined) return it.panelItem;
            for (let i = 0; i < it.children.length; i++) stack.push(it.children[i]);
        }
        return null;
    }
    // Any descendant whose objectName matches.
    function findNamed(name) {
        const stack = [shellLoader];
        while (stack.length) {
            const it = stack.pop();
            if (!it) continue;
            if (it.objectName === name) return it;
            // `data`, not `children`: also reaches non-Item objects
            // (Shortcut, Timer, ...) declared inside an Item.
            const kids = it.data !== undefined ? it.data : [];
            for (let i = 0; i < kids.length; i++) stack.push(kids[i]);
        }
        return null;
    }

    // Per shell surface: how many ENABLED Shortcuts claim Escape. Qt turns
    // two enabled claims in one window into activatedAmbiguously, so any
    // count above 1 means Escape silently does nothing in that window.
    function escapeClaims() {
        const out = {};
        for (const s of root.surfaces()) {
            let n = 0;
            const stack = [s];
            while (stack.length) {
                const o = stack.pop();
                if (!o) continue;
                if (String(o).startsWith("QQuickShortcut") && o.enabled && String(o.sequence) === "Escape") n++;
                const kids = o.data !== undefined ? o.data : (o.children || []);
                for (let i = 0; i < kids.length; i++) stack.push(kids[i]);
            }
            const name = root._name(s);
            out[name] = (out[name] || 0) + n;
        }
        return out;
    }

    function desktopClicked(x, y) { root.appClicks += 1; root.lastAppClick = { x: x, y: y }; }

    function _surfaces(item, out) {
        for (let i = 0; i < item.children.length; i++) {
            const c = item.children[i];
            if (c.isShellSurface || c.isToplevelWindow) out.push(c);
            else root._surfaces(c, out);
        }
        return out;
    }
    function surfaces() { return root._surfaces(shellLoader, []); }
    function _name(s) {
        if (s.objectName) return s.objectName;
        const str = String(s);
        const m = str.match(/^(\w+?)(_QML)?[_(]/);
        return m ? m[1] : str;
    }
    function inputOwner(x, y) {
        const ss = root.surfaces();
        for (let i = ss.length - 1; i >= 0; i--) {
            const s = ss[i];
            if (!s.visible) continue;
            const p = s.mapFromItem(root, x, y);
            if (p.x < 0 || p.y < 0 || p.x >= s.width || p.y >= s.height) continue;
            if (s.isToplevelWindow) return root._name(s);
            if (!s.mask) return root._name(s);
            if (s.mask.contains(p.x, p.y)) return root._name(s);
        }
        return null;
    }
    function inputRects() {
        const out = [];
        for (const s of root.surfaces()) {
            if (!s.visible) continue;
            const base = s.mapToItem(root, 0, 0);
            const rs = s.isToplevelWindow || !s.mask ? [{ x: 0, y: 0, w: s.width, h: s.height }] : s.mask.rects();
            for (const r of rs) out.push({ surface: root._name(s), x: r.x + base.x, y: r.y + base.y, w: r.w, h: r.h });
        }
        return out;
    }
}
