#!/usr/bin/env python3
"""Run the evidence gates available without a Windows wxPython runtime."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
import tempfile
import unicodedata
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

FOCUSED_M3_TESTS = (
    "tests/test_material_menu.py",
    "tests/test_m3_completion_contract.py",
    "tests/test_material3_global_contract.py",
    "tests/test_material_components_contract.py",
    "tests/test_material3_common_control_roles.py",
    "tests/test_m3_surface_inventory.py",
)

EXCLUDED_AST_DIRECTORIES = frozenset(
    {
        ".cache",
        ".claude",
        ".git",
        ".hg",
        ".mypy_cache",
        ".nox",
        ".pytest_cache",
        ".ruff_cache",
        ".svn",
        ".tox",
        ".venv",
        "__pycache__",
        "build",
        "cache",
        "dist",
        "env",
        "node_modules",
        "site-packages",
        "venv",
    }
)

EXPLICIT_AST_DIRECTORIES = (
    "amulet_map_editor",
    "app",
    "overlay",
    "patches",
    "scripts",
    "src",
    "tests",
)
EXPLICIT_AST_FILES = (
    "bootstrap.py",
    "conftest.py",
    "package_completed_codebase.py",
    "run_static_checks.py",
    "setup.py",
)

REQUIRED_KIT_PATHS = frozenset(
    {
        "CODEX_HANDOFF_M3_COMPLETION.md",
        "IMPLEMENTATION_MANIFEST.json",
        "KIT_PROVENANCE.json",
        "SHA256SUMS.txt",
        "START_HERE.md",
        "bootstrap.py",
        "overlay/amulet_map_editor/api/material_menu.py",
        "overlay/amulet_map_editor/api/wx/components.py",
        "overlay/amulet_map_editor/api/wx/material3.py",
        "overlay/scripts/validate-m3-completion.py",
        "overlay/tests/test_m3_completion_contract.py",
        "overlay/tests/test_material_menu.py",
        "package_completed_codebase.py",
        "patches/apply_completion.py",
        "run_static_checks.py",
    }
)

MANIFEST_METADATA_PATHS = frozenset({"IMPLEMENTATION_MANIFEST.json", "SHA256SUMS.txt"})
REQUIRED_MANIFEST_PATHS = REQUIRED_KIT_PATHS - MANIFEST_METADATA_PATHS
MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
MAX_KIT_FILE_BYTES = 16 * 1024 * 1024
MAX_KIT_TOTAL_BYTES = 64 * 1024 * 1024
MAX_KIT_FILES = 512
MAX_KIT_PATH_LENGTH = 512
MAX_MANIFEST_BYTES = 1024 * 1024
MAX_COMPRESSION_RATIO = 200
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
SHA256_LINE_PATTERN = re.compile(r"([0-9a-f]{64})  (.+)")
WINDOWS_RESERVED_NAMES = frozenset(
    {
        "aux",
        "clock$",
        "con",
        "conin$",
        "conout$",
        "nul",
        "prn",
        *(f"com{number}" for number in range(1, 10)),
        *(f"lpt{number}" for number in range(1, 10)),
        *(f"com{number}" for number in ("¹", "²", "³")),
        *(f"lpt{number}" for number in ("¹", "²", "³")),
    }
)


def _run(
    command: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
) -> None:
    print("+", " ".join(command))
    subprocess.run(command, cwd=cwd, env=env, check=True)


def _sanitized_python_env(*, pythonpath: Path | None = None) -> dict[str, str]:
    """Return an environment that cannot rewrite the Python/pytest checks."""

    env = {
        key: value
        for key, value in os.environ.items()
        if not key.upper().startswith(("PYTEST_", "PYTHON", "COVERAGE_", "COV_CORE_"))
    }
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    if pythonpath is not None:
        env["PYTHONPATH"] = str(pythonpath)
    return env


def _sanitized_git_env() -> dict[str, str]:
    """Return an environment that cannot redirect Git's repository inventory."""

    return {
        key: value
        for key, value in _sanitized_python_env().items()
        if not key.upper().startswith("GIT_")
    }


