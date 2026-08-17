from __future__ import annotations

import ast
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import unicodedata
import zipfile

import pytest

import run_static_checks as runner

REQUIRED_PAYLOAD = {
    "START_HERE.md": b"start here\n",
    "CODEX_HANDOFF_M3_COMPLETION.md": b"handoff\n",
    "KIT_PROVENANCE.json": b"{}\n",
    "bootstrap.py": b"print('bootstrap')\n",
    "package_completed_codebase.py": b"print('package')\n",
    "run_static_checks.py": b"print('checks')\n",
    "patches/apply_completion.py": b"print('patch')\n",
    "overlay/amulet_map_editor/api/material_menu.py": b"VALUE = 1\n",
    "overlay/amulet_map_editor/api/wx/components.py": b"VALUE = 1\n",
    "overlay/amulet_map_editor/api/wx/material3.py": b"VALUE = 1\n",
    "overlay/scripts/validate-m3-completion.py": b"print('validate')\n",
    "overlay/tests/test_material_menu.py": b"def test_menu(): pass\n",
    "overlay/tests/test_m3_completion_contract.py": b"def test_contract(): pass\n",
}


def _manifest(payload: dict[str, bytes]) -> dict[str, object]:
    files = [
        {
            "bytes": len(content),
            "path": path,
            "role": "fixture",
            "sha256": hashlib.sha256(content).hexdigest(),
        }
        for path, content in sorted(payload.items())
    ]
    return {
        "artifact": "test-kit",
        "file_count": len(files),
        "files": files,
        "schema_version": 1,
        "target": {
            "branch": "main",
            "commit": "0" * 40,
            "repository": "example/test",
        },
    }


def _sha256s(payload: dict[str, bytes], manifest_bytes: bytes) -> bytes:
    lines = [
        f"{hashlib.sha256(content).hexdigest()}  {path}"
        for path, content in sorted(payload.items())
    ]
    lines.append(
        f"{hashlib.sha256(manifest_bytes).hexdigest()}  IMPLEMENTATION_MANIFEST.json"
    )
    return ("\n".join(lines) + "\n").encode()


def _write_kit(root: Path, payload: dict[str, bytes] | None = None) -> None:
    payload = dict(REQUIRED_PAYLOAD if payload is None else payload)
    for relative, content in payload.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    manifest_bytes = (
        json.dumps(_manifest(payload), indent=2, sort_keys=True).encode() + b"\n"
    )
    (root / "IMPLEMENTATION_MANIFEST.json").write_bytes(manifest_bytes)
    (root / "SHA256SUMS.txt").write_bytes(_sha256s(payload, manifest_bytes))


def _write_zip(
    path: Path,
    payload: dict[str, bytes] | None = None,
    *,
    member_overrides: dict[str, bytes] | None = None,
) -> None:
    payload = dict(REQUIRED_PAYLOAD if payload is None else payload)
    member_overrides = {} if member_overrides is None else member_overrides
    manifest_bytes = (
        json.dumps(_manifest(payload), indent=2, sort_keys=True).encode() + b"\n"
    )
    members = {
        **payload,
        "IMPLEMENTATION_MANIFEST.json": manifest_bytes,
        "SHA256SUMS.txt": _sha256s(payload, manifest_bytes),
    }
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for relative, content in members.items():
            archive.writestr(
                f"test-kit/{relative}", member_overrides.get(relative, content)
            )


def test_python_environment_is_sanitized(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PYTEST_ADDOPTS", "--maxfail=0 -p hostile")
    monkeypatch.setenv("PYTEST_PLUGINS", "hostile_plugin")
    monkeypatch.setenv("PYTHONOPTIMIZE", "2")
    monkeypatch.setenv("PYTHONWARNINGS", "error")
    monkeypatch.setenv("PYTHONPATH", "hostile-path")
    monkeypatch.setenv("PYTHONHOME", "hostile-home")
    monkeypatch.setenv("PYTHONNOUSERSITE", "1")
    monkeypatch.setenv("PYTHONUSERBASE", "hostile-user-base")
    monkeypatch.setenv("UNCHANGED_SENTINEL", "present")

    env = runner._sanitized_python_env()

    assert "PYTEST_ADDOPTS" not in env
    assert "PYTEST_PLUGINS" not in env
    assert "PYTHONOPTIMIZE" not in env
    assert "PYTHONWARNINGS" not in env
    assert "PYTHONPATH" not in env
    assert "PYTHONHOME" not in env
    assert "PYTHONNOUSERSITE" not in env
    assert "PYTHONUSERBASE" not in env
    assert env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] == "1"
    assert env["PYTHONDONTWRITEBYTECODE"] == "1"
    assert env["UNCHANGED_SENTINEL"] == "present"


