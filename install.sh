#!/usr/bin/env bash
# Installer / updater for the DXrice dotfiles.
#
#   ./install.sh                 fresh install: asks where to put
#                                 everything, sanity checks, deps, input
#                                 group, monitor detection, deploy
#   ./install.sh update          git pull (auto-stashing any local repo
#                                 edits), then re-deploy -- any file you've
#                                 hand-edited in $XDG_CONFIG_HOME since the
#                                 last deploy is left alone, not
#                                 overwritten. Theme colors and taskbar
#                                 shortcuts live outside the repo, so this
#                                 never touches your personal look. Also
#                                 offers to set up (or re-sync) the SDDM
#                                 login theme if SDDM is installed -- see
#                                 'sddm-theme' below; same needs-sudo
#                                 prompt, no separate command required.
#   ./install.sh sddm-theme      deploy the DXrice login theme for SDDM
#                                 (needs sudo; only touches SDDM's own
#                                 theme dir and config -- never installs or
#                                 enables a display manager for you).
#                                 Re-run any time you change your
#                                 wallpaper/colors and want the login
#                                 screen to match.
#   ./install.sh uninstall       removes DXrice's own integration (shell
#                                 functions, recorded repo path, the SDDM
#                                 theme if you confirm) -- never your
#                                 saved theme/config/data, and never your
#                                 deployed app config files.
#   ./install.sh uninstall --purge
#                                 uninstall, AND permanently delete your
#                                 saved config/data/state after an explicit
#                                 confirmation naming exactly what goes.
#                                 Never the default -- always opt in.
#   ./install.sh install --dry-run
#   ./install.sh update --dry-run
#                                 report exactly what install/update would
#                                 do (packages, config init/migration,
#                                 files deployed, whether sudo would be
#                                 needed) without changing anything.
#   ./install.sh help            show this usage text
#
# Everything this rice needs beyond real app config files (which have to
# live where each app expects, e.g. $XDG_CONFIG_HOME/waybar/) stays inside
# one folder -- wherever you choose to put this checkout. Scripts run
# straight out of it; nothing gets copied loose into $HOME. install.sh
# records that folder's location in $XDG_STATE_HOME/dxrice/repo_path so
# hyprland.lua's keybinds (a plain text/Lua file deployed to a fixed
# dotfile path) can still find it after it's moved.
#
# Your saved theme/config lives in $XDG_CONFIG_HOME/dxrice (falling back to
# ~/.config/dxrice), your data/backups in $XDG_DATA_HOME/dxrice, and
# install.sh's own state in $XDG_STATE_HOME/dxrice -- installing, updating,
# or reinstalling this repo NEVER overwrites any of those; see README.md's
# "Configuration, data, state, and cache" section for the full guarantee.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$SCRIPT_DIR"
# XDG Base Directory locations -- see scripts/dxrice_xdg.py for the same
# resolution on the Python side. Never hardcode ~/.config/~/.local/* below
# this point; use these instead so a user's own XDG_* override is honored.
CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"
DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
STATE_HOME="${XDG_STATE_HOME:-$HOME/.local/state}"
DXRICE_CONFIG_DIR="$CONFIG_HOME/dxrice"
DXRICE_DATA_DIR="$DATA_HOME/dxrice"
STATE_DIR="$STATE_HOME/dxrice"

# First non-flag argument is the mode (default: install); --dry-run and
# --purge are flags that can appear anywhere alongside it.
MODE=""
DRY_RUN=0
PURGE=0
for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY_RUN=1 ;;
        --purge) PURGE=1 ;;
        *) [ -z "$MODE" ] && MODE="$arg" ;;
    esac
done
MODE="${MODE:-install}"

# The Hyprland ecosystem itself needs distro-specific handling (see
# install_hypr_ecosystem): native on Arch and openSUSE, third-party COPR on
# Fedora, no reliable path on Ubuntu/Debian (see that function for why).
# Everything else below is packaged natively pretty much everywhere, just
# under different names.
HYPR_PACKAGES=(hyprland hyprlock hypridle hyprpaper xdg-desktop-portal-hyprland)

