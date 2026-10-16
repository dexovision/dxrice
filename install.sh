#!/usr/bin/env bash
# Installer / updater for the DXrice dotfiles.
#
#   ./install.sh                 fresh install: asks where to put
#                                 everything, sanity checks, deps, input
#                                 group, monitor detection, deploy
#   ./install.sh update          fetch, show the incoming commits, ask,
#                                 fast-forward, then re-deploy. Refuses
#                                 (changing nothing) if your own edits in
#                                 the checkout touch the same files or the
#                                 branch has diverged, and says how to
#                                 resolve it. Never resets or stashes.
#                                 Files you've hand-edited in
#                                 $XDG_CONFIG_HOME are left alone. Also
#                                 offers to re-sync the SDDM login theme if
#                                 it's set up.
#   ./install.sh sddm-theme      deploy the DXrice login theme for SDDM
#                                 (needs sudo; only touches SDDM's own
#                                 theme dir and config -- never installs or
#                                 enables a display manager for you).
#                                 Re-run any time you change your
#                                 wallpaper/colors and want the login
#                                 screen to match.
#   ./install.sh uninstall       removes DXrice's own integration (its
#                                 services, shell functions, recorded repo
#                                 path, the SDDM theme if you confirm) -- never your
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
#   --yes                         answer yes to privileged and file-changing
#                                 prompts (package installs, the input group,
#                                 hyprland.lua migrations). Without a terminal
#                                 and without --yes, those prompts answer no.
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
ORIG_ARGS=("$@")
MODE=""
DRY_RUN=0
PURGE=0
ASSUME_YES="${DXRICE_ASSUME_YES:-0}"
for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY_RUN=1 ;;
        --purge) PURGE=1 ;;
        --yes|-y) ASSUME_YES=1 ;;
        *) [ -z "$MODE" ] && MODE="$arg" ;;
    esac
done
MODE="${MODE:-install}"

# Distro package names live in deps/<package manager>.list, one line per
# package (see deps/README.md); nothing below names a distro package.
# Hyprland 0.55 is the first release that reads hyprland.lua.
HYPRLAND_MIN_VERSION="0.55"

# Script basenames from much older, pre-Quickshell versions of this rice
# (back when it used plain bash scripts and had no dxrice_ prefix at all).
# Shared by reconcile_copy_once_ownership's recognizers (does a DEPLOYED
# copy-once file still point at these) and check_legacy_rice_checkout (is
# there an entire old CHECKOUT of the rice still on disk, referenced by leftover shell
# aliases) -- one list so a name added for one check is recognized by
# both, rather than two independently-maintained regexes drifting apart.
LEGACY_SCRIPT_NAMES=(manage-taskbar.sh reorder-taskbar.sh infinite_desktop_core.py
    theme_gui.py floating_tile_toggle.py)

# The systemd user units deploy_systemd_units writes and do_uninstall
# removes -- one list, so the two can't drift apart (scripts/
# dxrice_test_config_integrity.py also checks it against hyprland.lua's
# autostart lines).
DXRICE_UNITS=(dxrice-quickshell.service dxrice-auto-place-window.service dxrice-infinite-desktop.service)

# JetBrains Mono Nerd Font isn't a real package almost anywhere outside
# Arch's community repo -- fetched straight from the Nerd Fonts project's
# own releases for every other package manager (see
# install_nerd_font_fallback).
NERD_FONT_RELEASE_URL="https://github.com/ryanoasis/nerd-fonts/releases/latest/download/JetBrainsMono.zip"

SKIP_DEPS=0
PKG_MANAGER=""
INIT_SYSTEM=""
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
    sed -n '2,/^set -euo pipefail/{/^#/p}' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

# ask_yes_no "prompt" DEFAULT   (DEFAULT is Y or N)
# For routine questions. Without a terminal it takes the default.
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

