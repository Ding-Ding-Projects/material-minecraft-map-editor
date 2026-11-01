pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Window
import QtQuick3D

FocusScope {
    id: viewport
    objectName: "terrainViewport"
    property string mode: "orbit"
    property int attachmentEpoch: 0
    property bool attachmentInitialized: false
    property bool forwardHeld: false
    property bool backHeld: false
    property bool leftHeld: false
    property bool rightHeld: false
    property bool upHeld: false
    property bool downHeld: false
    property bool fastHeld: false
    signal inspectRequested()
    activeFocusOnTab: true
    Accessible.role: Accessible.Pane
    Accessible.name: "Read-only 3D cube-shape terrain"
    Accessible.description: backend.terrain.selectionText + ". Status details provides load coverage. Camera controls provides exact coordinates and keyboard help."
    function releaseInput() {
        forwardHeld = backHeld = leftHeld = rightHeld = upHeld = downHeld = fastHeld = false
        if (input) input.capturing = false
        backend.terrain.lookCapture(false)
    }
    Connections {
        target: viewport.Window.window
        function onActiveChanged() { if (!viewport.Window.window.active) viewport.releaseInput() }
        function onVisibilityChanged() { if (viewport.attachmentInitialized) viewport.attachView() }
    }
    onActiveFocusChanged: if (!activeFocus) releaseInput()
    function attachView() {
        let window = viewport.Window.window
        if (!visible || !window || !window.visible || window.visibility === Window.Minimized) {
            releaseInput()
            if (attachmentEpoch > 0) backend.terrain.viewportDetached(attachmentEpoch)
            return
        }
        attachmentEpoch = backend.terrain.viewportAttached(viewport)
        backend.terrain.viewportChanged(attachmentEpoch, sceneView.effectiveTextureSize.width, sceneView.effectiveTextureSize.height)
    }
    onVisibleChanged: {
        if (!visible) {
            releaseInput()
            if (attachmentEpoch > 0) backend.terrain.viewportDetached(attachmentEpoch)
        } else if (attachmentInitialized) attachView()
    }
    onModeChanged: releaseInput()
    Component.onCompleted: { attachmentInitialized = true; attachView() }
    Component.onDestruction: {
        attachmentInitialized = false
        releaseInput()
        if (attachmentEpoch > 0) backend.terrain.viewportDetached(attachmentEpoch)
    }
    Keys.onPressed: function(event) {
        if (event.key === Qt.Key_Escape) { releaseInput(); backend.terrain.cancelSelection(); event.accepted = true; return }
        if (event.key === Qt.Key_Return) { inspectRequested(); event.accepted = true; return }
        if (mode === "fly") {
            if (event.key === Qt.Key_W) forwardHeld = true
            else if (event.key === Qt.Key_S) backHeld = true
            else if (event.key === Qt.Key_A) leftHeld = true
            else if (event.key === Qt.Key_D) rightHeld = true
            else if (event.key === Qt.Key_E) upHeld = true
            else if (event.key === Qt.Key_Q) downHeld = true
            else if (event.key === Qt.Key_Shift) fastHeld = true
            else return
        } else {
            if (event.key === Qt.Key_Left) backend.terrain.orbit(-5, 0)
            else if (event.key === Qt.Key_Right) backend.terrain.orbit(5, 0)
            else if (event.key === Qt.Key_Up) backend.terrain.orbit(0, -5)
            else if (event.key === Qt.Key_Down) backend.terrain.orbit(0, 5)
            else if (event.key === Qt.Key_PageUp) backend.terrain.dolly(1)
            else if (event.key === Qt.Key_PageDown) backend.terrain.dolly(-1)
            else return
        }
        event.accepted = true
    }
    Keys.onReleased: function(event) {
        if (event.isAutoRepeat) return
        if (event.key === Qt.Key_W) forwardHeld = false
        if (event.key === Qt.Key_S) backHeld = false
        if (event.key === Qt.Key_A) leftHeld = false
        if (event.key === Qt.Key_D) rightHeld = false
        if (event.key === Qt.Key_E) upHeld = false
        if (event.key === Qt.Key_Q) downHeld = false
        if (event.key === Qt.Key_Shift) fastHeld = false
    }
    Timer {
        id: flight
        interval: 16; repeat: true
        property double previous: 0
        running: viewport.activeFocus && viewport.Window.window && viewport.Window.window.active && viewport.mode === "fly" && (viewport.forwardHeld || viewport.backHeld || viewport.leftHeld || viewport.rightHeld || viewport.upHeld || viewport.downHeld)
        onRunningChanged: previous = Date.now()
        onTriggered: {
            let now = Date.now(); let seconds = (now - previous) / 1000; previous = now
            if (seconds <= 0.05) backend.terrain.fly(Number(viewport.forwardHeld)-Number(viewport.backHeld), Number(viewport.rightHeld)-Number(viewport.leftHeld), Number(viewport.upHeld)-Number(viewport.downHeld), seconds, viewport.fastHeld)
        }
    }
    View3D {
        id: sceneView
        anchors.fill: parent
        renderMode: View3D.Offscreen
        property real pixelWidth: Math.max(1, width * Screen.devicePixelRatio)
        property real pixelHeight: Math.max(1, height * Screen.devicePixelRatio)
        property real targetScale: Math.min(1, 4096 / pixelWidth, 4096 / pixelHeight, Math.sqrt(67108864 / (8 * pixelWidth * pixelHeight)))
        explicitTextureWidth: Math.max(1, Math.floor(pixelWidth * targetScale))
        explicitTextureHeight: Math.max(1, Math.floor(pixelHeight * targetScale))
        camera: backend.terrain.projection === "orthographic" ? orthographic : perspective
        onEffectiveTextureSizeChanged: backend.terrain.viewportChanged(viewport.attachmentEpoch, effectiveTextureSize.width, effectiveTextureSize.height)
        environment: SceneEnvironment {
            backgroundMode: SceneEnvironment.Color
            clearColor: backend.dark ? "#151B14" : "#EDF3E8"
            antialiasingMode: SceneEnvironment.NoAA
            tonemapMode: SceneEnvironment.TonemapModeLinear
        }
        PerspectiveCamera {
            id: perspective
            position: backend.terrain.cameraPosition
            rotation: backend.terrain.cameraRotation
            clipNear: 0.1; clipFar: 4096; fieldOfView: 60
            fieldOfViewOrientation: PerspectiveCamera.Vertical
        }
        OrthographicCamera {
            id: orthographic
            position: backend.terrain.cameraPosition
            rotation: backend.terrain.cameraRotation
            clipNear: 0.1; clipFar: 4096
            horizontalMagnification: Math.max(1, sceneView.effectiveTextureSize.height) / backend.terrain.orthographicSpan
            verticalMagnification: horizontalMagnification
        }
        Repeater3D {
            model: backend.terrain.geometries
            delegate: Model {
                required property var modelData
                geometry: modelData
                materials: PrincipledMaterial {
                    lighting: PrincipledMaterial.NoLighting
                    baseColor: "white"
                    vertexColorsEnabled: true
                    cullMode: Material.BackFaceCulling
                }
            }
        }
        Model {
            geometry: backend.terrain.selectionGeometry
            materials: PrincipledMaterial { lighting: PrincipledMaterial.NoLighting; baseColor: "white"; vertexColorsEnabled: true; cullMode: Material.NoCulling }
        }
    }
    MouseArea {
        id: input
        anchors.fill: parent
        acceptedButtons: Qt.LeftButton | Qt.MiddleButton | Qt.RightButton
        preventStealing: true
        property real previousX: 0
        property real previousY: 0
        property real pressX: 0
        property real pressY: 0
        property bool capturing: false
        cursorShape: capturing ? Qt.BlankCursor : Qt.CrossCursor
        onPressed: function(mouse) {
            viewport.forceActiveFocus(); previousX = pressX = mouse.x; previousY = pressY = mouse.y
            if (viewport.mode === "fly" && mouse.button === Qt.RightButton) capturing = backend.terrain.lookCapture(true)
        }
        onPositionChanged: function(mouse) {
            if (!pressed) return
            let dx = mouse.x - previousX; let dy = mouse.y - previousY; previousX = mouse.x; previousY = mouse.y
            if (capturing) backend.terrain.look(dx * 0.3, dy * 0.3)
            else if ((mouse.buttons & Qt.LeftButton) && (mouse.modifiers & Qt.AltModifier)) backend.terrain.orbit(dx * 0.3, dy * 0.3)
            else if ((mouse.buttons & Qt.MiddleButton) || (viewport.mode === "pan" && (mouse.buttons & Qt.LeftButton))) backend.terrain.pan(-dx * 0.04, dy * 0.04)
        }
        onReleased: function(mouse) {
            if (capturing) { capturing = false; backend.terrain.lookCapture(false); return }
            if (mouse.button === Qt.LeftButton && viewport.mode !== "pan" && !(mouse.modifiers & Qt.AltModifier) && Math.abs(mouse.x-pressX)+Math.abs(mouse.y-pressY)<4) {
                let tw = sceneView.effectiveTextureSize.width; let th = sceneView.effectiveTextureSize.height
                if (tw > 0 && th > 0) backend.terrain.pick(mouse.x / width * tw, mouse.y / height * th, tw, th, Boolean(mouse.modifiers & Qt.ShiftModifier))
            }
        }
        onCanceled: { capturing = false; viewport.releaseInput() }
        onWheel: function(wheel) { backend.terrain.dolly(wheel.angleDelta.y / 120); wheel.accepted = true }
    }
    Label {
        anchors.centerIn: parent
        visible: backend.terrain.geometries.length === 0
        text: "No terrain loaded.\nOpen a Java world, then choose an area to load."
        horizontalAlignment: Text.AlignHCenter
        color: backend.dark ? "#C2C9BD" : "#424940"
        font.pixelSize: 18
    }
    Rectangle { anchors.fill: parent; color: "transparent"; border.width: viewport.activeFocus ? 2 : 0; border.color: backend.dark ? "#A5D395" : "#3F6837" }
}
