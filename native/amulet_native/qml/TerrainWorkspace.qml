pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ColumnLayout {
    id: workspace
    property color ink: backend.dark ? "#E1E5DC" : "#191D18"
    property bool compact: width < 1350 || backend.largeText
    property string mode: "orbit"
    spacing: 8
    RowLayout {
        Layout.fillWidth: true
        MdButton { text: "Load area…"; primary: true; onClicked: loadDialog.open() }
        MdButton { text: "Orbit"; primary: workspace.mode === "orbit"; onClicked: workspace.mode = "orbit" }
        MdButton { text: "Pan"; primary: workspace.mode === "pan"; onClicked: workspace.mode = "pan" }
        MdButton { text: "Fly"; primary: workspace.mode === "fly"; onClicked: workspace.mode = "fly" }
        MdButton { text: "Frame loaded"; enabled: backend.terrain.hasScene; onClicked: backend.terrain.frameLoaded() }
        MdButton { text: "Camera controls…"; onClicked: controlsDialog.open() }
        MdButton { text: "Inspect"; onClicked: inspectDialog.open() }
    }
    RowLayout {
        Layout.fillWidth: true
        Layout.minimumHeight: 48; Layout.maximumHeight: 48
        Label { text: backend.terrain.busy ? "Loading read-only terrain…" : backend.terrain.ready ? "Shape-only view; opacity, textures and lighting not represented" : backend.terrain.hasGeometry ? "Updating displayed view; picking waits for frame submission" : "No submitted terrain; see status details"; color: workspace.ink; Layout.fillWidth: true; wrapMode: Text.WordWrap; font.pixelSize: 14 }
        MdButton { text: "Status details…"; onClicked: statusDialog.open() }
    }
    TerrainViewport {
        id: viewport
        mode: workspace.mode
        Layout.fillWidth: true
        Layout.fillHeight: true
        Layout.minimumHeight: 320
        onInspectRequested: inspectDialog.open()
    }
    Label { text: backend.terrain.selectionText; color: workspace.ink; Layout.fillWidth: true; wrapMode: Text.WordWrap; font.pixelSize: 13 }
    MdDialog {
        id: controlsDialog
        title: "Camera and inspection controls"
        width: 640
        anchors.centerIn: Overlay.overlay
        contentItem: ColumnLayout {
            Label { text: backend.terrain.viewLabel + " · Camera " + backend.terrain.cameraText; wrapMode: Text.WordWrap; Layout.fillWidth: true }
            RowLayout {
                MdButton { text: "Perspective"; onClicked: backend.terrain.view("perspective") }
                MdButton { text: "Top"; onClicked: backend.terrain.view("top") }
                MdButton { text: "Front"; onClicked: backend.terrain.view("front") }
                MdButton { text: "Side"; onClicked: backend.terrain.view("side") }
            }
            MdButton { text: "Previous camera"; onClicked: backend.terrain.back() }
            MdButton { text: "Go to coordinates…"; onClicked: { controlsDialog.close(); goDialog.open() } }
            MdButton { text: "Cutaway…"; enabled: backend.terrain.hasScene; onClicked: { controlsDialog.close(); cutDialog.open() } }
            MdButton { text: "Select by coordinates…"; enabled: backend.terrain.hasScene; onClicked: { controlsDialog.close(); selectionDialog.open() } }
            MdButton { text: "Frame selection"; enabled: backend.terrain.hasScene; onClicked: backend.terrain.frameSelection() }
            MdButton { text: "Next unsupported cell"; enabled: backend.terrain.hasUnsupported; onClicked: { backend.terrain.nextUnsupported(); controlsDialog.close(); inspectDialog.open() } }
            Label { text: "Alt-drag orbits; middle-drag pans; Shift-click chooses box corners. Orbit uses arrow keys and Page Up/Down. Fly uses W/A/S/D and Q/E at 8 blocks/second, or Shift for 32. Right-button hold captures look; Escape, release or focus loss releases it. Enter opens inspection."; wrapMode: Text.WordWrap; Layout.fillWidth: true }
        }
        onClosed: viewport.forceActiveFocus()
    }
    MdDialog {
        id: statusDialog
        title: "Terrain load and coverage status"
        width: 640
        anchors.centerIn: Overlay.overlay
        contentItem: ColumnLayout {
            Label { text: backend.terrain.status; textFormat: Text.PlainText; wrapMode: Text.WordWrap; Layout.fillWidth: true }
            MdProgress { visible: backend.terrain.busy; indeterminate: true; Layout.fillWidth: true }
            MdButton { text: "Cancel terrain operation"; enabled: backend.terrain.busy; onClicked: backend.cancel() }
        }
        onClosed: viewport.forceActiveFocus()
    }
    MdDialog {
        id: loadDialog
        title: "Load an explicit bounded area"
        width: 820
        anchors.centerIn: Overlay.overlay
        contentItem: ColumnLayout {
            Label { text: "Loading replaces the displayed scene. No world files are changed. Each radius is 0 or 1; at most 9 chunks and 27 sections are requested."; Layout.fillWidth: true; wrapMode: Text.WordWrap }
            RowLayout {
                MdNumericField { id: cx; label: "Chunk X"; text: backend.terrainDraft.x; Layout.preferredWidth: 238 }
                MdNumericField { id: cz; label: "Chunk Z"; text: backend.terrainDraft.z; Layout.preferredWidth: 238 }
                MdNumericField { id: sy; label: "Section Y"; text: backend.terrainDraft.section; guidance: "Section Y is a signed integer from -128 through 127. One section contains 16 block layers. The selected radius must also stay inside this range."; Layout.preferredWidth: 238 }
            }
            RowLayout {
                Label { text: "Horizontal radius" }
                MdSpinBox { id: radius; from: 0; to: 1; value: 0; Accessible.name: "Horizontal chunk radius" }
                Label { text: "Vertical radius" }
                MdSpinBox { id: vertical; from: 0; to: 1; value: 0; Accessible.name: "Vertical section radius" }
            }
            MdButton { text: "Load selected area"; onClicked: { backend.loadTerrain(cx.text,cz.text,sy.text,radius.value,vertical.value,false); loadDialog.close() } }
            MdButton { text: "Load around camera"; onClicked: { backend.loadTerrain(cx.text,cz.text,sy.text,radius.value,vertical.value,true); loadDialog.close() } }
            Label { text: backend.references.status; textFormat: Text.PlainText; wrapMode: Text.WordWrap; Layout.fillWidth: true }
        }
        onClosed: viewport.forceActiveFocus()
    }
    MdDialog {
        id: goDialog
        title: "Go to camera coordinates"
        width: 820
        anchors.centerIn: Overlay.overlay
        contentItem: ColumnLayout {
            RowLayout {
                MdNumericField { id: gx; label: "Camera X"; text: "0"; maximumLength: 12; guidance: "Exact camera X integer: -34359738368 through 34359738367. Go does not load data or silently clamp."; Layout.preferredWidth: 238 }
                MdNumericField { id: gy; label: "Camera Y"; text: "64"; guidance: "Camera Y integer: -4096 through 4095. Loadable world Y is -2048 through 2047."; Layout.preferredWidth: 238 }
                MdNumericField { id: gz; label: "Camera Z"; text: "0"; maximumLength: 12; guidance: "Exact camera Z integer: -34359738368 through 34359738367. Go does not load data or silently clamp."; Layout.preferredWidth: 238 }
            }
            Label { text: "Go does not load data or clamp coordinates. X/Z: -34359738368…34359738367. Camera Y: -4096…4095. Loadable world Y remains -2048…2047."; Layout.fillWidth: true; wrapMode: Text.WordWrap }
            MdButton { text: "Go"; onClicked: { backend.terrain.go(gx.text,gy.text,gz.text); goDialog.close() } }
        }
        onClosed: viewport.forceActiveFocus()
    }
    MdDialog {
        id: cutDialog
        title: "Inclusive Y cutaway"
        width: 520
        anchors.centerIn: Overlay.overlay
        contentItem: ColumnLayout {
            Label { text: "Hides cells outside these Y bounds. Existing shape faces are shown; no material or cut-cap geometry is invented."; Layout.fillWidth: true; wrapMode: Text.WordWrap }
            RowLayout {
                Label { text: "Minimum Y" }
                MdSpinBox { id: low; from: backend.terrain.minimumY; to: backend.terrain.maximumY; value: from; Accessible.name: "Minimum visible world Y" }
                Label { text: "Maximum Y" }
                MdSpinBox { id: high; from: backend.terrain.minimumY; to: backend.terrain.maximumY; value: to; Accessible.name: "Maximum visible world Y" }
            }
            MdButton { text: "Apply cutaway"; onClicked: { backend.terrain.setCut(low.value,high.value); cutDialog.close() } }
        }
        onClosed: viewport.forceActiveFocus()
    }
    MdDialog {
        id: selectionDialog
        title: "Inclusive read-only box selection"
        width: 820
        anchors.centerIn: Overlay.overlay
        contentItem: ColumnLayout {
            Label { text: "Both corners are inclusive. X/Z use exact block coordinates. Y must be -2048 through 2047. Unloaded cells count as unknown."; wrapMode: Text.WordWrap; Layout.fillWidth: true }
            RowLayout {
                MdNumericField { id: ax; label: "First X"; text: "0"; maximumLength: 12; guidance: "Exact block X: -34359738368 through 34359738367."; Layout.preferredWidth: 238 }
                MdNumericField { id: ay; label: "First Y"; text: "0"; guidance: "Exact block Y: -2048 through 2047."; Layout.preferredWidth: 238 }
                MdNumericField { id: az; label: "First Z"; text: "0"; maximumLength: 12; guidance: "Exact block Z: -34359738368 through 34359738367."; Layout.preferredWidth: 238 }
            }
            RowLayout {
                MdNumericField { id: bx; label: "Second X"; text: "0"; maximumLength: 12; guidance: "Exact block X: -34359738368 through 34359738367."; Layout.preferredWidth: 238 }
                MdNumericField { id: by; label: "Second Y"; text: "0"; guidance: "Exact block Y: -2048 through 2047."; Layout.preferredWidth: 238 }
                MdNumericField { id: bz; label: "Second Z"; text: "0"; maximumLength: 12; guidance: "Exact block Z: -34359738368 through 34359738367."; Layout.preferredWidth: 238 }
            }
            MdButton { text: "Select bounds"; onClicked: { backend.terrain.selectBox(ax.text,ay.text,az.text,bx.text,by.text,bz.text); selectionDialog.close() } }
        }
        onClosed: viewport.forceActiveFocus()
    }
    MdDialog {
        id: inspectDialog
        title: "Selected shape or unsupported cell"
        width: Math.min(560,workspace.width-48)
        height: Math.min(600,workspace.height)
        anchors.centerIn: Overlay.overlay
        contentItem: BlockInspector { explorer: backend.terrain }
        onClosed: viewport.forceActiveFocus()
    }
}
