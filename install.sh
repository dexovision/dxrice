#!/usr/bin/env bash
# Installer / updater for the DXrice dotfiles.
#
#   ./install.sh            fresh install: asks where to put everything,
#                            sanity checks, deps, input group, monitor
#                            detection, deploy
#   ./install.sh update     git pull (auto-stashing any local repo edits),
#                            then re-deploy -- any file you've hand-edited
#                            in ~/.config since the last deploy is left
#                            alone, not overwritten. Theme colors and
#                            taskbar shortcuts live in ~/.config, not the
#                            repo, so this never touches your personal look.
#                            Also offers to set up (or re-sync) the SDDM
#                            login theme if SDDM is installed -- see
#                            'sddm-theme' below; same needs-sudo prompt,
#                            no separate command required.
#   ./install.sh sddm-theme  deploy the DXrice login theme for SDDM (needs
#                            sudo; only touches SDDM's own theme dir and
#                            config -- never installs or enables a display
#                            manager for you). Re-run any time you change
#                            your wallpaper/colors and want the login
#                            screen to match.
#   ./install.sh help       show this usage text
#
# Everything this rice needs beyond real app config files (which have to
# live where each app expects, e.g. ~/.config/waybar/) stays inside one
# folder -- wherever you choose to put this checkout. Scripts run straight
# out of it; nothing gets copied loose into $HOME. install.sh records that
# folder's location in ~/.local/state/dxrice/repo_path so hyprland.lua's
# keybinds (a plain text/Lua file deployed to a fixed dotfile path) can
# still find it after it's moved.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$SCRIPT_DIR"
STATE_DIR="$HOME/.local/state/dxrice"
MODE="${1:-install}"

# The Hyprland ecosystem itself needs distro-specific handling (see
# install_hypr_ecosystem): native on Arch and openSUSE, third-party COPR on
# Fedora, no reliable path on Ubuntu/Debian (see that function for why).
# Everything else below is packaged natively pretty much everywhere, just
# under different names.
HYPR_PACKAGES=(hyprland hyprlock hypridle hyprpaper xdg-desktop-portal-hyprland)

GENERAL_PACMAN=(swaybg waybar wofi mako kitty nautilus grim slurp cliphist qt5ct qt6ct
    pipewire pipewire-pulse pipewire-alsa wireplumber pavucontrol
    networkmanager network-manager-applet bluez bluez-utils blueman
    ttf-font-awesome noto-fonts ttf-jetbrains-mono-nerd polkit-kde-agent
    python python-evdev jq brightnessctl playerctl
    python-gobject gtk4 libadwaita gtk4-layer-shell)
AUR_PACKAGES=(nwg-look)

GENERAL_DNF=(swaybg waybar wofi mako kitty nautilus grim slurp qt5ct qt6ct
    pipewire pipewire-pulseaudio pipewire-alsa wireplumber pavucontrol
    NetworkManager network-manager-applet bluez blueman
    fontawesome-fonts google-noto-fonts-common polkit-kde
    python3 python3-evdev jq brightnessctl playerctl
    python3-gobject gtk4 libadwaita gtk4-layer-shell)

GENERAL_APT=(swaybg waybar wofi mako-notifier kitty nautilus grim slurp qt5ct qt6ct
    pipewire pipewire-pulse pipewire-alsa wireplumber pavucontrol
    network-manager network-manager-gnome bluez bluez-tools blueman
    fonts-font-awesome fonts-noto polkit-kde-agent-1
    python3 python3-evdev jq brightnessctl playerctl
    python3-gi libgtk-4-1 libadwaita-1-0 libgtk4-layer-shell0)
# cliphist has no apt package as of this writing -- handled as a manual
# note in check_dependencies instead of guessing a name that doesn't exist.

GENERAL_ZYPPER=(swaybg waybar wofi mako kitty nautilus grim slurp qt5ct qt6ct
    pipewire pipewire-pulseaudio pipewire-alsa wireplumber pavucontrol
    NetworkManager NetworkManager-applet bluez blueman
    fontawesome-fonts noto-sans-fonts polkit-kde-authentication-agent-1
    python3 python3-evdev jq brightnessctl playerctl
    python3-gobject gtk4 libadwaita-1-0 gtk4-layer-shell)