# confirm "prompt"
# For anything privileged (sudo, package installs, group changes) or anything
# that changes or moves the user's own files. Defaults to yes at a terminal.
# Without one it answers no, unless --yes was given: nothing is installed or
# edited because a script happened to run unattended.
confirm() {
    if [ "$ASSUME_YES" = "1" ]; then
        info "$1 [Y/n] -> yes (--yes)"
        return 0
    fi
    if [ ! -t 0 ]; then
        info "$1 [Y/n] -> no terminal attached, skipping (re-run with --yes to accept)"
        return 1
    fi
    ask_yes_no "$1" Y
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

# Which distro, package manager and init system this is. Package manager
# first found wins; os-release only names the distro in messages.
check_platform() {
    local distro="unknown Linux"
    if [ -r /etc/os-release ]; then
        distro="$(. /etc/os-release 2>/dev/null; echo "${PRETTY_NAME:-${NAME:-unknown Linux}}")"
    fi
    PKG_MANAGER="$(detect_pkg_manager)"
    if [ -d /run/systemd/system ]; then
        INIT_SYSTEM=systemd
    elif command -v openrc >/dev/null 2>&1 || command -v rc-status >/dev/null 2>&1; then
        INIT_SYSTEM=openrc
    else
        INIT_SYSTEM=other
    fi
    ok "System: $distro (package manager: $PKG_MANAGER, init: $INIT_SYSTEM)"
    if [ "$INIT_SYSTEM" != systemd ]; then
        info "No systemd: the shell and its daemons will run under DXrice's own supervisor"
        info "(scripts/dxrice_session.sh) instead of systemd user units."
    fi

    if [ "$PKG_MANAGER" = "unknown" ]; then
        warn "No supported package manager (pacman, emerge, dnf, apt, zypper) -- dependencies"
        info "can't be installed automatically. You can still continue if Hyprland, Quickshell"
        info "or waybar, Python 3 with python-evdev and PyGObject, GTK4 and libadwaita are already"
        info "installed; see the README's dependency table."
        if ! ask_yes_no "Continue anyway?" N; then
            exit 1
        fi
        SKIP_DEPS=1
    fi
}

detect_pkg_manager() {
    local pm
    for pm in pacman emerge dnf apt-get zypper; do
        if command -v "$pm" >/dev/null 2>&1; then
            [ "$pm" = apt-get ] && pm=apt
            echo "$pm"
            return
        fi
    done
    echo unknown
}

# packages GROUP: this package manager's packages in GROUP (deps/*.list)
packages() {
    local list="$REPO_DIR/deps/$PKG_MANAGER.list"
    [ -f "$list" ] || return 0
    awk -v g="$1" '$1 == g { print $2 }' "$list"
}

# manual_notes: "name -- where to get it" for packages no repository has
manual_notes() {
    local list="$REPO_DIR/deps/$PKG_MANAGER.list"
    [ -f "$list" ] || return 0
    awk '$1 == "manual" { name = $2; $1 = ""; $2 = ""; sub(/^ +/, ""); print name " -- " $0 }' "$list"
}

# Hyprland only reads hyprland.lua from 0.55 on; an older one silently
# ignores DXrice's whole config. Returns 1 (after explaining) when the
# installed Hyprland is too old, 0 otherwise (including when it's absent).
check_hyprland_version() {
    command -v Hyprland >/dev/null 2>&1 || return 0
    local v
    v="$(Hyprland --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+(\.[0-9]+)?' | head -1)"
    [ -n "$v" ] || return 0
    if [ "$(printf '%s\n%s\n' "$HYPRLAND_MIN_VERSION" "$v" | sort -V | head -1)" != "$HYPRLAND_MIN_VERSION" ]; then
        warn "Hyprland $v is installed, but DXrice's config (hyprland.lua) needs $HYPRLAND_MIN_VERSION or newer."
        info "Older Hyprland reads only hyprland.conf, so none of DXrice's keybinds or autostart"
        info "would load. Update Hyprland first (see the README for your distro)."
        return 1
    fi
    ok "Hyprland $v (needs $HYPRLAND_MIN_VERSION or newer)."
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
    "$(cat "${XDG_STATE_HOME:-$HOME/.local/state}/dxrice/repo_path" 2>/dev/null || echo "$HOME/dxrice")/install.sh" update
}
dx() {
    local repo
    repo="$(cat "${XDG_STATE_HOME:-$HOME/.local/state}/dxrice/repo_path" 2>/dev/null || echo "$HOME/dxrice")"
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
        overview)
            qs -p "$repo/quickshell/shell.qml" ipc call overview toggle 2>/dev/null \
                || echo "Couldn't reach Quickshell (is it installed and running?)." ;;
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
            echo "Usage: dx <update|theme|taskbar|settings|overview|lock|sddm-theme>"
            echo "  update      pull the latest DXrice and re-deploy (same as dxrice-update)"
            echo "  theme       open the Theme settings (Quickshell if installed, else GTK)"
            echo "  taskbar     open the Taskbar manager"
            echo "  settings    open Quick Settings (alias: qs)"
            echo "  overview    zoom the desktop out to see every window (SUPER+Tab)"
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
        python3 "$REPO_DIR/scripts/dxrice_rc_block.py" strip "$rc"

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
        python3 "$REPO_DIR/scripts/dxrice_rc_block.py" strip "$rc"
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

# Whether a path can be spliced into hyprland.lua's commands unquoted.
path_is_plain() {
    [[ "$1" =~ ^[A-Za-z0-9._/@+-]+$ ]]
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

    if ! path_is_plain "$answer"; then
        err "'$answer' contains spaces or shell characters."
        info "hyprland.lua runs DXrice's scripts by this path without quoting it, so"
        info "every keybind would break. Pick a path made of letters, digits and . _ - / + @"
        info "(for example ~/dxrice) and run ./install.sh again."
        exit 1
    fi

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
    DXRICE_LOCATION_CONFIRMED=1 exec "$answer/install.sh" "${ORIG_ARGS[@]}"
}

# ---------------------------------------------------------------------------
# Install steps
# ---------------------------------------------------------------------------

_pkg_installed() {
    case "$PKG_MANAGER" in
        pacman) pacman -Qi "$1" >/dev/null 2>&1 ;;
        emerge) compgen -G "${DXRICE_VDB:-/var/db/pkg}/$1-[0-9]*" >/dev/null ;;
        apt) dpkg -s "$1" >/dev/null 2>&1 ;;
        dnf|zypper) rpm -q "$1" >/dev/null 2>&1 ;;
        *) return 1 ;;
    esac
}

