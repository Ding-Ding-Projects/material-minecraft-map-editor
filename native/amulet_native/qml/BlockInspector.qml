pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ScrollView {
    id: inspector
    required property var explorer
    property color ink: backend.dark ? "#E1E5DC" : "#191D18"
    property var block: explorer.selectedBlock
    contentWidth: availableWidth
    contentHeight: details.implicitHeight
    clip: true
    ColumnLayout {
        id: details
        width: inspector.availableWidth
        spacing: 16
        Label { text: "Block inspector"; font.pixelSize: 22; color: inspector.ink }
        Label {
            text: inspector.explorer.ready ? inspector.block.name : "Select a decoded block"
            textFormat: Text.PlainText
            font.pixelSize: backend.largeText ? 20 : 16
            color: inspector.ink
            wrapMode: Text.WrapAnywhere
            Layout.fillWidth: true
        }
        Repeater {
            model: inspector.explorer.ready ? [
                ["World X, Y, Z", inspector.block.world], ["Local X, Y, Z", inspector.block.local],
                ["Dimension", inspector.block.dimension], ["Chunk X, Z", inspector.block.chunk],
                ["Data version", inspector.block.dataVersion]] : []
            delegate: ColumnLayout {
                required property var modelData
                Layout.fillWidth: true
                Label { text: modelData[0]; color: inspector.ink; font.pixelSize: 13 }
                Label { text: modelData[1]; color: inspector.ink; font.pixelSize: backend.largeText ? 18 : 14; wrapMode: Text.WrapAnywhere; textFormat: Text.PlainText; Layout.fillWidth: true }
            }
        }
        Label { text: "Recorded properties"; visible: inspector.explorer.ready; font.pixelSize: 16; color: inspector.ink }
        Repeater {
            model: inspector.explorer.ready ? inspector.block.properties : []
            delegate: Label {
                required property var modelData
                text: modelData.key + ": " + modelData.value
                textFormat: Text.PlainText
                font.pixelSize: backend.largeText ? 18 : 14
                color: inspector.ink
                wrapMode: Text.WrapAnywhere
                Layout.fillWidth: true
            }
        }
        Label { text: "No properties recorded"; visible: inspector.explorer.ready && inspector.block.properties.length === 0; color: inspector.ink; wrapMode: Text.WordWrap; Layout.fillWidth: true }
        Label { text: "Read-only. No block edits or world writes."; font.pixelSize: 14; color: inspector.ink; wrapMode: Text.WordWrap; Layout.fillWidth: true }
    }
}