def test_unlisted_python_startup_controls_are_removed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PYTHONMALLOC", "definitely-not-an-allocator")

    env = runner._sanitized_python_env()
    completed = subprocess.run(
        [sys.executable, "-c", "print('isolated child')"],
        check=False,
        capture_output=True,
        env=env,
        text=True,
    )

    assert "PYTHONMALLOC" not in env
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "isolated child"


def test_kit_pytest_uses_kit_cwd_and_controlled_pythonpath(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_kit(tmp_path)
    calls: list[tuple[list[str], Path | None, dict[str, str] | None]] = []
    monkeypatch.setattr(
        runner,
        "_run",
        lambda command, *, cwd=None, env=None: calls.append((command, cwd, env)),
    )
    monkeypatch.setattr(runner, "_test_patcher", lambda _kit: None)
    monkeypatch.setenv("PYTEST_ADDOPTS", "--collect-only")

    runner._run_kit_checks(tmp_path)

    pytest_call = next(call for call in calls if "pytest" in call[0])
    assert pytest_call[1] == tmp_path
    assert pytest_call[2] is not None
    assert "PYTEST_ADDOPTS" not in pytest_call[2]
    assert pytest_call[2]["PYTHONPATH"] == str(tmp_path / "overlay")
    assert pytest_call[0][pytest_call[0].index("-o") + 1] == "addopts="
    assert "--noconftest" in pytest_call[0]
    assert f"--rootdir={tmp_path}" in pytest_call[0]


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda data: data.update(file_count=data["file_count"] + 1), "file_count"),
        (
            lambda data: (
                data["files"].append(dict(data["files"][0])),
                data.update(file_count=len(data["files"])),
            ),
            "duplicate",
        ),
        (
            lambda data: data["files"][0].update(path="../outside.py"),
            "path",
        ),
        (
            lambda data: data["files"][0].update(bytes=999999),
            "size",
        ),
        (
            lambda data: data["files"][0].update(bytes=True),
            "size",
        ),
        (
            lambda data: data["files"][0].update(sha256="0" * 64),
            "hash",
        ),
        (lambda data: data.update(target=None), "target"),
    ],
)
def test_manifest_rejects_hostile_structure(
    tmp_path: Path, mutate, message: str
) -> None:
    _write_kit(tmp_path)
    manifest_path = tmp_path / "IMPLEMENTATION_MANIFEST.json"
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    mutate(data)
    manifest_path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises((ValueError, RuntimeError), match=message):
        runner._verify_manifest(tmp_path)


def test_manifest_is_required_for_kit_layout(tmp_path: Path) -> None:
    _write_kit(tmp_path)
    (tmp_path / "IMPLEMENTATION_MANIFEST.json").unlink()

    with pytest.raises(FileNotFoundError, match="IMPLEMENTATION_MANIFEST"):
        runner._is_kit_layout(tmp_path)


def test_parse_python_ignores_generated_and_agent_directories(tmp_path: Path) -> None:
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts/good.py").write_text("VALUE = 1\n", encoding="utf-8")
    for relative in (
        ".claude/probe.py",
        "build/generated.py",
        "dist/bundle.py",
        ".cache/cached.py",
        ".venv/library.py",
    ):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("this is invalid Python !!!\n", encoding="utf-8")
    unrelated = tmp_path / "unrelated/probe.py"
    unrelated.parent.mkdir()
    unrelated.write_text("this is invalid Python !!!\n", encoding="utf-8")

    assert runner._parse_python(tmp_path) == 1


