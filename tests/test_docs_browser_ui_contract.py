"""Static contract checks for the native offline documentation surface."""

from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
UI = (ROOT / "amulet_map_editor/api/wx/ui/documentation.py").read_text(encoding="utf-8")
FRAME = (ROOT / "amulet_map_editor/api/framework/amulet_ui.py").read_text(
    encoding="utf-8"
)


class DocumentationUiContractTestCase(unittest.TestCase):
    def test_native_dialog_has_search_and_article_navigation(self):
        for marker in (
            "class DocumentationDialog",
            "self.query",
            "self.regex",
            "self.article_view",
            "amulet://article/",
            "load_bundled_articles",
        ):
            self.assertIn(marker, UI)

    def test_documentation_is_reachable_from_menu_and_palette(self):
        self.assertIn('"Documentation…": self._open_documentation', FRAME)
        self.assertIn('("Documentation…", self._open_documentation)', FRAME)

    def test_browser_does_not_fetch_remote_content(self):
        self.assertNotIn("requests.", UI)
        self.assertNotIn("urllib.", UI)
        self.assertIn(
            "External links are not fetched",
            (ROOT / "docs/features/offline-documentation/README.md").read_text(
                encoding="utf-8"
            ),
        )

    def test_documentation_chrome_uses_persisted_language_modes_and_resources(self):
        for marker in (
            "preferences.load().language_mode",
            "_copy(\"title\", self._language_mode)",
            "documentation.en.title",
            "documentation.zh.title",
            "if mode == \"bilingual\"",
        ):
            self.assertIn(marker, UI if "documentation." not in marker else UI + (ROOT / "amulet_map_editor/lang/en.lang").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