def _excluded_ast_path(relative: Path) -> bool:
    return any(
        part.casefold() in EXCLUDED_AST_DIRECTORIES for part in relative.parts[:-1]
    )


def _contained_python_file(root: Path, path: Path) -> Path:
    relative = path.relative_to(root)
    resolved = path.resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise RuntimeError(f"Python path escapes AST root: {relative}") from exc
    return resolved


def _explicit_python_files(root: Path) -> list[Path]:
    paths: list[Path] = []
    for filename in EXPLICIT_AST_FILES:
        path = root / filename
        if path.is_file():
            paths.append(_contained_python_file(root, path))
    for directory in EXPLICIT_AST_DIRECTORIES:
        source_root = root / directory
        if not source_root.is_dir():
            continue
        for path in source_root.rglob("*.py"):
            relative = path.relative_to(root)
            if _excluded_ast_path(relative):
                continue
            resolved = _contained_python_file(root, path)
            if resolved.is_file():
                paths.append(resolved)
    return paths


def _git_python_files(root: Path) -> list[Path] | None:
    try:
        completed = subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "ls-files",
                "-z",
                "--cached",
                "--others",
                "--exclude-standard",
                "--",
                "*.py",
            ],
            check=False,
            capture_output=True,
            env=_sanitized_git_env(),
        )
    except OSError:
        return None
    if completed.returncode != 0:
        return None

    root_resolved = root.resolve(strict=True)
    paths: list[Path] = []
    try:
        output = completed.stdout.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RuntimeError("git returned non-UTF-8 Python paths") from exc
    for raw_path in output.split("\0"):
        if not raw_path:
            continue
        relative = Path(raw_path)
        if relative.is_absolute() or ".." in relative.parts:
            raise RuntimeError(f"git returned an unsafe Python path: {raw_path}")
        if _excluded_ast_path(relative):
            continue
        candidate = (root / relative).resolve(strict=True)
        try:
            candidate.relative_to(root_resolved)
        except ValueError as exc:
            raise RuntimeError(f"Python path escapes AST root: {raw_path}") from exc
        if candidate.is_file():
            paths.append(candidate)
    return paths


def _parse_python(root: Path) -> int:
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise NotADirectoryError(f"AST root is not a directory: {root}")

    paths = _git_python_files(root)
    if paths is None:
        paths = _explicit_python_files(root)

    unique_paths = sorted(set(paths))
    if not unique_paths:
        raise FileNotFoundError(f"No non-ignored Python files found under {root}")

    count = 0
    for path in unique_paths:
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
        patch_env = _sanitized_python_env()
        _run(command, cwd=kit, env=patch_env)
        first = target.read_text(encoding="utf-8")
        first_contract = contract.read_text(encoding="utf-8")
        _run(command, cwd=kit, env=patch_env)
        second = target.read_text(encoding="utf-8")
        second_contract = contract.read_text(encoding="utf-8")
        if first != second or first_contract != second_contract:
            raise AssertionError("Integration patch is not idempotent")
        ast.parse(second)
        ast.parse(second_contract)
        if "BEGIN CODEX MATERIAL 3 COMMAND MENU" not in second:
            raise RuntimeError("Integration patch omitted the command-menu marker")
        if "menu = wx.Menu()" in second:
            raise RuntimeError("Integration patch left the legacy wx.Menu constructor")
        if second.count("_scheduled_refresh_thread: threading.Thread | None") != 1:
            raise RuntimeError("Integration patch duplicated scheduled runtime state")
        if "wx.CallAfter(apply_material3, window)" in second_contract:
            raise RuntimeError("Integration patch left the obsolete theme assertion")
        if 'assert "apply_material3_deferred" in source' not in second_contract:
            raise RuntimeError("Integration patch omitted the deferred-theme contract")
        if 'assert "apply_material3_deferred(window)" in source' not in second_contract:
            raise RuntimeError(
                "Integration patch omitted the deferred-theme call contract"
            )
    print("Synthetic integration patch and idempotence passed")


