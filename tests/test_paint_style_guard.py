"""Guard against the black-flash regression: a window that paints itself in
``EVT_PAINT`` but never asks for ``wx.BG_STYLE_PAINT`` gets erased by the
system brush immediately before its own paint handler runs.  On a dark theme
that erase is black, and because it happens on every repaint -- not just the
first one -- it reads as a random flash across whatever surface forgot it.

This scans the real source tree (not a fixture) so it catches the next widget
that adds ``EVT_PAINT`` and forgets the other half, not just the six that were
found and fixed once.
"""

from __future__ import annotations

import ast
import os
import sys
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

PACKAGE_ROOT = os.path.join(REPO_ROOT, "amulet_map_editor")

# ``_Interactive`` is a mixin: it binds EVT_PAINT and stubs the erase in
# ``_bind_interaction``, but the paint-style declaration lives in whichever
# concrete subclass calls ``self._install(...)`` before that -- every real
# subclass does (verified by hand), so the mixin itself is not the place the
# declaration can appear.
MIXIN_EXEMPTIONS = frozenset({"_Interactive"})


def _iter_source_files():
    for dirpath, _dirnames, filenames in os.walk(PACKAGE_ROOT):
        for name in filenames:
            if name.endswith(".py"):
                yield os.path.join(dirpath, name)


def _binds_self_evt_paint(node: ast.ClassDef) -> bool:
    """True if ``node`` binds ``EVT_PAINT`` on its own window (``self``)."""
    for call in ast.walk(node):
        if not isinstance(call, ast.Call):
            continue
        func = call.func
        if not (isinstance(func, ast.Attribute) and func.attr == "Bind"):
            continue
        if not (isinstance(func.value, ast.Name) and func.value.id == "self"):
            continue
        if not call.args:
            continue
        first = call.args[0]
        if (
            isinstance(first, ast.Attribute)
            and first.attr == "EVT_PAINT"
            and isinstance(first.value, ast.Name)
            and first.value.id == "wx"
        ):
            return True
    return False


def _classes_binding_self_paint(source: str, path: str):
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError:  # pragma: no cover - not expected in this tree
        return
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and _binds_self_evt_paint(node):
            yield node


class PaintStyleGuardTest(unittest.TestCase):
    """Every class that paints itself opts out of the default GDI erase."""

    def test_self_painting_classes_declare_paint_style_and_stub_erase(self):
        offenders = []
        for path in _iter_source_files():
            with open(path, "r", encoding="utf-8") as handle:
                source = handle.read()
            if "EVT_PAINT" not in source:
                continue
            for node in _classes_binding_self_paint(source, path):
                if node.name in MIXIN_EXEMPTIONS:
                    continue
                segment = ast.get_source_segment(source, node) or ""
                declares_paint_style = (
                    "BG_STYLE_PAINT" in segment or "self._install(" in segment
                )
                stubs_erase = "EVT_ERASE_BACKGROUND" in segment
                if not (declares_paint_style and stubs_erase):
                    offenders.append(
                        (
                            os.path.relpath(path, REPO_ROOT),
                            node.name,
                            declares_paint_style,
                            stubs_erase,
                        )
                    )
        self.assertEqual(
            offenders,
            [],
            "Classes that bind EVT_PAINT on themselves must also set "
            "wx.BG_STYLE_PAINT (directly or via _Themed._install) and stub "
            "EVT_ERASE_BACKGROUND, or the system erase flashes before the "
            "paint handler ever runs: " + repr(offenders),
        )

    def test_guard_actually_fails_on_a_reverted_class(self):
        """Prove the scanner above is not vacuously true.

        A class shaped exactly like the real regression -- EVT_PAINT bound,
        no paint-style declaration, no erase stub -- must be caught.
        """
        broken_source = (
            "import wx\n\n"
            "class _Regressed(wx.Panel):\n"
            "    def __init__(self, parent):\n"
            "        super().__init__(parent)\n"
            "        self.Bind(wx.EVT_PAINT, self._on_paint)\n\n"
            "    def _on_paint(self, event):\n"
            "        pass\n"
        )
        classes = list(_classes_binding_self_paint(broken_source, "<probe>"))
        self.assertEqual(len(classes), 1)
        segment = ast.get_source_segment(broken_source, classes[0]) or ""
        declares_paint_style = (
            "BG_STYLE_PAINT" in segment or "self._install(" in segment
        )
        stubs_erase = "EVT_ERASE_BACKGROUND" in segment
        self.assertFalse(declares_paint_style)
        self.assertFalse(stubs_erase)

        fixed_source = (
            "import wx\n\n"
            "class _Fixed(wx.Panel):\n"
            "    def __init__(self, parent):\n"
            "        super().__init__(parent)\n"
            "        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)\n"
            "        self.Bind(wx.EVT_PAINT, self._on_paint)\n"
            "        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda e: None)\n\n"
            "    def _on_paint(self, event):\n"
            "        pass\n"
        )
        fixed_classes = list(_classes_binding_self_paint(fixed_source, "<probe>"))
        self.assertEqual(len(fixed_classes), 1)
        fixed_segment = ast.get_source_segment(fixed_source, fixed_classes[0]) or ""
        self.assertTrue(
            "BG_STYLE_PAINT" in fixed_segment or "self._install(" in fixed_segment
        )
        self.assertTrue("EVT_ERASE_BACKGROUND" in fixed_segment)


if __name__ == "__main__":
    unittest.main()
