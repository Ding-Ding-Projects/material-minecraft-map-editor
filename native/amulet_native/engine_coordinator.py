"""One explicit owner and lease for the native engine child."""

from PySide6.QtCore import QObject, QProcess, Signal


class EngineCoordinator(QObject):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.process = None
        self.owner = None

    @property
    def busy(self): return self.process is not None

    def acquire(self, owner):
        if self.process is not None:
            raise RuntimeError("Engine lease is already held")
        self.process = QProcess(self)
        self.owner = owner
        self.changed.emit()
        return self.process

    def release(self, owner, process):
        if self.process is not process or self.owner is not owner:
            raise RuntimeError("Engine lease identity mismatch")
        if process.state() != QProcess.ProcessState.NotRunning:
            raise RuntimeError("Engine exit is not yet acknowledged")
        self.process, self.owner = None, None
        process.deleteLater()
        self.changed.emit()
