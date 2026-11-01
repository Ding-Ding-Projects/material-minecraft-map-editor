pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ColumnLayout {
    id: slice
    required property var explorer
    signal inspectRequested()
    property color ink: backend.dark ? "#E1E5DC" : "#191D18"
    function focusGrid() { gridFrame.forceActiveFocus() }
    function revealSelection() {
        if (!explorer.ready || scroll.availableWidth <= 0 || scroll.availableHeight <= 0) return
        let position = explorer.revealCell(zoom.value, scroll.availableWidth, scroll.availableHeight,
                                          flick.contentX, flick.contentY)
        flick.contentX = position.x
        flick.contentY = position.y
    }
    Connections { target: slice.explorer; function onChanged() { Qt.callLater(slice.revealSelection) } }
    spacing: 12
    RowLayout {
        Layout.fillWidth: true
        Label { text: "Chunk slice, read-only"; color: slice.ink; font.pixelSize: 20; Layout.fillWidth: true }
        Label { text: "Cell size"; color: slice.ink }
        MdSpinBox { id: zoom; from: 24; to: 64; value: 28; stepSize: 4; Accessible.name: "Slice cell size"; onValueChanged: Qt.callLater(slice.revealSelection) }
        MdButton { text: "Inspect block"; enabled: slice.explorer.ready; onClicked: slice.inspectRequested() }
    }
    Label { text: "X increases right · Z increases down · Block categories, not textures"; color: slice.ink; font.pixelSize: 13; wrapMode: Text.WordWrap; Layout.fillWidth: true }
    ScrollView {
        id: scroll
        onAvailableWidthChanged: Qt.callLater(slice.revealSelection)
        onAvailableHeightChanged: Qt.callLater(slice.revealSelection)
        Layout.fillWidth: true
        Layout.fillHeight: true
        // At the minimum client height, preserve every control and scroll the
        // data view instead of forcing the entire workspace off-screen.
        Layout.minimumHeight: 80
        contentWidth: gridFrame.width
        contentHeight: gridFrame.height
        clip: true
        Flickable {
            id: flick
            contentWidth: gridFrame.width
            contentHeight: gridFrame.height
            boundsBehavior: Flickable.StopAtBounds
            FocusScope {
            id: gridFrame
            objectName: "chunkSliceGrid"
            width: 36 + zoom.value * 16
            height: 36 + zoom.value * 16
            activeFocusOnTab: true
            Accessible.role: Accessible.List
            Accessible.name: slice.explorer.ready ? "Block slice. Selected " + slice.explorer.selectedBlock.name + ", world " + slice.explorer.selectedBlock.world : "No decoded slice"
            Keys.onPressed: function(event) {
                if (!slice.explorer.ready) return
                let direction = ""
                if (event.key === Qt.Key_Left) direction = "left"
                else if (event.key === Qt.Key_Right) direction = "right"
                else if (event.key === Qt.Key_Up) direction = "up"
                else if (event.key === Qt.Key_Down) direction = "down"
                else if (event.key === Qt.Key_Home) direction = event.modifiers & Qt.ControlModifier ? "first" : "home"
                else if (event.key === Qt.Key_End) direction = event.modifiers & Qt.ControlModifier ? "last" : "end"
                else if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) { slice.inspectRequested(); event.accepted = true; return }
                else return
                slice.explorer.moveCell(direction)
                event.accepted = true
            }
            Repeater {
                model: 16
                delegate: Item {
                    required property int index
                    Text { x: 36 + index * zoom.value; width: zoom.value; horizontalAlignment: Text.AlignHCenter; text: index; color: slice.ink; font.pixelSize: 13 }
                    Text { y: 36 + index * zoom.value; width: 28; height: zoom.value; verticalAlignment: Text.AlignVCenter; horizontalAlignment: Text.AlignRight; text: index; color: slice.ink; font.pixelSize: 13 }
                }
            }
            Grid {
                x: 36; y: 36; columns: 16
                Repeater {
                    model: slice.explorer.cells
                    delegate: Rectangle {
                        required property var modelData
                        required property int index
                        width: zoom.value; height: zoom.value
                        color: modelData.color
                        border.width: index === slice.explorer.selectedCell ? 3 : 1
                        border.color: index === slice.explorer.selectedCell ? (backend.dark ? "white" : "#101510") : (backend.dark ? "#1D211C" : "#F1F5EC")
                        Text { anchors.centerIn: parent; text: index === slice.explorer.selectedCell ? "+" : ""; color: "white"; font.pixelSize: 20; style: Text.Outline; styleColor: "black" }
                        MouseArea { anchors.fill: parent; onClicked: { gridFrame.forceActiveFocus(); slice.explorer.selectCell(index) } }
                    }
                }
            }
            Rectangle { anchors.fill: parent; color: "transparent"; border.width: gridFrame.activeFocus ? 2 : 0; border.color: backend.dark ? "#A5D395" : "#3F6837" }
            }
        }
    }
    RowLayout {
        Label { text: "Select local X"; color: slice.ink }
        MdSpinBox { from: 0; to: 15; value: slice.explorer.selectedCell % 16; enabled: slice.explorer.ready; Accessible.name: "Selected local X"; onValueModified: slice.explorer.selectCell(Math.floor(slice.explorer.selectedCell / 16) * 16 + value) }
        Label { text: "Z"; color: slice.ink }
        MdSpinBox { from: 0; to: 15; value: Math.floor(slice.explorer.selectedCell / 16); enabled: slice.explorer.ready; Accessible.name: "Selected local Z"; onValueModified: slice.explorer.selectCell(value * 16 + slice.explorer.selectedCell % 16) }
        Label { text: slice.explorer.ready ? "World " + slice.explorer.selectedBlock.world : "No cell selected"; color: slice.ink; Layout.fillWidth: true; wrapMode: Text.WordWrap; font.pixelSize: 13 }
    }
}