# JetBrains Mono Nerd Font isn't a real package almost anywhere outside
# Arch's community repo -- fetched straight from the Nerd Fonts project's
# own releases for every other package manager (see
# install_nerd_font_fallback).
NERD_FONT_RELEASE_URL="https://github.com/ryanoasis/nerd-fonts/releases/latest/download/JetBrainsMono.zip"

SKIP_DEPS=0
PKG_MANAGER=""
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
    sed -n '2,19p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
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
    if command -v pacman >/dev/null 2>&1; then
        PKG_MANAGER="pacman"
    elif command -v dnf >/dev/null 2>&1; then
        PKG_MANAGER="dnf"
    elif command -v apt-get >/dev/null 2>&1; then
        PKG_MANAGER="apt"
    elif command -v zypper >/dev/null 2>&1; then
        PKG_MANAGER="zypper"
    else
        PKG_MANAGER="unknown"
    fi

    if [ "$PKG_MANAGER" = "unknown" ]; then
        warn "Couldn't find pacman, dnf, apt, or zypper -- this installer doesn't know how to"
        info "install dependencies automatically here. You can still continue: you'll need to"
        info "make sure Hyprland, waybar, wofi, mako, kitty, python-gobject, gtk4, libadwaita,"
        info "etc. are already installed yourself."
        if ! ask_yes_no "Continue anyway?" N; then
            exit 1
        fi
        SKIP_DEPS=1
        return
    fi
    ok "Detected package manager: $PKG_MANAGER"
}

record_repo_path() {
    mkdir -p "$STATE_DIR"
    printf '%s\n' "$REPO_DIR" > "$STATE_DIR/repo_path"
}

# Adds a `dxrice-update` shell function so updating doesn't require
# remembering where the checkout lives or cd-ing into it first. Reads
# repo_path at call time (not baked in), so it keeps working if the
# checkout is later moved. Idempotent -- checks for its own marker line
# before appending, safe to call on every install/update.
install_shell_alias() {
    local marker="# dxrice-update (added by DXrice's install.sh)"
    local block
    block=$(cat <<'BLOCK'
# dxrice-update (added by DXrice's install.sh)
dxrice-update() {
    "$(cat "$HOME/.local/state/dxrice/repo_path" 2>/dev/null || echo "$HOME/dxrice")/install.sh" update
}
BLOCK
)
    local added=0
    for rc in "$HOME/.bashrc" "$HOME/.zshrc"; do
        [ -f "$rc" ] || continue
        grep -qF "$marker" "$rc" 2>/dev/null && continue
        printf '\n%s\n' "$block" >> "$rc"
        ok "Added the 'dxrice-update' command to $rc"
        added=1
    done
    if [ "$added" = "1" ]; then
        info "Open a new terminal (or run 'source ~/.bashrc'/'source ~/.zshrc') to start using it."
    fi
}

# Lets a fresh install put the checkout wherever the user actually wants it,
# instead of silently assuming wherever they happened to `git clone` it to.
# Re-execs install.sh from the new location if it moves, so the rest of the
# script never has to think about REPO_DIR changing mid-run.
choose_install_location() {
    if [ "${DXRICE_LOCATION_CONFIRMED:-0}" = "1" ]; then
        ok "Using $REPO_DIR"
        return
    fi

    echo ""
    info "DXrice keeps everything (scripts, theme engine, state) in one folder --"
    info "only real app config files still go to their usual ~/.config/<app> spot."
    local default="$REPO_DIR" answer
    if [ -t 0 ]; then
        read -rp "Where should that folder be? [$default] " answer
    fi
    answer="${answer:-$default}"
    answer="${answer/#\~/$HOME}"
    answer="$(realpath -m "$answer")"

    if [ "$answer" = "$REPO_DIR" ]; then
        ok "Using $REPO_DIR"
        return
    fi
    if [ -e "$answer" ]; then
        err "'$answer' already exists -- pick an empty or nonexistent path."
        exit 1
    fi

    info "Moving checkout to $answer ..."
    mkdir -p "$(dirname "$answer")"
    mv "$REPO_DIR" "$answer"
    DXRICE_LOCATION_CONFIRMED=1 exec "$answer/install.sh" "$MODE"
}

# ---------------------------------------------------------------------------
# Install steps
# ---------------------------------------------------------------------------

_pkg_installed() {
    case "$PKG_MANAGER" in
        pacman) pacman -Qi "$1" >/dev/null 2>&1 ;;
        apt) dpkg -s "$1" >/dev/null 2>&1 ;;
        dnf|zypper) rpm -q "$1" >/dev/null 2>&1 ;;
    esac
}

