hl.monitor({
    output = "eDP-1",
    mode = "1920x1080@144.03",
    position = "0x0",
    scale = 1.0,
})

local terminal    = os.getenv("TERMINAL") or "kitty"
local fileManager = "nautilus"
local menu        = "wofi --show drun"

-- DXrice's scripts live inside the git checkout itself, not scattered into
-- $HOME -- install.sh records that checkout's location here so this file
-- (which is only ever deployed once, then yours to hand-edit) keeps working
-- no matter where the repo was cloned or later moved to.
local home = os.getenv("HOME")
local state_home = os.getenv("XDG_STATE_HOME") or (home .. "/.local/state")
local function dxrice_repo()
    local f = io.open(state_home .. "/dxrice/repo_path", "r")
    if f then
        local line = f:read("*l")
        f:close()
        if line and line ~= "" then return line end
    end
    return home .. "/dxrice"
end
local repo = dxrice_repo()

hl.on("hyprland.start", function()
    -- The Quickshell shell and DXrice's two daemons (window placement,
    -- infinite-desktop panning). dxrice_session.sh lives in the checkout, so
    -- fixes to how they start arrive with updates: under systemd it restarts
    -- DXrice's user units (crash recovery included); without systemd it
    -- supervises them itself. Without Quickshell it starts the waybar bars.
    hl.exec_cmd(repo .. "/scripts/dxrice_session.sh")

    local bg_path = os.getenv("BG_WALLPAPER") or (home .. "/Pictures/Wallpapers/default.png")
    hl.exec_cmd("swaybg -i '" .. bg_path:gsub("'", "'\\''") .. "' -m fill")

    hl.exec_cmd("mako")
    hl.exec_cmd("nm-applet --indicator")
    hl.exec_cmd("blueman-applet")
    -- Probes for whichever polkit agent is actually installed (see that
    -- script): a single hard-coded path here pointed at a binary no package
    -- ships, so no password prompt could ever appear.
    hl.exec_cmd(repo .. "/scripts/dxrice_polkit_agent.sh")
    hl.exec_cmd("wl-paste --type text --watch cliphist store")
    hl.exec_cmd("wl-paste --type image --watch cliphist store")
end)

hl.env("QT_QPA_PLATFORMTHEME", "qt6ct")
hl.env("XCURSOR_SIZE", "24")
hl.env("HYPRCURSOR_SIZE", "24")

hl.config({
    general = {
        gaps_in = 5,
        gaps_out = 12,
        border_size = 2,
        col = {
            active_border   = { colors = {"rgba(8090a0ee)", "rgba(c0a0b0ee)"}, angle = 45 },
            inactive_border = "rgba(1d2021aa)",
        },
        resize_on_border = true,
        allow_tearing = false,
        layout = "dwindle",
    },
    decoration = {
        rounding = 12,
        rounding_power = 2,
        active_opacity = 0.92,
        inactive_opacity = 0.85,
        shadow = {
            enabled = true,
            range = 15,
            render_power = 3,
            color = "rgba(00000055)",
        },
        blur = {
            enabled = true,
            size = 6,
            passes = 3,
            vibrancy = 0.2,
        },
    },
    animations = { enabled = true },
})

hl.curve("easeOutQuint", { type = "bezier", points = { {0.23, 1}, {0.32, 1} } })
hl.curve("linear", { type = "bezier", points = { {0, 0}, {1, 1} } })
hl.curve("quick", { type = "bezier", points = { {0.15, 0}, {0.1, 1} } })
hl.curve("easy", { type = "spring", mass = 1, stiffness = 71.2633, dampening = 15.8273644 })

hl.animation({ leaf = "windows", enabled = true, speed = 4.79, spring = "easy" })
hl.animation({ leaf = "windowsOut", enabled = true, speed = 1.49, bezier = "linear", style = "popin 87%" })
hl.animation({ leaf = "border", enabled = true, speed = 5.39, bezier = "easeOutQuint" })
hl.animation({ leaf = "fade", enabled = true, speed = 3.03, bezier = "quick" })
hl.animation({ leaf = "workspaces", enabled = true, speed = 1.94, bezier = "linear", style = "fade" })

hl.config({
    dwindle = { preserve_split = true },
    debug   = { vfr = true },
    misc    = { disable_hyprland_logo = true },
})

