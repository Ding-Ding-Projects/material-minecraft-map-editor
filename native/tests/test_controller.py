"""QCoreApplication-only integration, no desktop or window creation."""

import gzip
from pathlib import Path
import struct
import sys
import tempfile
import unittest

try:
    from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer, QUrl
    from native.amulet_native.controller import Controller
except ImportError:
    Controller = None

ROOT = Path(__file__).resolve().parents[2]
ENGINE = ROOT / "engine" / "target" / "debug" / (
    "material-world-engine.exe" if sys.platform == "win32" else "material-world-engine")


@unittest.skipUnless(Controller is not None and ENGINE.is_file(), "Pinned Qt runtime and built engine required")
class ControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.world = Path(self.directory.name)
        # Root compound > Data compound > DataVersion int > two END tags.
        nbt = b"\x0a\x00\x00\x0a\x00\x04Data\x03\x00\x0bDataVersion" + struct.pack(">i", 1343) + b"\x00\x00"
        self.payload = gzip.compress(nbt)
        (self.world / "level.dat").write_bytes(self.payload)
        self.controller = Controller(ENGINE)

    def tearDown(self):
        if self.controller.busy:
            self.controller.cancel()
            self.wait_idle()
        self.controller.deleteLater()
        self.app.processEvents()
        self.directory.cleanup()

    def wait_idle(self):
        loop = QEventLoop()
        poll = QTimer()
        poll.setInterval(10)
        poll.timeout.connect(lambda: loop.quit() if not self.controller.busy else None)
        deadline = QTimer()
        deadline.setSingleShot(True)
        deadline.timeout.connect(loop.quit)
        poll.start()
        deadline.start(10000)
        loop.exec()
        poll.stop()
        deadline.stop()
        self.assertFalse(self.controller.busy, "Engine did not acknowledge stopping")

    def test_real_probe_preserves_world(self):
        self.controller.openWorld(QUrl.fromLocalFile(str(self.world)))
        self.wait_idle()
        self.assertEqual(self.controller.state, "result")
        self.assertEqual(self.controller.facts["dataVersion"], "1343")
        self.assertEqual((self.world / "level.dat").read_bytes(), self.payload)
        self.assertEqual(sorted(p.name for p in self.world.iterdir()), ["level.dat"])

    def test_cancel_while_process_starting(self):
        self.controller.openWorld(QUrl.fromLocalFile(str(self.world)))
        self.controller.cancel()
        self.wait_idle()
        self.assertEqual(self.controller.state, "empty")

    def test_reselection_invalidates_previous_request(self):
        self.controller.openWorld(QUrl.fromLocalFile(str(self.world)))
        self.controller.openWorld(QUrl.fromLocalFile(str(self.world)))
        self.wait_idle()
        self.assertEqual(self.controller.generation, 2)
        self.assertEqual(self.controller.state, "result")

    def test_close_waits_for_child_stop(self):
        closed = []
        self.controller.closeReady.connect(lambda: closed.append(not self.controller.busy))
        self.controller.openWorld(QUrl.fromLocalFile(str(self.world)))
        self.controller.requestClose()
        self.wait_idle()
        self.assertEqual(closed, [True])

    def test_failed_start_reports_visible_explorer_state(self):
        invalid = self.world / "invalid-engine.exe"
        invalid.write_bytes(b"not an executable")
        self.controller.engine_path = invalid
        self.controller.openWorld(QUrl.fromLocalFile(str(self.world)))
        self.wait_idle()
        self.assertEqual(self.controller.state, "unsupported")
        self.assertEqual(self.controller.explorer.status, self.controller.message)
        self.assertFalse(self.controller.explorer.ready)

    def test_early_exit_reports_visible_explorer_state(self):
        self.controller.engine_path = Path(sys.executable)
        self.controller.openWorld(QUrl.fromLocalFile(str(self.world)))
        owned_child = self.controller.process
        owned_child.closeWriteChannel()
        self.wait_idle()
        self.assertEqual(self.controller.state, "unsupported")
        self.assertEqual(self.controller.explorer.status, self.controller.message)
        self.assertIn("before a complete response", self.controller.explorer.status)


if __name__ == "__main__":
    unittest.main()