# Script basenames from much older, pre-Quickshell versions of this rice
# (back when it used plain bash scripts and had no dxrice_ prefix at all).
# Shared by reconcile_copy_once_ownership's recognizers (does a DEPLOYED
# copy-once file still point at these) and check_legacy_rice_checkout (is
# there an entire old CHECKOUT of the rice still on disk, referenced by leftover shell
# aliases) -- one list so a name added for one check is recognized by
# both, rather than two independently-maintained regexes drifting apart.
LEGACY_SCRIPT_NAMES=(manage-taskbar.sh reorder-taskbar.sh infinite_desktop_core.py
    theme_gui.py floating_tile_toggle.py)

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
    sed -n '2,55p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
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
    # Bracketed by explicit begin/end markers (not just a name check) so
    # this can always be found and replaced wholesale on a later update --
    # matching only the function name would miss any *other* change to the
    # body (e.g. a new dx subcommand) once the marker line itself no longer
    # differs between versions.
    local block
    block=$(cat <<'BLOCK'
# BEGIN dxrice shell functions (added by DXrice's install.sh)
dxrice-update() {
    "$(cat "$HOME/.local/state/dxrice/repo_path" 2>/dev/null || echo "$HOME/dxrice")/install.sh" update
}
dx() {
    local repo
    repo="$(cat "$HOME/.local/state/dxrice/repo_path" 2>/dev/null || echo "$HOME/dxrice")"
    case "$1" in
        update)
            "$repo/install.sh" update ;;
        theme)
            qs -p "$repo/quickshell/shell.qml" ipc call theme toggle 2>/dev/null \
                || python3 "$repo/scripts/dxrice_theme_gui.py" ;;
        taskbar)
            qs -p "$repo/quickshell/shell.qml" ipc call taskbar toggle 2>/dev/null \
                || python3 "$repo/scripts/dxrice_taskbar_gui.py" ;;
        settings|qs)
            qs -p "$repo/quickshell/shell.qml" ipc call quicksettings toggle 2>/dev/null \
                || python3 "$repo/scripts/dxrice_quick_settings.py" ;;
        sddm-theme)
            "$repo/install.sh" sddm-theme ;;
        lock)
            # Deliberately no GTK/hyprlock fallback here -- this is an
            # explicit try-it-yourself command for the new Quickshell lock
            # screen (see quickshell/LockScreen.qml), not a replacement for
            # the SUPER+L keybind, which still goes straight to hyprlock.
            if ! qs -p "$repo/quickshell/shell.qml" ipc call lock engage 2>&1; then
                echo "Couldn't reach the Quickshell lock screen (is Quickshell installed and running?)."
                echo "SUPER+L / 'hyprlock' still works as always."
            fi
            ;;
        *)
            echo "Usage: dx <update|theme|taskbar|settings|lock|sddm-theme>"
            echo "  update      pull the latest DXrice and re-deploy (same as dxrice-update)"
            echo "  theme       open the Theme settings (Quickshell if installed, else GTK)"
            echo "  taskbar     open the Taskbar manager"
            echo "  settings    open Quick Settings (alias: qs)"
            echo "  lock        try the new Quickshell lock screen (SUPER+L still uses hyprlock)"
            echo "  sddm-theme  sync the SDDM login theme (needs sudo)"
            return 1
            ;;
    esac
}
# END dxrice shell functions
BLOCK
)
    local added=0
    for rc in "$HOME/.bashrc" "$HOME/.zshrc"; do
        [ -f "$rc" ] || continue

        local before after
        before="$(cat "$rc" 2>/dev/null)"

        # Strip out ANY previous version of this block -- old pre-`dx`
        # single-function form, or a previous begin/end-bracketed form --
        # so re-running this always leaves exactly one, current copy
        # instead of silently going stale after the first install.
        DXRICE_RC_PATH="$rc" python3 - <<'PYEOF'
import os, re
path = os.environ["DXRICE_RC_PATH"]
with open(path) as f:
    content = f.read()

bracketed = re.compile(
    r"\n?# BEGIN dxrice shell functions \(added by DXrice's install\.sh\)\n"
    r"(?:.*\n)*?"
    r"# END dxrice shell functions\n?"
)
content = bracketed.sub("\n", content, count=1)

legacy_v1 = re.compile(
    r"\n?# dxrice-update \(added by DXrice's install\.sh\)\n"
    r"dxrice-update\(\) \{\n(?:.*\n)*?\}\n"
)
content = legacy_v1.sub("\n", content, count=1)

# The brief window before this got begin/end markers: same "/ dx" marker
# text as the current block, but no brackets, and both functions inline.
legacy_v2 = re.compile(
    r"\n?# dxrice-update / dx \(added by DXrice's install\.sh\)\n"
    r"dxrice-update\(\) \{\n(?:.*\n)*?\}\n"
    r"dx\(\) \{\n(?:.*\n)*?\}\n"
)
content = legacy_v2.sub("\n", content, count=1)

# Each \n? above only ever eats ONE of the newlines adjoining a stripped
# block, not the whole blank-line gap left behind -- across repeated
# install/update runs that stacks into an ever-growing run of blank lines
# before the re-appended block (confirmed live: 1 blank line after the
# first run, 2 after the second, 3 after the third, unbounded). Collapsing
# to a single trailing newline here, right before the block is
# re-appended below, caps the gap at exactly one blank line forever.
content = content.rstrip("\n") + "\n"

# Atomic write: a process killed mid-write must never leave a truncated
# shell rc file behind -- write to a temp file in the same directory, then
# rename, so the original survives intact if anything goes wrong.
tmp_path = path + f".dxrice.{os.getpid()}.tmp"
try:
    existing_mode = os.stat(path).st_mode & 0o777
except OSError:
    existing_mode = None
with open(tmp_path, "w") as f:
    f.write(content)
    f.flush()
    os.fsync(f.fileno())
if existing_mode is not None:
    os.chmod(tmp_path, existing_mode)
os.replace(tmp_path, path)
PYEOF

        after="$(cat "$rc" 2>/dev/null)"
        printf '\n%s\n' "$block" >> "$rc"
        if [ "$before" != "$after" ]; then
            ok "Updated the 'dx' and 'dxrice-update' commands in $rc"
        else
            ok "Added the 'dx' and 'dxrice-update' commands to $rc"
        fi
        added=1
    done
    if [ "$added" = "1" ]; then
        info "Open a new terminal (or run 'source ~/.bashrc'/'source ~/.zshrc') to pick up any changes."
    fi
}