# Always behind confirm(). emerge --ask shows Portage's own plan (USE flags,
# dependencies, keyword changes) and asks again before building anything.
_pkg_install() {
    case "$PKG_MANAGER" in
        pacman) sudo pacman -S --needed "$@" ;;
        emerge) sudo emerge --ask --noreplace "$@" ;;
        dnf) sudo dnf install -y "$@" ;;
        apt) sudo apt-get update && sudo apt-get install -y "$@" ;;
        zypper) sudo zypper install -y "$@" ;;
    esac
}

# missing GROUP: the GROUP packages not installed yet
missing() {
    local pkg
    while read -r pkg; do
        [ -n "$pkg" ] || continue
        _pkg_installed "$pkg" || echo "$pkg"
    done < <(packages "$1")
}

check_dependencies() {
    if [ "$SKIP_DEPS" = "1" ]; then
        warn "Skipping dependency check (no supported package manager found)."
        return
    fi

    info "Checking dependencies via $PKG_MANAGER..."
    local -a core=()
    mapfile -t core < <(missing core)
    if [ "${#core[@]}" -gt 0 ]; then
        warn "Missing: ${core[*]}"
        if confirm "Install them now with $PKG_MANAGER (needs sudo)?"; then
            _pkg_install "${core[@]}" || warn "Install failed or was cancelled; continuing anyway."
        fi
    else
        ok "All dependencies present."
    fi

    local note
    while IFS= read -r note; do
        [ -n "$note" ] || continue
        command -v "${note%% *}" >/dev/null 2>&1 && continue
        info "Optional, not installed automatically: $note"
    done < <(manual_notes)

    install_hypr_ecosystem
    install_quickshell
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
    local -a missing_hypr=()
    mapfile -t missing_hypr < <(missing hypr)
    if [ "${#missing_hypr[@]}" -eq 0 ]; then
        ok "Hyprland ecosystem present."
        return
    fi

    case "$PKG_MANAGER" in
        pacman|zypper)
            warn "Missing Hyprland packages: ${missing_hypr[*]}"
            if confirm "Install them now (needs sudo)?"; then
                _pkg_install "${missing_hypr[@]}" || warn "Install failed or was cancelled; continuing anyway."
            fi
            ;;
        emerge)
            warn "Missing Hyprland packages: ${missing_hypr[*]}"
            if [ -z "$(portageq best_visible / gui-wm/hyprland 2>/dev/null)" ]; then
                info "No Hyprland ebuild is visible to Portage. Hyprland $HYPRLAND_MIN_VERSION+ is in the"
                info "hyproverlay overlay; the README's Gentoo section shows how to add it"
                info "(eselect repository enable hyproverlay && emaint sync -r hyproverlay)."
            elif confirm "Install them with emerge --ask (needs sudo; Portage shows its plan first)?"; then
                _pkg_install "${missing_hypr[@]}" || warn "emerge failed or was cancelled; continuing anyway."
            fi
            ;;
        dnf)
            warn "Fedora doesn't ship Hyprland in its official repos -- it needs a third-party COPR."
            info "solopasha/hyprland is the most commonly referenced one, but it's unmaintained as"
            info "of this writing -- check https://wiki.hypr.land for whatever's currently"
            info "recommended before trusting this."
            if ask_yes_no "Try enabling solopasha/hyprland and installing from it now?" N; then
                sudo dnf copr enable -y solopasha/hyprland || warn "Could not enable that COPR."
                sudo dnf install -y "${missing_hypr[@]}" || warn "Install failed -- that COPR may be stale; check the Hyprland wiki for a current alternative."
            else
                info "Skipped -- install Hyprland yourself (https://wiki.hypr.land/Getting-Started/Installation/) and re-run this."
            fi
            ;;
        apt)
            warn "Hyprland has no reliable Ubuntu/Debian package. Its own community advises"
            info "against running it on point-release distros like Ubuntu for this reason. If you"
            info "want to try anyway, see https://wiki.hypr.land/Getting-Started/Installation/ for"
            info "building from source. Skipping automatic install of: ${missing_hypr[*]}"
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
    if command -v qs >/dev/null 2>&1 || [ -z "$(missing shell)" ]; then
        ok "Quickshell present."
        return
    fi

    case "$PKG_MANAGER" in
        pacman)
            if confirm "Install Quickshell (the bar, panels and overview; needs sudo)?"; then
                _pkg_install quickshell || warn "Install failed or was cancelled; the GTK apps will be used instead."
            else
                info "Skipped -- the older GTK apps will be used instead. Install 'quickshell' any time."
            fi
            ;;
        emerge)
            if [ -z "$(portageq best_visible / gui-apps/quickshell 2>/dev/null)" ]; then
                info "Quickshell is in the GURU overlay (gui-apps/quickshell); enable it with"
                info "eselect repository enable guru && emaint sync -r guru, then re-run this."
                info "Until then the waybar bars and the GTK apps are used instead."
            elif confirm "Install Quickshell with emerge --ask (needs sudo)?"; then
                _pkg_install gui-apps/quickshell || warn "emerge failed or was cancelled; the GTK apps will be used instead."
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
    if ! confirm "JetBrainsMono Nerd Font isn't packaged here -- download and install it now?"; then
        return
    fi

    local tmp
    tmp="$(mktemp -d)"
    info "Downloading JetBrainsMono Nerd Font..."
    local fetched=0
    if command -v curl >/dev/null 2>&1; then
        curl -fsSL --connect-timeout 15 "$NERD_FONT_RELEASE_URL" -o "$tmp/JetBrainsMono.zip" && fetched=1
    else
        wget -q --timeout=15 "$NERD_FONT_RELEASE_URL" -O "$tmp/JetBrainsMono.zip" && fetched=1
    fi
    if [ "$fetched" != 1 ] || [ ! -s "$tmp/JetBrainsMono.zip" ]; then
        warn "Download failed -- install the font yourself from $NERD_FONT_RELEASE_URL"
        rm -rf "$tmp"
        return
    fi

    mkdir -p "$DATA_HOME/fonts"
    if ! unzip -oq "$tmp/JetBrainsMono.zip" -d "$DATA_HOME/fonts/JetBrainsMonoNerdFont"; then
        warn "The downloaded font archive couldn't be unpacked -- install it yourself from $NERD_FONT_RELEASE_URL"
        rm -rf "$tmp"
        return
    fi
    rm -rf "$tmp"
    if command -v fc-cache >/dev/null 2>&1; then fc-cache -f "$DATA_HOME/fonts" >/dev/null 2>&1 || true; fi
    ok "Installed JetBrainsMono Nerd Font."
}