def _safe_relative_path(value: object, *, label: str) -> PurePosixPath:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} path must be a non-empty string")
    if len(value) > MAX_KIT_PATH_LENGTH:
        raise ValueError(f"{label} path exceeds the bounded path length")
    if unicodedata.normalize("NFC", value) != value:
        raise ValueError(f"{label} path is not Unicode-normalized: {value}")
    if "\\" in value or any(
        ord(character) < 32 or character in '<>:"|?*' for character in value
    ):
        raise ValueError(f"{label} path uses unsafe Windows characters")
    raw_parts = value.split("/")
    if any(part in {"", ".", ".."} for part in raw_parts):
        raise ValueError(f"{label} path is not normalized: {value}")
    if any(part.endswith((" ", ".")) or ":" in part for part in raw_parts):
        raise ValueError(f"{label} path is unsafe on Windows: {value}")
    if any(
        part.split(".", 1)[0].casefold() in WINDOWS_RESERVED_NAMES for part in raw_parts
    ):
        raise ValueError(f"{label} path uses a reserved Windows name: {value}")
    path = PurePosixPath(value)
    if path.is_absolute() or path.as_posix() != value:
        raise ValueError(f"{label} path is not a contained relative path: {value}")
    return path


def _path_key(path: PurePosixPath) -> str:
    return "/".join(
        unicodedata.normalize("NFC", part).casefold() for part in path.parts
    )


def _path_ancestor_keys(path: PurePosixPath) -> set[str]:
    return {
        _path_key(PurePosixPath(*path.parts[:part_count]))
        for part_count in range(1, len(path.parts))
    }


