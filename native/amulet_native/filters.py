"""Independent per-selector filter state and bounded asynchronous regex work."""

import json
import re
from pathlib import Path
import hashlib

from .regex_runtime import direct_interpreter, identity, WorkerOutput, validate_result

from PySide6.QtCore import QObject, Property, QProcess, QTimer, Signal, Slot


class SelectorFilter(QObject):
    changed = Signal()
    busyChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.items = []
        self._visible = []
        self._query, self._sample = "", ""
        self._regex, self._ignore, self._multiline = False, True, False
        self._status = "Plain-text mode"
        self._matches = []
        self.generation = 0
        self.workers = set()
        self.receipts = []
        self._runtime = None
        self.debounce = QTimer(self)
        self.debounce.setSingleShot(True)
        self.debounce.setInterval(150)
        self.debounce.timeout.connect(self._run)

    @Property("QStringList", notify=changed)
    def visibleItems(self): return self._visible
    @Property(str, notify=changed)
    def query(self): return self._query
    @Property(str, notify=changed)
    def sample(self): return self._sample
    @Property(bool, notify=changed)
    def regexMode(self): return self._regex
    @Property(bool, notify=changed)
    def ignoreCase(self): return self._ignore
    @Property(bool, notify=changed)
    def multiline(self): return self._multiline
    @Property(str, notify=changed)
    def status(self): return self._status
    @Property("QVariantList", notify=changed)
    def matches(self): return self._matches

    def set_items(self, items):
        self.items = list(items)
        self._refresh()

    @Slot(str)
    def setQuery(self, value): self._query = value[:512]; self._refresh()
    @Slot(str)
    def setSample(self, value): self._sample = value[:4096]; self._refresh()
    @Slot(bool)
    def setRegexMode(self, value): self._regex = value; self._refresh()
    @Slot(bool)
    def setIgnoreCase(self, value): self._ignore = value; self._refresh()
    @Slot(bool)
    def setMultiline(self, value): self._multiline = value; self._refresh()
    @Slot(str)
    def insertLiteral(self, value): self._query = (self._query + re.escape(value))[:512]; self._regex = True; self._refresh()

    def _refresh(self):
        self.generation += 1
        self.debounce.stop()
        for process in tuple(self.workers):
            process.kill()
        self._matches = []
        if not self._regex:
            query = self._query.casefold() if self._ignore else self._query
            self._visible = [s for s in self.items if query in (s.casefold() if self._ignore else s)]
            self._status = "Plain-text mode"
        else:
            self._visible = []
            self._status = "Validating bounded regular expression…"
            self.debounce.start()
        self.changed.emit()
        self.busyChanged.emit()

    @property
    def busy(self):
        return bool(self.workers or self.debounce.isActive())

    def _run(self):
        if self.workers:
            self.debounce.start(50)
            return
        try:
            runtime = direct_interpreter()
            if hashlib.sha256(Path(runtime["path"]).read_bytes()).hexdigest() != runtime["sha256"]:
                raise ValueError("Verified regex interpreter changed")
        except (OSError, ValueError) as error:
            self._status = str(error)
            self.changed.emit()
            self.busyChanged.emit()
            return
        self._runtime = runtime
        generation = self.generation
        items, sample = tuple(self.items), self._sample
        engine_version = "Python re " + ".".join(map(str, runtime["version"]))
        process = QProcess(self)
        self.workers.add(process)
        self.busyChanged.emit()
        timer = QTimer(process)
        timer.setSingleShot(True)
        output = WorkerOutput()
        state = {"error": "", "verified": False, "pid": None}
        receipt = {"generation": generation, "qprocessPid": None, "evaluatorPid": None,
                   "interpreterSha256": runtime["sha256"], "verified": False,
                   "stopAcknowledged": False, "outcome": "starting"}
        self.receipts.append(receipt)
        self.receipts = self.receipts[-32:]
        payload = json.dumps({"pattern": self._query, "sample": sample, "items": items,
                              "ignoreCase": self._ignore, "multiline": self._multiline}).encode()
        if len(payload) > 65536:
            self.workers.remove(process)
            process.deleteLater()
            self._status = "Regex request exceeds 64 KiB"
            self.changed.emit()
            self.busyChanged.emit()
            return
        process.setProgram(runtime["path"])
        process.setArguments(["-I", "-S", str(Path(__file__).with_name("regex_worker.py"))])

        def abort(message):
            state["error"] = message
            receipt["outcome"] = message
            process.kill()

        def started():
            state["pid"] = int(process.processId())
            receipt["qprocessPid"] = state["pid"]
            if generation != self.generation:
                process.kill()

        def read():
            try:
                while process.bytesAvailable():
                    output.append(bytes(process.read(min(8192, process.bytesAvailable()))))
                if not state["verified"]:
                    hello = output.take_hello()
                    if hello is not None:
                        if (not isinstance(hello, dict) or set(hello) != {"event", "pid", "executable", "version"}
                                or hello["event"] != "ready" or type(hello["pid"]) is not int
                                or hello["pid"] != state["pid"]
                                or identity(hello["executable"]) != runtime["identity"]
                                or not isinstance(hello["version"], list)
                                or any(type(v) is not int for v in hello["version"])
                                or hello["version"] != runtime["version"]):
                            raise ValueError("Regex evaluator identity does not match owned process")
                        state["verified"] = True
                        receipt["verified"] = True
                        receipt["evaluatorPid"] = hello["pid"]
                        if generation != self.generation:
                            process.kill()
                            return
                        if process.write(payload) != len(payload):
                            raise ValueError("Regex request write incomplete")
                        process.closeWriteChannel()
                        timer.start(750)
            except (ValueError, TypeError, OSError) as error:
                abort(str(error))

        def finish(*unused):
            timer.stop()
            if process not in self.workers:
                return
            # The final drain goes through the same cumulative byte bound.
            read()
            self.workers.remove(process)
            receipt["stopAcknowledged"] = True
            if generation == self.generation:
                try:
                    if state["error"]:
                        raise ValueError(state["error"])
                    if not state["verified"]:
                        raise ValueError("Regex worker exited before identity acknowledgement")
                    if process.exitStatus() != QProcess.ExitStatus.NormalExit or process.exitCode() != 0:
                        raise ValueError("Regex worker exited without a successful response")
                    result = json.loads(output.data)
                    indices, matches = validate_result(result, items, sample, engine_version)
                    self._visible = [items[i] for i in indices]
                    self._matches = matches
                    self._status = engine_version + f" · {len(indices)} matching choices · maximum 64 sample matches"
                    receipt["outcome"] = "completed"
                except (ValueError, KeyError, TypeError) as error:
                    self._visible, self._matches = [], []
                    self._status = str(error)[:300]
                    receipt["outcome"] = self._status
                self.changed.emit()
            else:
                receipt["outcome"] = "superseded-or-stopped"
            process.deleteLater()
            self.busyChanged.emit()

        process.started.connect(started)
        process.readyReadStandardOutput.connect(read)
        process.readyReadStandardError.connect(lambda: abort("Unexpected regex worker diagnostics"))
        process.finished.connect(finish)
        process.errorOccurred.connect(lambda error: finish() if error == QProcess.ProcessError.FailedToStart else None)
        timer.timeout.connect(lambda: abort("Regex execution exceeded its startup/time limit"))
        timer.start(2000)
        process.start()

    def stop(self):
        self.generation += 1
        self.debounce.stop()
        for process in tuple(self.workers):
            process.kill()
        # Only finished/error acknowledgement removes an owned process.
        self.busyChanged.emit()