def test_git_python_inventory_ignores_hostile_git_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    good = tmp_path / "good.py"
    hidden = tmp_path / "hidden.py"
    good.write_text("VALUE = 1\n", encoding="utf-8")
    hidden.write_text("this is invalid Python !!!\n", encoding="utf-8")
    subprocess.run(
        ["git", "-C", str(tmp_path), "add", "good.py", "hidden.py"], check=True
    )
    (tmp_path / ".gitignore").write_text("hidden.py\n", encoding="utf-8")
    subprocess.run(
        ["git", "-C", str(tmp_path), "add", ".gitignore"], check=True
    )

    alternate_index = tmp_path / "alternate.index"
    alternate_env = os.environ.copy()
    alternate_env["GIT_INDEX_FILE"] = str(alternate_index)
    subprocess.run(
        ["git", "-C", str(tmp_path), "add", "good.py", ".gitignore"],
        check=True,
        env=alternate_env,
    )
    monkeypatch.setenv("GIT_INDEX_FILE", str(alternate_index))

    paths = runner._git_python_files(tmp_path)

    assert paths is not None
    assert {path.name for path in paths} == {"good.py", "hidden.py"}


def test_repo_argument_drives_ast_root_from_hostile_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner_root = tmp_path / "runner"
    repo = tmp_path / "target"
    hostile_cwd = tmp_path / "elsewhere"
    for path in (runner_root, repo, hostile_cwd):
        path.mkdir()
    (runner_root / "run_static_checks.py").write_text("", encoding="utf-8")
    parsed: list[Path] = []
    integrated: list[Path] = []
    monkeypatch.setattr(runner, "__file__", str(runner_root / "run_static_checks.py"))
    monkeypatch.setattr(runner, "_parse_python", lambda root: parsed.append(root) or 0)
    monkeypatch.setattr(runner, "_is_kit_layout", lambda _root: False)
    monkeypatch.setattr(
        runner,
        "_run_integrated_checks",
        lambda root, *, full_tests: integrated.append(root),
    )
    monkeypatch.chdir(hostile_cwd)
    monkeypatch.setattr(sys, "argv", ["run_static_checks.py", "--repo", str(repo)])

    assert runner.main() == 0
    assert parsed == [repo.resolve()]
    assert integrated == [repo.resolve()]


def test_no_args_runs_both_layouts_when_repo_markers_exist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner_path = tmp_path / "run_static_checks.py"
    runner_path.write_text("", encoding="utf-8")
    (tmp_path / "amulet_map_editor").mkdir()
    (tmp_path / "tests").mkdir()
    kit_calls: list[Path] = []
    integrated_calls: list[Path] = []
    monkeypatch.setattr(runner, "__file__", str(runner_path))
    monkeypatch.setattr(runner, "_parse_python", lambda _root: 0)
    monkeypatch.setattr(runner, "_is_kit_layout", lambda _root: True)
    monkeypatch.setattr(runner, "_run_kit_checks", lambda root: kit_calls.append(root))
    monkeypatch.setattr(
        runner,
        "_run_integrated_checks",
        lambda root, *, full_tests: integrated_calls.append(root),
    )
    monkeypatch.setattr(sys, "argv", ["run_static_checks.py"])

    assert runner.main() == 0
    assert kit_calls == [tmp_path]
    assert integrated_calls == [tmp_path]


def test_zip_validation_checks_layout_manifest_and_bounds(tmp_path: Path) -> None:
    valid = tmp_path / "valid.zip"
    _write_zip(valid)
    runner._verify_zip(valid)

    extra = tmp_path / "extra.zip"
    _write_zip(extra)
    with zipfile.ZipFile(extra, "a") as archive:
        archive.writestr("test-kit/unmanifested.py", "VALUE = 1\n")
    with pytest.raises((ValueError, RuntimeError), match="manifest"):
        runner._verify_zip(extra)

    traversal = tmp_path / "traversal.zip"
    _write_zip(traversal)
    with zipfile.ZipFile(traversal, "a") as archive:
        archive.writestr("test-kit/../escape.py", "VALUE = 1\n")
    with pytest.raises((ValueError, RuntimeError), match="path"):
        runner._verify_zip(traversal)

    missing = tmp_path / "missing-layout.zip"
    missing_payload = dict(REQUIRED_PAYLOAD)
    missing_payload.pop("overlay/amulet_map_editor/api/wx/material3.py")
    _write_zip(missing, missing_payload)
    with pytest.raises((ValueError, RuntimeError), match="required kit layout"):
        runner._verify_zip(missing)

    hash_mismatch = tmp_path / "hash-mismatch.zip"
    _write_zip(
        hash_mismatch,
        member_overrides={"START_HERE.md": b"start HERE\n"},
    )
    with pytest.raises((ValueError, RuntimeError), match="manifest hash mismatch"):
        runner._verify_zip(hash_mismatch)


