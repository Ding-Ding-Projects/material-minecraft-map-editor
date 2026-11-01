import QtQuick
import QtQuick.Controls

ToolButton {
    id: control
    required property string actionName
    implicitWidth: 48
    implicitHeight: 48
    Accessible.name: actionName
    ToolTip.visible: hovered || activeFocus
    ToolTip.text: actionName
    ToolTip.delay: 600
    background: Rectangle {
        radius: 24
        color: control.down ? (backend.dark ? "#424940" : "#C2C9BD")
             : control.hovered ? (backend.dark ? "#272B26" : "#E5E9E0") : "transparent"
        border.width: control.activeFocus ? 2 : 0
        border.color: backend.dark ? "#A5D395" : "#3F6837"
    }
}
