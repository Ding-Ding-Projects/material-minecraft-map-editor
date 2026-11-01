"""Explicit local reference selection, never world-derived discovery."""

from pathlib import Path
from PySide6.QtCore import QObject, Property, Signal, Slot, QUrl


class ReferenceSettings(QObject):
    changed = Signal()
    effectiveChanged = Signal()

    def __init__(self, settings, override=None, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.override = override
        self.saved = settings.value("references/root", "", type=str)
        self._status = "Engine verification pending." if self.root else "Select a reference directory to enable verified geometry."

    @Property(str, notify=changed)
    def root(self): return self.override if self.override is not None else self.saved

    @Property(str, notify=changed)
    def status(self): return self._status

    @Property(bool, constant=True)
    def overridden(self): return self.override is not None

    @Slot(QUrl)
    def select(self, url):
        try:
            if not url.isLocalFile():
                raise ValueError("Select a local reference directory.")
            path = Path(url.toLocalFile())
            if not path.is_absolute() or not path.is_dir():
                raise ValueError("Reference directory must exist and be absolute.")
            selected = str(path.resolve(strict=True))
        except (ValueError, OSError) as error:
            self._status = str(error)
            self.changed.emit()
            return
        self.saved = selected
        self.settings.setValue("references/root", selected)
        self._status = ("Saved for the next launch; the explicit startup override remains active."
                        if self.overridden else "Selected directory. Engine verification pending.")
        self.changed.emit()
        if not self.overridden:
            self.effectiveChanged.emit()

    @Slot()
    def clear(self):
        self.saved = ""
        self.settings.remove("references/root")
        self._status = ("Saved selection cleared; startup override remains active." if self.overridden
                        else "No reference directory selected. Slice inspection remains available.")
        self.changed.emit()
        if not self.overridden:
            self.effectiveChanged.emit()

    def engine_arguments(self):
        if not self.root:
            return []
        path = Path(self.root)
        if not path.is_absolute():
            raise ValueError("Configured reference root is not absolute.")
        return ["--reference-root", str(path), "--reference-profile", "vanilla-java-1.20.1"]

    def report(self, message):
        self._status = str(message)[:500]
        self.changed.emit()
