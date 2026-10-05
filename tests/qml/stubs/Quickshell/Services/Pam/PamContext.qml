import QtQuick
QtObject {
    property bool active: false
    property string config: ""
    property string user: ""
    signal completed(int result)
    signal pamMessage()
    signal error(var err)
    property bool responseRequired: false
    function start() {}
    function respond(r) {}
}