# Companion to install_shell_alias() for uninstall -- strips the same
# begin/end-bracketed block (and both older unmarked forms) without adding
# anything back.
remove_shell_alias() {
    local removed=0
    for rc in "$HOME/.bashrc" "$HOME/.zshrc"; do
        [ -f "$rc" ] || continue
        local before after
        before="$(cat "$rc" 2>/dev/null)"
        DXRICE_RC_PATH="$rc" python3 - <<'PYEOF'
import os, re
path = os.environ["DXRICE_RC_PATH"]
with open(path) as f:
    content = f.read()

bracketed = re.compile(
    r"\n?# BEGIN dxrice shell functions \(added by DXrice's install\.sh\)\n"
    r"(?:.*\n)*?"
    r"# END dxrice shell functions\n?"
)
content = bracketed.sub("\n", content, count=1)

legacy_v1 = re.compile(
    r"\n?# dxrice-update \(added by DXrice's install\.sh\)\n"
    r"dxrice-update\(\) \{\n(?:.*\n)*?\}\n"
)
content = legacy_v1.sub("\n", content, count=1)

legacy_v2 = re.compile(
    r"\n?# dxrice-update / dx \(added by DXrice's install\.sh\)\n"
    r"dxrice-update\(\) \{\n(?:.*\n)*?\}\n"
    r"dx\(\) \{\n(?:.*\n)*?\}\n"
)
content = legacy_v2.sub("\n", content, count=1)

# Same blank-line-gap normalization as install_shell_alias -- leaves the
# file exactly as if the block had never been there, not with a stray
# trailing blank line from the strip.
content = content.rstrip("\n") + "\n"

# Atomic write: a process killed mid-write must never leave a truncated
# shell rc file behind -- write to a temp file in the same directory, then
# rename, so the original survives intact if anything goes wrong.
tmp_path = path + f".dxrice.{os.getpid()}.tmp"
try:
    existing_mode = os.stat(path).st_mode & 0o777
except OSError:
    existing_mode = None
with open(tmp_path, "w") as f:
    f.write(content)
    f.flush()
    os.fsync(f.fileno())
if existing_mode is not None:
    os.chmod(tmp_path, existing_mode)
os.replace(tmp_path, path)
PYEOF
        after="$(cat "$rc" 2>/dev/null)"
        if [ "$before" != "$after" ]; then
            ok "Removed the 'dx' and 'dxrice-update' commands from $rc"
            removed=1
        fi
    done
    # Deliberately NOT a bare `[ cond ] && info ...` here: that idiom
    # returns the TEST's own exit status whenever the condition is false,
    # and being this function's LAST statement makes that status become
    # remove_shell_alias's own return value. Called as a plain statement
    # (see do_uninstall), that silently kills the whole script under
    # `set -e` any time nothing needed removing (e.g. a second uninstall
    # run, or a user who never had the block) -- not an actual error, just
    # the common case. Confirmed live: the sibling bug in check_dependencies
    # below did exactly this and killed a real install partway through.
    if [ "$removed" = "1" ]; then
        info "Open a new terminal (or re-source your shell rc) to drop them from your current shell."
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
    # CONFIRMED LIVE BUG (bash -x trace from a real install): a bare
    # `[ cond ] && action` as a function's LAST statement makes that
    # test's own exit status become check_dependencies's return value
    # whenever cond is false -- which it always is on pacman, the most
    # common case this installer runs on. check_dependencies is called as
    # a plain statement in do_install (no ||/if guard), and with
    # `set -euo pipefail` active, that silently killed the ENTIRE install
    # right after printing "Quickshell present.", before Step 3/4 ever
    # ran -- no error message from install.sh itself, just a dead script.
    # An `if` never leaves its own exit status exposed this way.
    if [ "$PKG_MANAGER" != "pacman" ]; then
        install_nerd_font_fallback
    fi
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

    mkdir -p "$DATA_HOME/fonts"
    unzip -oq "$tmp/JetBrainsMono.zip" -d "$DATA_HOME/fonts/JetBrainsMonoNerdFont"
    rm -rf "$tmp"
    command -v fc-cache >/dev/null 2>&1 && fc-cache -f "$DATA_HOME/fonts" >/dev/null 2>&1
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

# Turns LEGACY_SCRIPT_NAMES into a single alternation for grep -E/bash's
# =~, with literal dots escaped -- shared by reconcile_copy_once_ownership's
# recognizers and check_legacy_rice_checkout so a name added for one is
# recognized by both, rather than two independently-maintained regexes.
_legacy_names_regex() {
    local IFS='|'
    local escaped=()
    local name
    for name in "${LEGACY_SCRIPT_NAMES[@]}"; do
        escaped+=("${name//./\\.}")
    done
    echo "${escaped[*]}"
}

# Ownership reconciliation for every copy-once file (hyprland.lua + the
# four waybar configs). Used to be three independent checks here --
# check_stale_hyprland_lua, check_stale_waybar_configs (marker-based,
# correctly recognized a current-shaped DXrice file and left it alone),
# and check_foreign_copy_once_files (snapshot-absence-based: "no snapshot
# => DXrice never put this here => offer to replace it"). The third ran
# independently of what the first two had just established, so a file
# they'd positively recognized as a genuine, current-shaped DXrice
# deployment -- just one that predates the copy_once_snapshots mechanism
# added after it was deployed -- still got treated as foreign purely for
# lacking a snapshot. Live incident this caused: a real ~/.config/waybar/
# config-dock, with real custom taskbar shortcuts (Brave/Discord/Sober/
# Steam/Prism Launcher/VirtualBox/VS Code), backed up and overwritten with
# the bare template on a completely ordinary `install.sh install` run.
#
# All classification now goes through one shared model (see
# scripts/dxrice_copy_once_ownership.py for the full state machine and its
# own test suite) with one hard invariant: if ownership cannot be proven,
# the file is preserved -- uncertainty never results in an overwrite. Only
# a file positively identified as DXrice's own (current-shaped but missing
# its snapshot, or an old pre-Quickshell shape) is ever eligible for any
# action, and even then: a current-shaped one is never touched at all
# (just silently given the snapshot it was always missing), and an
# old-shaped one is only ever replaced after this same explicit,
# declined-by-default-does-nothing confirmation the old checks already
# used.
reconcile_copy_once_ownership() {
    local ownership_py="$REPO_DIR/scripts/dxrice_copy_once_ownership.py"
    [ -f "$ownership_py" ] || return 0
    command -v python3 >/dev/null 2>&1 || return 0

    local rel state detail
    while IFS=$'\t' read -r rel state detail; do
        [ -n "$rel" ] || continue
        case "$state" in
            LEGACY_DXRICE)
                if [ "$detail" = "current-shaped" ]; then
                    # Positively DXrice's own, already in the shape the
                    # repo ships today -- nothing to replace, just backfill
                    # the snapshot it never got. Never reads or rewrites
                    # the live file. Failure here (e.g. an unwritable
                    # state dir) leaves the live file untouched either
                    # way -- warn and move on rather than letting a bare
                    # `&&` list's nonzero status take the whole install
                    # down via set -e over something that was never going
                    # to touch the user's file in the first place.
                    if python3 "$ownership_py" claim-snapshot "$rel" "$CONFIG_HOME" "$STATE_DIR" "$REPO_DIR"; then
                        ok "~/.config/$rel recognized as your existing DXrice deployment -- left exactly as it is."
                    else
                        warn "Couldn't record ~/.config/$rel as a known DXrice deployment (non-fatal) --"
                        info "the file itself is untouched; this will be retried on the next run."
                    fi
                    continue
                fi
                # old-shaped: a genuine pre-Quickshell DXrice file. Same
                # upgrade offer the old per-file checks used.
                warn "~/.config/$rel is from a much older version of this rice."
                info "It predates the current layout, so it won't pick that up on its own."
                if [ -L "$CONFIG_HOME/$rel" ]; then
                    info "Note: this path is currently a symlink -- replacing it backs up and"
                    info "preserves whatever it points to, but points this path at a plain file"
                    info "afterward instead of your symlink."
                fi
                if ask_yes_no "Back it up and let the current version deploy instead?" Y; then
                    mkdir -p "$STATE_DIR/backups"
                    local backup="$STATE_DIR/backups/${rel//\//_}.$(date +%s).bak"
                    if ! cp "$CONFIG_HOME/$rel" "$backup"; then
                        warn "Backup to $backup failed -- leaving ~/.config/$rel exactly as it is."
                    elif ! cmp -s "$CONFIG_HOME/$rel" "$backup"; then
                        warn "Backup at $backup doesn't match the original -- leaving ~/.config/$rel"
                        info "exactly as it is rather than risk deleting it on an unverified backup."
                        rm -f "$backup"
                    else
                        rm -f "$CONFIG_HOME/$rel"
                        ok "Backed up to $backup and removed the live copy -- deploying the current version next."
                    fi
                else
                    warn "Leaving ~/.config/$rel as-is -- it'll keep looking like the old rice until"
                    info "you either edit it by hand or re-run install and say yes here."
                fi
                ;;
            FOREIGN)
                info "~/.config/$rel exists but looks like it belongs to a different setup --"
                info "left completely alone; DXrice's own version won't deploy over it."
                ;;
            UNKNOWN)
                info "~/.config/$rel already exists and DXrice can't positively tell whose it is --"
                info "left completely alone (never guessed at) until you move it yourself."
                ;;
            DXRICE_OWNED_UNCHANGED|DXRICE_OWNED_MODIFIED)
                : # Already tracked and already safe -- dxrice_deploy.py's
                  # own hash-guard (or, for these copy-once files, its
                  # unconditional "leave alone if it exists" rule) handles
                  # this; nothing for install.sh itself to do.
                ;;
        esac
    done < <(python3 "$ownership_py" classify "$CONFIG_HOME" "$STATE_DIR")
}