_pkg_install() {
    case "$PKG_MANAGER" in
        pacman) sudo pacman -S --needed "$@" ;;
        dnf) sudo dnf install -y "$@" ;;
        apt) sudo apt-get update && sudo apt-get install -y "$@" ;;
        zypper) sudo zypper install -y "$@" ;;
    esac
}

check_dependencies() {
    if [ "$SKIP_DEPS" = "1" ]; then
        warn "Skipping dependency check (no supported package manager found)."
        return
    fi

    info "Checking dependencies via $PKG_MANAGER..."
    local -a general
    case "$PKG_MANAGER" in
        pacman) general=("${GENERAL_PACMAN[@]}") ;;
        dnf) general=("${GENERAL_DNF[@]}") ;;
        apt) general=("${GENERAL_APT[@]}") ;;
        zypper) general=("${GENERAL_ZYPPER[@]}") ;;
    esac

    local missing=()
    for pkg in "${general[@]}"; do
        _pkg_installed "$pkg" || missing+=("$pkg")
    done
    if [ "${#missing[@]}" -gt 0 ]; then
        warn "Missing: ${missing[*]}"
        if ask_yes_no "Install them now?" Y; then
            _pkg_install "${missing[@]}" || warn "Install failed or was cancelled; continuing anyway."
        fi
    else
        ok "All dependencies present."
    fi

    if [ "$PKG_MANAGER" = "pacman" ]; then
        local missing_aur=()
        for pkg in "${AUR_PACKAGES[@]}"; do
            pacman -Qi "$pkg" >/dev/null 2>&1 || missing_aur+=("$pkg")
        done
        if [ "${#missing_aur[@]}" -gt 0 ]; then
            warn "AUR packages not installed (install manually with yay/paru): ${missing_aur[*]}"
        fi
    else
        warn "nwg-look (theme picker helper) isn't packaged outside Arch -- build it yourself"
        info "from https://github.com/nwg-piotr/nwg-look if you want it; everything else in"
        info "this rice works fine without it."
        if ! command -v cliphist >/dev/null 2>&1; then
            warn "cliphist (clipboard history) doesn't have a package on most non-Arch distros."
            info "Grab a release binary from https://github.com/sentriz/cliphist if you want it."
        fi
    fi

    install_hypr_ecosystem
    install_quickshell
    [ "$PKG_MANAGER" != "pacman" ] && install_nerd_font_fallback
}

# Hyprland itself needs distro-specific handling: officially packaged on
# Arch and openSUSE, only reachable via a third-party COPR on Fedora (which
# can and does go stale -- solopasha/hyprland, the most commonly referenced
# one, is unmaintained as of this writing), and with no reliable package on
# Ubuntu/Debian at all -- Hyprland's own community advises against running
# it on point-release distros since it needs newer wlroots/graphics stack
# versions than their stable base ships. See https://wiki.hypr.land for
# whatever the current recommended path is before trusting any of this
# blindly on Fedora specifically.
install_hypr_ecosystem() {
    local missing=()
    for pkg in "${HYPR_PACKAGES[@]}"; do
        _pkg_installed "$pkg" || missing+=("$pkg")
    done
    if [ "${#missing[@]}" -eq 0 ]; then
        ok "Hyprland ecosystem present."
        return
    fi

    case "$PKG_MANAGER" in
        pacman|zypper)
            warn "Missing Hyprland packages: ${missing[*]}"
            if ask_yes_no "Install them now?" Y; then
                _pkg_install "${missing[@]}" || warn "Install failed or was cancelled; continuing anyway."
            fi
            ;;
        dnf)
            warn "Fedora doesn't ship Hyprland in its official repos -- it needs a third-party COPR."
            info "solopasha/hyprland is the most commonly referenced one, but it's unmaintained as"
            info "of this writing -- check https://wiki.hypr.land for whatever's currently"
            info "recommended before trusting this."
            if ask_yes_no "Try enabling solopasha/hyprland and installing from it now?" N; then
                sudo dnf copr enable -y solopasha/hyprland || warn "Could not enable that COPR."
                sudo dnf install -y "${missing[@]}" || warn "Install failed -- that COPR may be stale; check the Hyprland wiki for a current alternative."
            else
                info "Skipped -- install Hyprland yourself (https://wiki.hypr.land/Getting-Started/Installation/) and re-run this."
            fi
            ;;
        apt)
            warn "Hyprland has no reliable Ubuntu/Debian package. Its own community advises"
            info "against running it on point-release distros like Ubuntu for this reason. If you"
            info "want to try anyway, see https://wiki.hypr.land/Getting-Started/Installation/ for"
            info "building from source. Skipping automatic install of: ${missing[*]}"
            ;;
    esac
}

