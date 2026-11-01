from pathlib import Path
import tempfile
import unittest
from PySide6.QtCore import QCoreApplication,QSettings,QUrl
from native.amulet_native.references import ReferenceSettings


class ReferenceSettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app=QCoreApplication.instance() or QCoreApplication([])

    def test_explicit_override_does_not_rewrite_saved_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);saved=root/"saved";saved.mkdir();override=root/"override";override.mkdir()
            settings=QSettings(str(root/"settings.ini"),QSettings.Format.IniFormat)
            model=ReferenceSettings(settings,str(override))
            model.select(QUrl.fromLocalFile(str(saved)))
            self.assertEqual(model.root,str(override))
            self.assertEqual(settings.value("references/root"),str(saved))
            model.clear();self.assertEqual(model.root,str(override))
            self.assertEqual(model.engine_arguments(),["--reference-root",str(override),"--reference-profile","vanilla-java-1.20.1"])

    def test_no_default_and_nonlocal_selection_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            model=ReferenceSettings(QSettings(str(Path(directory)/"settings.ini"),QSettings.Format.IniFormat))
            self.assertEqual(model.root,"");self.assertEqual(model.engine_arguments(),[])
            model.select(QUrl("https://example.invalid/references"))
            self.assertEqual(model.root,"");self.assertIn("local",model.status)