# Narrower companion to reconcile_copy_once_ownership: a hyprland.lua
# already recognized as current-shaped (so that check leaves it alone) can
# still predate a later change to one specific bind -- e.g. the taskbar
# manager moving from a kitty-terminal script to a GUI. Patches just that
# one line in place, leaving every other keybind/customization untouched.
migrate_taskbar_bind() {
    local f="$CONFIG_HOME/hypr/hyprland.lua"
    [ -f "$f" ] || return 0
    grep -q "dxrice-manage-taskbar.sh" "$f" 2>/dev/null || return 0

    info "Updating your SUPER+SHIFT+A bind to the new taskbar GUI..."
    sed -i -E \
        's#hl\.dsp\.exec_cmd\("kitty -e " \.\. repo \.\. "/scripts/dxrice-manage-taskbar\.sh"\)#hl.dsp.exec_cmd("python3 " .. repo .. "/scripts/dxrice_taskbar_gui.py")#' \
        "$f"
}

# Quickshell and the two always-on Python daemons (new-window placement,
# infinite-desktop panning) are started via a systemd --user unit instead
# of a bare exec_cmd, specifically so a crash doesn't mean "dead for the
# rest of the session" -- Restart=on-failure brings each one back on its
# own, and StartLimitBurst stops a genuinely broken one from restart-
# looping forever. Mechanism verified live against a real systemd --user
# instance with a throwaway, uniquely-named test unit (never touching any
# real dxrice process): a script made to always fail was restarted exactly
# StartLimitBurst times, then systemd correctly stopped retrying with
# "start-limit-hit" -- both the recovery and the safety cutoff confirmed
# working before this was ever wired into a real unit.
#
# Units are regenerated on every install/update, never hand-edited, so
# overwriting them every run is always safe -- this machine's real
# resolved qs/python3 paths and repo location are baked in fresh each
# time, picked up the same way a relocated repo already works everywhere
# else in this installer.
deploy_systemd_units() {
    command -v systemctl >/dev/null 2>&1 || return 0
    local unit_dir="$CONFIG_HOME/systemd/user"
    mkdir -p "$unit_dir"

    local qs_bin python_bin
    qs_bin="$(command -v qs || true)"
    python_bin="$(command -v python3 || true)"

    if [ -n "$qs_bin" ]; then
        cat > "$unit_dir/dxrice-quickshell.service" <<EOF
[Unit]
Description=DXrice Quickshell shell (bars, taskbar, quick settings, theme editor)
StartLimitIntervalSec=30
StartLimitBurst=5

[Service]
ExecStart=$qs_bin -p $REPO_DIR/quickshell/shell.qml
Restart=on-failure
RestartSec=1
EOF
    fi

    if [ -n "$python_bin" ]; then
        cat > "$unit_dir/dxrice-auto-place-window.service" <<EOF
[Unit]
Description=DXrice new-window auto-placement
StartLimitIntervalSec=30
StartLimitBurst=5

[Service]
ExecStart=$python_bin $REPO_DIR/scripts/dxrice_auto_place_window.py
Restart=on-failure
RestartSec=1
EOF

        cat > "$unit_dir/dxrice-infinite-desktop.service" <<EOF
[Unit]
Description=DXrice infinite-desktop panning/drag daemon
StartLimitIntervalSec=30
StartLimitBurst=5

[Service]
ExecStart=$python_bin $REPO_DIR/scripts/dxrice_infinite_desktop_core.py 1.6
Restart=on-failure
RestartSec=1
EOF
    fi

    systemctl --user daemon-reload 2>/dev/null || true
}