check_input_group() {
    info "Checking 'input' group membership (required for the infinite desktop)..."
    if id -nG "$USER" | grep -qw input; then
        ok "Already in the 'input' group."
    else
        if confirm "Add $USER to the 'input' group now?"; then
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
                        ok "$CONFIG_HOME/$rel recognized as your existing DXrice deployment -- left exactly as it is."
                    else
                        warn "Couldn't record $CONFIG_HOME/$rel as a known DXrice deployment (non-fatal) --"
                        info "the file itself is untouched; this will be retried on the next run."
                    fi
                    continue
                fi
                # old-shaped: a genuine pre-Quickshell DXrice file. Same
                # upgrade offer the old per-file checks used.
                warn "$CONFIG_HOME/$rel is from a much older version of this rice."
                info "It predates the current layout, so it won't pick that up on its own."
                if [ -L "$CONFIG_HOME/$rel" ]; then
                    info "Note: this path is currently a symlink -- replacing it backs up and"
                    info "preserves whatever it points to, but points this path at a plain file"
                    info "afterward instead of your symlink."
                fi
                if confirm "Back it up and let the current version deploy instead?"; then
                    mkdir -p "$STATE_DIR/backups"
                    local backup
                    backup="$STATE_DIR/backups/${rel//\//_}.$(date +%s).bak"
                    if ! cp "$CONFIG_HOME/$rel" "$backup"; then
                        warn "Backup to $backup failed -- leaving $CONFIG_HOME/$rel exactly as it is."
                    elif ! cmp -s "$CONFIG_HOME/$rel" "$backup"; then
                        warn "Backup at $backup doesn't match the original -- leaving $CONFIG_HOME/$rel"
                        info "exactly as it is rather than risk deleting it on an unverified backup."
                        rm -f "$backup"
                    else
                        rm -f "$CONFIG_HOME/$rel"
                        ok "Backed up to $backup and removed the live copy -- deploying the current version next."
                    fi
                else
                    warn "Leaving $CONFIG_HOME/$rel as-is -- it'll keep looking like the old rice until"
                    info "you either edit it by hand or re-run install and say yes here."
                fi
                ;;
            FOREIGN)
                info "$CONFIG_HOME/$rel exists but looks like it belongs to a different setup --"
                info "left completely alone; DXrice's own version won't deploy over it."
                ;;
            UNKNOWN)
                info "$CONFIG_HOME/$rel already exists and DXrice can't positively tell whose it is --"
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

    if confirm "Remove those stale alias lines and move the old checkout(s) out of the way?"; then
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

            # write through a symlinked rc (dotfile managers) to its target
            local tmp existing_mode target
            target="$(realpath "$rc")"
            tmp="$(mktemp "$(dirname "$target")/.$(basename "$target").XXXXXX")"
            existing_mode="$(stat -c %a "$target" 2>/dev/null || echo 644)"
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
                mv "$tmp" "$target"
                ok "Removed the stale alias line(s) from $rc"
            else
                rm -f "$tmp"
            fi
        done
        mkdir -p "$STATE_DIR/backups"
        for d in "${uniq_dirs[@]}"; do
            local dest
            dest="$STATE_DIR/backups/$(basename "$d").$(date +%s)"
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

