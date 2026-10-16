# Package lists

One file per package manager, read by `install.sh`. Each line is
`GROUP PACKAGE`; `#` starts a comment.

| group | meaning | installer behaviour |
|---|---|---|
| `core` | needed by the desktop as shipped | checked; missing ones offered for install, after asking |
| `hypr` | Hyprland and its own tools | checked; installed only where the distro packages them (see `install.sh`'s `install_hypr_ecosystem`) |
| `shell` | Quickshell | checked; optional (the GTK apps and waybar are the fallback) |
| `manual` | not packaged in the main repositories | never installed; the user is told where to get it |

Changing a package name means editing one line here; `install.sh` itself
doesn't name distro packages.