hl.layer_rule({ name = "waybar-blur", match = { namespace = "^(waybar|waybar-top|waybar-left|waybar-right|waybar-dock)$" }, blur = true, ignore_alpha = 0.6 })
hl.layer_rule({ name = "wofi-blur",   match = { namespace = "wofi" },   blur = true, ignore_alpha = 0.6 })
hl.layer_rule({ name = "theme-blur", match = { namespace = "dxrice-theme" }, blur = true, ignore_alpha = 0.6 })
-- quicksettings-blur/taskbar-blur/calendar-blur (dxrice-quicksettings,
-- dxrice-taskbar, dxrice-calendar) removed: those namespaces belonged to
-- PanelWindows that no longer exist -- Quick Settings/Taskbar/Calendar are
-- now hosted inside TopBar's and Dock's own windows (see ShellIsland.qml),
-- so bar-top-blur/bar-dock-blur below already cover them.
hl.layer_rule({ name = "bar-top-blur", match = { namespace = "dxrice-bar-top" }, blur = true, ignore_alpha = 0.6 })
hl.layer_rule({ name = "bar-dock-blur", match = { namespace = "dxrice-bar-dock" }, blur = true, ignore_alpha = 0.6 })
-- The desktop overview (SUPER+Tab) only, unanimated by the compositor. The
-- `fade` animation above also fades every layer surface in and out as a
-- whole (fadeLayersIn/Out); over the overview, which animates itself, that
-- composited it at 0..100% over the real windows while its window pictures
-- moved, so every window showed twice. no_anim ends this surface's fade on
-- its first frame and skips its fade-out; the bar, dock, notifications and
-- launchers keep theirs.
hl.layer_rule({ name = "overview-no-anim", match = { namespace = "^dxrice-overview$" }, no_anim = true })

hl.config({
    input = {
        kb_layout = "us",
        follow_mouse = 1,
        sensitivity = 0,
        touchpad = { natural_scroll = false },
    },
})

hl.gesture({ fingers = 3, direction = "horizontal", action = "workspace" })

local mainMod = "SUPER"

