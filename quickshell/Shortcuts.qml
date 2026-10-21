pragma Singleton
import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Hyprland

// The saved application shortcuts -- one list, read from the dock's config
// (~/.config/waybar/config-dock, which the Taskbar manager edits) -- and
// everything about them the bar and the dock share: launching one, and
// whether its app has a window open.
QtObject {
    id: root
    readonly property string configPath: Xdg.configHome + "/waybar/config-dock"
    property var list: []

    property FileView configFile: FileView {
        path: root.configPath
        watchChanges: true
        onFileChanged: this.reload()
        onLoaded: root.reload()
    }
    function reload() {
        try {
            const cfg = JSON.parse(configFile.text());
            const ids = cfg["modules-left"] || [];
            root.list = ids.map((id) => ({
                id,
                label: cfg[id] ? (cfg[id]["tooltip-format"] || cfg[id]["dxrice_label"] || id) : id,
                glyph: cfg[id] ? cfg[id]["format"] || "" : "",
                onClick: cfg[id] ? cfg[id]["on-click"] || "" : "",
            }));
        } catch (e) {
            console.warn("Shortcuts: could not read", root.configPath, e);
        }
    }

    // The command a shortcut runs. Must mirror TaskbarManager.unwrapShellCmd's
    // un-escaping exactly: on-click holds `sh -c '<cmd> >/dev/null 2>&1 &'`
    // with the command's own quotes '\''-escaped.
    function commandOf(onClick) {
        const m = /^sh -c '(.*) >\/dev\/null 2>&1 &'$/.exec(String(onClick || ""));
        return m ? m[1].replace(/'\\''/g, "'") : String(onClick || "");
    }
    // Launch one ("bar" or "dock" names who asked, for the launch scope).
    // Returns "launcher" for the app-launcher shortcut, which the caller opens.
    function launch(onClick, from) {
        const cmd = root.commandOf(onClick);
        if (cmd === "wofi --show drun") return "launcher";
        if (cmd) Launcher.launch(from || "dock", ["sh", "-c", cmd]);
        return cmd ? "launched" : "";
    }

    // Which shortcuts' apps are open. A shortcut's app is the program its
    // command runs, by name ("/usr/bin/discord --x" -> "discord"); an open
    // window matches when its class or app id is that name, ends in it after
    // a dot ("org.gnome.Nautilus"), or starts with it and a dash
    // ("brave-browser").
    function appKeyOf(onClick) {
        let parts = root.commandOf(onClick).trim().split(/\s+/);
        while (parts.length && (parts[0] === "env" || parts[0].indexOf("=") > 0)) parts.shift();
        const prog = parts.length ? parts[0].split("/").pop().toLowerCase() : "";
        return prog === "sh" || prog === "bash" ? "" : prog;
    }
    function matches(cls, key) {
        if (!cls || !key) return false;
        const c = String(cls).toLowerCase();
        return c === key || c.endsWith("." + key) || c.startsWith(key + "-");
    }
    function classOf(t) {
        if (!t) return "";
        if (t.lastIpcObject && t.lastIpcObject.class) return String(t.lastIpcObject.class);
        return t.wayland && t.wayland.appId ? String(t.wayland.appId) : "";
    }
    readonly property var runningClasses: {
        const l = Hyprland.toplevels ? Hyprland.toplevels.values : [];
        const out = [];
        for (let i = 0; i < l.length; i++) { const c = root.classOf(l[i]); if (c) out.push(c); }
        return out;
    }
    function isRunning(key) {
        if (!key) return false;
        for (const c of root.runningClasses) if (root.matches(c, key)) return true;
        return false;
    }
}
