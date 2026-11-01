"""Asynchronous, process-owned read-only engine integration."""

from pathlib import Path

from PySide6.QtCore import QObject, Property, QProcess, QSettings, QTimer, QUrl, Signal, Slot

from .framing import Decoder, accepts_reply, encode_request, probe_facts, world_identity
from .explorer import Explorer
from .references import ReferenceSettings
from .engine_coordinator import EngineCoordinator


class Controller(QObject):
    changed = Signal()
    closeReady = Signal()

    def __init__(self, engine_path: Path, reference_root_override=None):
        super().__init__()
        self.engine_path = engine_path
        self.settings = QSettings("MaterialMapEditor", "NativeInspector")
        self._references = ReferenceSettings(self.settings, reference_root_override, self)
        self.coordinator = EngineCoordinator(self)
        self._dark = self.settings.value("appearance/dark", True, type=bool)
        self._large = self.settings.value("accessibility/largeText", False, type=bool)
        self._state = "empty"
        self._message = "Choose a Java world directory to inspect its actual metadata."
        self._path = ""
        self._facts = {}
        self._engine = "Not connected"
        self._explorer = Explorer(self)
        self._explorer.readRequested.connect(self._read_chunk)
        self._explorer.invalidated.connect(self.cancel)
        self._explorer.helpersChanged.connect(self._helpers_changed)
        self.generation = 0
        self.identity = ""
        self.process = None
        self.pending = None
        self.closing = False
        self.close_announced = False
        self.stopping = False
        self.decoder = Decoder()
        self.diagnostic_bytes = 0
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._timeout)
        self.coordinator.changed.connect(self._coordinator_changed)
        self._references.effectiveChanged.connect(self._references_changed)

    @Property(str, notify=changed)
    def state(self): return self._state

    @Property(QObject, constant=True)
    def explorer(self): return self._explorer

    @Property(QObject, constant=True)
    def references(self): return self._references

    @Property(str, notify=changed)
    def message(self): return self._message

    @Property(str, notify=changed)
    def worldPath(self): return self._path

    @Property("QVariantMap", notify=changed)
    def facts(self): return self._facts

    @Property(str, notify=changed)
    def engineVersion(self): return self._engine

    @Property(bool, notify=changed)
    def busy(self): return self.coordinator.busy or self._explorer.helpers_busy

    @Property(bool, notify=changed)
    def dark(self): return self._dark

    @Property(bool, notify=changed)
    def largeText(self): return self._large

    @Slot(bool)
    def setDark(self, value):
        self._dark = value
        self.settings.setValue("appearance/dark", value)
        self.changed.emit()

    @Slot(bool)
    def setLargeText(self, value):
        self._large = value
        self.settings.setValue("accessibility/largeText", value)
        self.changed.emit()

    @Slot(QUrl)
    def openWorld(self, url):
        if self.closing:
            return
        self.generation += 1
        self.pending = None
        self.identity = ""
        self._facts = {}
        self._explorer.reset()
        try:
            if not url.isLocalFile():
                raise ValueError("Choose a local directory")
            identity = world_identity(url.toLocalFile())
            if not Path(identity).is_dir():
                raise ValueError("Choose a directory")
        except (ValueError, OSError) as error:
            self._state, self._message = "empty", str(error)
            if self.process:
                self._stop()
            self.changed.emit()
            return
        self.identity = self._path = identity
        self.pending = (self.generation, identity, None)
        self._state, self._message = "probing", "Starting read-only metadata inspection…"
        if self.process:
            self._stop()
        else:
            self._start_pending()
        self.changed.emit()

    def _start_pending(self):
        if self.pending is None or self.closing:
            return
        if self.coordinator.busy:
            return
        generation, identity, chunk_request = self.pending
        self.pending = None
        if not self.engine_path.is_file():
            self._state = "unsupported"
            self._message = "Engine executable unavailable. Build the native engine before opening a world."
            self._explorer.clear(self._message)
            self.changed.emit()
            return
        try:
            arguments = self._references.engine_arguments()
        except ValueError as error:
            arguments = []
            self._references.report(str(error) + " Geometry unavailable; structural inspection remains available.")
        process = self.coordinator.acquire(self)
        self.process = process
        self.stopping = False
        self.decoder = Decoder()
        self.diagnostic_bytes = 0
        self.expected = f"{generation}:info"
        self.phase = "info"
        self.chunk_request = chunk_request
        self.active_generation, self.active_identity = generation, identity
        process.setProgram(str(self.engine_path))
        process.setArguments(arguments)
        process.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        # Drain diagnostics without displaying or retaining paths/user metadata.
        process.readyReadStandardError.connect(lambda: self._drain_diagnostics(process))
        process.readyReadStandardOutput.connect(lambda: self._read(process))
        process.started.connect(lambda: self._started(process))
        process.finished.connect(lambda code, status: self._finished(process, code))
        process.errorOccurred.connect(lambda error: self._process_error(process, error))
        self.timer.start(30000)
        process.start()

    def _started(self, process):
        if process is not self.process:
            return
        if self.stopping:
            process.kill()
        else:
            self._send(process, "engine.info")

    def _send(self, process, method, params=None):
        if process is not self.process or self.stopping:
            return
        payload = encode_request(self.expected, method, params)
        if process.write(payload) != len(payload):
            self._fail("Could not send the complete engine request.")

    def _read(self, process):
        if process is not self.process:
            return
        if self.stopping:
            process.read(65536)
            return
        try:
            for response in self.decoder.feed(bytes(process.read(65536))):
                if not accepts_reply(response, self.expected, self.active_generation,
                                     self.generation, self.active_identity, self.identity):
                    raise ValueError("Stale or mismatched engine response")
                if "error" in response:
                    error = response["error"]
                    message = error.get("message", "Probe failed") if isinstance(error, dict) else "Probe failed"
                    if isinstance(error, dict) and error.get("code") == "response_too_large":
                        message = "Chunk response exceeds the supported transport limit."
                    self._fail(str(message)[:500])
                    return
                result = response["result"]
                if self.phase == "info":
                    if (not isinstance(result, dict) or type(result.get("protocolVersion")) is not int
                            or result.get("protocolVersion") != 1
                            or not isinstance(result.get("methods"), list)
                            or not all(m in result["methods"] for m in
                                       ("world.probe", "world.dimensions", "world.chunk_summary"))):
                        raise ValueError("Engine does not support the required read-only protocol")
                    self._engine = str(result.get("version", "Unavailable"))[:80]
                    if self.chunk_request is None:
                        self._next_request(process, "probe", "world.probe", {"path": self.active_identity})
                        self._message = "Reading level.dat without changing world files…"
                    else:
                        request = self.chunk_request
                        self._next_request(process, "chunk", "world.chunk_summary",
                                           {"path": self.active_identity, "dimension": request.dimension,
                                            "chunkX": request.x, "chunkZ": request.z})
                    self.changed.emit()
                elif self.phase == "probe":
                    self._facts = probe_facts(result)
                    self._message = "Discovering region-backed dimensions…"
                    self._next_request(process, "dimensions", "world.dimensions", {"path": self.active_identity})
                    self.changed.emit()
                elif self.phase == "dimensions":
                    self._explorer.accept_dimensions(result)
                    self._state = "result"
                    self._message = "World opened read-only. Choose a dimension and chunk. 3D terrain, editing and saving remain unavailable."
                    self._stop()
                    self.changed.emit()
                    break
                elif self.phase == "chunk":
                    self._explorer.accept_chunk(result, self.chunk_request)
                    self._state = "result"
                    self._message = self._explorer.status
                    self._stop()
                    self.changed.emit()
                    break
            if process.bytesAvailable() and not self.stopping:
                QTimer.singleShot(0, lambda: self._read(process))
        except (ValueError, TypeError, RecursionError, UnicodeError):
            self._fail("Invalid or unsupported engine response. No world changes were made.")

    def _next_request(self, process, phase, method, params):
        self.phase = phase
        self.expected = f"{self.active_generation}:{phase}"
        self._send(process, method, params)

    def _read_chunk(self, request):
        if self.closing or not self.identity:
            return
        self.generation += 1
        # ChunkRequest is frozen. Later edits to coordinate drafts cannot
        # relabel the active operation or change response validation.
        self.pending = (self.generation, self.identity, request)
        self._state, self._message = "probing", self._explorer.status
        if self.process:
            self._stop()
        else:
            self._start_pending()
        self.changed.emit()

    def _drain_diagnostics(self, process):
        if process is not self.process:
            return
        process.setReadChannel(QProcess.ProcessChannel.StandardError)
        self.diagnostic_bytes += len(process.read(8192))
        remaining = process.bytesAvailable()
        process.setReadChannel(QProcess.ProcessChannel.StandardOutput)
        if self.diagnostic_bytes > 65536 and not self.stopping:
            self._fail("Engine diagnostic output exceeded the safety limit.")
        elif remaining and not self.stopping:
            QTimer.singleShot(0, lambda: self._drain_diagnostics(process))

    def _fail(self, message):
        self._state, self._message = "unsupported", message
        self._explorer.clear(message)
        self._stop()
        self.changed.emit()

    def _stop(self):
        self.timer.stop()
        if self.process is None:
            return
        self.stopping = True
        self.process.kill()
        # Completion is only acknowledged by QProcess.finished/error, not kill().
        self.timer.start(3000)

    def _timeout(self):
        if self.stopping:
            self._message = "Engine stop is not yet acknowledged. Wait, or cancel closing the window."
            self.changed.emit()
        else:
            self._fail("Metadata inspection exceeded the 30-second limit.")

    def _process_error(self, process, error):
        if process is self.process and error == QProcess.ProcessError.FailedToStart:
            self._state, self._message = "unsupported", "Engine could not start. Verify the native build."
            self._explorer.clear(self._message)
            self._finished(process, -1)

    def _finished(self, process, code):
        if process is not self.process:
            return
        self.timer.stop()
        if not self.stopping and self._state == "probing":
            self._state, self._message = "unsupported", "Engine stopped before a complete response."
            self._explorer.clear(self._message)
        self.process = None
        self.stopping = False
        self.coordinator.release(self, process)
        if self.closing:
            self._maybe_close()
        elif self.pending:
            self._start_pending()
        elif self._state == "probing":
            self._state, self._message = "empty", "Probe canceled. No world changes were made."
            self._explorer.clear(self._message)
        self.changed.emit()

    @Slot()
    def cancel(self):
        self.generation += 1
        self.pending = None
        self._explorer.shutdown()
        if self.process:
            self._message = "Cancel requested. Waiting for the read-only engine to stop…"
            self._stop()
        self.changed.emit()

    @Slot()
    def requestClose(self):
        self.closing = True
        self.close_announced = False
        self._explorer.shutdown()
        if self.process:
            self.cancel()
        else:
            self._maybe_close()
        if self.busy:
            self._message = "Waiting for owned inspection and regex workers to acknowledge stopping."
            self.changed.emit()

    @Slot()
    def cancelClose(self):
        self.closing = False
        self.close_announced = False
        self.changed.emit()

    def _helpers_changed(self):
        self.changed.emit()
        self._maybe_close()

    def _maybe_close(self):
        if self.closing and not self.busy and not self.close_announced:
            self.close_announced = True
            self.closeReady.emit()

    def assert_stopped(self):
        if self.busy:
            raise RuntimeError("Cannot destroy presentation while owned workers remain unacknowledged")

    def _references_changed(self):
        self.cancel()
        self._message = "Reference directory changed. Engine verification occurs on the next request."
        self.changed.emit()

    def _coordinator_changed(self):
        self.changed.emit()
        if not self.coordinator.busy and self.pending is not None and not self.closing:
            QTimer.singleShot(0, self._start_pending)
        self._maybe_close()