hl.bind(mainMod .. " + Q", hl.dsp.exec_cmd(terminal))
-- Plain killactive just sends a polite close request, which apps like
-- Discord/Steam/Slack intercept to hide to tray instead of quitting.
-- dxrice_force_close_window.py signals the active window's whole process
-- tree instead of just the one PID hyprctl reports (see its docstring for
-- why a plain process-group kill isn't safe here).
hl.bind(mainMod .. " + C", hl.dsp.exec_cmd("python3 " .. repo .. "/scripts/dxrice_force_close_window.py"))
hl.bind(mainMod .. " + E", hl.dsp.exec_cmd(fileManager))
hl.bind(mainMod .. " + V", hl.dsp.window.float({ action = "toggle" }))
hl.bind(mainMod .. " + R", hl.dsp.exec_cmd(menu))
hl.bind(mainMod .. " + P", hl.dsp.window.pseudo())
hl.bind(mainMod .. " + J", hl.dsp.layout("togglesplit"))
hl.bind(mainMod .. " + F", hl.dsp.window.fullscreen({ action = "toggle", mode = "fullscreen" }))
hl.bind(mainMod .. " + M", hl.dsp.window.fullscreen({ action = "toggle", mode = "maximized" }))

for i = 1, 10 do
    local key = i % 10
    hl.bind(mainMod .. " + " .. key, hl.dsp.focus({ workspace = i }))
    hl.bind(mainMod .. " + SHIFT + " .. key, hl.dsp.window.move({ workspace = i }))
end

hl.bind("PRINT", hl.dsp.exec_cmd("bash -c 'mkdir -p ~/Pictures/Screenshots && grim -g \"$(slurp)\" - | tee ~/Pictures/Screenshots/$(date +%Y-%m-%d_%H-%M-%S).png | wl-copy'"))
hl.bind(mainMod .. " + SHIFT + S", hl.dsp.exec_cmd("bash -c 'mkdir -p ~/Pictures/Screenshots && grim -g \"$(slurp)\" - | tee ~/Pictures/Screenshots/$(date +%Y-%m-%d_%H-%M-%S).png | wl-copy'"))
hl.bind(mainMod .. " + PRINT", hl.dsp.exec_cmd("bash -c 'mkdir -p ~/Pictures/Screenshots && grim - | tee ~/Pictures/Screenshots/$(date +%Y-%m-%d_%H-%M-%S).png | wl-copy'"))

hl.bind(mainMod .. " + mouse_down", hl.dsp.focus({ workspace = "e+1" }))
hl.bind(mainMod .. " + mouse_up", hl.dsp.focus({ workspace = "e-1" }))
hl.bind(mainMod .. " + mouse:272", hl.dsp.window.drag(),   { mouse = true })
hl.bind(mainMod .. " + mouse:273", hl.dsp.window.resize(), { mouse = true })

hl.bind("XF86AudioRaiseVolume", hl.dsp.exec_cmd("wpctl set-volume -l 1 @DEFAULT_AUDIO_SINK@ 5%+"), { locked = true, repeating = true })
hl.bind("XF86AudioLowerVolume", hl.dsp.exec_cmd("wpctl set-volume @DEFAULT_AUDIO_SINK@ 5%-"), { locked = true, repeating = true })
hl.bind("XF86AudioMute", hl.dsp.exec_cmd("wpctl set-mute @DEFAULT_AUDIO_SINK@ toggle"), { locked = true, repeating = true })
hl.bind("XF86MonBrightnessUp", hl.dsp.exec_cmd("brightnessctl -e4 -n2 set 5%+"), { locked = true, repeating = true })
hl.bind("XF86MonBrightnessDown", hl.dsp.exec_cmd("brightnessctl -e4 -n2 set 5%-"), { locked = true, repeating = true })

hl.bind(mainMod .. " + SHIFT + E", hl.dsp.exec_cmd("kitty -e yazi"))
hl.bind(mainMod .. " + L", hl.dsp.exec_cmd("hyprlock"))
hl.bind(mainMod .. " + SHIFT + V", hl.dsp.exec_cmd("cliphist list | wofi --dmenu | cliphist decode | wl-copy"))
hl.bind(mainMod .. " + SHIFT + C", hl.dsp.exec_cmd("kitty --class cava -e cava"))
hl.bind(mainMod .. " + SHIFT + R", hl.dsp.exec_cmd("hyprctl reload"))

hl.window_rule({
    name = "suppress-maximize-events",
    match = { class = ".*" },
    suppress_event = "maximize",
})

-- Real, live-verified wayland app-ids for nautilus/pavucontrol (both
-- previously listed by their binary name, which never matched: Hyprland
-- matches against the actual app-id/class a client reports, confirmed
-- live as "org.gnome.Nautilus" and "org.pulseaudio.pavucontrol" -- so this
-- size-forcing rule silently never fired for either app before. The other
-- five entries were not independently re-verified this pass.
-- "cava" removed: it is a terminal ncurses visualizer, not a Wayland
-- toplevel with its own app-id -- it runs INSIDE whichever terminal
-- launches it (e.g. class "kitty"), so a rule matching class="cava"
-- could never match anything. Confirmed live: blueman-manager/qt5ct/
-- qt6ct/nwg-look all report exactly the class already listed here and
-- all correctly receive the 1100x750 size.
local float_apps = { "org.gnome.Nautilus", "org.pulseaudio.pavucontrol", "blueman-manager", "qt5ct", "qt6ct", "nwg-look" }
for _, class in ipairs(float_apps) do
    hl.window_rule({
        name = "float-" .. class,
        match = { class = class },
        float = true,
        size = {1100, 750},
    })
end

hl.window_rule({ name = "kitty-glass", match = { class = "kitty" }, opacity = "0.82 override 0.75 override" })
hl.window_rule({ name = "float-everything", match = { class = ".*" }, float = true })

-- Quickshell if it's running (it's toggled, not relaunched, hence the
-- separate `qs ipc call ... toggle` rather than starting a new process
-- each press); the old per-invocation GTK app otherwise.
hl.bind(mainMod .. " + SHIFT + A", hl.dsp.exec_cmd(
    "sh -c 'qs -p " .. repo .. "/quickshell/shell.qml ipc call taskbar toggle 2>/dev/null " ..
    "|| python3 " .. repo .. "/scripts/dxrice_taskbar_gui.py'"))
hl.bind(mainMod .. " + SHIFT + T", hl.dsp.exec_cmd(
    "sh -c 'qs -p " .. repo .. "/quickshell/shell.qml ipc call theme toggle 2>/dev/null " ..
    "|| python3 " .. repo .. "/scripts/dxrice_theme_gui.py'"))

hl.bind(mainMod .. " + Z", hl.dsp.focus({ workspace = "-1" }))
hl.bind(mainMod .. " + X", hl.dsp.focus({ workspace = "+1" }))
hl.bind(mainMod .. " + SHIFT + Z", hl.dsp.window.move({ workspace = "-1" }))
hl.bind(mainMod .. " + SHIFT + X", hl.dsp.window.move({ workspace = "+1" }))
-- SUPER+D is back to its original job from before any auto-arrange work:
-- dxrice_floating_tile_toggle.py, toggling this workspace's windows
-- between floating and tiled. It briefly ran the whole-desktop
-- auto-arrange solver instead, but pressing that same key reliably
-- re-tiled floating windows via something outside this config's own bind
-- table (never tracked down conclusively -- unrelated to the toggle
-- script below, which has its own, intentional float/tile behavior and
-- was never implicated). Auto-arrange (dxrice_auto_arrange.py) now lives
-- on SUPER+G instead, clear of whatever that was.
hl.bind(mainMod .. " + D", hl.dsp.exec_cmd("python3 " .. repo .. "/scripts/dxrice_floating_tile_toggle.py"))

-- Whole-desktop auto-arrange (Algorithm B) -- not the older collision-only
-- resolver (dxrice_align_windows.py, still present and unbound -- point
-- this bind at it instead to revert to that simpler behavior).
hl.bind(mainMod .. " + G", hl.dsp.exec_cmd("python3 " .. repo .. "/scripts/dxrice_auto_arrange.py"))

-- Desktop overview: SUPER+Tab zooms the current workspace out until every
-- window -- the whole Galaxy Spiral, past the screen edges too -- fits on
-- screen, and SUPER+Tab again zooms back in. A view (live window pictures
-- drawn by Quickshell, Overview.qml), never a re-layout. Click a window to
-- focus it; Esc or a click on empty space closes. To use another key,
-- change it on the hl.bind line -- nothing else refers to it.
local function overview(action)
    return hl.dsp.exec_cmd("sh -c 'qs -p " .. repo .. "/quickshell/shell.qml ipc call overview "
        .. action .. " 2>/dev/null'")
end
hl.bind(mainMod .. " + Tab", overview("toggle"))

hl.bind(mainMod .. " + left",  hl.dsp.exec_cmd("python3 " .. repo .. "/scripts/dxrice_navigate_windows.py left"))
hl.bind(mainMod .. " + right", hl.dsp.exec_cmd("python3 " .. repo .. "/scripts/dxrice_navigate_windows.py right"))
hl.bind(mainMod .. " + up",    hl.dsp.exec_cmd("python3 " .. repo .. "/scripts/dxrice_navigate_windows.py up"))
hl.bind(mainMod .. " + down",  hl.dsp.exec_cmd("python3 " .. repo .. "/scripts/dxrice_navigate_windows.py down"))

hl.bind(mainMod .. " + SHIFT + left",  hl.dsp.exec_cmd("python3 " .. repo .. "/scripts/dxrice_move_window.py left"),  { repeating = true })
hl.bind(mainMod .. " + SHIFT + right", hl.dsp.exec_cmd("python3 " .. repo .. "/scripts/dxrice_move_window.py right"), { repeating = true })
hl.bind(mainMod .. " + SHIFT + up",    hl.dsp.exec_cmd("python3 " .. repo .. "/scripts/dxrice_move_window.py up"),    { repeating = true })
hl.bind(mainMod .. " + SHIFT + down",  hl.dsp.exec_cmd("python3 " .. repo .. "/scripts/dxrice_move_window.py down"),  { repeating = true })

hl.bind(mainMod .. " + CTRL + left",  hl.dsp.exec_cmd("python3 " .. repo .. "/scripts/dxrice_resize_window.py left"),  { repeating = true })
hl.bind(mainMod .. " + CTRL + right", hl.dsp.exec_cmd("python3 " .. repo .. "/scripts/dxrice_resize_window.py right"), { repeating = true })
hl.bind(mainMod .. " + CTRL + up",    hl.dsp.exec_cmd("python3 " .. repo .. "/scripts/dxrice_resize_window.py up"),    { repeating = true })
hl.bind(mainMod .. " + CTRL + down",  hl.dsp.exec_cmd("python3 " .. repo .. "/scripts/dxrice_resize_window.py down"),  { repeating = true })

hl.bind(mainMod .. " + W", hl.dsp.exec_cmd("firefox"))
-- Native Wayland + PipeWire capture: under XWayland (Discord's default)
-- screen sharing sees only X11 windows and a full-screen share is black.
hl.bind(mainMod .. " + SHIFT + D", hl.dsp.exec_cmd("discord --enable-features=WebRTCPipeWireCapturer,WaylandWindowDecorations --ozone-platform=wayland"))
hl.bind(mainMod .. " + SHIFT + M", hl.dsp.exec_cmd("pavucontrol"))
hl.bind(mainMod .. " + SHIFT + B", hl.dsp.exec_cmd("blueman-manager"))
hl.bind(mainMod .. " + N", hl.dsp.exec_cmd("nm-connection-editor"))
hl.bind(mainMod .. " + I", hl.dsp.exec_cmd("nwg-look"))
hl.bind(mainMod .. " + U", hl.dsp.exec_cmd("qt6ct"))
hl.bind(mainMod .. " + SHIFT + K", hl.dsp.exec_cmd("hyprctl kill"))
