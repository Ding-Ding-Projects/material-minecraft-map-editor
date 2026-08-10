#!/usr/bin/env python3
"""Run the evidence gates available without a Windows wxPython runtime."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile

FIXTURE = """from __future__ import annotations
import threading
import wx
from amulet_map_editor.api.wx.components import MaterialButton

class AmuletUI:
    def __init__(self):
        self._command_menus: list[wx.Menu] = []
        self._scheduled_runtime = scheduled_runtime.ScheduledRuntimeController(
            on_state=self._apply_scheduled_runtime_state
        )
        self._scheduled_timer = wx.CallLater(1000, self._refresh_scheduled_runtime)

    def _refresh_scheduled_runtime(self) -> None:
        if self.IsBeingDeleted():
            return
        prefs = school_mode.presentation_preferences(preferences.load())
        base = {
            key: getattr(prefs, key)
            for key in ("language_mode", "theme", "density", "accent")
        }
        threading.Thread(
            target=self._scheduled_runtime.refresh,
            args=(base,),
            name="amulet-scheduled-settings",
            daemon=True,
        ).start()
        self._scheduled_timer = wx.CallLater(
            5 * 60 * 1000, self._refresh_scheduled_runtime
        )
    def _apply_scheduled_runtime_state(
        self, state: scheduled_runtime.RuntimeScheduleState
    ) -> None:
        pass

    def create_menu(self):
        menu_dict = {}
        self._command_bar_sizer.Clear(delete_windows=True)
        for old_menu in self._command_menus:
            old_menu.Destroy()
        self._command_menus.clear()
        for menu_name, menu_data in menu_dict.items():
            menu = wx.Menu()
        apply_material3(self._command_bar)
        self._command_bar.Layout()
    def _open_preferences(self, _event=None) -> None:
        pass

class AmuletLevelNotebook:
    def _page_changed(self, evt: wx.BookCtrlEvent):
        if evt.GetOldSelection() != evt.GetSelection():
            if self.GetCurrentPage() is self._main_menu:
                self.apply_tab_workspace()
            else:
                self.apply_tab_workspace()
"""

GLOBAL_CONTRACT_FIXTURE = """from pathlib import Path

def test_all_new_windows_receive_material_theme():
    source = Path("amulet_map_editor/api/framework/app.py").read_text()
    assert "wx.CallAfter(apply_material3, window)" in source
    assert "wx.CallLater(100, apply_material3, window)" in source
"""


def _run(command: list[str], *, cwd: Path | None = None, env=None) -> None:
    print("+", " ".join(command))
    subprocess.run(command, cwd=cwd, env=env, check=True)


def _parse_python(root: Path) -> int:
    count = 0
    for path in sorted(root.rglob("*.py")):
        if any(part == "__pycache__" for part in path.parts):
            continue
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        count += 1
    print(f"AST parsed {count} Python files")
    return count


def _test_patcher(kit: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="m3-patch-") as temporary:
        repo = Path(temporary)
        target = repo / "amulet_map_editor/api/framework/amulet_ui.py"
        target.parent.mkdir(parents=True)
        target.write_text(FIXTURE, encoding="utf-8", newline="\n")
        contract = repo / "tests/test_material3_global_contract.py"
        contract.parent.mkdir(parents=True)
        contract.write_text(GLOBAL_CONTRACT_FIXTURE, encoding="utf-8", newline="\n")
        command = [
            sys.executable,
            str(kit / "patches/apply_completion.py"),
            "--repo",
            str(repo),
            "--no-backup",
        ]
        _run(command)
        first = target.read_text(encoding="utf-8")
        first_contract = contract.read_text(encoding="utf-8")
        _run(command)
        second = target.read_text(encoding="utf-8")
        second_contract = contract.read_text(encoding="utf-8")
        if first != second or first_contract != second_contract:
            raise AssertionError("Integration patch is not idempotent")
        ast.parse(second)
        ast.parse(second_contract)
        assert "BEGIN CODEX MATERIAL 3 COMMAND MENU" in second
        assert "menu = wx.Menu()" not in second
        assert second.count("_scheduled_refresh_thread: threading.Thread | None") == 1
        assert "wx.CallAfter(apply_material3, window)" not in second_contract
        assert 'assert "apply_material3_deferred" in source' in second_contract
        assert 'assert "apply_material3_deferred(window)" in source' in second_contract
    print("Synthetic integration patch and idempotence passed")


def _verify_manifest(kit: Path) -> None:
    manifest_path = kit / "IMPLEMENTATION_MANIFEST.json"
    if not manifest_path.is_file():
        print("Manifest not generated yet; skipped hash verification")
        return
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for entry in manifest["files"]:
        path = kit / entry["path"]
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != entry["sha256"]:
            raise AssertionError(f"Manifest hash mismatch: {entry['path']}")
    print(f"Verified {len(manifest['files'])} manifest hashes")


def _verify_zip(path: Path) -> None:
    with zipfile.ZipFile(path) as archive:
        bad = archive.testzip()
        if bad:
            raise AssertionError(f"Corrupt ZIP member: {bad}")
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise AssertionError("ZIP contains duplicate members")
    print(f"ZIP integrity passed: {path} ({len(names)} files)")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path)
    parser.add_argument("--zip", type=Path)
    parser.add_argument("--full-tests", action="store_true")
    args = parser.parse_args()

    kit = Path(__file__).resolve().parent
    _parse_python(kit)
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPATH"] = str(kit / "overlay") + os.pathsep + env.get("PYTHONPATH", "")
    _run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            str(kit / "overlay/tests/test_material_menu.py"),
            str(kit / "overlay/tests/test_m3_completion_contract.py"),
        ],
        env=env,
    )
    _test_patcher(kit)
    _verify_manifest(kit)

    if args.repo:
        repo = args.repo.resolve()
        _run(
            [
                sys.executable,
                str(repo / "scripts/validate-m3-completion.py"),
                "--repo",
                str(repo),
            ]
        )
        tests = (
            ["tests"]
            if args.full_tests
            else [
                name
                for name in (
                    "tests/test_material_menu.py",
                    "tests/test_m3_completion_contract.py",
                    "tests/test_material3_global_contract.py",
                    "tests/test_material_components_contract.py",
                    "tests/test_material3_common_control_roles.py",
                    "tests/test_m3_surface_inventory.py",
                )
                if (repo / name).is_file()
            ]
        )
        repo_env = os.environ.copy()
        repo_env["PYTHONDONTWRITEBYTECODE"] = "1"
        print(
            "+",
            " ".join(
                [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *tests]
            ),
        )
        subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *tests],
            cwd=repo,
            env=repo_env,
            check=True,
        )
    if args.zip:
        _verify_zip(args.zip.resolve())
    print("All available static checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
