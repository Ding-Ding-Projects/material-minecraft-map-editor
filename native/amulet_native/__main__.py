"""Launch with python -m native.amulet_native from the repository root."""

import os
from pathlib import Path
import sys

from PySide6.QtCore import QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine

from .controller import Controller
from .lifetime import destroy_presentation


def main():
    os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Material")
    application = QGuiApplication(sys.argv)
    application.setApplicationName("Material Minecraft Map Editor")
    application.setOrganizationName("MaterialMapEditor")
    root = Path(__file__).resolve().parents[2]
    executable = "material-world-engine.exe" if sys.platform == "win32" else "material-world-engine"
    controller = Controller(root / "engine" / "target" / "debug" / executable)
    engine = QQmlApplicationEngine()
    try:
        engine.rootContext().setContextProperty("backend", controller)
        engine.load(QUrl.fromLocalFile(str(Path(__file__).parent / "qml" / "Main.qml")))
        if not engine.rootObjects():
            return 1
        return application.exec()
    finally:
        # QML bindings and destruction handlers still use the controller.
        # Release presentation first, including the failed-load path.
        destroy_presentation(engine, controller)


if __name__ == "__main__":
    raise SystemExit(main())
