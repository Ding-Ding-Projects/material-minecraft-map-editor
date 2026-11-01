"""Exercise QML destruction callbacks without any GUI or desktop surface."""

from pathlib import Path
import unittest

try:
    from PySide6.QtCore import QCoreApplication, QObject, QUrl, Slot, qInstallMessageHandler
    from PySide6.QtQml import QQmlApplicationEngine
    from shiboken6 import delete, isValid
    from native.amulet_native.controller import Controller
    from native.amulet_native.lifetime import destroy_presentation
except ImportError:
    QQmlApplicationEngine = None


if QQmlApplicationEngine is not None:
    class Recorder(QObject):
        def __init__(self):
            super().__init__()
            self.values = []

        @Slot(str)
        def record(self, text):
            self.values.append(text)


@unittest.skipUnless(QQmlApplicationEngine is not None, "Pinned Qt runtime required")
class LifetimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def setUp(self):
        self.messages = []
        self.previous = qInstallMessageHandler(lambda kind, context, message: self.messages.append(message))
        self.backend = Controller(Path("nonexistent-engine"))
        self.recorder = Recorder()
        self.engine = QQmlApplicationEngine()
        self.engine.rootContext().setContextProperty("backend", self.backend)
        self.engine.rootContext().setContextProperty("recorder", self.recorder)
        self.engine.loadData(b'''
import QtQml
QtObject {
    property string observed: backend.message
    Component.onDestruction: recorder.record(backend.message)
}
''', QUrl("lifetime-fixture.qml"))
        self.assertEqual(len(self.engine.rootObjects()), 1)

    def tearDown(self):
        if isValid(self.engine):
            destroy_presentation(self.engine, self.backend)
        elif isValid(self.backend):
            delete(self.backend)
        delete(self.recorder)
        qInstallMessageHandler(self.previous)

    def test_backend_survives_root_and_engine_destruction(self):
        expected = self.backend.message
        order = []
        self.engine.rootObjects()[0].destroyed.connect(lambda: order.append("root"))
        self.engine.destroyed.connect(lambda: order.append("engine"))
        self.backend.destroyed.connect(lambda: order.append("backend"))
        destroy_presentation(self.engine, self.backend)
        self.assertEqual(order, ["root", "engine", "backend"])
        self.assertEqual(self.recorder.values, [expected])
        self.assertEqual(self.messages, [])

    def test_old_backend_first_order_reproduces_null_binding(self):
        delete(self.backend)
        self.assertTrue(any("null" in message and "message" in message for message in self.messages),
                        self.messages)
        # This deliberately broken order is the negative regression only.
        # Production always calls destroy_presentation with a live backend.


if __name__ == "__main__":
    unittest.main()
