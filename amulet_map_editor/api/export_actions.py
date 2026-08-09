"""Shared actions for opening generated exports in the configured editor.

Export producers should not duplicate editor discovery, path validation, or
failure handling.  This small wx-independent adapter keeps the action safe to
call from native dialogs and from tests without ever making an editor a hard
dependency of an export.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from amulet_map_editor.api import external_editor


@dataclass(frozen=True)
class ExportEditorAction:
    """The export target and the structured editor outcome."""

    target: Path
    result: external_editor.EditorResult

    @property
    def ok(self) -> bool:
        return self.result.ok

    @property
    def message(self) -> str:
        return self.result.message


def open_exported_path(
    target: str | Path,
    *,
    opener: Callable[[str | Path], external_editor.EditorResult] | None = None,
) -> ExportEditorAction:
    """Open an exported file/folder, returning a safe non-throwing result.

    ``opener`` is injectable for wx-independent tests.  Unexpected launcher
    failures are converted into the same structured result contract as the
    external-editor bridge, so a missing or broken editor cannot fail export.
    """

    path = Path(target).expanduser()
    launch = opener or external_editor.open_path
    try:
        result = launch(path)
    except Exception as exc:  # pragma: no cover - defensive boundary
        result = external_editor.EditorResult(
            False, "launch_failed", f"Could not open the exported path: {exc}"
        )
    return ExportEditorAction(path, result)