# Quickshell (the Theme/Taskbar/Quick Settings UI) is fully optional: every
# keybind and waybar on-click that uses it checks for `qs` first and falls
# straight back to the older per-invocation GTK app if it isn't found (see
# hyprland.lua and waybar/config), so skipping this never breaks anything --
# it just means you get the plainer GTK apps instead of the animated
# Quickshell ones. Packaged natively on Arch; Fedora needs a third-party
# COPR; no clean path on Ubuntu/Debian/openSUSE as of this writing --
# see https://quickshell.org for whatever's current before trusting this.
install_quickshell() {
    if _pkg_installed quickshell || command -v qs >/dev/null 2>&1; then
        ok "Quickshell present."
        return
    fi

    case "$PKG_MANAGER" in
        pacman)
            if ask_yes_no "Install Quickshell (Theme/Taskbar/Quick Settings UI)?" Y; then
                _pkg_install quickshell || warn "Install failed or was cancelled; the GTK apps will be used instead."
            else
                info "Skipped -- the older GTK apps will be used instead. Install 'quickshell' any time."
            fi
            ;;
        dnf)
            warn "Fedora doesn't ship Quickshell in its official repos -- it needs a third-party COPR."
            info "Check https://quickshell.org for the currently recommended one before trusting this."
            if ask_yes_no "Try enabling errornointernet/quickshell and installing from it now?" N; then
                sudo dnf copr enable -y errornointernet/quickshell || warn "Could not enable that COPR."
                sudo dnf install -y quickshell || warn "Install failed -- that COPR may be stale; check quickshell.org for a current alternative."
            else
                info "Skipped -- the older GTK apps will be used instead."
            fi
            ;;
        apt|zypper)
            warn "Quickshell has no packaged path on this distro as of this writing."
            info "The older GTK apps (Theme/Taskbar/Quick Settings) will be used instead -- see"
            info "https://quickshell.org if you want to build it from source anyway."
            ;;
    esac
}

