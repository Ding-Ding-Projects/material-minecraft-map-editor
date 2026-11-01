pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Layouts

ColumnLayout {
    id: control
    required property string label
    property alias text: field.text
    property int maximumLength: 11
    property string guidance: "This is a chunk coordinate, not a block coordinate. Enter a decimal integer from -2147483648 through 2147483647. The initial draft is 0; no data is read until Read chunk is selected. Clear removes this draft and requires a new valid value."
    signal accepted()
    spacing: 4
    Label { text: control.label; color: backend.dark ? "#E1E5DC" : "#191D18" }
    RowLayout {
        spacing: 4
        TextField {
            id: field
            Layout.fillWidth: true
            Layout.minimumWidth: 130
            implicitHeight: 48
            Material.containerStyle: Material.Outlined
            maximumLength: control.maximumLength
            selectByMouse: true
            Accessible.name: control.label + ", signed decimal integer"
            Accessible.description: control.guidance
            onAccepted: control.accepted()
        }
        MdWindowButton { text: "×"; actionName: "Clear " + control.label; onClicked: { field.clear(); field.forceActiveFocus() } }
        MdWindowButton { text: "?"; actionName: "Help for " + control.label; onClicked: help.open() }
    }
    MdDialog {
        id: help
        title: control.label
        width: 460
        anchors.centerIn: Overlay.overlay
        contentItem: Label {
            text: control.guidance
            wrapMode: Text.WordWrap
        }
        onClosed: field.forceActiveFocus()
    }
}