def _validate_manifest_data(
    manifest: object,
) -> tuple[str, dict[str, tuple[int, str]]]:
    if not isinstance(manifest, dict):
        raise ValueError("Manifest root must be an object")
    if manifest.get("schema_version") != 1:
        raise ValueError("Manifest schema_version must be 1")

    artifact = manifest.get("artifact")
    artifact_path = _safe_relative_path(artifact, label="Manifest artifact")
    if len(artifact_path.parts) != 1:
        raise ValueError("Manifest artifact must be one directory name")

    target = manifest.get("target")
    if not isinstance(target, dict):
        raise ValueError("Manifest target must be an object")
    repository = target.get("repository")
    branch = target.get("branch")
    commit = target.get("commit")
    if not isinstance(repository, str) or not re.fullmatch(
        r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository
    ):
        raise ValueError("Manifest target repository is invalid")
    if (
        not isinstance(branch, str)
        or not branch.strip()
        or len(branch) > 256
        or any(ord(character) < 32 for character in branch)
    ):
        raise ValueError("Manifest target branch is invalid")
    if (
        not isinstance(commit, str)
        or re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", commit) is None
    ):
        raise ValueError("Manifest target commit is invalid")

    generated_date = manifest.get("generated_date")
    if generated_date is not None and (
        not isinstance(generated_date, str)
        or re.fullmatch(r"\d{4}-\d{2}-\d{2}", generated_date) is None
    ):
        raise ValueError("Manifest generated_date is invalid")

    files = manifest.get("files")
    file_count = manifest.get("file_count")
    if not isinstance(files, list):
        raise ValueError("Manifest files must be a list")
    if type(file_count) is not int or file_count != len(files):
        raise ValueError("Manifest file_count must equal the files list length")
    if not 1 <= file_count <= MAX_KIT_FILES:
        raise ValueError("Manifest file_count exceeds the bounded file limit")

    validated: dict[str, tuple[int, str]] = {}
    seen_keys: set[str] = set()
    implicit_directory_keys: set[str] = set()
    total_bytes = 0
    for index, entry in enumerate(files):
        if not isinstance(entry, dict):
            raise ValueError(f"Manifest file entry {index} must be an object")
        path = _safe_relative_path(entry.get("path"), label="Manifest")
        path_text = path.as_posix()
        path_key = _path_key(path)
        if path_key in seen_keys:
            raise ValueError(f"Manifest contains a duplicate path: {path_text}")
        ancestor_keys = _path_ancestor_keys(path)
        if ancestor_keys & seen_keys or path_key in implicit_directory_keys:
            raise ValueError(
                f"Manifest contains a file/descendant path conflict: {path_text}"
            )
        seen_keys.add(path_key)
        implicit_directory_keys.update(ancestor_keys)
        if path_text in MANIFEST_METADATA_PATHS:
            raise ValueError(f"Manifest cannot recursively list metadata: {path_text}")

        size = entry.get("bytes")
        if type(size) is not int or not 0 <= size <= MAX_KIT_FILE_BYTES:
            raise ValueError(f"Manifest size is invalid for {path_text}")
        digest = entry.get("sha256")
        if not isinstance(digest, str) or SHA256_PATTERN.fullmatch(digest) is None:
            raise ValueError(f"Manifest hash is invalid for {path_text}")
        role = entry.get("role")
        if not isinstance(role, str) or not role.strip():
            raise ValueError(f"Manifest role is invalid for {path_text}")

        total_bytes += size
        if total_bytes > MAX_KIT_TOTAL_BYTES:
            raise ValueError("Manifest sizes exceed the bounded total size")
        validated[path_text] = (size, digest)

    missing = sorted(REQUIRED_MANIFEST_PATHS - validated.keys())
    if missing:
        raise ValueError(
            "Manifest is missing required kit paths: " + ", ".join(missing)
        )
    return artifact_path.as_posix(), validated


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_sha256s(data: bytes) -> dict[str, str]:
    if len(data) > MAX_MANIFEST_BYTES:
        raise ValueError("SHA256SUMS.txt exceeds the bounded metadata size")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("SHA256SUMS.txt is not UTF-8") from exc
    result: dict[str, str] = {}
    seen_keys: set[str] = set()
    for line_number, line in enumerate(text.splitlines(), start=1):
        match = SHA256_LINE_PATTERN.fullmatch(line)
        if match is None:
            raise ValueError(f"SHA256SUMS.txt line {line_number} is invalid")
        digest, raw_path = match.groups()
        safe_path = _safe_relative_path(raw_path, label="SHA256SUMS")
        key = _path_key(safe_path)
        if key in seen_keys:
            raise ValueError(f"SHA256SUMS.txt contains a duplicate path: {raw_path}")
        seen_keys.add(key)
        result[safe_path.as_posix()] = digest
    return result


def _verify_sha256s(data: bytes, expected: dict[str, str]) -> None:
    actual = _parse_sha256s(data)
    if actual.keys() != expected.keys():
        missing = sorted(expected.keys() - actual.keys())
        extra = sorted(actual.keys() - expected.keys())
        raise ValueError(
            "SHA256SUMS.txt correspondence mismatch; "
            f"missing={missing}, extra={extra}"
        )
    for path, digest in expected.items():
        if actual[path] != digest:
            raise ValueError(f"SHA256SUMS.txt hash mismatch: {path}")