# JetBrainsMono Nerd Font (the glyphs throughout this whole rice -- waybar
# icons, kitty, etc.) isn't a real package almost anywhere outside Arch's
# community repo. Fetched directly from the Nerd Fonts project's own
# releases instead of guessing a distro package name that doesn't exist.
install_nerd_font_fallback() {
    if fc-list 2>/dev/null | grep -qi "JetBrainsMono Nerd Font"; then
        ok "JetBrainsMono Nerd Font already installed."
        return
    fi
    if ! command -v curl >/dev/null 2>&1 && ! command -v wget >/dev/null 2>&1; then
        warn "Need curl or wget to fetch the Nerd Font -- install one and re-run, or grab it"
        info "yourself from $NERD_FONT_RELEASE_URL"
        return
    fi
    if ! command -v unzip >/dev/null 2>&1; then
        warn "Need 'unzip' to install the Nerd Font -- install it and re-run, or fetch/unzip"
        info "$NERD_FONT_RELEASE_URL into ~/.local/share/fonts yourself."
        return
    fi
    if ! ask_yes_no "JetBrainsMono Nerd Font isn't packaged here -- download and install it now?" Y; then
        return
    fi

    local tmp
    tmp="$(mktemp -d)"
    info "Downloading JetBrainsMono Nerd Font..."
    if command -v curl >/dev/null 2>&1; then
        curl -fsSL "$NERD_FONT_RELEASE_URL" -o "$tmp/JetBrainsMono.zip"
    else
        wget -q "$NERD_FONT_RELEASE_URL" -O "$tmp/JetBrainsMono.zip"
    fi
    if [ ! -s "$tmp/JetBrainsMono.zip" ]; then
        warn "Download failed -- install the font yourself from $NERD_FONT_RELEASE_URL"
        rm -rf "$tmp"
        return
    fi

    mkdir -p "$HOME/.local/share/fonts"
    unzip -oq "$tmp/JetBrainsMono.zip" -d "$HOME/.local/share/fonts/JetBrainsMonoNerdFont"
    rm -rf "$tmp"
    command -v fc-cache >/dev/null 2>&1 && fc-cache -f "$HOME/.local/share/fonts" >/dev/null 2>&1
    ok "Installed JetBrainsMono Nerd Font."
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

# hyprland.lua is only ever copied in once, then left as yours to hand-edit
# (see do_deploy/dxrice_deploy.py) -- which means a machine that got a
# broken/ancient copy from a much older version of this rice (old script
# names, no dxrice_ prefix, hardcoded ~/scripts) is stuck with it forever,
# silently, even after every other bug in this repo gets fixed. Detect that
# specific case and offer a backed-up replacement -- never touches a
# hyprland.lua that isn't recognizably an old copy of this rice's own file.
check_stale_hyprland_lua() {
    local f="$HOME/.config/hypr/hyprland.lua"
    [ -f "$f" ] || return 0

    if grep -q "dxrice_repo" "$f" 2>/dev/null; then
        return 0
    fi
    # (dxrice_/dxrice-)? because even older copies of this rice, from before
    # scripts were renamed with that prefix, still used these same base names.
    if ! grep -qE "(dxrice[-_])?(manage-taskbar\.sh|infinite_desktop_core\.py|theme_gui\.py|floating_tile_toggle\.py)" "$f" 2>/dev/null; then
        return 0
    fi

    warn "Your ~/.config/hypr/hyprland.lua is from a much older version of this rice."
    info "It still points at script names/locations that don't exist anymore, so"
    info "keybinds and the infinite desktop cannot work with it as it is now."
    if ask_yes_no "Back it up and replace it with the current version?" Y; then
        mkdir -p "$STATE_DIR/backups"
        local backup="$STATE_DIR/backups/hyprland.lua.$(date +%s).bak"
        cp "$f" "$backup"
        rm -f "$f"
        ok "Backed up to $backup and removed the live copy -- deploying the current version next."
    else
        warn "Leaving it as-is -- binds and the infinite desktop will keep not working until"
        info "you either fix it by hand or re-run install and say yes to replacing it."
    fi
}

# Narrower companion to check_stale_hyprland_lua: a hyprland.lua already on
# the current repo-path scheme (so the check above leaves it alone) can
# still predate a later change to one specific bind -- e.g. the taskbar
# manager moving from a kitty-terminal script to a GUI. Patches just that
# one line in place, leaving every other keybind/customization untouched.
migrate_taskbar_bind() {
    local f="$HOME/.config/hypr/hyprland.lua"
    [ -f "$f" ] || return 0
    grep -q "dxrice-manage-taskbar.sh" "$f" 2>/dev/null || return 0

    info "Updating your SUPER+SHIFT+A bind to the new taskbar GUI..."
    sed -i -E \
        's#hl\.dsp\.exec_cmd\("kitty -e " \.\. repo \.\. "/scripts/dxrice-manage-taskbar\.sh"\)#hl.dsp.exec_cmd("python3 " .. repo .. "/scripts/dxrice_taskbar_gui.py")#' \
        "$f"
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
    mkdir -p ~/.config/{hypr,kitty,waybar,mako,wofi}
    python3 "$REPO_DIR/scripts/dxrice_deploy.py" "$REPO_DIR"

    echo ""
    info "Rendering theme (waybar/wofi/mako/kitty/hyprlock from theme.json)..."
    # No explicit path: dxrice_apply_theme.py seeds ~/.config/dxrice/theme.json
    # from the repo's default on a fresh install, then reuses that live copy
    # on every later run (including `install.sh update`) -- your own color
    # tweaks never get overwritten by a repo update, and never show up as a
    # locally-modified tracked file either.
    python3 "$REPO_DIR/scripts/dxrice_apply_theme.py" || true
}

hyprland_is_running() {
    [ -n "${HYPRLAND_INSTANCE_SIGNATURE:-}" ] || pgrep -x Hyprland >/dev/null 2>&1
}

# Confirms the files the keybinds/infinite-desktop actually depend on exist
# where they need to -- rather than leaving you to guess whether "deploy"
# silently no-op'd or the checkout itself is incomplete.
verify_deploy() {
    echo ""
    info "Verifying deployed files..."
    local required=(
        "$HOME/.config/hypr/hyprland.lua"
        "$STATE_DIR/repo_path"
        "$REPO_DIR/scripts/dxrice_infinite_desktop_core.py"
        "$REPO_DIR/scripts/dxrice_taskbar_gui.py"
        "$REPO_DIR/scripts/dxrice_theme_gui.py"
        "$REPO_DIR/scripts/dxrice_apply_theme.py"
        "$REPO_DIR/scripts/dxrice_quick_settings.py"
        "$REPO_DIR/scripts/dxrice_force_close_window.py"
        "$REPO_DIR/scripts/dxrice_gtk_widgets.py"
        "$REPO_DIR/scripts/dxrice_list_desktop_apps.py"
        "$REPO_DIR/quickshell/shell.qml"
        "$REPO_DIR/quickshell/qmldir"
        "$REPO_DIR/quickshell/Theme.qml"
        "$REPO_DIR/quickshell/QuickSettings.qml"
        "$REPO_DIR/quickshell/ThemeEditor.qml"
        "$REPO_DIR/quickshell/TaskbarManager.qml"
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
    if [ -d "$HOME/scripts" ]; then
        info "Note: ~/scripts still exists -- check the deploy output above for"
        info "anything it says was left alone there (an old hand-edited copy, or a"
        info "file this rice doesn't recognize). Anything it silently removed is"
        info "already gone."
    fi
    return 0
}

do_install() {
    banner
    check_not_root
    require_repo_layout
    check_platform

    step "Step 1/4 -- Where should this live?"
    choose_install_location
    record_repo_path
    install_shell_alias
    ok "This folder is now the source of truth for theming and updates:"
    info "$REPO_DIR"

    step "Step 2/4 -- Dependencies"
    check_dependencies

    step "Step 3/4 -- Permissions"
    check_input_group

    step "Step 4/4 -- Deploying your rice"
    check_stale_hyprland_lua
    migrate_taskbar_bind
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

    if command -v sddm >/dev/null 2>&1; then
        echo ""
        if ask_yes_no "SDDM is installed -- deploy the matching DXrice login theme too? (needs sudo)" N; then
            do_sddm_theme || warn "SDDM theme sync failed -- re-run './install.sh sddm-theme' to retry (the rest of your install is unaffected)."
        else
            info "Skipped. Run './install.sh sddm-theme' any time you want it."
        fi
    fi
}

# Deploys sddm/ (this repo's login theme) into SDDM's own theme directory
# and points /etc/sddm.conf.d at it. Never installs or enables SDDM itself
# -- only offered/run when it's already present. Safe to re-run any time
# your wallpaper or colors change; see scripts/dxrice_sync_sddm_theme.py
# for exactly what it touches (only /usr/share/sddm/themes/dxrice and
# /etc/sddm.conf.d/dxrice.conf) and how to revert it.
do_sddm_theme() {
    if ! command -v sddm >/dev/null 2>&1; then
        err "SDDM doesn't appear to be installed -- this only themes an SDDM you already have."
        exit 1
    fi
    require_repo_layout
    info "This needs sudo to write to /usr/share/sddm and /etc/sddm.conf.d."
    sudo python3 "$REPO_DIR/scripts/dxrice_sync_sddm_theme.py"
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
            info "Stashing your local repo edits..."
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
    check_stale_hyprland_lua
    migrate_taskbar_bind
    local hypr_existed=0
    [ -s "$HOME/.config/hypr/hyprland.lua" ] && hypr_existed=1

    record_repo_path
    install_shell_alias
    do_deploy
    verify_deploy || true

    if [ "$hypr_existed" = "0" ]; then
        echo ""
        info "Detecting your monitor for the freshly-deployed hyprland.lua..."
        detect_monitor
    fi

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

    if command -v sddm >/dev/null 2>&1; then
        echo ""
        if [ -f /etc/sddm.conf.d/dxrice.conf ]; then
            if ask_yes_no "Re-sync the DXrice SDDM login theme with your current wallpaper/colors? (needs sudo)" Y; then
                do_sddm_theme || warn "SDDM theme re-sync failed -- re-run './install.sh sddm-theme' to retry (the rest of your update is unaffected)."
            fi
        elif ask_yes_no "SDDM is installed -- set up the matching DXrice login theme too? (needs sudo)" N; then
            do_sddm_theme || warn "SDDM theme sync failed -- re-run './install.sh sddm-theme' to retry (the rest of your update is unaffected)."
        else
            info "Skipped. Run './install.sh sddm-theme' any time you want it."
        fi
    fi
}

case "$MODE" in
    install|"") do_install ;;
    update) do_update ;;
    sddm-theme) do_sddm_theme ;;
    help|-h|--help) usage ;;
    *) usage; exit 1 ;;
esac
