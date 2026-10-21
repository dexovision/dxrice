import QtQuick
import Quickshell
import Quickshell.Io

// The weather where you said you are (Settings > Experience: "weather_location",
// "weather_units"), from Open-Meteo through scripts/dxrice_weather.py: the
// condition and the temperature large, what it feels like, humidity and
// wind, and the next three days. Asked when it appears and every 15
// minutes while it is shown (the script caches for 10).
//
// It never guesses: with no place set it says so, an unknown place or no
// network says that, and an old answer says it is old.
//
// theme.json "weather_style": "card" (default) is all of the above;
// "tile" is the temperature and the sky alone, large, on a tilted rounded
// square -- the same data and the same honest states, in a third of the
// space.
DesktopWidget {
    id: root
    name: "weather"
    defaultCorner: "bottom-right"
    defaultOn: false
    surface: "none"
    interactive: false
    readonly property bool tile: Theme.data.weather_style === "tile"
    contentWidth: root.tile ? 176 : 330
    contentHeight: root.tile ? 176 : body.implicitHeight

    property var report: null            // the script's last answer
    readonly property bool ok: root.report !== null && root.report.error === undefined
    readonly property string unit: root.ok && root.report.units === "imperial" ? "°F" : "°C"
    readonly property string windUnit: root.ok && root.report.units === "imperial" ? "mph" : "km/h"
    readonly property string place: String(Theme.data.weather_location || "")

    Process {
        id: fetch
        objectName: "weatherFetch"
        command: ["python3", Quickshell.shellDir + "/../scripts/dxrice_weather.py"]
        stdout: StdioCollector {
            onStreamFinished: {
                try { root.report = JSON.parse(this.text.trim()); }
                catch (e) { root.report = { error: "No weather right now." }; }
            }
        }
    }
    function refresh() { if (root.active && !fetch.running) fetch.running = true; }
    onActiveChanged: root.refresh()
    onPlaceChanged: root.refresh()
    Component.onCompleted: root.refresh()
    Timer { running: root.active; interval: 15 * 60 * 1000; repeat: true; onTriggered: root.refresh() }

    // WMO weather codes (what Open-Meteo reports) -> a word and a glyph
    function describe(code, day) {
        const c = Number(code);
        const g = (cp) => String.fromCodePoint(cp);
        if (c === 0) return { word: "Clear", glyph: g(day ? 0xe30d : 0xe32b) };
        if (c === 1) return { word: "Mainly clear", glyph: g(day ? 0xe30c : 0xe379) };
        if (c === 2) return { word: "Partly cloudy", glyph: g(day ? 0xe302 : 0xe37e) };
        if (c === 3) return { word: "Overcast", glyph: g(0xe312) };
        if (c === 45 || c === 48) return { word: "Fog", glyph: g(0xe313) };
        if (c >= 51 && c <= 57) return { word: "Drizzle", glyph: g(0xe31b) };
        if (c >= 61 && c <= 67) return { word: "Rain", glyph: g(0xe318) };
        if (c >= 71 && c <= 77) return { word: "Snow", glyph: g(0xe31a) };
        if (c >= 80 && c <= 82) return { word: "Showers", glyph: g(0xe319) };
        if (c === 85 || c === 86) return { word: "Snow showers", glyph: g(0xe35e) };
        if (c >= 95) return { word: "Thunderstorm", glyph: g(0xe31d) };
        return { word: "", glyph: "" };
    }
    readonly property var now: root.ok ? root.describe(root.report.code, root.report.is_day) : ({ word: "", glyph: "" })

    // ---- "tile" ----
    Item {
        id: tileFace
        objectName: "weatherTile"
        visible: root.tile
        anchors.fill: parent
        Rectangle {
            anchors.centerIn: parent
            width: parent.width - 18; height: width
            radius: 44
            rotation: -8
            antialiasing: true
            color: Qt.rgba(Theme.panelTone.r, Theme.panelTone.g, Theme.panelTone.b, 0.8)
            border.width: 1
            border.color: Theme.borderIdle
        }
        Column {
            anchors.centerIn: parent
            spacing: -2
            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                visible: root.ok
                text: root.now.glyph
                color: Theme.accent
                font.family: Theme.iconFamily; font.pixelSize: 40
            }
            Text {
                objectName: "weatherTileTemp"
                anchors.horizontalCenter: parent.horizontalCenter
                text: root.ok ? Math.round(root.report.temp) + "°" : "\u2014"
                color: Theme.textActive
                font.family: Theme.fontFamily; font.pixelSize: 50; font.weight: Font.DemiBold
            }
            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                width: 130
                horizontalAlignment: Text.AlignHCenter
                elide: Text.ElideRight
                text: !root.ok ? (root.report === null ? "Asking\u2026" : "No weather")
                      : root.now.word + (root.report.stale === true ? " \u00b7 offline" : "")
                color: Theme.textActive; opacity: 0.75
                font.family: Theme.fontFamily; font.pixelSize: 12
            }
        }
    }

    Column {
        id: body
        visible: !root.tile
        width: parent.width
        spacing: 6

        // no answer yet, or an honest reason there is none
        Text {
            objectName: "weatherMessage"
            visible: !root.ok
            width: parent.width
            wrapMode: Text.WordWrap
            text: root.report === null ? "Asking Open-Meteo..." : root.report.error
            color: Theme.textActive; opacity: 0.75
            font.family: Theme.fontFamily; font.pixelSize: 14
        }

        Row {
            visible: root.ok
            spacing: 14
            Text {
                objectName: "weatherGlyph"
                anchors.verticalCenter: parent.verticalCenter
                text: root.now.glyph
                color: Theme.accent
                font.family: Theme.iconFamily; font.pixelSize: 54
            }
            Column {
                anchors.verticalCenter: parent.verticalCenter
                spacing: -4
                Text {
                    objectName: "weatherTemp"
                    text: root.ok ? Math.round(root.report.temp) + "°" : ""
                    color: Theme.textActive
                    font.family: Theme.fontFamily; font.pixelSize: 64; font.weight: Font.Light
                }
                Text {
                    objectName: "weatherCondition"
                    text: root.ok ? root.now.word + "  ·  " + root.report.place : ""
                    color: Theme.textActive; opacity: 0.8
                    font.family: Theme.fontFamily; font.pixelSize: 14; font.weight: Font.Medium
                }
            }
        }
        Text {
            objectName: "weatherDetails"
            visible: root.ok
            text: root.ok ? "feels " + Math.round(root.report.feels) + "°   " + Math.round(root.report.humidity) + "%   "
                            + Math.round(root.report.wind) + " " + root.windUnit
                          : ""
            color: Theme.textActive; opacity: 0.65
            font.family: Theme.fontMono; font.pixelSize: 12
        }
        Rectangle { visible: root.ok; width: parent.width; height: 1; color: Theme.textActive; opacity: 0.18 }
        Row {
            objectName: "weatherDays"
            visible: root.ok
            spacing: 22
            Repeater {
                model: root.ok ? root.report.days : []
                delegate: Column {
                    required property var modelData
                    required property int index
                    spacing: 2
                    Text {
                        text: index === 0 ? "Today" : Qt.formatDate(new Date(modelData.date + "T12:00:00"), "ddd")
                        color: Theme.accent
                        font.family: Theme.fontFamily; font.pixelSize: 11; font.weight: Font.Bold; font.letterSpacing: 1
                    }
                    Row {
                        spacing: 6
                        Text {
                            text: root.describe(modelData.code, true).glyph
                            color: Theme.textActive; opacity: 0.8
                            font.family: Theme.iconFamily; font.pixelSize: 15
                        }
                        Text {
                            text: Math.round(modelData.max) + "° " + Math.round(modelData.min) + "°"
                            color: Theme.textActive
                            font.family: Theme.fontMono; font.pixelSize: 12
                        }
                    }
                }
            }
        }
        Text {
            objectName: "weatherStale"
            visible: root.ok && root.report.stale === true
            text: "offline · from " + (root.ok ? Qt.formatDateTime(new Date(root.report.fetched * 1000), "HH:mm") : "")
            color: Theme.textActive; opacity: 0.5
            font.family: Theme.fontMono; font.pixelSize: 11
        }
    }
}
