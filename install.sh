#!/usr/bin/env bash
# Installer / updater for the DXrice dotfiles.
#
#   ./install.sh            fresh install: sanity checks, deps, input group,
#                            monitor detection, deploy everything
#   ./install.sh update     git pull (auto-stashing local repo edits like
#                            theme.json tweaks), then re-deploy -- any file
#                            you've hand-edited in ~/.config or ~/scripts
#                            since the last deploy is left alone, not
#                            overwritten
#   ./install.sh help       show this usage text
#
# Can be cloned to any path/name you like -- it records its own location in
# ~/.local/state/dxrice/repo_path so the theme engine and taskbar manager
# can find it later, wherever that ends up being.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$SCRIPT_DIR"
STATE_DIR="$HOME/.local/state/dxrice"
MODE="${1:-install}"

PACMAN_PACKAGES=(hyprland hyprlock hypridle hyprpaper swaybg xdg-desktop-portal-hyprland
    waybar wofi mako kitty nautilus grim slurp cliphist qt5ct qt6ct
    pipewire pipewire-pulse pipewire-alsa wireplumber pavucontrol
    networkmanager network-manager-applet bluez bluez-utils blueman
    ttf-font-awesome noto-fonts ttf-jetbrains-mono-nerd polkit-kde-agent
    python python-evdev jq brightnessctl playerctl
    python-gobject gtk4 libadwaita)
AUR_PACKAGES=(nwg-look)

SKIP_DEPS=0
INPUT_GROUP_JUST_ADDED=0

# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
    C_RESET=$'\033[0m'; C_BOLD=$'\033[1m'; C_DIM=$'\033[2m'
    C_RED=$'\033[31m'; C_GREEN=$'\033[32m'; C_YELLOW=$'\033[33m'; C_CYAN=$'\033[36m'
else
    C_RESET=""; C_BOLD=""; C_DIM=""; C_RED=""; C_GREEN=""; C_YELLOW=""; C_CYAN=""
fi

step() { echo ""; echo "${C_BOLD}${C_CYAN}==> $*${C_RESET}"; }
ok()   { echo "${C_GREEN}  [OK]${C_RESET}    $*"; }
warn() { echo "${C_YELLOW}  [!]${C_RESET}     $*"; }
err()  { echo "${C_RED}  [ERROR]${C_RESET}  $*" >&2; }
info() { echo "  $*"; }

banner() {
    echo "${C_BOLD}${C_CYAN}DXrice${C_RESET} ${C_DIM}-- Hyprland rice installer${C_RESET}"
    echo "${C_DIM}Checkout: $REPO_DIR${C_RESET}"
}

