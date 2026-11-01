pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

MdDialog {
    id: dialog
    required property var filterModel
    title: "Selector regex workbench"
    width: 680
    height: Math.min(680, Overlay.overlay.height - 48)
    anchors.centerIn: Overlay.overlay
    contentItem: ScrollView {
        id: scroll
        contentWidth: availableWidth
        contentHeight: content.implicitHeight
        clip: true
        ColumnLayout {
            id: content
            width: scroll.availableWidth
            spacing: 12
            Switch { text: "Use regular expression"; checked: dialog.filterModel.regexMode; onToggled: dialog.filterModel.setRegexMode(checked) }
            Label { text: "Pattern for this selector" }
            TextField { text: dialog.filterModel.query; maximumLength: 512; Layout.fillWidth: true; Accessible.name: "Selector regex pattern"; onTextEdited: dialog.filterModel.setQuery(text) }
            RowLayout {
                CheckBox { text: "Ignore case"; checked: dialog.filterModel.ignoreCase; onToggled: dialog.filterModel.setIgnoreCase(checked) }
                CheckBox { text: "Multiline anchors"; checked: dialog.filterModel.multiline; onToggled: dialog.filterModel.setMultiline(checked) }
            }
            Label { text: "Insert escaped literal" }
            RowLayout {
                TextField { id: literal; Layout.fillWidth: true; maximumLength: 128; Accessible.name: "Literal text to escape" }
                MdButton { text: "Insert"; onClicked: { dialog.filterModel.insertLiteral(literal.text); literal.clear() } }
            }
            Label { text: "Test text (maximum 4096 characters)" }
            TextArea { text: dialog.filterModel.sample; textFormat: TextEdit.PlainText; Layout.fillWidth: true; Layout.preferredHeight: 96; wrapMode: TextEdit.Wrap; Accessible.name: "Regex sample text"; onTextChanged: if (activeFocus) dialog.filterModel.setSample(text) }
            Label { text: dialog.filterModel.status; textFormat: Text.PlainText; Layout.fillWidth: true; wrapMode: Text.WordWrap }
            Repeater {
                model: dialog.filterModel.matches
                delegate: Label { required property var modelData; text: "[" + modelData.start + ", " + modelData.end + ") " + modelData.text; textFormat: Text.PlainText; wrapMode: Text.WrapAnywhere; Layout.fillWidth: true }
            }
            Label {
                text: "Supported: Python re matching, case and multiline flags, escaped literal insertion, sample match spans, and this selector's filter. Each run is isolated with a 750 ms execution limit. Unsupported: engine conversion, step debugger, benchmark, replacement/code templates, saved collections and file search. Full RegexBuddy parity is not delivered."
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
            }
        }
    }
}