# hyprland.lua is the user's file after the first deploy, so template fixes
# never reach it on their own. scripts/dxrice_hypr_migrate.py knows each
# fix as an exact edit of text an earlier template shipped; this shows the
# ones that apply, asks, backs the file up, and applies them. Lines the user
# has changed don't match and are left alone.
migrate_hyprland_lua() {
    local f="$CONFIG_HOME/hypr/hyprland.lua" helper="$REPO_DIR/scripts/dxrice_hypr_migrate.py"
    [ -f "$f" ] && [ -f "$helper" ] || return 0
    local plan
    plan="$(python3 "$helper" plan "$f" 2>/dev/null)" || return 0
    [ -n "$plan" ] || return 0

    local id desc automatic=0
    info "Your hyprland.lua predates these fixes from the current template:"
    while IFS=$'\t' read -r id desc; do
        if [ "$id" = manual ]; then
            info "  - (by hand) $desc"
        else
            info "  - $desc"
            automatic=1
        fi
    done <<<"$plan"
    if [ "$DRY_RUN" = "1" ] || [ "$automatic" = 0 ]; then
        return 0
    fi
    if ! confirm "Apply them (the file is backed up first)?"; then
        info "Left as it is. Apply them later with: ./install.sh update"
        return 0
    fi
    local backup
    if backup="$(python3 "$helper" apply "$f" "$STATE_DIR/backups")"; then
        ok "Updated hyprland.lua (backup: $backup). Hyprland reloads it on save."
    else
        warn "Couldn't update hyprland.lua -- it was left unchanged."
    fi
}

