pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ColumnLayout {
    id: workspace
    property var explorer: backend.explorer
    property color ink: backend.dark ? "#E1E5DC" : "#191D18"
    property bool compact: width < 1350 || backend.largeText
    spacing: 12
    RowLayout {
        Layout.fillWidth: true
        MdSelect {
            id: dimension
            label: "Dimension"
            filterModel: workspace.explorer.dimensionFilter
            choices: workspace.explorer.dimensionIds
            Layout.fillWidth: true
            Layout.minimumWidth: 220
            selectedIndex: choices.indexOf(workspace.explorer.dimension)
            onChosen: function(index) { workspace.explorer.selectDimension(choices[index]) }
        }
        MdNumericField {
            id: chunkX; label: "Chunk X"; text: "0"; Layout.preferredWidth: 238
            onAccepted: if (read.enabled) workspace.explorer.readChunk(text, chunkZ.text)
        }
        MdNumericField {
            id: chunkZ; label: "Chunk Z"; text: "0"; Layout.preferredWidth: 238
            onAccepted: if (read.enabled) workspace.explorer.readChunk(chunkX.text, text)
        }
        MdButton { id: read; text: "Read chunk"; primary: true; enabled: workspace.explorer.dimension.length > 0 && validation.text.length === 0; onClicked: workspace.explorer.readChunk(chunkX.text, chunkZ.text) }
    }
    Label { id: validation; text: workspace.explorer.coordinateError(chunkX.text, chunkZ.text); visible: text.length > 0; color: backend.dark ? "#FFB4AB" : "#BA1A1A"; Layout.fillWidth: true; wrapMode: Text.WordWrap }
    Label { text: workspace.explorer.status; color: workspace.ink; textFormat: Text.PlainText; Layout.fillWidth: true; wrapMode: Text.WordWrap }
    MdProgress { visible: backend.busy; indeterminate: true; Layout.fillWidth: true }
    RowLayout {
        Layout.fillWidth: true
        MdSelect { label: "Section"; filterModel: workspace.explorer.sectionFilter; choices: workspace.explorer.sectionLabels; selectedIndex: workspace.explorer.sectionIndex; enabled: workspace.explorer.ready; Layout.fillWidth: true; onChosen: function(index) { workspace.explorer.selectSection(index) } }
        Label { text: "Local Y"; color: workspace.ink }
        MdSpinBox { from: 0; to: 15; value: workspace.explorer.localY; enabled: workspace.explorer.ready; Accessible.name: "Local Y within section"; onValueModified: workspace.explorer.setLocalY(value) }
        Label { text: "World Y: " + workspace.explorer.worldY; color: workspace.ink; Layout.preferredWidth: 180 }
    }
    RowLayout {
        Layout.fillWidth: true
        Layout.fillHeight: true
        spacing: 24
        ChunkSlice {
            id: sliceView
            explorer: workspace.explorer
            Layout.fillWidth: true
            Layout.fillHeight: true
            onInspectRequested: { if (workspace.compact) detailDialog.open(); else blockDetails.forceActiveFocus() }
        }
        BlockInspector { id: blockDetails; explorer: workspace.explorer; visible: !workspace.compact; Layout.preferredWidth: 280; Layout.fillHeight: true; activeFocusOnTab: true; Keys.onEscapePressed: sliceView.focusGrid() }
    }
    MdDialog {
        id: detailDialog
        title: "Block inspector"
        width: Math.min(560, workspace.width - 48)
        height: Math.min(600, workspace.height)
        anchors.centerIn: parent
        modal: true
        standardButtons: Dialog.Close
        contentItem: BlockInspector { explorer: workspace.explorer }
        onClosed: sliceView.focusGrid()
    }
}