def _verify_manifest(kit: Path) -> dict[str, tuple[int, str]]:
    manifest_path = kit / "IMPLEMENTATION_MANIFEST.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Required manifest is missing: {manifest_path}")
    if manifest_path.stat().st_size > MAX_MANIFEST_BYTES:
        raise ValueError("Manifest exceeds the bounded metadata size")
    manifest_bytes = manifest_path.read_bytes()
    try:
        manifest = json.loads(manifest_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Manifest is not valid UTF-8 JSON") from exc
    _artifact, entries = _validate_manifest_data(manifest)

    root = kit.resolve(strict=True)
    expected_sums = {
        "IMPLEMENTATION_MANIFEST.json": hashlib.sha256(manifest_bytes).hexdigest()
    }
    for relative, (expected_size, expected_digest) in entries.items():
        path = (kit / Path(*PurePosixPath(relative).parts)).resolve(strict=True)
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"Manifest path escapes kit root: {relative}") from exc
        if not path.is_file():
            raise ValueError(f"Manifest path is not a regular file: {relative}")
        if path.stat().st_size != expected_size:
            raise ValueError(f"Manifest size mismatch: {relative}")
        digest = _sha256_file(path)
        if digest != expected_digest:
            raise ValueError(f"Manifest hash mismatch: {relative}")
        expected_sums[relative] = digest

    sums_path = kit / "SHA256SUMS.txt"
    if not sums_path.is_file():
        raise FileNotFoundError(f"Required checksum file is missing: {sums_path}")
    _verify_sha256s(sums_path.read_bytes(), expected_sums)

    expected_local_paths = entries.keys() | MANIFEST_METADATA_PATHS
    actual_local_paths: dict[str, str] = {}
    for path in kit.rglob("*"):
        relative_path = path.relative_to(kit)
        relative_text = relative_path.as_posix()
        safe_path = _safe_relative_path(relative_text, label="Local kit")
        if path.is_symlink():
            raise ValueError(f"Local kit contains a symbolic link: {relative_text}")
        if path.is_dir():
            continue
        if not path.is_file():
            raise ValueError(f"Local kit contains a non-regular entry: {relative_text}")
        key = _path_key(safe_path)
        if key in actual_local_paths:
            raise ValueError(
                "Local kit contains a duplicate normalized path: " + relative_text
            )
        actual_local_paths[key] = safe_path.as_posix()
    actual_path_set = set(actual_local_paths.values())
    if actual_path_set != expected_local_paths:
        missing = sorted(expected_local_paths - actual_path_set)
        extra = sorted(actual_path_set - expected_local_paths)
        raise ValueError(
            "Manifest local correspondence mismatch; "
            f"missing={missing}, extra={extra}"
        )
    print(f"Verified {len(entries)} manifest hashes and checksum entries")
    return entries