detect_monitor() {
    local target="$CONFIG_HOME/hypr/hyprland.lua"
    command -v hyprctl >/dev/null 2>&1 || { warn "hyprctl not found (Hyprland not running yet) -- skipping monitor auto-detect, edit hypr/hyprland.lua's eDP-1/resolution by hand."; return; }
    python3 - "$target" "$REPO_DIR/scripts" <<'PYEOF'
import json, re, subprocess, sys

target = sys.argv[1]
sys.path.insert(0, sys.argv[2])
from dxrice_manifest import atomic_write_bytes

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
atomic_write_bytes(target, content.encode())
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
        "$REPO_DIR/scripts/dxrice_spiral.py"
        "$REPO_DIR/scripts/dxrice_overview.py"
        "$REPO_DIR/scripts/dxrice_hypr_ipc.py"
        "$REPO_DIR/scripts/dxrice_resize_memory.py"
        "$REPO_DIR/scripts/dxrice_window_class.py"
        "$REPO_DIR/scripts/dxrice_singleton.py"
        "$REPO_DIR/scripts/dxrice_xdg.py"
        "$REPO_DIR/scripts/dxrice_taskbar_gui.py"
        "$REPO_DIR/scripts/dxrice_theme_gui.py"
        "$REPO_DIR/scripts/dxrice_apply_theme.py"
        "$REPO_DIR/scripts/dxrice_quick_settings.py"
        "$REPO_DIR/scripts/dxrice_force_close_window.py"
        "$REPO_DIR/scripts/dxrice_gtk_widgets.py"
        "$REPO_DIR/scripts/dxrice_list_desktop_apps.py"
        "$REPO_DIR/scripts/dxrice_launch.sh"
        "$REPO_DIR/scripts/dxrice_session.sh"
        "$REPO_DIR/scripts/dxrice_power.sh"
        "$REPO_DIR/scripts/dxrice_polkit_agent.sh"
        "$REPO_DIR/scripts/dxrice_monitor.py"
        "$REPO_DIR/quickshell/shell.qml"
        "$REPO_DIR/quickshell/qmldir"
        "$REPO_DIR/quickshell/Theme.qml"
        "$REPO_DIR/quickshell/QuickSettings.qml"
        "$REPO_DIR/quickshell/ThemeEditor.qml"
        "$REPO_DIR/quickshell/TaskbarManager.qml"
        "$REPO_DIR/quickshell/Overview.qml"
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
    # hyprland.lua runs these directly, so they must be executable (a
    # checkout unpacked from an archive can lose the bit)
    for f in "$REPO_DIR/scripts/dxrice_session.sh" "$REPO_DIR/scripts/dxrice_polkit_agent.sh"; do
        if [ -f "$f" ] && [ ! -x "$f" ]; then
            err "NOT EXECUTABLE: $f -- fix with: chmod +x '$f'"
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
        local test_log="$STATE_DIR/verify-tests.log"
        mkdir -p "$STATE_DIR"
        if python3 "$REPO_DIR/scripts/dxrice_test_placement.py" >"$test_log" 2>&1; then
            ok "Window placement/arrangement tests passed."
        else
            warn "Window placement/arrangement tests FAILED -- see $test_log"
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
    check_hyprland_version || true

    step "Step 3/4 -- Permissions"
    check_input_group

    step "Step 4/4 -- Deploying your rice"
    reconcile_copy_once_ownership
    migrate_hyprland_lua
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
# Disables and deletes DXrice's own systemd user units (and stops the ones
# that can be stopped safely -- see below). Before this,
# uninstall left all three in place -- and since hyprland.lua's autostart
# restarts them by name at every login, they kept coming back (and, with
# the checkout deleted, fail-looped until systemd's start limit). Once the
# unit files are gone those autostart lines have nothing left to start.
#
# Only touches a unit that is both in DXRICE_UNITS and was written by
# deploy_systemd_units (every unit it writes has a "Description=DXrice ..."
# line); a same-named unit someone wrote by hand is reported, not removed.
# No other unit is ever passed to systemctl.
# Whether dxrice-quickshell.service's cgroup holds nothing but Quickshell
# and processes it started and still parents (its own helpers). Apps the
# shell launches go into their own scopes (scripts/dxrice_launch.sh), but
# one started before that, or where scopes weren't available, still sits
# in this cgroup -- and is not a descendant of Quickshell, since it was
# started detached. Stopping the unit then would kill it.
# DXRICE_CGROUP_ROOT / DXRICE_PROC_ROOT: test hooks.
quickshell_unit_is_self_contained() {
    local unit=dxrice-quickshell.service cg main pid p depth
    local cg_root="${DXRICE_CGROUP_ROOT:-/sys/fs/cgroup}" proc_root="${DXRICE_PROC_ROOT:-/proc}"
    cg=$(systemctl --user show -p ControlGroup --value "$unit" 2>/dev/null)
    main=$(systemctl --user show -p MainPID --value "$unit" 2>/dev/null)
    case "$main" in ''|0|*[!0-9]*) return 1 ;; esac
    [ -n "$cg" ] && [ -r "$cg_root$cg/cgroup.procs" ] || return 1
    while read -r pid; do
        [ -n "$pid" ] || continue
        p=$pid depth=0
        while [ "$p" != "$main" ]; do
            p=$(sed -n 's/^PPid:[[:space:]]*//p' "$proc_root/$p/status" 2>/dev/null)
            depth=$((depth + 1))
            case "$p" in ''|0|1) return 1 ;; esac
            [ "$depth" -lt 64 ] || return 1
        done
    done < "$cg_root$cg/cgroup.procs"
    return 0
}