# Narrower companion to migrate_taskbar_bind, same pattern: an already-
# deployed hyprland.lua (so reconcile_copy_once_ownership left it alone)
# can still predate the systemd-supervision change above. Patches just
# those three specific exec_cmd lines in place -- matched against this
# installer's own exact previous template text, verified against this
# session's real deployed file before being written -- leaving every
# other keybind/customization completely untouched.
migrate_exec_to_systemd_units() {
    local f="$CONFIG_HOME/hypr/hyprland.lua"
    [ -f "$f" ] || return 0
    grep -q "dxrice-quickshell.service" "$f" 2>/dev/null && return 0  # already migrated

    grep -q 'qs -p " .. repo .. "/quickshell/shell.qml -d -n' "$f" 2>/dev/null || return 0

    info "Updating your Quickshell/placement/panning autostart to use systemd"
    info "supervision (so a crash recovers on its own instead of staying dead)..."
    python3 - "$f" <<'PYEOF'
import os
import re
import sys

path = sys.argv[1]
with open(path) as fh:
    content = fh.read()

content = content.replace(
    '"qs -p " .. repo .. "/quickshell/shell.qml -d -n; else "',
    '"systemctl --user restart dxrice-quickshell.service; else "',
)
content = re.sub(
    r'hl\.exec_cmd\("python3 " \.\. repo \.\. "/scripts/dxrice_infinite_desktop_core\.py 1\.6[^"]*"\)',
    'hl.exec_cmd("systemctl --user restart dxrice-infinite-desktop.service")',
    content,
)
content = re.sub(
    r'hl\.exec_cmd\("python3 " \.\. repo \.\. "/scripts/dxrice_auto_place_window\.py[^"]*"\)',
    'hl.exec_cmd("systemctl --user restart dxrice-auto-place-window.service")',
    content,
)

# Atomic write -- this rewrites a live, user-customized hyprland.lua in
# place; a process killed mid-write must never leave it truncated.
tmp_path = path + f".dxrice.{os.getpid()}.tmp"
try:
    existing_mode = os.stat(path).st_mode & 0o777
except OSError:
    existing_mode = None
with open(tmp_path, "w") as fh:
    fh.write(content)
    fh.flush()
    os.fsync(fh.fileno())
if existing_mode is not None:
    os.chmod(tmp_path, existing_mode)
os.replace(tmp_path, path)
PYEOF
}

# A machine that ran a much older, pre-dxrice version of this exact rice
# (before the dxrice_ prefix, before Quickshell, back when the taskbar
# manager was a plain bash script) can have that ENTIRE OLD CHECKOUT still
# sitting on disk, with its own shell aliases pointing straight at it --
# completely separate from, and invisible to, install_shell_alias/
# remove_shell_alias, which only ever manage the single "# BEGIN/END
# dxrice shell functions" block THIS installer writes. Left alone, the
# old checkout and its aliases just sit there forever, confusingly
# working alongside the current one. Live-reported: a fresh install next
# to an ancient checkout at ~/hyprland-rice-main, with ~/.bashrc still
# carrying its own `alias managetaskbar=...`/`alias reordertaskbar=...`
# pointing straight at it.
#
# Detected the same way reconcile_copy_once_ownership detects an old
# hyprland.lua: by name, not by guessing at a path. Scans ~/.bashrc and
# ~/.zshrc for a plain `alias ...=` line that mentions one of
# LEGACY_SCRIPT_NAMES -- the current rice's own managed block never
# generates a line like this, so a match here is never a false positive
# against dxrice's own aliases, and never touches anything else the user
# put in their own rc file (a dxrice-unrelated alias sitting right next to
# one of these, like a personal shortcut or compiler alias, is left
# completely alone).
check_legacy_rice_checkout() {
    local names_re
    names_re="$(_legacy_names_regex)"
    local rc found_dirs=() found_lines=()

    for rc in "$HOME/.bashrc" "$HOME/.zshrc"; do
        [ -f "$rc" ] || continue
        while IFS= read -r line; do
            [[ "$line" =~ alias[[:space:]] ]] || continue
            [[ "$line" =~ ($names_re) ]] || continue
            local path dir
            path=$(grep -oE "[^ \"']*(${names_re})" <<<"$line" | head -1)
            [ -n "$path" ] || continue
            # Every version of this rice old enough to use these names
            # still kept them in a scripts/ subdirectory of the checkout
            # root -- strip that suffix to get the root itself.
            dir="${path%/scripts/*}"
            [ -d "$dir" ] || continue
            [ -d "$dir/scripts" ] || continue  # confirm it's a real checkout, not a stale/moved path
            found_dirs+=("$dir")
            found_lines+=("$rc:$line")
        done < "$rc"
    done

    [ "${#found_dirs[@]}" -eq 0 ] && return 0

    local -A seen=()
    local uniq_dirs=() d
    for d in "${found_dirs[@]}"; do
        [ -n "${seen[$d]:-}" ] && continue
        seen[$d]=1
        uniq_dirs+=("$d")
    done

    warn "Found what looks like a much older checkout of this rice, from before it"
    info "used the dxrice_ names or Quickshell:"
    for d in "${uniq_dirs[@]}"; do
        info "  $d"
    done
    info "Referenced by these leftover shell alias(es), outside anything this"
    info "installer itself manages:"
    local fl
    for fl in "${found_lines[@]}"; do
        info "  $fl"
    done

    if ask_yes_no "Remove those stale alias lines and move the old checkout(s) out of the way?" Y; then
        # Remove EXACTLY the lines found_lines recorded above -- the ones
        # that already passed every check (alias-shaped, names a legacy
        # script, resolves to a real existing checkout directory) -- by
        # exact string match, never a fresh broad regex pass. Confirmed
        # live: a prior version here used `grep -vE "$names_re"` against
        # the WHOLE file, which matches that bare substring on ANY line
        # regardless of alias-ness -- it silently deleted an unrelated
        # comment and an unrelated echo string that merely mentioned
        # "theme_gui.py" in passing, and even deleted a line from the dx()
        # function install_shell_alias had just written in the same run,
        # because "theme_gui.py" is a substring of "dxrice_theme_gui.py".
        # Exact-line removal can't match either case: a comment/echo line
        # was never in found_lines (it never matched alias[[:space:]]),
        # and dxrice_theme_gui.py's actual line was never in found_lines
        # either (install_shell_alias hadn't even run yet when detection
        # happened, and that line was never an alias in the first place).
        for rc in "$HOME/.bashrc" "$HOME/.zshrc"; do
            [ -f "$rc" ] || continue
            local lines_to_remove=()
            local fl2
            for fl2 in "${found_lines[@]}"; do
                [ "${fl2%%:*}" = "$rc" ] && lines_to_remove+=("${fl2#*:}")
            done
            [ "${#lines_to_remove[@]}" -eq 0 ] && continue

            local tmp existing_mode
            tmp="$(mktemp "$(dirname "$rc")/.$(basename "$rc").XXXXXX")"
            existing_mode="$(stat -c %a "$rc" 2>/dev/null || echo 644)"
            local out_line keep lr
            : > "$tmp"
            while IFS= read -r out_line || [ -n "$out_line" ]; do
                keep=1
                for lr in "${lines_to_remove[@]}"; do
                    if [ "$out_line" = "$lr" ]; then
                        keep=0
                        break
                    fi
                done
                [ "$keep" = "1" ] && printf '%s\n' "$out_line" >> "$tmp"
            done < "$rc"

            if ! cmp -s "$rc" "$tmp"; then
                chmod "$existing_mode" "$tmp"
                mv "$tmp" "$rc"
                ok "Removed the stale alias line(s) from $rc"
            else
                rm -f "$tmp"
            fi
        done
        mkdir -p "$STATE_DIR/backups"
        for d in "${uniq_dirs[@]}"; do
            local dest="$STATE_DIR/backups/$(basename "$d").$(date +%s)"
            if mv "$d" "$dest"; then
                ok "Moved $d to $dest (not deleted -- safe to remove by hand once you've confirmed you don't need anything from it)"
            else
                warn "Could not move $d -- leaving it in place."
            fi
        done
        info "Open a new terminal (or re-source your shell rc) to drop the old aliases from your current shell."
    else
        warn "Leaving the old checkout and its aliases in place."
    fi
}

