import QtQuick

// A desktop widget's label: what the reading is, above it -- small, bold,
// spaced capitals, in the readable accent. Every widget names itself the
// same way (the meters, reminders, weather, the system readout), so a
// glance across the desktop finds the labels in one voice and the values
// in another.
Text {
    color: Theme.accentText
    font.family: Theme.fontFamily
    font.pixelSize: 10
    font.weight: Font.Bold
    font.letterSpacing: 2
    font.capitalization: Font.AllUppercase
}
