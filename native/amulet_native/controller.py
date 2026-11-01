"""Asynchronous, process-owned read-only engine integration."""

from pathlib import Path

from PySide6.QtCore import QObject, Property, QProcess, QSettings, QTimer, QUrl, Signal, Slot

from .framing import Decoder, accepts_reply, encode_request, probe_facts, world_identity


class Controller(QObject):
    changed = Signal()
    closeReady = Signal()

    def __init__(self, engine_path: Path):
        super().__init__()
        self.engine_path = engine_path
        self.settings = QSettings("MaterialMapEditor", "NativeInspector")
        self._dark = self.settings.value("appearance/dark", True, type=bool)
        self._large = self.settings.value("accessibility/largeText", False, type=bool)
        self._state = "empty"
        self._message = "Choose a Java world directory to inspect its actual metadata."
        self._path = ""
        self._facts = {}
        self._engine = "Not connected"
        self.generation = 0
        self.identity = ""
        self.process = None
        self.pending = None
        self.closing = False
        self.stopping = False
        self.decoder = Decoder()
        self.diagnostic_bytes = 0
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._timeout)

    @Property(str, notify=changed)
    def state(self): return self._state

    @Property(str, notify=changed)
    def message(self): return self._message

    @Property(str, notify=changed)
    def worldPath(self): return self._path

    @Property("QVariantMap", notify=changed)
    def facts(self): return self._facts

    @Property(str, notify=changed)
    def engineVersion(self): return self._engine

    @Property(bool, notify=changed)
    def busy(self): return self.process is not None

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
        self.pending = (self.generation, identity)
        self._state, self._message = "probing", "Starting read-only metadata inspection…"
        if self.process:
            self._stop()
        else:
            self._start_pending()
        self.changed.emit()

    def _start_pending(self):
        if self.pending is None or self.closing:
            return
        generation, identity = self.pending
        self.pending = None
        if not self.engine_path.is_file():
            self._state = "unsupported"
            self._message = "Engine executable unavailable. Build the native engine before opening a world."
            self.changed.emit()
            return
        process = QProcess(self)
        self.process = process
        self.stopping = False
        self.decoder = Decoder()
        self.diagnostic_bytes = 0
        self.expected = f"{generation}:info"
        self.phase = "info"
        self.active_generation, self.active_identity = generation, identity
        process.setProgram(str(self.engine_path))
        process.setArguments([])
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
                    self._fail(str(message)[:500])
                    return
                result = response["result"]
                if self.phase == "info":
                    if (not isinstance(result, dict) or result.get("protocolVersion") != 1
                            or "world.probe" not in result.get("methods", [])):
                        raise ValueError("Engine does not support the required read-only protocol")
                    self._engine = str(result.get("version", "Unavailable"))[:80]
                    self.phase = "probe"
                    self.expected = f"{self.active_generation}:probe"
                    self._message = "Reading level.dat without changing world files…"
                    self._send(process, "world.probe", {"path": self.active_identity})
                    self.changed.emit()
                else:
                    self._facts = probe_facts(result)
                    self._state = "result"
                    self._message = "Metadata read successfully. Terrain rendering and editing are not available in this increment."
                    self._stop()
                    self.changed.emit()
            if process.bytesAvailable() and not self.stopping:
                QTimer.singleShot(0, lambda: self._read(process))
        except (ValueError, TypeError, RecursionError, UnicodeError):
            self._fail("Invalid or unsupported engine response. No world changes were made.")

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
            self._finished(process, -1)

    def _finished(self, process, code):
        if process is not self.process:
            return
        self.timer.stop()
        if not self.stopping and self._state == "probing":
            self._state, self._message = "unsupported", "Engine stopped before a complete response."
        self.process = None
        self.stopping = False
        process.deleteLater()
        if self.closing:
            self.closeReady.emit()
        elif self.pending:
            self._start_pending()
        elif self._state == "probing":
            self._state, self._message = "empty", "Probe canceled. No world changes were made."
        self.changed.emit()

    @Slot()
    def cancel(self):
        self.generation += 1
        self.pending = None
        if self.process:
            self._message = "Cancel requested. Waiting for the read-only engine to stop…"
            self._stop()
        self.changed.emit()

    @Slot()
    def requestClose(self):
        self.closing = True
        if self.process:
            self.cancel()
        else:
            self.closeReady.emit()

    @Slot()
    def cancelClose(self):
        self.closing = False
        self.changed.emit()
