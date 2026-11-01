pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Layouts

ColumnLayout {
    id: selector
    required property string label
    required property var filterModel
    required property var choices
    property int selectedIndex: -1
    signal chosen(int index)
    spacing: 4
    Label { text: selector.label; color: backend.dark ? "#E1E5DC" : "#191D18" }
    ComboBox {
        id: combo
        Layout.fillWidth: true
        implicitHeight: 48
        model: selector.choices
        currentIndex: selector.selectedIndex
        Accessible.name: selector.label
        onActivated: selector.chosen(currentIndex)
        popup: Popup {
            y: combo.height
            width: Math.max(combo.width, 420)
            height: Math.min(380, Overlay.overlay.height - 120)
            padding: 12
            contentItem: ColumnLayout {
                RowLayout {
                    TextField { id: query; text: selector.filterModel.query; placeholderText: "Filter choices"; Layout.fillWidth: true; maximumLength: 512; Accessible.name: selector.label + " filter"; onTextEdited: selector.filterModel.setQuery(text) }
                    MdWindowButton { text: "×"; actionName: "Clear " + selector.label + " filter"; onClicked: selector.filterModel.setQuery("") }
                    MdButton { text: "Regex…"; onClicked: builder.open() }
                }
                Label { text: selector.filterModel.status; Layout.fillWidth: true; wrapMode: Text.WordWrap; textFormat: Text.PlainText }
                ListView {
                    id: results
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    model: selector.filterModel.visibleItems
                    delegate: ItemDelegate {
                        required property string modelData
                        width: results.width
                        text: modelData
                        Accessible.name: modelData
                        onClicked: { selector.chosen(selector.choices.indexOf(modelData)); combo.popup.close(); combo.forceActiveFocus() }
                    }
                    Label { anchors.centerIn: parent; visible: results.count === 0; text: "No matching choices" }
                }
            }
        }
    }
    MdRegexDialog { id: builder; filterModel: selector.filterModel; onClosed: combo.forceActiveFocus() }
}