# Root-cause fix for a real, previously-silent failure mode: hyprland.lua is
# copy-once (see do_deploy/dxrice_deploy.py) so it's yours to hand-edit
# forever, but that also means a `git pull` that adds a new required
# autostart line or default keybind to the repo's template has no way to
# ever reach your already-deployed copy -- and nothing ever told you it
# happened. That's exactly what let dxrice_auto_place_window.py's autostart
# line silently never run for a full session. Never modifies your live
# file -- only tells you, in plain terms, what's new.
check_hypr_drift() {
    python3 "$REPO_DIR/scripts/dxrice_check_hypr_drift.py" 2>/dev/null || true
}

detect_monitor() {
    local target="$CONFIG_HOME/hypr/hyprland.lua"
    command -v hyprctl >/dev/null 2>&1 || { warn "hyprctl not found (Hyprland not running yet) -- skipping monitor auto-detect, edit hypr/hyprland.lua's eDP-1/resolution by hand."; return; }
    python3 - "$target" <<'PYEOF'
import json, os, re, subprocess, sys

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
# Atomic write -- same reasoning as migrate_exec_to_systemd_units: this is
# a live, user-customized file, never safe to truncate mid-write.
tmp_path = target + f".dxrice.{os.getpid()}.tmp"
try:
    existing_mode = os.stat(target).st_mode & 0o777
except OSError:
    existing_mode = None
with open(tmp_path, "w") as f:
    f.write(content)
    f.flush()
    os.fsync(f.fileno())
if existing_mode is not None:
    os.chmod(tmp_path, existing_mode)
os.replace(tmp_path, target)
print(f"Detected monitor {name} ({mode} at {pos}) and wrote it into hyprland.lua")
PYEOF
}

