pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Layouts
import QtQuick.Dialogs
import QtQuick.Window

ApplicationWindow {
    id: window
    width: 1600
    height: 900
    minimumWidth: 1280
    minimumHeight: 720
    visible: true
    title: "Material Minecraft Map Editor"
    flags: Qt.Window | Qt.FramelessWindowHint
    Material.theme: backend.dark ? Material.Dark : Material.Light
    Material.primary: backend.dark ? "#A5D395" : "#3F6837"
    Material.accent: Material.primary
    color: backend.dark ? "#101510" : "#F7FBF2"
    property color ink: backend.dark ? "#E1E5DC" : "#191D18"
    property color secondaryInk: backend.dark ? "#C2C9BD" : "#424940"
    property color panel: backend.dark ? "#191D18" : "#F1F5EC"
    property bool allowClose: false
    property int bodySize: backend.largeText ? 20 : 16
    onClosing: function(close) {
        if (!allowClose) {
            close.accepted = false
            if (backend.busy) closeDialog.open()
            backend.requestClose()
        }
    }
    Connections {
        target: backend
        function onCloseReady() { window.allowClose = true; window.close() }
    }
    Shortcut { sequence: "Ctrl+O"; onActivated: folder.open() }
    Shortcut { sequence: "Alt+F4"; onActivated: window.close() }
    Shortcut { sequence: "Escape"; enabled: backend.busy; onActivated: backend.cancel() }
    Shortcut { sequence: "F6"; onActivated: openButton.forceActiveFocus() }
    Shortcut { sequence: "Alt+Space"; onActivated: windowMenu.open() }

    FolderDialog {
        id: folder
        title: "Choose a Java world directory"
        onAccepted: backend.openWorld(selectedFolder)
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 24
        spacing: 20
        RowLayout {
            objectName: "titleBarLayout"
            Layout.fillWidth: true
            Layout.fillHeight: false
            Layout.minimumHeight: 56
            Layout.preferredHeight: 56
            Layout.maximumHeight: 56
            Label {
                text: "Material Minecraft Map Editor"
                font.pixelSize: 22
                color: window.ink
                Layout.preferredWidth: 410
                Accessible.name: text
            }
            Item {
                Layout.fillWidth: true
                Layout.fillHeight: false
                Layout.minimumHeight: 48
                Layout.preferredHeight: 48
                Layout.maximumHeight: 48
                TapHandler {
                    onDoubleTapped: window.visibility === Window.Maximized ? window.showNormal() : window.showMaximized()
                }
                DragHandler {
                    target: null
                    onActiveChanged: if (active) window.startSystemMove()
                }
            }
            MdButton { text: "Accessibility"; onClicked: accessibility.open() }
            MdButton { text: backend.dark ? "Light theme" : "Dark theme"; onClicked: backend.setDark(!backend.dark) }
            MdWindowButton { actionName: "Minimize"; text: "−"; onClicked: window.showMinimized() }
            MdWindowButton {
                actionName: window.visibility === Window.Maximized ? "Restore" : "Maximize"
                text: window.visibility === Window.Maximized ? "❐" : "□"
                onClicked: window.visibility === Window.Maximized ? window.showNormal() : window.showMaximized()
            }
            MdWindowButton { actionName: "Close"; text: "×"; onClicked: window.close() }
        }
        Rectangle {
            Layout.fillWidth: true
            Layout.minimumHeight: 1
            Layout.preferredHeight: 1
            Layout.maximumHeight: 1
            color: backend.dark ? "#424940" : "#C2C9BD"
        }
        RowLayout {
            objectName: "worldActionsLayout"
            Layout.fillWidth: true
            Layout.fillHeight: false
            Layout.minimumHeight: 56
            Layout.preferredHeight: 56
            Layout.maximumHeight: 56
            Label { text: "World inspector"; font.pixelSize: 28; color: window.ink; Layout.fillWidth: true }
            MdButton { id: openButton; text: "Open world…"; primary: true; onClicked: folder.open() }
            MdButton { text: "Cancel probe"; visible: backend.busy; onClicked: backend.cancel() }
        }
        RowLayout {
            objectName: "worldBodyLayout"
            visible: backend.explorer.dimensionIds.length === 0
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumHeight: 320
            spacing: 24
            Rectangle {
                Layout.preferredWidth: 300
                Layout.fillHeight: true
                radius: 16
                color: window.panel
                ScrollView {
                    id: worldScroll
                    objectName: "worldDetailsScroll"
                    anchors.fill: parent
                    anchors.margins: 24
                    contentWidth: availableWidth
                    contentHeight: worldDetails.implicitHeight
                    clip: true
                    ColumnLayout {
                        id: worldDetails
                        width: worldScroll.availableWidth
                        height: implicitHeight
                        spacing: 20
                        Label { text: "Local world"; font.pixelSize: 22; color: window.ink }
                        Label {
                            text: backend.worldPath.length ? backend.worldPath : "No world selected"
                            wrapMode: Text.WrapAnywhere
                            Layout.fillWidth: true
                            font.pixelSize: window.bodySize
                            color: window.secondaryInk
                            textFormat: Text.PlainText
                        }
                        Rectangle { Layout.fillWidth: true; height: 1; color: backend.dark ? "#424940" : "#C2C9BD" }
                        Label {
                            text: "Read-only inspection"
                            font.pixelSize: window.bodySize
                            color: window.ink
                            wrapMode: Text.WordWrap
                            Layout.fillWidth: true
                        }
                        Label {
                            text: "The engine reads level.dat. It does not modify your world or start Minecraft."
                            font.pixelSize: window.bodySize
                            color: window.secondaryInk
                            wrapMode: Text.WordWrap
                            Layout.fillWidth: true
                        }
                        Label { text: "Engine version"; font.pixelSize: 14; color: window.secondaryInk }
                        Label { text: backend.engineVersion; font.pixelSize: window.bodySize; color: window.ink }
                    }
                }
            }
            Rectangle {
                Layout.fillWidth: true
                Layout.fillHeight: true
                radius: 16
                color: window.panel
                ScrollView {
                    id: resultScroll
                    objectName: "probeResultScroll"
                    anchors.fill: parent
                    anchors.margins: 32
                    contentWidth: availableWidth
                    contentHeight: resultDetails.implicitHeight
                    clip: true
                    ColumnLayout {
                        id: resultDetails
                        width: resultScroll.availableWidth
                        height: implicitHeight
                        spacing: 24
                        Label {
                            text: backend.state === "result" ? "World metadata"
                                : backend.state === "probing" ? "Inspecting world"
                                : backend.state === "unsupported" ? "Inspection unavailable" : "Open a Java world"
                            font.pixelSize: 28
                            color: window.ink
                            Layout.fillWidth: true
                            wrapMode: Text.WordWrap
                        }
                        Label {
                            text: backend.message
                            textFormat: Text.PlainText
                            color: window.secondaryInk
                            font.pixelSize: window.bodySize
                            Layout.fillWidth: true
                            wrapMode: Text.WordWrap
                            Accessible.role: Accessible.StaticText
                            Accessible.name: text
                        }
                        ProgressBar { Layout.fillWidth: true; indeterminate: true; visible: backend.busy; Accessible.name: "Read-only inspection in progress" }
                        Repeater {
                            model: backend.state === "result" ? [
                                ["Edition", backend.facts.edition],
                                ["Data version", backend.facts.dataVersion],
                                ["Verified capability", backend.facts.support],
                                ["Editing", backend.facts.editing]] : []
                            delegate: ColumnLayout {
                                required property var modelData
                                Layout.fillWidth: true
                                spacing: 8
                                Label { text: modelData[0]; font.pixelSize: 14; color: window.secondaryInk }
                                Label { text: modelData[1]; font.pixelSize: window.bodySize; color: window.ink; Layout.fillWidth: true; wrapMode: Text.WordWrap }
                                Rectangle { Layout.fillWidth: true; height: 1; color: backend.dark ? "#424940" : "#C2C9BD" }
                            }
                        }
                        Label {
                            visible: backend.state === "empty"
                            text: "Choose the directory containing level.dat. Java compatibility beyond structural metadata is not verified. Bedrock support is deferred."
                            font.pixelSize: window.bodySize
                            color: window.secondaryInk
                            wrapMode: Text.WordWrap
                            Layout.fillWidth: true
                        }
                    }
                }
            }
        }
        ChunkWorkspace {
            visible: backend.explorer.dimensionIds.length > 0
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumHeight: 320
        }
        Label {
            objectName: "provenanceFooter"
            text: "Native inspection increment  ·  Build version: unavailable  ·  Updated-at provenance: unavailable"
            font.pixelSize: 13
            color: window.secondaryInk
            Layout.fillWidth: true
            Layout.fillHeight: false
            Layout.minimumHeight: implicitHeight
            Layout.preferredHeight: implicitHeight
            Layout.maximumHeight: implicitHeight
            wrapMode: Text.WordWrap
        }
    }

    Dialog {
        id: accessibility
        title: "Accessibility"
        anchors.centerIn: parent
        width: 520
        modal: true
        standardButtons: Dialog.Close
        contentItem: ColumnLayout {
            spacing: 20
            Switch { text: "Larger text"; checked: backend.largeText; onToggled: backend.setLargeText(checked) }
            Label { text: "Tab moves through controls. Ctrl+O opens a world. Escape cancels inspection. F6 focuses Open world. Alt+Space opens window actions."; wrapMode: Text.WordWrap; Layout.fillWidth: true }
            Label { text: "Motion is disabled in this increment. Narration and contrast customization are not yet available."; wrapMode: Text.WordWrap; Layout.fillWidth: true }
        }
    }
    Dialog {
        id: closeDialog
        title: "Stopping read-only inspection"
        anchors.centerIn: parent
        width: 520
        modal: true
        closePolicy: Popup.NoAutoClose
        contentItem: ColumnLayout {
            Label { text: backend.message; wrapMode: Text.WordWrap; Layout.fillWidth: true }
            MdButton { text: "Cancel close"; onClicked: { backend.cancelClose(); closeDialog.close() } }
            Label { text: "The window closes after the engine acknowledges stopping."; wrapMode: Text.WordWrap; Layout.fillWidth: true }
        }
    }
    Menu {
        id: windowMenu
        x: 24; y: 72
        MenuItem { text: "Minimize"; onTriggered: window.showMinimized() }
        MenuItem { text: "Maximize"; onTriggered: window.showMaximized() }
        MenuItem { text: "Restore"; onTriggered: window.showNormal() }
        MenuItem { text: "Close"; onTriggered: window.close() }
    }
    // Edge drag zones preserve native resize without intercepting client controls.
    Repeater {
        model: [Qt.LeftEdge, Qt.RightEdge, Qt.TopEdge, Qt.BottomEdge]
        delegate: MouseArea {
            required property int modelData
            x: modelData === Qt.RightEdge ? window.width - 6 : 0
            y: modelData === Qt.BottomEdge ? window.height - 6 : 0
            width: modelData === Qt.LeftEdge || modelData === Qt.RightEdge ? 6 : window.width
            height: modelData === Qt.TopEdge || modelData === Qt.BottomEdge ? 6 : window.height
            enabled: window.visibility !== Window.Maximized
            onPressed: window.startSystemResize(modelData)
        }
    }
}
