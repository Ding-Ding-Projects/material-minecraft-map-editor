"""Launch with python -m native.amulet_native from the repository root."""

import os
import argparse
from pathlib import Path
import sys

from PySide6.QtCore import QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine

from .controller import Controller
from .lifetime import destroy_presentation


def main():
    arguments = argparse.ArgumentParser(description="Native read-only world workspace")
    arguments.add_argument("--reference-root", help="Explicit absolute local reference directory for this launch")
    options, qt_arguments = arguments.parse_known_args()
    if options.reference_root is not None and not Path(options.reference_root).is_absolute():
        arguments.error("--reference-root must be an absolute directory")
    os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Material")
    application = QGuiApplication([sys.argv[0], *qt_arguments])
    application.setApplicationName("Material Minecraft Map Editor")
    application.setOrganizationName("MaterialMapEditor")
    root = Path(__file__).resolve().parents[2]
    executable = "material-world-engine.exe" if sys.platform == "win32" else "material-world-engine"
    controller = Controller(root / "engine" / "target" / "debug" / executable, options.reference_root)
    engine = QQmlApplicationEngine()
    try:
        engine.rootContext().setContextProperty("backend", controller)
        engine.load(QUrl.fromLocalFile(str(Path(__file__).parent / "qml" / "Main.qml")))
        if not engine.rootObjects():
            return 1
        controller.terrain.attach_window(engine.rootObjects()[0])
        return application.exec()
    finally:
        # QML bindings and destruction handlers still use the controller.
        # Release presentation first, including the failed-load path.
        destroy_presentation(engine, controller)


if __name__ == "__main__":
    raise SystemExit(main())