do_deploy() {
    info "Deploying configs (anything you've hand-edited is protected)..."
    mkdir -p "$CONFIG_HOME"/{hypr,kitty,waybar,mako,wofi}
    if ! python3 "$REPO_DIR/scripts/dxrice_deploy.py" "$REPO_DIR"; then
        err "Deploying configs failed (see the Python error above) -- stopping here rather than"
        info "continuing into theme rendering and systemd setup against a half-deployed state."
        info "Every individual file write above is all-or-nothing (atomic), so whatever it did"
        info "reach is correctly in place -- re-run './install.sh' (or 'update') once you've"
        info "resolved whatever the error above points at to pick up the rest."
        exit 1
    fi

    echo ""
    info "Rendering theme (waybar/wofi/mako/kitty/hyprlock from theme.json)..."
    # No explicit path: dxrice_apply_theme.py seeds ~/.config/dxrice/theme.json
    # from the repo's default on a fresh install, then reuses that live copy
    # on every later run (including `install.sh update`) -- your own color
    # tweaks never get overwritten by a repo update, and never show up as a
    # locally-modified tracked file either.
    python3 "$REPO_DIR/scripts/dxrice_apply_theme.py" || true

    echo ""
    info "Setting up systemd supervision for Quickshell and the placement/panning daemons..."
    deploy_systemd_units
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
        "$CONFIG_HOME/hypr/hyprland.lua"
        "$STATE_DIR/repo_path"
        "$REPO_DIR/scripts/dxrice_infinite_desktop_core.py"
        "$REPO_DIR/scripts/dxrice_auto_place_window.py"
        "$REPO_DIR/scripts/dxrice_auto_arrange.py"
        "$REPO_DIR/scripts/dxrice_hypr_ipc.py"
        "$REPO_DIR/scripts/dxrice_singleton.py"
        "$REPO_DIR/scripts/dxrice_xdg.py"
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

    # Deterministic placement/arrangement geometry tests -- pure-Python,
    # no live Hyprland needed (see the script's own docstring), so this
    # runs safely as part of every install/update rather than only when
    # someone happens to run it by hand. A failure here means the window
    # placement/auto-arrange logic itself is broken, not a deploy problem,
    # so it's reported distinctly rather than folded into the file-presence
    # check above.
    if command -v python3 >/dev/null 2>&1 && [ -f "$REPO_DIR/scripts/dxrice_test_placement.py" ]; then
        if python3 "$REPO_DIR/scripts/dxrice_test_placement.py" >/tmp/dxrice-verify-tests.log 2>&1; then
            ok "Window placement/arrangement tests passed."
        else
            warn "Window placement/arrangement tests FAILED -- see /tmp/dxrice-verify-tests.log"
            info "SUPER+G and new-window auto-placement may not behave correctly."
        fi
    fi

    if [ -f "$CONFIG_HOME/hypr/hyprland.conf" ]; then
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
    reconcile_copy_once_ownership
    migrate_taskbar_bind
    migrate_exec_to_systemd_units
    check_legacy_rice_checkout
    local hypr_existed=0
    [ -f "$CONFIG_HOME/hypr/hyprland.lua" ] && hypr_existed=1

    do_deploy
    verify_deploy || true
    check_hypr_drift

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

# Removes DXrice's own integration points -- never your saved themes,
# config, data, or state, and never the app config files it deployed into
# real ~/.config/<app> directories (those are indistinguishable from your
# own hand-edits by the time you'd uninstall, so deleting them
# automatically would be guessing at what you want gone). A full wipe of
# $DXRICE_CONFIG_DIR/$DXRICE_DATA_DIR/$STATE_DIR is a separate, explicit
# --purge flag -- never the default, and it confirms exactly what it's
# about to delete before doing it.
do_uninstall() {
    banner
    local purge="$PURGE"

    step "Removing DXrice integration"
    remove_shell_alias

    if [ -f "$STATE_DIR/repo_path" ]; then
        rm -f "$STATE_DIR/repo_path"
        ok "Removed the recorded repo location ($STATE_DIR/repo_path)"
    fi

    if [ -d /usr/share/sddm/themes/dxrice ] || [ -f /etc/sddm.conf.d/dxrice.conf ]; then
        if ask_yes_no "The DXrice SDDM login theme is installed -- remove it too? (needs sudo)" Y; then
            sudo rm -f /etc/sddm.conf.d/dxrice.conf
            sudo rm -rf /usr/share/sddm/themes/dxrice
            ok "SDDM theme and config removed -- SDDM will use its default theme on the next login."
        else
            info "Left in place. Remove later with: sudo rm -f /etc/sddm.conf.d/dxrice.conf && sudo rm -rf /usr/share/sddm/themes/dxrice"
        fi
    fi

    echo ""
    echo "${C_BOLD}${C_GREEN}Application removed.${C_RESET} User configuration and themes were preserved at:"
    info "  Config: $DXRICE_CONFIG_DIR"
    info "  Data:   $DXRICE_DATA_DIR"
    info "  State:  $STATE_DIR"
    info "Your deployed app configs (hyprland.lua, waybar, wofi, etc. under $CONFIG_HOME)"
    info "were left exactly as they are -- delete them yourself if you want a clean slate."
    info "This checkout ($REPO_DIR) was not deleted; remove it yourself if you're done with it."

    if [ "$purge" = "1" ]; then
        echo ""
        warn "${C_BOLD}--purge requested.${C_RESET} This will PERMANENTLY DELETE:"
        info "  $DXRICE_CONFIG_DIR  (your theme.json, colors, wallpaper choice, presets)"
        info "  $DXRICE_DATA_DIR    (saved themes, migration/SDDM backups)"
        info "  $STATE_DIR          (deploy manifest, repo_path)"
        if ask_yes_no "Are you SURE you want to permanently delete these?" N; then
            rm -rf "$DXRICE_CONFIG_DIR" "$DXRICE_DATA_DIR" "$STATE_DIR"
            ok "Purged. Nothing of DXrice's remains outside this checkout and your deployed app configs."
        else
            info "Purge cancelled -- your config/data/state were left in place."
        fi
    else
        echo ""
        info "To also permanently delete your saved config/themes/data, re-run:"
        info "  ./install.sh uninstall --purge"
    fi
}

# Read-only: reports exactly what install/update would do without doing any
# of it. Deliberately does not call check_platform/check_dependencies/
# do_deploy/do_sddm_theme etc. directly -- those mutate or prompt -- this
# re-derives the same decisions from cheap, side-effect-free inspection
# instead, so "nothing below is actually changed" is a claim this function
# can actually back up.
do_dry_run() {
    local for_mode="$1"
    banner
    echo ""
    echo "${C_BOLD}${C_CYAN}DRY RUN${C_RESET} (${for_mode}) -- nothing below is actually changed."

    step "Repository"
    require_repo_layout
    info "Checkout: $REPO_DIR"
    if [ -f "$STATE_DIR/repo_path" ]; then
        info "repo_path already recorded at $STATE_DIR/repo_path -- would leave it as-is."
    else
        info "Would create $STATE_DIR and record this checkout's location there."
    fi

    step "Package manager / dependencies"
    local pm=""
    if command -v pacman >/dev/null 2>&1; then pm="pacman"
    elif command -v dnf >/dev/null 2>&1; then pm="dnf"
    elif command -v apt-get >/dev/null 2>&1; then pm="apt"
    elif command -v zypper >/dev/null 2>&1; then pm="zypper"
    fi
    if [ -z "$pm" ]; then
        warn "No supported package manager detected -- would skip automatic dependency installation."
    else
        PKG_MANAGER="$pm"
        info "Detected: $pm"
        local -a general=() missing=()
        case "$pm" in
            pacman) general=("${GENERAL_PACMAN[@]}") ;;
            dnf) general=("${GENERAL_DNF[@]}") ;;
            apt) general=("${GENERAL_APT[@]}") ;;
            zypper) general=("${GENERAL_ZYPPER[@]}") ;;
        esac
        for pkg in "${general[@]}"; do
            _pkg_installed "$pkg" || missing+=("$pkg")
        done
        if [ "${#missing[@]}" -gt 0 ]; then
            info "Would offer to install (needs sudo): ${missing[*]}"
        else
            ok "All general dependencies already present -- nothing to install."
        fi
        local -a hmissing=()
        for pkg in "${HYPR_PACKAGES[@]}"; do
            _pkg_installed "$pkg" || hmissing+=("$pkg")
        done
        [ "${#hmissing[@]}" -gt 0 ] && info "Would also offer Hyprland packages (needs sudo): ${hmissing[*]}"
        if _pkg_installed quickshell || command -v qs >/dev/null 2>&1; then
            ok "Quickshell already present."
        else
            info "Would offer to install Quickshell (needs sudo, pacman only -- other distros get manual instructions)."
        fi
    fi

    step "Input group"
    if id -nG "$USER" | grep -qw input; then
        ok "Already in the 'input' group."
    else
        info "Would offer to add you to the 'input' group (needs sudo)."
    fi

    step "Config initialization / migration ($DXRICE_CONFIG_DIR)"
    local theme_json="$DXRICE_CONFIG_DIR/theme.json"
    if [ -f "$theme_json" ]; then
        ok "Live theme config exists -- would be preserved exactly, never replaced."
        local schema current
        schema="$(python3 -c "import json,sys; print(json.load(open(sys.argv[1])).get('schema_version', 0))" "$theme_json" 2>/dev/null || echo "?")"
        current="$(cd "$REPO_DIR/scripts" && python3 -c "import dxrice_config_migrate as m; print(m.CURRENT_SCHEMA_VERSION)" 2>/dev/null || echo "?")"
        if [ "$schema" != "$current" ] && [ "$schema" != "?" ] && [ "$current" != "?" ]; then
            info "Schema version $schema is behind current ($current) -- would back up to"
            info "$DXRICE_DATA_DIR/backups/<timestamp>/ and migrate (adds new keys only, never"
            info "overwrites or removes anything you've already set)."
        else
            ok "Schema version is current -- no migration needed."
        fi
    else
        info "No live config yet -- would initialize $theme_json from the repo's shipped"
        info "default ($REPO_DIR/theme/theme.json)."
    fi

    step "App config deployment ($CONFIG_HOME)"
    for rel in hypr/hyprland.lua waybar/config waybar/config-left waybar/config-right waybar/config-dock wofi/config; do
        local dst="$CONFIG_HOME/$rel"
        if [ -f "$dst" ]; then
            ok "$rel exists -- copy-once, would be left exactly as you have it."
        else
            info "$rel missing -- would be created from the repo's default."
        fi
    done
    info "waybar/wofi/mako/kitty/hyprlock's rendered theme files would be re-rendered from"
    info "your live theme.json -- except any you've hand-edited since the last deploy"
    info "(tracked in $STATE_DIR/manifest.json), which would be left untouched and reported."

    step "SDDM"
    if ! command -v sddm >/dev/null 2>&1; then
        info "SDDM not detected -- would skip entirely (never installs a display manager)."
    elif [ -f /etc/sddm.conf.d/dxrice.conf ]; then
        info "DXrice SDDM theme already active -- would offer to re-sync it (needs sudo);"
        info "declining leaves your current login screen untouched."
    else
        info "SDDM detected, no DXrice theme active yet -- would ask before touching anything"
        info "(needs sudo); declining is the default and leaves SDDM completely alone."
    fi

    echo ""
    echo "${C_BOLD}${C_CYAN}End of dry run.${C_RESET} Nothing was changed. Run without --dry-run to apply."
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
            # A failed pop (merge conflict between your edit and the pulled
            # change) can leave literal <<<<<<< conflict markers sitting in
            # a tracked .py file -- confirmed live: redeploying straight
            # through that state makes dxrice_deploy.py's own `import`
            # crash with a raw Python SyntaxError traceback instead of a
            # clear explanation. Stop here instead; the stash is never
            # dropped on failure, so nothing is lost by stopping.
            if ! git stash pop; then
                err "Could not auto-restore your stashed local repo edits -- this usually means"
                info "they conflict with what was just pulled. Your edits are safe in the stash"
                info "(not lost), but the repo is left mid-conflict, so redeploying now would fail."
                info "Resolve it by hand, then re-run './install.sh update':"
                info "  git status               # see which file(s) conflict"
                info "  <edit the conflicted file(s), remove the <<<<<<< / ======= / >>>>>>> markers>"
                info "  git add <file>            # mark each one resolved"
                info "  git stash drop            # once you're happy with the result"
                exit 1
            fi
        fi
    fi

    step "Redeploying"
    reconcile_copy_once_ownership
    migrate_taskbar_bind
    migrate_exec_to_systemd_units
    check_legacy_rice_checkout
    local hypr_existed=0
    [ -s "$CONFIG_HOME/hypr/hyprland.lua" ] && hypr_existed=1

    record_repo_path
    install_shell_alias
    do_deploy
    verify_deploy || true
    check_hypr_drift

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
    install|"")
        if [ "$DRY_RUN" = "1" ]; then do_dry_run install; else do_install; fi ;;
    update)
        if [ "$DRY_RUN" = "1" ]; then do_dry_run update; else do_update; fi ;;
    sddm-theme) do_sddm_theme ;;
    uninstall) do_uninstall ;;
    help|-h|--help) usage ;;
    *) usage; exit 1 ;;
esac
