"""Qt presentation model for validated, read-only chunk slices."""

from PySide6.QtCore import QObject, Property, Signal, Slot

from .chunks import ChunkRequest, coordinate, dimensions, parse_chunk
from .navigation import move_cell, reveal_cell
from .filters import SelectorFilter


class Explorer(QObject):
    changed = Signal()
    readRequested = Signal(object)
    invalidated = Signal()
    helpersChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._dimensions = []
        self._dimension = ""
        self.chunk = None
        self.section = 0
        self.local_y = 0
        self.selected = 0
        self._status = "Open a world to discover dimensions."
        self._dimension_filter = SelectorFilter(self)
        self._section_filter = SelectorFilter(self)
        self._dimension_filter.busyChanged.connect(self.helpersChanged)
        self._section_filter.busyChanged.connect(self.helpersChanged)

    @property
    def helpers_busy(self):
        return self._dimension_filter.busy or self._section_filter.busy

    @Property(QObject, constant=True)
    def dimensionFilter(self): return self._dimension_filter
    @Property(QObject, constant=True)
    def sectionFilter(self): return self._section_filter

    @Property("QStringList", notify=changed)
    def dimensionIds(self): return self._dimensions

    @Property(str, notify=changed)
    def dimension(self): return self._dimension

    @Property(str, notify=changed)
    def status(self): return self._status

    @Property("QStringList", notify=changed)
    def sectionLabels(self):
        return [f"Section {s.y} · Y {s.y * 16}…{s.y * 16 + 15}" for s in self.chunk.sections] if self.chunk else []

    @Property(int, notify=changed)
    def sectionIndex(self): return self.section

    @Property(int, notify=changed)
    def localY(self): return self.local_y

    @Property(int, notify=changed)
    def selectedCell(self): return self.selected

    @Property("QVariantList", notify=changed)
    def cells(self): return self.chunk.slice(self.section, self.local_y) if self.ready else []

    @Property(bool, notify=changed)
    def ready(self): return bool(self.chunk and self.chunk.available and self.chunk.sections)

    @Property("QVariantMap", notify=changed)
    def selectedBlock(self):
        return self.chunk.cell(self.section, self.selected % 16, self.local_y, self.selected // 16) if self.ready else {}

    @Property("QVariantMap", notify=changed)
    def inspection(self):
        # One value carries validity and its data together, so QML never mixes
        # a new ready flag with the previous selectedBlock binding.
        if not self.ready:
            return {"valid": False, "block": None, "message": "Select a decoded block"}
        return {"valid": True, "block": self.selectedBlock, "message": ""}

    @Property(str, notify=changed)
    def worldY(self): return str(self.chunk.sections[self.section].y * 16 + self.local_y) if self.ready else "Unavailable"

    def reset(self):
        self._dimensions, self._dimension = [], ""
        self._dimension_filter.set_items([])
        self.clear("Discovering region-backed dimensions…")

    def clear(self, message):
        self.chunk = None
        self.section = self.local_y = self.selected = 0
        self._status = message
        self._section_filter.set_items([])
        self.changed.emit()

    def accept_dimensions(self, result):
        self._dimensions = dimensions(result)
        self._dimension_filter.set_items(self._dimensions)
        self._dimension = self._dimensions[0] if self._dimensions else ""
        self.clear("Choose chunk coordinates and select Read chunk." if self._dimensions else "No region-backed dimensions found.")

    @Slot(str)
    def selectDimension(self, identity):
        if identity not in self._dimensions or identity == self._dimension:
            return
        self.invalidated.emit()
        self._dimension = identity
        self.clear("Dimension changed. Select Read chunk to inspect these coordinates.")

    @Slot(str, str, result=str)
    def coordinateError(self, x, z):
        try:
            coordinate(x)
            coordinate(z)
            return ""
        except ValueError:
            return "Chunk X and Z must be signed integers from -2147483648 to 2147483647."

    @Slot(str, str)
    def readChunk(self, x, z):
        try:
            request = ChunkRequest(self._dimension, coordinate(x), coordinate(z))
            if request.dimension not in self._dimensions:
                raise ValueError("Choose a discovered dimension")
        except ValueError as error:
            self.clear(str(error))
            return
        self.clear(f"Reading {request.dimension}, chunk {request.x}, {request.z}…")
        self.readRequested.emit(request)

    def accept_chunk(self, result, request):
        chunk = parse_chunk(result, request)
        if request.dimension != self._dimension:
            raise ValueError("Dimension changed during chunk inspection")
        self.chunk = chunk
        self.section = self.local_y = self.selected = 0
        self._status = (f"Chunk {request.x}, {request.z} · read-only" if chunk.sections else
                        "No decoded sections available." if chunk.available else
                        f"Chunk not stored at {request.x}, {request.z}.")
        self._section_filter.set_items(self.sectionLabels)
        self.changed.emit()

    @Slot(int)
    def selectSection(self, index):
        if self.chunk and 0 <= index < len(self.chunk.sections):
            self.section, self.local_y, self.selected = index, 0, 0
            self.changed.emit()

    @Slot(int)
    def setLocalY(self, y):
        if self.ready and 0 <= y <= 15:
            self.local_y = y
            self.changed.emit()

    @Slot(int)
    def selectCell(self, index):
        if self.ready and 0 <= index < 256:
            self.selected = index
            self.changed.emit()

    @Slot(str)
    def moveCell(self, direction):
        self.selectCell(move_cell(self.selected, direction))

    @Slot(int, float, float, float, float, result="QVariantMap")
    def revealCell(self, size, width, height, x, y):
        return reveal_cell(self.selected, size, width, height, x, y)

    def shutdown(self):
        self._dimension_filter.stop()
        self._section_filter.stop()
