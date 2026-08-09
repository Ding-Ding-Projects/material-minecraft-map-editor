"""Safe, wx-independent integration with an external code editor.

The application never assumes that ``code`` is installed.  Detection is
bounded to the executable names and well-known per-user/system locations, and
opening a path returns a structured result instead of raising when a user has
not installed an editor or the configured path has gone stale.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Callable, Iterable, Mapping

from amulet_map_editor.api import config

EDITOR_CONFIG_ID = "external_editor"
MAX_PATH_LENGTH = 4096


@dataclass(frozen=True)
class EditorCandidate:
    """An executable discovered on this machine."""

    path: Path
    label: str
    source: str


@dataclass(frozen=True)
class EditorResult:
    """The non-blocking outcome of validation or an editor launch."""

    ok: bool
    status: str
    message: str
    command: tuple[str, ...] = ()


def _normalise_path(value: str | os.PathLike[str] | None) -> Path | None:
    if value is None:
        return None
    text = os.path.expandvars(os.fspath(value)).strip()
    if not text or len(text) > MAX_PATH_LENGTH:
        return None
    return Path(text).expanduser()


def validate_editor_path(value: str | os.PathLike[str] | None) -> EditorResult:
    """Validate a selected executable without attempting to run it."""

    path = _normalise_path(value)
    if path is None:
        return EditorResult(
            False, "not_configured", "No external editor is configured."
        )
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError):
        return EditorResult(
            False, "unavailable", f"External editor was not found: {path}"
        )
    if not resolved.is_file():
        return EditorResult(
            False, "unavailable", f"External editor is not a file: {resolved}"
        )
    return EditorResult(True, "available", f"External editor ready: {resolved}")


def load_selected() -> str:
    """Return the persisted executable path, or an empty string."""

    raw = config.get(EDITOR_CONFIG_ID, {})
    if not isinstance(raw, dict):
        return ""
    value = raw.get("path", "")
    return value if isinstance(value, str) else ""


def select_editor(value: str | os.PathLike[str] | None) -> EditorResult:
    """Persist a valid executable path, or leave the previous choice intact."""

    result = validate_editor_path(value)
    if not result.ok:
        return result
    path = str(_normalise_path(value).resolve())  # type: ignore[union-attr]
    config.put(EDITOR_CONFIG_ID, {"path": path})
    return EditorResult(True, "selected", f"Selected external editor: {path}")


def clear_selected() -> None:
    """Forget the selected editor without touching other preferences."""

    config.put(EDITOR_CONFIG_ID, {"path": ""})


def _candidate_paths(
    environ: Mapping[str, str], platform: str, which: Callable[[str], str | None]
) -> Iterable[EditorCandidate]:
    names = ("code", "code-insiders")
    for name in names:
        found = which(name)
        if found:
            yield EditorCandidate(Path(found), name, "PATH")
        if platform.startswith("win"):
            found = which(f"{name}.cmd")
            if found:
                yield EditorCandidate(Path(found), name, "PATH")

    home = Path(environ.get("USERPROFILE") or environ.get("HOME") or "~").expanduser()
    roots = [
        Path(environ.get("LOCALAPPDATA", "")) / "Programs",
        Path(environ.get("ProgramFiles", "")),
        Path(environ.get("ProgramFiles(x86)", "")),
        home / "scoop" / "apps",
    ]
    products = (
        ("Microsoft VS Code", "code", "Visual Studio Code"),
        ("Microsoft VS Code Insiders", "code-insiders", "Visual Studio Code Insiders"),
    )
    for root in roots:
        if not str(root):
            continue
        for folder, command, label in products:
            base = root / folder
            for path in (
                base / "bin" / f"{command}.cmd",
                base / "bin" / command,
                base / ("Code - Insiders.exe" if "Insiders" in folder else "Code.exe"),
                root
                / ("vscode-insiders" if "Insiders" in folder else "vscode")
                / "current"
                / ("Code - Insiders.exe" if "Insiders" in folder else "Code.exe"),
            ):
                yield EditorCandidate(path, label, "standard location")

    portable = environ.get("VSCODE_PORTABLE")
    if portable:
        data = Path(portable).expanduser()
        for path, label in (
            (data.parent / "Code.exe", "Visual Studio Code portable"),
            (
                data.parent / "Code - Insiders.exe",
                "Visual Studio Code Insiders portable",
            ),
            (data.parent / "code.cmd", "Visual Studio Code portable"),
        ):
            yield EditorCandidate(path, label, "VSCODE_PORTABLE")


def discover_editors(
    *,
    environ: Mapping[str, str] | None = None,
    platform: str | None = None,
    which: Callable[[str], str | None] = shutil.which,
) -> tuple[EditorCandidate, ...]:
    """Find unique existing VS Code executables in deterministic order."""

    environment = dict(os.environ if environ is None else environ)
    candidates: list[EditorCandidate] = []
    seen: set[Path] = set()
    for candidate in _candidate_paths(environment, platform or sys.platform, which):
        try:
            path = candidate.path.expanduser().resolve(strict=True)
        except (OSError, RuntimeError):
            continue
        if not path.is_file() or path in seen:
            continue
        seen.add(path)
        candidates.append(EditorCandidate(path, candidate.label, candidate.source))
    return tuple(candidates)


def open_path(
    target: str | os.PathLike[str],
    *,
    editor: str | os.PathLike[str] | None = None,
    runner: Callable[..., object] = subprocess.Popen,
) -> EditorResult:
    """Open a file or folder, treating folders as VS Code workspace roots."""

    path = _normalise_path(target)
    if path is None:
        return EditorResult(
            False, "invalid_target", "The exported path is empty or too long."
        )
    try:
        target_path = path.resolve(strict=True)
    except (OSError, RuntimeError):
        return EditorResult(
            False, "invalid_target", f"Exported path was not found: {path}"
        )
    if not target_path.is_file() and not target_path.is_dir():
        return EditorResult(
            False, "invalid_target", f"Exported path is not openable: {target_path}"
        )

    selected = (
        _normalise_path(editor)
        if editor is not None
        else _normalise_path(load_selected())
    )
    if selected is None:
        discovered = discover_editors()
        selected = discovered[0].path if discovered else None
    validation = validate_editor_path(selected)
    if not validation.ok:
        return validation
    executable = str(selected.resolve())  # type: ignore[union-attr]
    command = (
        (executable, "--reuse-window", "--folder-uri", target_path.as_uri())
        if target_path.is_dir()
        else (executable, "--reuse-window", str(target_path))
    )
    try:
        runner(command, close_fds=True)
    except (OSError, ValueError) as exc:
        return EditorResult(
            False, "launch_failed", f"Could not open the exported path: {exc}", command
        )
    return EditorResult(
        True, "opened", f"Opened {target_path.name} in the external editor.", command
    )
