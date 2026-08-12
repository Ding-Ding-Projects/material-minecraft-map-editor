"""Orchestrates one conversion or a batch, and records local history.

This is the only module a UI surface calls into. It never overwrites a
source file, always writes its output atomically, and always reports a
batch's outcomes as four honestly separate counts -- converted, skipped,
cancelled, failed -- rather than collapsing them into one number.
"""

from __future__ import annotations

import os
import tempfile
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, List, Optional, Sequence

from amulet_map_editor.api import config
from amulet_map_editor.api.converter import sandbox
from amulet_map_editor.api.converter.registry import (
    Adapter,
    adapters_for_source,
    get_adapter,
)
from amulet_map_editor.api.converter.signatures import detect_format_full

HISTORY_IDENTIFIER = "converter_history"
#: Bounded so the history record itself cannot grow without limit.
MAX_HISTORY_ENTRIES = 500


class ConvertOutcome(Enum):
    CONVERTED = "converted"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"
    FAILED = "failed"


@dataclass(frozen=True)
class ConvertResult:
    source_path: str
    outcome: ConvertOutcome
    adapter_id: Optional[str] = None
    output_path: Optional[str] = None
    reason: str = ""
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True)
class BatchOutcome:
    results: Sequence[ConvertResult]

    @property
    def converted(self) -> int:
        return sum(1 for r in self.results if r.outcome is ConvertOutcome.CONVERTED)

    @property
    def skipped(self) -> int:
        return sum(1 for r in self.results if r.outcome is ConvertOutcome.SKIPPED)

    @property
    def cancelled(self) -> int:
        return sum(1 for r in self.results if r.outcome is ConvertOutcome.CANCELLED)

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if r.outcome is ConvertOutcome.FAILED)


#: Backwards/forwards-friendly alias -- some callers read a batch result as
#: one object rather than reaching into ``.results``.
BatchResult = BatchOutcome


def detect_source(
    path: str, *, max_read_bytes: int = 64 * 1024 * 1024
) -> Optional[str]:
    """Detect a file's real format from its bytes, bounded by size."""
    size = os.path.getsize(path)
    if size > max_read_bytes:
        # Detection itself still reads only a bounded prefix; a JSON file
        # over the bound cannot be confirmed in full, so it is reported as
        # unknown rather than accepted on a partial parse.
        with open(path, "rb") as fp:
            prefix = fp.read(65536)
        from amulet_map_editor.api.converter.signatures import detect_format

        fmt = detect_format(prefix)
        return None if fmt == "json" else fmt
    with open(path, "rb") as fp:
        data = fp.read()
    return detect_format_full(data)


def _atomic_write(destination: str, data: bytes) -> None:
    directory = os.path.dirname(destination) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".convert-", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fp:
            fp.write(data)
            fp.flush()
            os.fsync(fp.fileno())
        os.replace(tmp_path, destination)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


def _record_history(result: ConvertResult) -> None:
    entries = config.get(HISTORY_IDENTIFIER, [])
    if not isinstance(entries, list):
        entries = []
    entries.append(
        {
            "source_path": result.source_path,
            "outcome": result.outcome.value,
            "adapter_id": result.adapter_id,
            "output_path": result.output_path,
            "reason": result.reason,
            "timestamp": result.timestamp,
        }
    )
    entries = entries[-MAX_HISTORY_ENTRIES:]
    config.put(HISTORY_IDENTIFIER, entries)


def read_history() -> List[dict]:
    entries = config.get(HISTORY_IDENTIFIER, [])
    return list(entries) if isinstance(entries, list) else []


def clear_history() -> None:
    config.put(HISTORY_IDENTIFIER, [])


def convert_one(
    source_path: str,
    adapter_id: str,
    destination_path: str,
    *,
    overwrite_confirmed: bool = False,
    record: bool = True,
) -> ConvertResult:
    """Convert one file. Never overwrites the source; never guesses."""
    adapter = get_adapter(adapter_id)
    if adapter is None:
        result = ConvertResult(
            source_path, ConvertOutcome.FAILED, adapter_id, reason="Unknown adapter"
        )
        if record:
            _record_history(result)
        return result

    if os.path.abspath(destination_path) == os.path.abspath(source_path):
        result = ConvertResult(
            source_path,
            ConvertOutcome.SKIPPED,
            adapter_id,
            reason="Destination would overwrite the source file",
        )
        if record:
            _record_history(result)
        return result

    if os.path.exists(destination_path) and not overwrite_confirmed:
        result = ConvertResult(
            source_path,
            ConvertOutcome.SKIPPED,
            adapter_id,
            reason="Destination already exists and was not confirmed for overwrite",
        )
        if record:
            _record_history(result)
        return result

    try:
        if not os.path.isfile(source_path):
            raise ValueError("Source file does not exist")
        with open(source_path, "rb") as fp:
            data = fp.read()
        detected = detect_format_full(data)
        if detected != adapter.source_format:
            raise ValueError(
                f"Source bytes were detected as {detected!r}, not the "
                f"{adapter.source_format!r} this adapter requires -- refusing "
                "to guess"
            )
    except (OSError, ValueError) as exc:
        result = ConvertResult(
            source_path, ConvertOutcome.SKIPPED, adapter_id, reason=str(exc)
        )
        if record:
            _record_history(result)
        return result

    outcome = sandbox.run_adapter(adapter, data)
    if not outcome.ok:
        result = ConvertResult(
            source_path,
            ConvertOutcome.FAILED,
            adapter_id,
            reason=f"{outcome.status}: {outcome.message}",
        )
        if record:
            _record_history(result)
        return result

    try:
        _atomic_write(destination_path, outcome.data)
    except OSError as exc:
        result = ConvertResult(
            source_path,
            ConvertOutcome.FAILED,
            adapter_id,
            reason=f"Could not write output: {exc}",
        )
        if record:
            _record_history(result)
        return result

    result = ConvertResult(
        source_path, ConvertOutcome.CONVERTED, adapter_id, output_path=destination_path
    )
    if record:
        _record_history(result)
    return result


def convert_batch(
    jobs: Sequence[dict],
    *,
    should_cancel: Optional[Callable[[], bool]] = None,
    on_progress: Optional[Callable[[int, int, ConvertResult], None]] = None,
) -> BatchOutcome:
    """Convert a batch of ``{"source_path", "adapter_id", "destination_path",
    "overwrite_confirmed"}`` jobs, honouring cancellation between files.

    ``should_cancel`` is polled before each file starts; once it returns
    True every remaining job is reported as cancelled rather than silently
    dropped, so a batch report always accounts for every job it was given.
    """
    results: List[ConvertResult] = []
    total = len(jobs)
    cancelled_from = None
    for index, job in enumerate(jobs):
        if cancelled_from is not None or (should_cancel and should_cancel()):
            if cancelled_from is None:
                cancelled_from = index
            result = ConvertResult(
                job["source_path"],
                ConvertOutcome.CANCELLED,
                job.get("adapter_id"),
                reason="Batch was cancelled before this file started",
            )
            _record_history(result)
        else:
            result = convert_one(
                job["source_path"],
                job["adapter_id"],
                job["destination_path"],
                overwrite_confirmed=bool(job.get("overwrite_confirmed", False)),
            )
        results.append(result)
        if on_progress:
            on_progress(index + 1, total, result)
    return BatchOutcome(results)


def compatible_targets(source_path: str) -> Sequence[Adapter]:
    fmt = detect_source(source_path)
    return adapters_for_source(fmt)
