import unittest

from PySide6.QtCore import QCoreApplication
from native.amulet_native.chunks import ChunkRequest
from native.amulet_native.explorer import Explorer
from test_chunks import palette_result


class InspectionSnapshotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app = QCoreApplication.instance() or QCoreApplication([])

    def test_every_transition_has_complete_or_explicitly_invalid_snapshot(self):
        explorer = Explorer()
        snapshots = [explorer.inspection]
        explorer.changed.connect(lambda: snapshots.append(explorer.inspection))
        request = ChunkRequest("minecraft:overworld", -1, -1)
        explorer.accept_dimensions({"readOnly": True, "dimensions": [{"id": request.dimension, "readOnly": True}]})
        explorer.accept_chunk(palette_result(), request)
        explorer.selectCell(255)
        explorer.setLocalY(15)
        explorer.clear("Reading another chunk")
        explorer.accept_chunk(palette_result(), request)
        explorer.accept_chunk({"dimension": request.dimension, "chunkX": -1, "chunkZ": -1,
                               "readOnly": True, "available": False}, request)
        self.assertTrue(any(s["valid"] for s in snapshots))
        self.assertFalse(snapshots[-1]["valid"])
        for state in snapshots:
            self.assertEqual(set(state), {"valid", "block", "message"})
            if state["valid"]:
                block = state["block"]
                for field in ("name", "world", "local", "dimension", "chunk", "dataVersion"):
                    self.assertIsInstance(block[field], str)
                self.assertIsInstance(block["properties"], list)
                self.assertEqual(state["message"], "")
            else:
                self.assertIsNone(state["block"])
                self.assertEqual(state["message"], "Select a decoded block")
        # Old snapshots are retained values, not a mutable alias to new state.
        valid = next(s for s in snapshots if s["valid"])
        self.assertEqual(valid["block"]["world"], "-16, -64, -16")
        explorer.shutdown(); explorer.deleteLater(); self.app.processEvents()
