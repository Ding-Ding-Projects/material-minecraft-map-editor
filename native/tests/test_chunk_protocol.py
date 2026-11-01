"""Real synthetic MCA integration through the asynchronous native controller."""

from pathlib import Path
import tempfile
import unittest

from chunk_fixture import snapshot, write_world
import test_controller as support


@unittest.skipUnless(support.Controller is not None and support.ENGINE.is_file(), "Pinned runtime and engine required")
class ChunkProtocolTests(unittest.TestCase):
    setUpClass = classmethod(support.ControllerTests.setUpClass.__func__)
    setUp = support.ControllerTests.setUp
    tearDown = support.ControllerTests.tearDown
    wait_idle = support.ControllerTests.wait_idle
    def test_real_palette_and_numeric_mca_reads_preserve_files(self):
        from PySide6.QtCore import QUrl
        for numeric in (False, True):
            with tempfile.TemporaryDirectory() as directory:
                world = Path(directory)
                write_world(world, numeric=numeric)
                before = snapshot(world)
                self.controller.openWorld(QUrl.fromLocalFile(str(world)))
                self.wait_idle()
                explorer = self.controller.explorer
                self.assertEqual(explorer.dimensionIds, ["minecraft:overworld"])
                explorer.readChunk("-1", "-1")
                self.wait_idle()
                self.assertTrue(explorer.ready, self.controller.message)
                explorer.setLocalY(2)
                explorer.selectCell(3 * 16 + 4)
                self.assertEqual(explorer.selectedBlock["world"], "-12, -62, -13")
                self.assertEqual(explorer.selectedBlock["name"], "Numeric block 5" if numeric else "minecraft:stone")
                self.assertEqual(snapshot(world), before)
                explorer.readChunk("0", "0")
                self.wait_idle()
                self.assertFalse(explorer.ready)
                self.assertIn("not stored", explorer.status)

    def test_canceled_chunk_cannot_restore_slice(self):
        from PySide6.QtCore import QUrl
        write_world(self.world)
        self.controller.openWorld(QUrl.fromLocalFile(str(self.world)))
        self.wait_idle()
        explorer = self.controller.explorer
        explorer.readChunk("-1", "-1")
        self.controller.cancel()
        self.wait_idle()
        self.assertFalse(explorer.ready)

    def test_chunk_reselection_uses_last_dispatched_tuple(self):
        from PySide6.QtCore import QUrl
        write_world(self.world)
        self.controller.openWorld(QUrl.fromLocalFile(str(self.world)))
        self.wait_idle()
        explorer = self.controller.explorer
        explorer.readChunk("-1", "-1")
        explorer.readChunk("0", "0")
        self.wait_idle()
        self.assertFalse(explorer.ready)
        self.assertIn("0, 0", explorer.status)

    def test_dimension_change_invalidates_inflight_chunk(self):
        from PySide6.QtCore import QUrl
        write_world(self.world)
        (self.world / "DIM-1" / "region").mkdir(parents=True)
        self.controller.openWorld(QUrl.fromLocalFile(str(self.world)))
        self.wait_idle()
        explorer = self.controller.explorer
        explorer.selectDimension("minecraft:overworld")
        explorer.readChunk("-1", "-1")
        explorer.selectDimension("minecraft:the_nether")
        self.wait_idle()
        self.assertEqual(explorer.dimension, "minecraft:the_nether")
        self.assertFalse(explorer.ready)


if __name__ == "__main__": unittest.main()
