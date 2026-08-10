"""The command palette indexes every surface on the site.

This replaced a guard that asserted the palette scraped the DOM from app.js:

    assert "querySelectorAll('#feature-grid .feature-card')" in APP

That pinned one implementation and actively forbade a better one. The palette
now collects from ``AmuletSite.paletteSources()``: each module registers its own
entries, so the palette holds no second copy of the inventory and cannot drift
from what is actually on the page. The contract it was protecting -- everything
is findable, and choosing a result teleports to the surface that owns it -- is
unchanged, so that is what is checked here.
"""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "docs" / "site"

#: Hand-written on purpose. "Every module that registers a source registers a
#: valid one" passes on a site where nothing registers anything, so the
#: enumeration is what makes a whole category going missing fail. Each entry is
#: (file, what it must contribute).
REQUIRED_SOURCES = (
    ("tabs.js", "every tab"),
    ("panels.js", "features, articles, and captures"),
    ("settings-panel.js", "every setting"),
    ("notifications.js", "the notification commands"),
)


class SitePaletteInventoryContractTests(unittest.TestCase):
    def setUp(self):
        self.palette = (SITE / "palette.js").read_text(encoding="utf-8")

    def test_every_owning_module_registers_its_own_palette_entries(self):
        for filename, contribution in REQUIRED_SOURCES:
            with self.subTest(module=filename, contributes=contribution):
                source = (SITE / filename).read_text(encoding="utf-8")
                # The call, not the bare name: a substring check is satisfied by
                # `registerPaletteSourceX`, so renaming the call away left this
                # passing on a module that had stopped registering anything.
                self.assertIn(
                    "registerPaletteSource(",
                    source,
                    f"{filename} contributes {contribution} to the palette and "
                    "must register it, or those results silently disappear",
                )

    def test_the_palette_collects_from_the_registry_rather_than_its_own_copy(self):
        self.assertIn(
            "paletteSources()",
            self.palette,
            "the palette must read the shared registry; a second inventory of "
            "its own is exactly what drifts from the page",
        )
        # A hard-coded scrape would reintroduce the drift this design removed.
        self.assertNotIn("#feature-grid .feature-card", self.palette)
        self.assertNotIn("#settings-grid .setting-card", self.palette)

    def test_choosing_a_result_teleports_to_the_owning_surface(self):
        for marker in ("scrollIntoView", "focus("):
            with self.subTest(behaviour=marker):
                self.assertIn(
                    marker,
                    self.palette,
                    "a palette result must reveal and focus the thing it names, "
                    "not merely switch tabs and leave the reader hunting",
                )

    def test_the_shortcut_and_the_listbox_semantics_are_present(self):
        self.assertIn("shiftKey", self.palette)
        self.assertIn("aria-activedescendant", self.palette)
        index = (SITE / "index.html").read_text(encoding="utf-8")
        self.assertIn('role="listbox"', index)
        self.assertIn('id="palette-results"', index)


if __name__ == "__main__":
    unittest.main()
