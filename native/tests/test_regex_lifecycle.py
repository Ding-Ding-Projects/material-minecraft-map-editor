import json
import os
from pathlib import Path
import unittest

from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer, QUrl
from native.amulet_native.controller import Controller
from native.amulet_native.filters import SelectorFilter
from native.amulet_native.regex_runtime import WorkerOutput, direct_interpreter, validate_result
from process_snapshot import snapshot, descendants
import test_controller as support

OWNERSHIP_RECEIPTS = []


def wait_for(predicate, milliseconds=4000):
    if predicate(): return
    loop = QEventLoop()
    poll = QTimer(); poll.setInterval(5)
    poll.timeout.connect(lambda: loop.quit() if predicate() else None)
    deadline = QTimer(); deadline.setSingleShot(True); deadline.timeout.connect(loop.quit)
    poll.start(); deadline.start(milliseconds); loop.exec(); poll.stop(); deadline.stop()
    if not predicate(): raise AssertionError("Owned worker acknowledgement timed out")


@unittest.skipUnless(os.name == "nt", "Native Windows process ownership receipt required")
class RegexOwnershipTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app = QCoreApplication.instance() or QCoreApplication([])

    def setUp(self): self.model = SelectorFilter()

    def tearDown(self):
        self.model.stop()
        wait_for(lambda: not self.model.busy)
        self.model.deleteLater(); self.app.processEvents()

    def start_expensive(self, model):
        model.setQuery("(a+)+$")
        model.setSample("a" * 4095 + "!")
        model.setRegexMode(True)
        wait_for(lambda: bool(model.receipts and model.receipts[-1]["verified"]))
        receipt = model.receipts[-1]
        self.assertEqual(receipt["qprocessPid"], receipt["evaluatorPid"])
        tree = snapshot()
        self.assertIn(receipt["evaluatorPid"], tree)
        self.assertEqual(descendants(receipt["evaluatorPid"], tree), set())
        return receipt

    def assert_stopped_receipt(self, receipt):
        self.assertTrue(receipt["stopAcknowledged"])
        tree = snapshot()
        self.assertNotIn(receipt["evaluatorPid"], tree)
        self.assertEqual(descendants(receipt["evaluatorPid"], tree), set())
        OWNERSHIP_RECEIPTS.append(dict(receipt, absentAfterStop=True, descendantsAfterStop=0))

    def test_timeout_stops_exact_evaluator_without_descendants(self):
        receipt = self.start_expensive(self.model)
        wait_for(lambda: not self.model.busy)
        self.assertIn("limit", self.model.status)
        self.assert_stopped_receipt(receipt)

    def test_supersede_stops_evaluator_before_next_result(self):
        receipt = self.start_expensive(self.model)
        self.model.setQuery("^stone$")
        self.model.setSample("stone")
        wait_for(lambda: not self.model.busy)
        self.assertEqual(self.model.matches[0]["text"], "stone")
        self.assert_stopped_receipt(receipt)
        self.assert_stopped_receipt(self.model.receipts[-1])

    def test_close_waits_for_both_selectors_and_engine(self):
        controller = Controller(support.ENGINE)
        closed = []
        controller.closeReady.connect(lambda: closed.append(not controller.busy))
        try:
            first = self.start_expensive(controller.explorer.dimensionFilter)
            second = self.start_expensive(controller.explorer.sectionFilter)
            controller.openWorld(QUrl.fromLocalFile(str(Path(__file__).parent)))
            controller.requestClose()
            wait_for(lambda: bool(closed))
            self.assertEqual(closed, [True])
            self.assertFalse(controller.busy)
            self.assert_stopped_receipt(first)
            self.assert_stopped_receipt(second)
        finally:
            controller.requestClose()
            wait_for(lambda: not controller.busy)
            controller.deleteLater(); self.app.processEvents()

    def test_cancel_close_does_not_emit_close_when_worker_finishes(self):
        controller = Controller(support.ENGINE)
        closed = []
        controller.closeReady.connect(lambda: closed.append(True))
        try:
            receipt = self.start_expensive(controller.explorer.dimensionFilter)
            controller.requestClose()
            self.assertFalse(closed)
            controller.cancelClose()
            wait_for(lambda: not controller.busy)
            self.assertEqual(closed, [])
            self.assert_stopped_receipt(receipt)
            controller.requestClose()
            self.assertEqual(closed, [True])
        finally:
            controller.requestClose(); wait_for(lambda: not controller.busy)
            controller.deleteLater(); self.app.processEvents()


class RegexProtocolTests(unittest.TestCase):
    def test_final_drain_uses_cumulative_output_bound(self):
        output = WorkerOutput()
        output.append(b"{}\n")
        output.take_hello()
        output.append(b"x" * (65536 - 3))
        with self.assertRaises(ValueError): output.append(b"x")

    def test_complete_result_schema_rejects_corruption(self):
        version = "Python re 3.11.9"
        valid = {"indices": [0], "matches": [{"start": 0, "end": 1, "text": "a"}], "engine": version}
        self.assertEqual(validate_result(valid, ["a"], "a", version)[0], [0])
        for updates in ({"indices": [True]}, {"indices": [0, 0]}, {"matches": [None]},
                        {"matches": [{"start": 0, "end": 2, "text": "a"}]},
                        {"matches": [{"start": 0, "end": 1, "text": "wrong"}]},
                        {"engine": "other"}, {"unexpected": 1}):
            with self.assertRaises(ValueError): validate_result(dict(valid, **updates), ["a"], "a", version)
