import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).parents[1]
PREFERENCES_UI = ROOT / "amulet_map_editor/api/wx/ui/preferences.py"


def _language_keys(path: Path):
    return {
        line.split("=", 1)[0].strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#") and "=" in line
    }


class ScheduledSettingsUiContractTestCase(unittest.TestCase):
    def setUp(self):
        self.source = PREFERENCES_UI.read_text(encoding="utf-8")
        self.tree = ast.parse(self.source)
        self.dialog = next(
            node
            for node in self.tree.body
            if isinstance(node, ast.ClassDef) and node.name == "PreferencesDialog"
        )
        self.methods = {
            node.name: node
            for node in self.dialog.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }

    def test_native_schedule_tab_has_local_rule_editor_controls(self):
        self.assertIn("_build_schedule_tab", self.methods)
        init_source = ast.get_source_segment(self.source, self.methods["__init__"])
        self.assertIn("self._build_schedule_tab()", init_source)

        schedule_source = ast.get_source_segment(
            self.source, self.methods["_build_schedule_tab"]
        )
        for required in (
            "wx.ScrolledWindow",
            "wx.ListBox",
            "wx.TextCtrl",
            "wx.CheckBox",
            "wx.SpinCtrl",
            "schedule_every_day",
            "schedule_weekdays",
            "schedule_start_date",
            "schedule_end_date",
            "schedule_start_time",
            "schedule_end_time",
            "schedule_language",
            "schedule_theme",
            "schedule_density",
            "schedule_accent",
            "schedule_validation",
        ):
            self.assertIn(required, schedule_source)

    def test_schedule_load_save_and_invalid_storage_guard_are_wired(self):
        init_source = ast.get_source_segment(self.source, self.methods["__init__"])
        self.assertIn("schedules.load()", init_source)
        self.assertIn("ScheduleValidationError", init_source)

        save_method = self.methods["_save"]
        guarded_blocks = [
            node
            for node in save_method.body
            if isinstance(node, ast.If)
            and ast.unparse(node.test) == "self._schedule_load_error is None"
        ]
        self.assertEqual(len(guarded_blocks), 1)
        guarded_source = ast.get_source_segment(self.source, guarded_blocks[0])
        self.assertIn("schedules.replace_rules", guarded_source)
        self.assertNotIn(
            "schedules.replace_rules", self.source[: self.source.index(guarded_source)]
        )

        build_source = ast.get_source_segment(
            self.source, self.methods["_build_schedule_tab"]
        )
        self.assertIn("control.Enable(False)", build_source)
        self.assertIn('self._schedule_text("loaderror"', build_source)

    def test_rule_form_uses_domain_models_and_validated_source_metadata(self):
        form_source = ast.get_source_segment(
            self.source, self.methods["_rule_from_schedule_form"]
        )
        self.assertIn("schedules.ScheduledValues", form_source)
        self.assertIn("schedules.ScheduleRule", form_source)
        self.assertIn("schedules.ALL_WEEKDAYS", form_source)
        self.assertIn("scheduled_sources.ScheduleSource", form_source)
        self.assertIn('self.schedule_source_url.ChangeValue("")', self.source)
        lowered = self.source.lower()
        self.assertNotIn("requests.", lowered)
        self.assertNotIn("urllib.", lowered)
        self.assertIn("scheduled source url", lowered)

    def test_baseline_locales_cover_schedule_labels_and_validation(self):
        required = {
            "preferences.schedule.tab",
            "preferences.schedule.explanation",
            "preferences.schedule.weekdays",
            "preferences.schedule.everyday",
            "preferences.schedule.startdate",
            "preferences.schedule.enddate",
            "preferences.schedule.starttime",
            "preferences.schedule.endtime",
            "preferences.schedule.language",
            "preferences.schedule.theme",
            "preferences.schedule.density",
            "preferences.schedule.accent",
            "preferences.schedule.source",
            "preferences.schedule.sourceurl",
            "preferences.schedule.sourceentity",
            "preferences.schedule.sourcerefresh",
            "preferences.schedule.validationerror",
            "preferences.schedule.loaderror",
            "preferences.schedule.saveerror",
            "preferences.schedule.unapplied",
        }
        for locale in ("en.lang", "zh_TW.lang"):
            with self.subTest(locale=locale):
                keys = _language_keys(ROOT / "amulet_map_editor/lang" / locale)
                self.assertEqual(required - keys, set())


if __name__ == "__main__":
    unittest.main()