def test_zip_rejects_case_aliases_and_compression_bombs(tmp_path: Path) -> None:
    alias = tmp_path / "alias.zip"
    _write_zip(alias)
    with zipfile.ZipFile(alias, "a") as archive:
        archive.writestr("test-kit/start_here.MD", "alias\n")
    with pytest.raises((ValueError, RuntimeError), match="duplicate normalized"):
        runner._verify_zip(alias)

    bomb = tmp_path / "bomb.zip"
    payload = dict(REQUIRED_PAYLOAD)
    payload["START_HERE.md"] = b"0" * (1024 * 1024)
    _write_zip(bomb, payload)
    with pytest.raises((ValueError, RuntimeError), match="compression-ratio"):
        runner._verify_zip(bomb)


def test_zip_member_count_is_bounded(tmp_path: Path) -> None:
    archive_path = tmp_path / "too-many.zip"
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_STORED) as archive:
        for number in range(runner.MAX_KIT_FILES + 33):
            archive.writestr(f"test-kit/files/{number}.txt", "x")

    with pytest.raises((ValueError, RuntimeError), match="member count"):
        runner._verify_zip(archive_path)


def test_zip_rejects_special_entries_and_path_conflicts(tmp_path: Path) -> None:
    directory_payload = tmp_path / "directory-payload.zip"
    _write_zip(directory_payload)
    with zipfile.ZipFile(directory_payload, "a") as archive:
        directory = zipfile.ZipInfo("test-kit/payload/")
        directory.external_attr = (stat.S_IFDIR | 0o755) << 16
        archive.writestr(directory, b"0" * (4 * 1024 * 1024))
    with pytest.raises((ValueError, RuntimeError), match="directory is not empty"):
        runner._verify_zip(directory_payload)

    device = tmp_path / "device.zip"
    _write_zip(device)
    with zipfile.ZipFile(device, "a") as archive:
        special = zipfile.ZipInfo("test-kit/device")
        special.create_system = 3
        special.external_attr = (stat.S_IFCHR | 0o644) << 16
        archive.writestr(special, b"device")
    with pytest.raises((ValueError, RuntimeError), match="not a regular file"):
        runner._verify_zip(device)

    conflict = tmp_path / "conflict.zip"
    _write_zip(conflict)
    with zipfile.ZipFile(conflict, "a") as archive:
        archive.writestr("test-kit/conflict", b"file")
        archive.writestr("test-kit/conflict/child.py", b"VALUE = 1\n")
    with pytest.raises((ValueError, RuntimeError), match="path conflict"):
        runner._verify_zip(conflict)

    unicode_alias = tmp_path / "unicode-alias.zip"
    _write_zip(unicode_alias)
    decomposed = unicodedata.normalize("NFD", "café.txt")
    with zipfile.ZipFile(unicode_alias, "a") as archive:
        archive.writestr(f"test-kit/{decomposed}", b"alias")
    with pytest.raises((ValueError, RuntimeError), match="Unicode-normalized"):
        runner._verify_zip(unicode_alias)


@pytest.mark.parametrize("name", ["CONIN$", "CONOUT$", "COM¹", "LPT²"])
def test_paths_reject_extended_windows_device_names(name: str) -> None:
    with pytest.raises(ValueError, match="reserved Windows name"):
        runner._safe_relative_path(name, label="Fixture")


def test_local_manifest_rejects_unmanifested_pytest_controls(tmp_path: Path) -> None:
    _write_kit(tmp_path)
    (tmp_path / "pytest.ini").write_text(
        "[pytest]\naddopts=--collect-only\n", encoding="utf-8"
    )

    with pytest.raises((ValueError, RuntimeError), match="local correspondence"):
        runner._verify_manifest(tmp_path)


def test_runner_uses_no_runtime_assert_statements() -> None:
    source = Path(runner.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    runtime_asserts = [node for node in ast.walk(tree) if isinstance(node, ast.Assert)]
    assert runtime_asserts == []
