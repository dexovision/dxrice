pragma Singleton
import QtQuick

// The shell's spatial registry -- the piece that was structurally missing.
//
// Before this, every panel hardcoded where it thought its originating bar
// element was (`margins { top: 44 }`, `margins { bottom: 60 }`). Those
// numbers were only ever correct by coincidence: nothing connected them to
// the bar, so resizing the bar, changing its padding, or letting the volume
// readout grow a digit silently broke the relationship, and a panel could
// never know WHERE on the edge it was supposed to come from.
//
// Now the edges publish their own geometry here and the panels read it. The
// bar is the single source of truth for its own size and for where each
// trigger physically sits, so if the bar moves, resizes, or its status
// cluster changes width, every panel's origin and attachment follows with
// no constant to update. This is also the only reason the panels can be
// treated as branches of one shell rather than three floating windows:
// they share a coordinate space, not just a color palette.
QtObject {
    // ---- the shell's geometry system ----
    // One source of truth for every surface in the shell: the bar's capsules,
    // the dock, and every panel they expand into. These were previously four
    // files' worth of independent magic numbers (islandHeight 28 here,
    // dockHeight 60 there, roundingXl on one surface and roundingLg on
    // another), which is the concrete reason the result could not read as one
    // system no matter how each piece was tuned in isolation -- there was no
    // system, only coincidence.
    //
    // `radius` is the shell's OUTER arc -- the collapsed capsule's, and the
    // expanded panel's far corners (the ones away from the origin control).
    // The origin-side corners are handled separately, in ShellIsland.qml:
    // they stay fixed at that island's OWN collapsedHeight/2 permanently,
    // never transitioning to `radius` even at full size, which is what keeps
    // a visible, literal trace of "this was a pill" on the edge nearest the
    // control that opened it. That is a deliberate asymmetry, not an
    // oversight -- see ShellIsland.qml's corner properties for the actual
    // per-corner logic.
    //
    // `cardRadius` is the shell's INNER arc, for content grouped inside an
    // expanded panel (a settings group, a metric card) -- distinctly
    // smaller than `radius`, never equal to it. A flat one-radius-everywhere
    // shell is what made every surface read as an interchangeable rounded
    // rectangle; a real surface has an outer silhouette and inner
    // substructure that are visibly different scales of the same shape
    // language, not the same number reused.
    readonly property real unit: 36        // collapsed capsule height
    readonly property real radius: unit / 2  // == 18, the shell's outer arc
    readonly property real cardRadius: Math.round(radius * 0.6)  // == 11, inner arc
    readonly property real gap: 8          // screen-edge margin, and between capsules
    readonly property real pad: 12         // horizontal padding inside a capsule
    readonly property real chip: 24        // inner chip height (status/workspace pills)
    readonly property real chipRadius: chip / 2

    // ---- the expanded-panel content grammar (layers 4-6: navigation,
    // content region, internal cards) -- shared tokens so a settings group
    // in Quick Settings and a shortcut-list section in Taskbar are visibly
    // the same KIND of thing, even though what is inside them differs. ----
    readonly property real navHeight: 30     // the quiet in-surface tab strip
    readonly property real cardGap: 10       // between sibling cards
    readonly property real cardPad: 12       // inside a card, to its own content
    // A compact row height (a settings row, a text-input field) -- was a
    // bare `34` independently at several call sites (TaskbarManager's
    // shortcut/module rows, its own add-shortcut dialog's input fields).
    readonly property real rowHeight: 34

    // The dock is the same system one step up: its tiles are exactly `unit`,
    // so a dock icon and a bar capsule are the same size, and the slab is
    // that plus a gap above and below.
    readonly property real dockTile: unit
    readonly property real dockUnit: unit + gap * 2

    // ---- expanded-panel width family: every island picked its own bare
    // expandedWidth (320/640/680) with no shared vocabulary connecting
    // them, even though the dock's own comment already reasoned "640 lands
    // in the same size family as Quick Settings' 680, so the two dashboards
    // read as siblings" -- these three tokens are that reasoning, made
    // real. Values are UNCHANGED from what each island already used --
    // this only names them, it doesn't resize anything (that's a Phase 8+
    // composition decision, not infrastructure).
    readonly property real panelWidthCompact: 320  // a single-purpose panel (Calendar)
    readonly property real panelWidthMedium: 640   // a secondary dashboard (Taskbar)
    readonly property real panelWidthWide: 680      // a primary dashboard (Quick Settings)

    // ---- edge metrics, published by TopBar/Dock themselves ----
    // Panels anchor flush to these rather than to a literal 44 / 60.
    property real topEdgeHeight: 0
    property real bottomEdgeHeight: 0

    // Shared backstop so an expanded panel never runs off the far edge of a
    // shorter-than-assumed display -- TopBar.qml and Dock.qml each used to
    // define their own identical `clampToScreen(h)` function independently.
    // `edgeMargin` is the gap that needs to stay free on the far side too
    // (each caller already has its own `gap`-based margin constant, but
    // passes it explicitly rather than this function assuming which one).
    function clampToScreen(h, edgeMargin) {
        return Math.min(h, screenHeight - edgeMargin * 2);
    }

    // The real, live monitor height (published by TopBar.qml, which already
    // has `root.screen` -- see PanelWindow's own convention for reading it).
    // Every panel's expanded size needs to be checked against this, not
    // against an assumed 1080: a panel that fits its own Rectangle just fine
    // can still run off the bottom of a shorter display, which is just as
    // broken as clipping content inside a correctly-sized surface. Defaults
    // to 1080 only until TopBar's own Binding sets the real value on startup.
    property real screenHeight: 1080
}
