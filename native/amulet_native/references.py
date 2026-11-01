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
        self._ready = False

    @Property(str, notify=changed)
    def root(self): return self.override if self.override is not None else self.saved

    @Property(str, notify=changed)
    def status(self): return self._status

    @Property(bool, notify=changed)
    def ready(self): return self._ready

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
        self._ready = False
        self.settings.setValue("references/root", selected)
        self._status = ("Saved for the next launch; the explicit startup override remains active."
                        if self.overridden else "Selected directory. Engine verification pending.")
        self.changed.emit()
        if not self.overridden:
            self.effectiveChanged.emit()

    @Slot()
    def clear(self):
        self.saved = ""
        self._ready = False
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
        self._ready = False
        self._status = str(message)[:500]
        self.changed.emit()

    def accept_summary(self, summary):
        from .terrain_scene import REGISTRY,SHAPE_HASH,CAPABILITY
        self._ready = False
        if not isinstance(summary,dict):
            self.report("Engine reference validation is not acknowledged.");return False
        if summary.get("status") == "unavailable":
            self.report("Geometry unavailable: " + str(summary.get("reasonCode","unspecified"))[:128]);return False
        if (set(summary)!={'status','profile','dataVersion','registry','shapeEvidenceSha256','availableGeometryEvidence'}
                or summary['status']!='ready' or summary['profile']!='vanilla-java-1.20.1'
                or type(summary['dataVersion']) is not int or summary['dataVersion']!=3465
                or summary['registry']!=REGISTRY or type(summary['registry'].get('schemaVersion')) is not int
                or summary['shapeEvidenceSha256']!=SHAPE_HASH or summary['availableGeometryEvidence']!=[CAPABILITY]):
            self.report("Engine reference acknowledgement does not match the pinned profile.");return False
        self._ready=True
        self._status="Engine verified the pinned membership reports and shape evidence. Opaque material behavior is not verified."
        self.changed.emit();return True
