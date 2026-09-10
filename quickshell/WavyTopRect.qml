import QtQuick
import QtQuick.Shapes

// A thin scalloped strip that visually stitches a panel to the bar sitting
// directly above it -- ported from caelestia-dots/shell's own
// WavyTopRect.qml. Used as the very top sliver of a bar-anchored dropdown
// (Quick Settings) so the panel reads as *part of* the bar rather than a
// separate floating card with a gap underneath it.
Shape {
    id: root

    property color color: Theme.layer1
    property int waves: 4
    property real amplitude: 3

    preferredRendererType: Shape.CurveRenderer
    asynchronous: true

    ShapePath {
        strokeWidth: 0
        strokeColor: "transparent"
        fillColor: root.color

        PathSvg {
            path: {
                const w = root.width;
                const h = root.height;
                const a = root.amplitude;
                const n = Math.max(1, root.waves);
                const wl = w / n;
                const half = wl / 2;

                let d = `M 0,${a} `;
                for (let i = 0; i < n; ++i) {
                    const x = i * wl;
                    d += `Q ${x + half / 2},${-a} ${x + half},${a} `;
                    d += `Q ${x + half + half / 2},${3 * a} ${x + wl},${a} `;
                }
                d += `L ${w},${h} L 0,${h} Z`;
                return d;
            }
        }

        Behavior on fillColor {
            ColorAnimation { duration: Theme.durationFast; easing.type: Theme.easingType; easing.bezierCurve: Theme.curveStandard }
        }
    }
}
