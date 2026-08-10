#!/usr/bin/env python3
"""Fail-closed static validator for the Material 3 completion overlay."""

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
import sys


REQUIRED = (
    "amulet_map_editor/api/material_menu.py",
    "amulet_map_editor/api/wx/material3.py",
    "amulet_map_editor/api/wx/components.py",
    "amulet_map_editor/api/framework/amulet_ui.py",
    "tests/test_material_menu.py",
    "tests/test_m3_completion_contract.py",
    "tests/test_material3_global_contract.py",
)


def validate(repo: Path) -> list[str]:
    errors: list[str] = []
    for relative in REQUIRED:
        path = repo / relative
        if not path.is_file():
            errors.append(f"missing required file: {relative}")
            continue
        if path.suffix == ".py":
            try:
                ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            except (SyntaxError, UnicodeError) as error:
                errors.append(f"invalid Python in {relative}: {error}")

    material3 = repo / "amulet_map_editor/api/wx/material3.py"
    if material3.is_file():
        source = material3.read_text(encoding="utf-8")
        checks = {
            "one preferences.load call": source.count("preferences.load()") == 1,
            "one scheduled-runtime read": source.count(
                "scheduled_runtime.current_values()"
            )
            == 1,
            "one element-override read": source.count("load_overrides()") == 1,
            "iterative window traversal": "stack: list[wx.Window] = [window]" in source,
            "no recursive application": "apply_material3(child)" not in source,
            "immutable pass context": "class MaterialThemeContext" in source,
            "single root layout": source.count("window.Layout()") == 1,
            "system appearance support": "wx.SystemSettings.GetAppearance()" in source,
            "system theme resolution": "theme = _resolve_theme(" in source,
            "live system-colour refresh": "wx.EVT_SYS_COLOUR_CHANGED" in source,
            "non-recursive custom best size": "natural_height: int = 0" in source,
            "deferred theme compatibility": "def apply_material3_deferred" in source,
        }
        errors.extend(name for name, passed in checks.items() if not passed)

    components = repo / "amulet_map_editor/api/wx/components.py"
    if components.is_file():
        source = components.read_text(encoding="utf-8")
        checks = {
            "MaterialMenu popup": "class MaterialMenu(wx.PopupTransientWindow)" in source,
            "MaterialSearchField": "class MaterialSearchField" in source,
            "capture-loss recovery": "wx.EVT_MOUSE_CAPTURE_LOST" in source,
            "key-up activation": "wx.EVT_KEY_UP" in source,
            "Windows popup focus style": "PU_CONTAINS_CONTROLS" in source,
            "no native menu construction": "wx.Menu(" not in source,
            "explicit focus restoration": "_restore_focus_if_live" in source,
            "dynamic label relayout": "parent.Layout()" in source,
            "best-size recursion absent": "_control_min_height(self)" not in source,
        }
        errors.extend(name for name, passed in checks.items() if not passed)

    amulet_ui = repo / "amulet_map_editor/api/framework/amulet_ui.py"
    if amulet_ui.is_file():
        source = amulet_ui.read_text(encoding="utf-8")
        try:
            start = source.index("    def create_menu(self):")
            end = source.index("    def _open_preferences", start)
            menu = source[start:end]
        except ValueError:
            errors.append("could not locate AmuletUI.create_menu")
        else:
            checks = {
                "integration patch marker": "BEGIN CODEX MATERIAL 3 COMMAND MENU" in menu,
                "MaterialMenuItem integration": "MaterialMenuItem(" in menu,
                "MaterialMenu integration": "MaterialMenu(" in menu,
                "native command menu removed": "wx.Menu(" not in menu,
                "overlap guard": "_scheduled_refresh_thread" in source,
            }
            errors.extend(name for name, passed in checks.items() if not passed)

    global_contract = repo / "tests/test_material3_global_contract.py"
    if global_contract.is_file():
        source = global_contract.read_text(encoding="utf-8")
        checks = {
            "stale direct deferred assertion removed": (
                "wx.CallAfter(apply_material3, window)" not in source
                and "wx.CallLater(100, apply_material3, window)" not in source
            ),
            "deferred helper contract retained": (
                'assert "apply_material3_deferred" in source' in source
                and 'assert "apply_material3_deferred(window)" in source' in source
            ),
        }
        errors.extend(name for name, passed in checks.items() if not passed)
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    repo = args.repo.resolve()
    errors = validate(repo)
    payload = {
        "repo": str(repo),
        "status": "pass" if not errors else "fail",
        "errors": errors,
    }
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    elif errors:
        print("Material 3 completion validation failed:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
    else:
        print("Material 3 completion static validation passed")
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