def _verify_zip(path: Path) -> None:
    if not path.is_file():
        raise FileNotFoundError(f"ZIP does not exist: {path}")
    if path.stat().st_size > MAX_ARCHIVE_BYTES:
        raise ValueError("ZIP exceeds the bounded compressed size")
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        if not 1 <= len(infos) <= MAX_KIT_FILES + 32:
            raise ValueError("ZIP member count exceeds the bounded limit")

        roots: set[str] = set()
        members: dict[str, zipfile.ZipInfo] = {}
        seen_archive_keys: set[str] = set()
        archive_file_keys: set[str] = set()
        archive_directory_keys: set[str] = set()
        total_bytes = 0
        for info in infos:
            if info.flag_bits & 0x1:
                raise ValueError(f"ZIP member is encrypted: {info.filename}")
            if info.orig_filename != info.filename:
                raise ValueError(
                    f"ZIP member has an unsafe original path: {info.orig_filename}"
                )
            unix_mode = (info.external_attr >> 16) & 0xFFFF
            unix_file_type = stat.S_IFMT(unix_mode)
            dos_attributes = info.external_attr & 0xFFFF
            if dos_attributes & 0x400:
                raise ValueError(
                    f"ZIP member has reparse-point metadata: {info.filename}"
                )
            if info.is_dir():
                if unix_file_type not in {0, stat.S_IFDIR}:
                    raise ValueError(
                        f"ZIP directory has non-directory metadata: {info.filename}"
                    )
                if info.file_size != 0 or info.CRC != 0 or info.compress_size > 64:
                    raise ValueError(f"ZIP directory is not empty: {info.filename}")
            elif unix_file_type not in {0, stat.S_IFREG}:
                raise ValueError(f"ZIP member is not a regular file: {info.filename}")
            elif dos_attributes & 0x10:
                raise ValueError(f"ZIP file has directory metadata: {info.filename}")

            raw_name = info.filename[:-1] if info.is_dir() else info.filename
            archive_path = _safe_relative_path(raw_name, label="ZIP")
            if len(archive_path.parts) == 1:
                if not info.is_dir():
                    raise ValueError(
                        "ZIP files must live below one kit root directory: "
                        f"{info.filename}"
                    )
                root_name = archive_path.parts[0]
                root_key = _path_key(archive_path)
                if root_key in seen_archive_keys:
                    raise ValueError(
                        f"ZIP contains a duplicate normalized path: {info.filename}"
                    )
                seen_archive_keys.add(root_key)
                archive_directory_keys.add(root_key)
                roots.add(root_name)
                continue
            if len(archive_path.parts) < 2:
                raise ValueError(
                    f"ZIP path must live below one kit root directory: {info.filename}"
                )
            root_name = archive_path.parts[0]
            roots.add(root_name)
            relative = PurePosixPath(*archive_path.parts[1:])
            archive_key = _path_key(archive_path)
            if archive_key in seen_archive_keys:
                raise ValueError(
                    f"ZIP contains a duplicate normalized path: {info.filename}"
                )
            seen_archive_keys.add(archive_key)

            ancestor_keys = _path_ancestor_keys(archive_path)
            if ancestor_keys & archive_file_keys:
                raise ValueError(
                    f"ZIP contains a file/descendant path conflict: {info.filename}"
                )
            if info.is_dir():
                if archive_key in archive_file_keys:
                    raise ValueError(
                        f"ZIP contains a file/directory path conflict: {info.filename}"
                    )
                archive_directory_keys.add(archive_key)
                archive_directory_keys.update(ancestor_keys)
                continue
            if archive_key in archive_directory_keys:
                raise ValueError(
                    f"ZIP contains a file/descendant path conflict: {info.filename}"
                )
            archive_file_keys.add(archive_key)
            archive_directory_keys.update(ancestor_keys)

            if info.file_size < 0 or info.file_size > MAX_KIT_FILE_BYTES:
                raise ValueError(
                    f"ZIP member exceeds the bounded size: {info.filename}"
                )
            total_bytes += info.file_size
            if total_bytes > MAX_KIT_TOTAL_BYTES + (2 * MAX_MANIFEST_BYTES):
                raise ValueError("ZIP members exceed the bounded total size")
            if info.file_size and info.compress_size == 0:
                raise ValueError(
                    f"ZIP member has an invalid compressed size: {info.filename}"
                )
            if (
                info.file_size
                and info.file_size / max(info.compress_size, 1) > MAX_COMPRESSION_RATIO
            ):
                raise ValueError(
                    f"ZIP member exceeds the compression-ratio bound: {info.filename}"
                )
            members[relative.as_posix()] = info

        if len(roots) != 1:
            raise ValueError("ZIP must contain exactly one kit root directory")
        missing_layout = sorted(REQUIRED_KIT_PATHS - members.keys())
        if missing_layout:
            raise ValueError(
                "ZIP is missing required kit layout: " + ", ".join(missing_layout)
            )

        manifest_info = members["IMPLEMENTATION_MANIFEST.json"]
        if manifest_info.file_size > MAX_MANIFEST_BYTES:
            raise ValueError("ZIP manifest exceeds the bounded metadata size")
        manifest_bytes = archive.read(manifest_info)
        try:
            manifest = json.loads(manifest_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("ZIP manifest is not valid UTF-8 JSON") from exc
        artifact, entries = _validate_manifest_data(manifest)
        if artifact != next(iter(roots)):
            raise ValueError("ZIP root does not match the manifest artifact")

        payload_paths = members.keys() - MANIFEST_METADATA_PATHS
        if payload_paths != entries.keys():
            missing = sorted(entries.keys() - payload_paths)
            extra = sorted(payload_paths - entries.keys())
            raise ValueError(
                "ZIP manifest correspondence mismatch; "
                f"missing={missing}, extra={extra}"
            )

        expected_sums = {
            "IMPLEMENTATION_MANIFEST.json": hashlib.sha256(manifest_bytes).hexdigest()
        }
        for relative, (expected_size, expected_digest) in entries.items():
            info = members[relative]
            if info.file_size != expected_size:
                raise ValueError(f"ZIP manifest size mismatch: {relative}")
            digest = hashlib.sha256()
            observed_size = 0
            with archive.open(info) as stream:
                while chunk := stream.read(1024 * 1024):
                    observed_size += len(chunk)
                    if observed_size > expected_size:
                        raise ValueError(
                            f"ZIP member exceeded declared size: {relative}"
                        )
                    digest.update(chunk)
            if observed_size != expected_size:
                raise ValueError(f"ZIP member size mismatch: {relative}")
            if digest.hexdigest() != expected_digest:
                raise ValueError(f"ZIP manifest hash mismatch: {relative}")
            expected_sums[relative] = expected_digest

        sums_info = members["SHA256SUMS.txt"]
        if sums_info.file_size > MAX_MANIFEST_BYTES:
            raise ValueError("ZIP checksum metadata exceeds the bounded size")
        _verify_sha256s(archive.read(sums_info), expected_sums)

        bad = archive.testzip()
        if bad:
            raise RuntimeError(f"Corrupt ZIP member: {bad}")
    print(f"ZIP integrity passed: {path} ({len(members)} files)")


def _is_kit_layout(root: Path) -> bool:
    patcher = root / "patches/apply_completion.py"
    kit_payload_present = (root / "overlay").exists() or patcher.exists()
    if not kit_payload_present:
        return False

    missing = [
        root / relative
        for relative in REQUIRED_KIT_PATHS
        if not (root / relative).is_file()
    ]
    if missing:
        missing_text = ", ".join(str(path.relative_to(root)) for path in missing)
        raise FileNotFoundError(
            f"Incomplete completion-kit layout; missing: {missing_text}"
        )
    return True


def _is_integrated_layout(root: Path) -> bool:
    return (root / "amulet_map_editor").is_dir() and (root / "tests").is_dir()


def _run_kit_checks(kit: Path) -> None:
    print(f"Detected completion-kit layout: {kit}")
    _verify_manifest(kit)
    env = _sanitized_python_env(pythonpath=kit / "overlay")
    _run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "-o",
            "addopts=",
            "-c",
            os.devnull,
            "--noconftest",
            f"--rootdir={kit}",
            str(kit / "overlay/tests/test_material_menu.py"),
            str(kit / "overlay/tests/test_m3_completion_contract.py"),
        ],
        cwd=kit,
        env=env,
    )
    _test_patcher(kit)