remove_systemd_units() {
    local unit_dir="$CONFIG_HOME/systemd/user" unit path
    local -a owned=()
    for unit in "${DXRICE_UNITS[@]}"; do
        path="$unit_dir/$unit"
        [ -f "$path" ] || continue
        if grep -q '^Description=DXrice ' "$path" 2>/dev/null; then
            owned+=("$unit")
        else
            warn "Leaving $path in place -- it wasn't written by DXrice."
        fi
    done
    [ "${#owned[@]}" -gt 0 ] || return 0

    # dxrice-quickshell.service is only stopped when nothing but Quickshell
    # itself lives in its cgroup (see quickshell_unit_is_self_contained):
    # stopping a unit kills its whole cgroup, and an app opened from an
    # older shell -- the browser, a game, the terminal running this
    # uninstall -- may still be in there. Otherwise its file is removed so
    # it doesn't start again, and the running bar ends at logout.
    local -a stop=()
    local keeps_shell=0
    for unit in "${owned[@]}"; do
        if [ "$unit" != dxrice-quickshell.service ]; then
            stop+=("$unit")
        elif command -v systemctl >/dev/null 2>&1 && quickshell_unit_is_self_contained; then
            stop+=("$unit")
        else
            keeps_shell=1
        fi
    done
    if command -v systemctl >/dev/null 2>&1; then
        if [ "${#stop[@]}" -gt 0 ]; then
            info "Stopping DXrice's services: ${stop[*]}"
            systemctl --user stop "${stop[@]}" >/dev/null 2>&1 || true
        fi
        # The units have no [Install] section today, so there is normally
        # nothing to disable; this covers an older or hand-enabled copy.
        systemctl --user disable "${owned[@]}" >/dev/null 2>&1 || true
        systemctl --user reset-failed "${owned[@]}" >/dev/null 2>&1 || true
    fi
    for unit in "${owned[@]}"; do
        rm -f "$unit_dir/$unit"
    done
    if command -v systemctl >/dev/null 2>&1; then
        systemctl --user daemon-reload >/dev/null 2>&1 || true
    fi
    ok "Removed DXrice's services: ${owned[*]}"
    if [ "$keeps_shell" = 1 ]; then
        info "The DXrice bar keeps running until you log out -- stopping it now would"
        info "also close every app you opened from the dock or launcher."
    fi

    local lua="$CONFIG_HOME/hypr/hyprland.lua"
    if [ -f "$lua" ] && grep -qE 'dxrice-[a-z-]*\.service|dxrice_session\.sh' "$lua" 2>/dev/null; then
        info "Your hyprland.lua still has DXrice's autostart lines. With the services removed"
        info "they no longer start anything; delete them yourself if you want them gone."
    fi
}