usage() {
    sed -n '2,15p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

# ask_yes_no "prompt" DEFAULT   (DEFAULT is Y or N)
ask_yes_no() {
    local prompt="$1" default="$2" suffix reply
    if [ "$default" = "Y" ]; then suffix="[Y/n]"; else suffix="[y/N]"; fi
    if [ ! -t 0 ]; then
        info "$prompt $suffix -> no terminal attached, defaulting to '$default'"
        reply="$default"
    else
        read -rp "$prompt $suffix " reply
        reply="${reply:-$default}"
    fi
    [[ "$reply" =~ ^[Yy]$ ]]
}

# ---------------------------------------------------------------------------
# Sanity checks
# ---------------------------------------------------------------------------

require_repo_layout() {
    if [ ! -d "$REPO_DIR/scripts" ] || [ ! -d "$REPO_DIR/theme" ]; then
        err "This doesn't look like a full DXrice checkout."
        info "Expected to find '$REPO_DIR/scripts' and '$REPO_DIR/theme' next to install.sh,"
        info "but at least one is missing. If you only downloaded install.sh by itself"
        info "(e.g. via a raw-file link), that won't work -- clone the whole repository:"
        info ""
        info "  git clone <repo-url> dxrice"
        info "  cd dxrice"
        info "  ./install.sh"
        exit 1
    fi
}

check_not_root() {
    if [ "$(id -u)" = "0" ]; then
        err "Don't run this as root."
        info "It deploys into your own \$HOME and only calls sudo for the specific"
        info "pacman/usermod commands that actually need it."
        exit 1
    fi
}

check_platform() {
    if ! command -v pacman >/dev/null 2>&1; then
        warn "pacman not found -- this installer targets Arch Linux (or an Arch-based distro)."
        info "You can still continue: dependency checks/installs will just be skipped, and"
        info "you'll need to make sure Hyprland, waybar, wofi, mako, kitty, python-gobject,"
        info "gtk4, libadwaita, etc. are already installed yourself."
        if ! ask_yes_no "Continue anyway?" N; then
            exit 1
        fi
        SKIP_DEPS=1
    fi
}

record_repo_path() {
    mkdir -p "$STATE_DIR"
    printf '%s\n' "$REPO_DIR" > "$STATE_DIR/repo_path"
}

# ---------------------------------------------------------------------------
# Install steps
# ---------------------------------------------------------------------------

check_dependencies() {
    if [ "$SKIP_DEPS" = "1" ]; then
        warn "Skipping dependency check (no pacman on this system)."
        return
    fi

    info "Checking pacman dependencies..."
    local missing=()
    for pkg in "${PACMAN_PACKAGES[@]}"; do
        pacman -Qi "$pkg" >/dev/null 2>&1 || missing+=("$pkg")
    done
    if [ "${#missing[@]}" -gt 0 ]; then
        warn "Missing: ${missing[*]}"
        if ask_yes_no "Install them now with pacman?" Y; then
            sudo pacman -S --needed "${missing[@]}" || warn "pacman install failed or was cancelled; continuing anyway."
        fi
    else
        ok "All pacman dependencies present."
    fi

    local missing_aur=()
    for pkg in "${AUR_PACKAGES[@]}"; do
        pacman -Qi "$pkg" >/dev/null 2>&1 || missing_aur+=("$pkg")
    done
    if [ "${#missing_aur[@]}" -gt 0 ]; then
        warn "AUR packages not installed (install manually with yay/paru): ${missing_aur[*]}"
    fi
}

check_input_group() {
    info "Checking 'input' group membership (required for the infinite desktop)..."
    if id -nG "$USER" | grep -qw input; then
        ok "Already in the 'input' group."
    else
        if ask_yes_no "Add $USER to the 'input' group now?" Y; then
            if sudo usermod -aG input "$USER"; then
                ok "Added. You must log out and back in (or reboot) for this to take effect."
                INPUT_GROUP_JUST_ADDED=1
            else
                warn "usermod failed; add yourself to 'input' manually."
            fi
        fi
    fi
}

detect_monitor() {
    local target="$HOME/.config/hypr/hyprland.lua"
    command -v hyprctl >/dev/null 2>&1 || { warn "hyprctl not found (Hyprland not running yet) -- skipping monitor auto-detect, edit hypr/hyprland.lua's eDP-1/resolution by hand."; return; }
    python3 - "$target" <<'PYEOF'
import json, re, subprocess, sys

target = sys.argv[1]
try:
    monitors = json.loads(subprocess.run(
        ["hyprctl", "monitors", "-j"], capture_output=True, text=True, timeout=2
    ).stdout)
except Exception:
    print("Could not query hyprctl monitors -- skipping auto-detect.")
    sys.exit(0)
if not monitors:
    sys.exit(0)

m = monitors[0]
name = m["name"]
mode = f'{m["width"]}x{m["height"]}@{m["refreshRate"]:.2f}'
pos = f'{m["x"]}x{m["y"]}'

with open(target) as f:
    content = f.read()
content = re.sub(r'output\s*=\s*"[^"]*"', f'output = "{name}"', content, count=1)
content = re.sub(r'mode\s*=\s*"[^"]*"', f'mode = "{mode}"', content, count=1)
content = re.sub(r'position\s*=\s*"[^"]*"', f'position = "{pos}"', content, count=1)
with open(target, "w") as f:
    f.write(content)
print(f"Detected monitor {name} ({mode} at {pos}) and wrote it into hyprland.lua")
PYEOF
}

do_deploy() {
    info "Deploying configs (anything you've hand-edited is protected)..."
    mkdir -p ~/.config/{hypr,kitty,waybar,mako,wofi} ~/scripts
    python3 "$REPO_DIR/scripts/dxrice_deploy.py" "$REPO_DIR"

    echo ""
    info "Rendering theme (waybar/wofi/mako/kitty/hyprlock from theme.json)..."
    python3 "$REPO_DIR/scripts/dxrice_apply_theme.py" "$REPO_DIR/theme/theme.json" || true
}

hyprland_is_running() {
    [ -n "${HYPRLAND_INSTANCE_SIGNATURE:-}" ] || pgrep -x Hyprland >/dev/null 2>&1
}

# Confirms the files the keybinds/infinite-desktop actually depend on made
# it to their real, live locations -- rather than leaving you to guess
# whether "deploy" silently no-op'd.
verify_deploy() {
    echo ""
    info "Verifying deployed files..."
    local required=(
        "$HOME/.config/hypr/hyprland.lua"
        "$HOME/scripts/dxrice_infinite_desktop_core.py"
        "$HOME/scripts/dxrice-manage-taskbar.sh"
        "$HOME/scripts/dxrice_theme_gui.py"
        "$HOME/scripts/dxrice_apply_theme.py"
    )
    local all_ok=1
    for f in "${required[@]}"; do
        if [ -s "$f" ]; then
            ok "$f"
        else
            err "MISSING: $f"
            all_ok=0
        fi
    done
    if [ "$all_ok" = "0" ]; then
        warn "One or more required files didn't make it to their live location."
        info "Re-run './install.sh update' from inside $REPO_DIR and check the"
        info "output above it for python errors -- nothing else will work until"
        info "these exist."
        return 1
    fi
    ok "Everything the keybinds depend on is in place."

    if [ -f "$HOME/.config/hypr/hyprland.conf" ]; then
        warn "You also have a leftover ~/.config/hypr/hyprland.conf."
        info "Hyprland prefers hyprland.lua when both exist, so this is harmless,"
        info "but it's dead weight -- safe to delete if you don't need it for anything else."
    fi
    return 0
}

do_install() {
    banner
    check_not_root
    require_repo_layout
    check_platform

    step "Step 1/4 -- Recording repo location"
    record_repo_path
    ok "This checkout is now the source of truth for theming and updates:"
    info "$REPO_DIR"

    step "Step 2/4 -- Dependencies"
    check_dependencies

    step "Step 3/4 -- Permissions"
    check_input_group

    step "Step 4/4 -- Deploying your rice"
    local hypr_existed=0
    [ -f "$HOME/.config/hypr/hyprland.lua" ] && hypr_existed=1

    do_deploy
    verify_deploy || true

    if [ "$hypr_existed" = "0" ]; then
        echo ""
        info "Detecting your monitor for hyprland.lua..."
        detect_monitor
    fi

    echo ""
    echo "${C_BOLD}${C_GREEN}Install complete.${C_RESET}"
    info "Useful keybinds (once hyprland.lua is actually loaded -- see below):"
    info "  SUPER + SHIFT + T   theme settings GUI"
    info "  SUPER + SHIFT + A   taskbar app manager"
    info "  SUPER + D           floating/tile toggle"
    if [ "$INPUT_GROUP_JUST_ADDED" = "1" ]; then
        warn "You were just added to the 'input' group -- log out and back in (or reboot) before the infinite desktop will work."
    fi

    if [ "$hypr_existed" = "0" ] && hyprland_is_running; then
        echo ""
        warn "${C_BOLD}Hyprland is currently running -- your keybinds will NOT work yet.${C_RESET}"
        info "Hyprland decides whether to load hyprland.conf or hyprland.lua only"
        info "ONCE, when it starts. Since it was already running before hyprland.lua"
        info "existed, this session is still using whatever it loaded at boot (almost"
        info "certainly a bare default with none of this rice's binds)."
        info "A 'hyprctl reload' does NOT fix this -- you must fully log out of this"
        info "Hyprland session (or reboot) and log back in for the binds and the"
        info "infinite desktop to appear."
    else
        info "Log out and back in once so autostart (waybar, mako, swaybg, etc.) picks everything up."
    fi
    info "Later, pull updates with: ./install.sh update"
}

do_update() {
    banner
    require_repo_layout
    cd "$REPO_DIR"

    step "Checking repo status"
    if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
        warn "Not a git repository -- skipping git pull, deploying what's on disk."
    else
        local stashed=0
        if [ -n "$(git status --porcelain)" ]; then
            info "Stashing your local repo edits (e.g. theme.json tweaks from the GUI)..."
            git stash push -u -m "dxrice-update-autostash" >/dev/null
            stashed=1
        fi

        if ! git rev-parse --abbrev-ref --symbolic-full-name '@{u}' >/dev/null 2>&1; then
            warn "Current branch has no upstream tracking branch -- skipping git pull."
        else
            info "Pulling latest changes..."
            if ! git pull --ff-only; then
                err "git pull --ff-only failed."
                info "This usually means your local branch has diverged from the remote"
                info "(e.g. you made local commits, or the remote history was rewritten)."
                info "Resolve it by hand, then re-run './install.sh update':"
                info "  git fetch && git status     # see how far you've diverged"
                info "  git pull --rebase           # replay local commits on top, if you want to keep them"
                if [ "$stashed" = "1" ]; then
                    info "Restoring your stashed local edits first..."
                    git stash pop || warn "Could not auto-restore stashed changes; recover with 'git stash list' / 'git stash pop'."
                fi
                exit 1
            fi
            ok "Repo up to date."
        fi

        if [ "$stashed" = "1" ]; then
            info "Restoring your local repo edits..."
            git stash pop || warn "Could not auto-restore stashed changes cleanly -- run 'git stash list' / 'git stash pop' by hand to recover them."
        fi
    fi

    step "Redeploying"
    local hypr_existed=0
    [ -s "$HOME/.config/hypr/hyprland.lua" ] && hypr_existed=1

    record_repo_path
    do_deploy
    verify_deploy || true

    echo ""
    echo "${C_BOLD}${C_GREEN}Update complete.${C_RESET}"
    info "Anything hand-edited in ~/.config or ~/scripts was left alone (see above)."

    if [ "$hypr_existed" = "0" ] && hyprland_is_running; then
        echo ""
        warn "${C_BOLD}hyprland.lua was just created for the first time, and Hyprland is running.${C_RESET}"
        info "Hyprland only decides between hyprland.conf and hyprland.lua once, at"
        info "startup -- this session is still on whatever it loaded at boot, so"
        info "keybinds and the infinite desktop will NOT appear until you fully log"
        info "out (or reboot) and back in. 'hyprctl reload' is not enough here."
    fi
}

case "$MODE" in
    install|"") do_install ;;
    update) do_update ;;
    help|-h|--help) usage ;;
    *) usage; exit 1 ;;
esac
