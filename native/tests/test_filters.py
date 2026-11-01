import unittest

from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer
from native.amulet_native.filters import SelectorFilter
from native.amulet_native.regex_worker import evaluate


class FilterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app = QCoreApplication.instance() or QCoreApplication([])

    def setUp(self): self.model = SelectorFilter()

    def tearDown(self):
        self.model.stop()
        self.model.deleteLater()
        self.app.processEvents()

    def wait_result(self):
        loop = QEventLoop()
        tick = QTimer(); tick.setInterval(10)
        tick.timeout.connect(lambda: loop.quit() if not self.model.workers and not self.model.debounce.isActive() else None)
        deadline = QTimer(); deadline.setSingleShot(True); deadline.timeout.connect(loop.quit)
        tick.start(); deadline.start(5000); loop.exec(); tick.stop(); deadline.stop()
        self.assertFalse(self.model.workers)
        self.assertFalse(self.model.debounce.isActive())

    def test_independent_query_and_actual_regex_matching(self):
        other = SelectorFilter()
        try:
            self.model.set_items(["minecraft:overworld", "minecraft:the_end"])
            other.set_items(["Section -4", "Section 0"])
            self.model.setQuery("^minecraft:.*end$")
            self.model.setRegexMode(True)
            self.model.setSample("minecraft:the_end")
            self.wait_result()
            self.assertEqual(self.model.visibleItems, ["minecraft:the_end"])
            self.assertEqual(self.model.matches[0]["end"], 17)
            self.assertEqual(other.query, "")
            self.assertEqual(other.visibleItems, ["Section -4", "Section 0"])
        finally:
            other.stop(); other.deleteLater()

    def test_invalid_expression_and_literal_insertion(self):
        self.model.set_items(["a.b", "axb"])
        self.model.setQuery("("); self.model.setRegexMode(True); self.wait_result()
        self.assertEqual(self.model.visibleItems, [])
        self.assertIn("unterminated", self.model.status)
        self.model.setQuery(""); self.model.insertLiteral("a.b"); self.wait_result()
        self.assertEqual(self.model.visibleItems, ["a.b"])

    def test_expensive_expression_is_killed(self):
        self.model.setQuery("(a+)+$")
        self.model.setSample("a" * 4095 + "!")
        self.model.setRegexMode(True)
        self.wait_result()
        self.assertIn("limit", self.model.status)

    def test_worker_bounds_and_flags(self):
        result = evaluate({"pattern": "^A", "sample": "a\na", "items": ["a"], "ignoreCase": True, "multiline": True})
        self.assertEqual(len(result["matches"]), 2)
        with self.assertRaises(ValueError): evaluate({"pattern": "a" * 513, "sample": "", "items": []})