do_uninstall() {
    banner
    check_not_root
    local purge="$PURGE"

    step "Removing DXrice integration"
    remove_systemd_units
    remove_shell_alias

    if [ -f "$STATE_DIR/repo_path" ]; then
        rm -f "$STATE_DIR/repo_path"
        ok "Removed the recorded repo location ($STATE_DIR/repo_path)"
    fi

    if [ -d /usr/share/sddm/themes/dxrice ] || [ -f /etc/sddm.conf.d/dxrice.conf ]; then
        if confirm "The DXrice SDDM login theme is installed -- remove it too? (needs sudo)"; then
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
    PKG_MANAGER="$(detect_pkg_manager)"
    if [ "$PKG_MANAGER" = unknown ]; then
        warn "No supported package manager detected -- would skip automatic dependency installation."
    else
        info "Detected: $PKG_MANAGER (package list: deps/$PKG_MANAGER.list)"
        local -a core=() hypr=()
        mapfile -t core < <(missing core)
        mapfile -t hypr < <(missing hypr)
        if [ "${#core[@]}" -gt 0 ]; then
            info "Would offer to install (needs sudo): ${core[*]}"
        else
            ok "All general dependencies already present -- nothing to install."
        fi
        if [ "${#hypr[@]}" -gt 0 ]; then
            info "Would also offer Hyprland packages where $PKG_MANAGER can install them: ${hypr[*]}"
        fi
        if command -v qs >/dev/null 2>&1 || [ -z "$(missing shell)" ]; then
            ok "Quickshell already present."
        else
            info "Would offer Quickshell where it's packaged (pacman, emerge with GURU);"
            info "otherwise the waybar bars and GTK apps are used."
        fi
    fi
    check_hyprland_version || true

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

# Brings the checkout up to its upstream branch, or explains why not and
# returns 1 having changed nothing. Never resets, stashes or rewrites
# anything: local edits stay exactly where they are, and an update that
# would touch the same files is refused with the steps to resolve it.
# Sets UPDATE_SUMMARY for the final report.
update_checkout() {
    local branch upstream before
    before="$(git rev-parse --short HEAD)"
    if ! branch="$(git symbolic-ref --short -q HEAD)"; then
        warn "The checkout is on a detached commit ($before), not a branch -- not updating it."
        info "Check out a branch (e.g. 'git -C $REPO_DIR checkout main') and re-run."
        UPDATE_SUMMARY="Left on detached commit $before."
        return 0
    fi
    if ! upstream="$(git rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null)"; then
        warn "Branch '$branch' has no upstream to update from -- deploying it as it is."
        UPDATE_SUMMARY="Branch $branch at $before (no upstream)."
        return 0
    fi

    local remote
    remote="$(git config "branch.$branch.remote" || echo origin)"
    info "Fetching $upstream..."
    if [ "$remote" != "." ] && ! git fetch --quiet "$remote" 2>"$STATE_DIR/fetch.err"; then
        err "Couldn't fetch updates: $(head -1 "$STATE_DIR/fetch.err" 2>/dev/null)"
        info "Nothing was changed. Check your network connection and run './install.sh update' again."
        return 1
    fi

    local ahead behind
    read -r ahead behind < <(git rev-list --left-right --count "HEAD...$upstream")
    if [ "$behind" = 0 ]; then
        ok "Already up to date ($branch at $before)."
        UPDATE_SUMMARY="Already up to date: $branch at $before."
        return 0
    fi

    echo ""
    info "$behind new commit(s) on $upstream:"
    git log --oneline --no-decorate -n 15 "HEAD..$upstream" | sed 's/^/    /'
    [ "$behind" -gt 15 ] && info "    ... and $((behind - 15)) more"
    echo ""

    if [ "$ahead" != 0 ]; then
        err "Your branch has $ahead commit(s) of its own that $upstream doesn't, so it can't be"
        info "fast-forwarded. Nothing was changed. To keep your commits on top of the update:"
        info "  git -C $REPO_DIR pull --rebase      # then re-run ./install.sh update"
        info "To see what differs first: git -C $REPO_DIR log --oneline --left-right HEAD...$upstream"
        return 1
    fi

    # Files with local changes (tracked or not) that the update also touches.
    local -a overlap=()
    mapfile -t overlap < <(comm -12 \
        <(git status --porcelain=v1 -uall | cut -c4- | sed 's/.* -> //' | sort -u) \
        <(git diff --name-only HEAD "$upstream" | sort -u))
    if [ "${#overlap[@]}" -gt 0 ]; then
        err "You've changed files in the checkout that this update also changes:"
        local f
        for f in "${overlap[@]}"; do info "    $f"; done
        info "Nothing was changed. Either keep your version aside and update:"
        info "  git -C $REPO_DIR stash push -- ${overlap[*]}"
        info "  ./install.sh update"
        info "  git -C $REPO_DIR stash pop        # re-apply your edits, resolving any conflict"
        info "or discard your edits to those files (git -C $REPO_DIR restore <file>) and re-run."
        return 1
    fi

    if ! ask_yes_no "Update $branch from $before to $(git rev-parse --short "$upstream")?" Y; then
        info "Not updated. Deploying the checkout as it is."
        UPDATE_SUMMARY="Update declined: $branch stays at $before."
        return 0
    fi
    if ! git merge --ff-only --quiet "$upstream"; then
        err "The update couldn't be applied; the checkout is still at $before."
        info "See 'git -C $REPO_DIR status' for what's in the way."
        return 1
    fi
    local after
    after="$(git rev-parse --short HEAD)"
    printf '%s %s -> %s\n' "$(date -Iseconds)" "$before" "$after" >> "$STATE_DIR/update-history"
    ok "Updated $branch: $before -> $after."
    UPDATE_SUMMARY="Updated $branch from $before to $after ($behind commit(s)). To go back: git -C $REPO_DIR checkout $before"
}

do_update() {
    banner
    check_not_root
    require_repo_layout
    mkdir -p "$STATE_DIR"
    cd "$REPO_DIR"
    if ! path_is_plain "$REPO_DIR"; then
        warn "This checkout's path ($REPO_DIR) contains spaces or shell characters;"
        info "hyprland.lua's keybinds can't run scripts from it. Move it (e.g. to ~/dxrice)"
        info "and run ./install.sh from there."
    fi

    step "Checking for updates"
    UPDATE_SUMMARY="Deployed the checkout as it is (no update was applied)."
    if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
        warn "Not a git repository -- deploying what's on disk."
    else
        update_checkout || exit 1
    fi

    step "Redeploying"
    reconcile_copy_once_ownership
    migrate_hyprland_lua
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
    info "$UPDATE_SUMMARY"
    info "Anything hand-edited in $CONFIG_HOME was left alone (see above)."
    info "Nothing was restarted: the running bar and daemons keep their old code until"
    info "you log out and back in."

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
            if confirm "Re-sync the DXrice SDDM login theme with your current wallpaper/colors? (needs sudo)"; then
                do_sddm_theme || warn "SDDM theme re-sync failed -- re-run './install.sh sddm-theme' to retry (the rest of your update is unaffected)."
            fi
        elif ask_yes_no "SDDM is installed -- set up the matching DXrice login theme too? (needs sudo)" N; then
            do_sddm_theme || warn "SDDM theme sync failed -- re-run './install.sh sddm-theme' to retry (the rest of your update is unaffected)."
        else
            info "Skipped. Run './install.sh sddm-theme' any time you want it."
        fi
    fi
}

# Sourcing (rather than running) this file only defines its functions --
# scripts/dxrice_test_installer_lifecycle.sh uses that to test individual
# migrations against a throwaway HOME without running an install.
if [ "${BASH_SOURCE[0]}" != "$0" ]; then
    return 0 2>/dev/null || true
fi

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
