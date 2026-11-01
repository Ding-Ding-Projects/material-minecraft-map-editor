import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material

Button {
    id: control
    property bool primary: false
    implicitHeight: 48
    font.pixelSize: backend.largeText ? 18 : 14
    highlighted: primary
    Material.roundedScale: Material.FullScale
    Accessible.name: text
    background: Rectangle {
        radius: height / 2
        color: !control.enabled ? "transparent" : control.primary
            ? (backend.dark ? "#A5D395" : "#3F6837")
            : (backend.dark ? "#3E4A36" : "#DCE7D3")
        border.width: control.activeFocus ? 3 : 0
        border.color: backend.dark ? "#E1E5DC" : "#191D18"
        Rectangle {
            anchors.fill: parent
            radius: parent.radius
            color: backend.dark ? "white" : "black"
            opacity: control.down ? 0.12 : control.hovered ? 0.08 : 0
        }
    }
    contentItem: Text {
        text: control.text
        font: control.font
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
        color: !control.enabled ? (backend.dark ? "#8C9388" : "#72796F")
            : control.primary ? (backend.dark ? "#10380A" : "white")
            : (backend.dark ? "#DCE7D3" : "#151F0F")
    }
}