def _run_integrated_checks(repo: Path, *, full_tests: bool) -> None:
    print(f"Detected integrated repository layout: {repo}")
    validator = repo / "scripts/validate-m3-completion.py"
    if not validator.is_file():
        raise FileNotFoundError(
            f"Integrated M3 validator is missing: {validator.relative_to(repo)}"
        )

    repo_env = _sanitized_python_env()
    _run(
        [sys.executable, str(validator), "--repo", str(repo)],
        cwd=repo,
        env=repo_env,
    )
    if full_tests:
        tests = ["tests"]
    else:
        missing = [name for name in FOCUSED_M3_TESTS if not (repo / name).is_file()]
        if missing:
            raise FileNotFoundError(
                "Integrated M3 focused tests are missing: " + ", ".join(missing)
            )
        tests = list(FOCUSED_M3_TESTS)

    _run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "-o",
            "addopts=",
            *tests,
        ],
        cwd=repo,
        env=repo_env,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path)
    parser.add_argument("--zip", type=Path)
    parser.add_argument("--full-tests", action="store_true")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent
    explicit_repo = args.repo.resolve() if args.repo else None
    ast_root = explicit_repo if explicit_repo is not None else root
    _parse_python(ast_root)
    kit_layout = _is_kit_layout(root)
    if kit_layout:
        _run_kit_checks(root)

    repo = explicit_repo
    if repo is None and _is_integrated_layout(root):
        repo = root
    if repo is not None:
        _run_integrated_checks(repo, full_tests=args.full_tests)
    elif not kit_layout:
        raise FileNotFoundError(
            f"No completion-kit or integrated repository layout found at {root}"
        )
    if args.zip:
        _verify_zip(args.zip.resolve())
    print("All available static checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
