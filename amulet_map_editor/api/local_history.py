"""Append-only, local Git-backed history for application-owned records.

The history repository deliberately lives in the application's data directory,
never in a project opened by the user.  This module has no wx dependency so it
can be used by settings, notifications, and future history panels alike.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

SCHEMA_VERSION = 1
MAX_IDENTIFIER_LENGTH = 160
MAX_TYPE_LENGTH = 80
MAX_PAYLOAD_BYTES = 1024 * 1024
MAX_EVENT_BYTES = (MAX_PAYLOAD_BYTES * 2) + (64 * 1024)
MAX_QUERY_LENGTH = 256
MAX_EXPORT_EVENTS = 10_000
_ACTIONS = frozenset(("created", "updated", "deleted", "restored"))


class LocalHistoryError(RuntimeError):
    """Raised when a history operation cannot be completed safely."""


class HistoryValidationError(LocalHistoryError, ValueError):
    """Raised when an event or record exceeds the bounded history contract."""


def default_history_root() -> Path:
    """Return an application-data path, independent of any opened project."""

    override = os.environ.get("AMULET_HISTORY_DIR")
    if override:
        return Path(override).expanduser().resolve()
    if os.name == "nt":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    elif os.name == "darwin":
        base = str(Path.home() / "Library" / "Application Support")
    else:
        base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return (Path(base) / "AmuletMapEditor" / "history").resolve()


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _json_bytes(value: Any, *, max_bytes: int = MAX_PAYLOAD_BYTES) -> bytes:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise HistoryValidationError(
            "record payload must be finite, JSON-serialisable UTF-8"
        ) from exc
    if len(encoded) > max_bytes:
        raise HistoryValidationError(f"JSON value exceeds {max_bytes} bytes")
    return encoded


def _validate_text(value: str, name: str, limit: int) -> str:
    if not isinstance(value, str) or not value or len(value) > limit:
        raise HistoryValidationError(
            f"{name} must be non-empty and at most {limit} characters"
        )
    if "\x00" in value:
        raise HistoryValidationError(f"{name} must not contain NUL")
    return value


def _parse_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HistoryValidationError("history timestamp is invalid") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True)
class HistoryEvent:
    """One immutable event in the local history stream."""

    event_id: str
    record_id: str
    record_type: str
    action: str
    timestamp: str
    before: Any
    after: Any

    @property
    def payload(self) -> Any:
        """The state produced by the event (``None`` means deleted)."""

        return self.after

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "event_id": self.event_id,
            "record_id": self.record_id,
            "record_type": self.record_type,
            "action": self.action,
            "timestamp": self.timestamp,
            "before": self.before,
            "after": self.after,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "HistoryEvent":
        required = {
            "schema_version",
            "event_id",
            "record_id",
            "record_type",
            "action",
            "timestamp",
            "before",
            "after",
        }
        if set(value) != required or value["schema_version"] != SCHEMA_VERSION:
            raise LocalHistoryError("history event schema is unsupported or incomplete")
        event_id = _validate_text(value["event_id"], "event_id", 64)
        record_id = _validate_text(
            value["record_id"], "record_id", MAX_IDENTIFIER_LENGTH
        )
        record_type = _validate_text(
            value["record_type"], "record_type", MAX_TYPE_LENGTH
        )
        action = _validate_text(value["action"], "action", 16)
        if action not in _ACTIONS:
            raise LocalHistoryError("history event action is unsupported")
        timestamp = _validate_text(value["timestamp"], "timestamp", 40)
        _parse_time(timestamp)
        _json_bytes(value["before"])
        _json_bytes(value["after"])
        return cls(
            event_id,
            record_id,
            record_type,
            action,
            timestamp,
            value["before"],
            value["after"],
        )


class LocalHistory:
    """Store application-owned snapshots in an isolated local Git repository.

    ``root`` should be an application-data directory, not a project directory.
    The class creates ``records/`` and ``events/`` inside that directory and
    commits each change without rewriting prior events.  History failures can
    be contained with :meth:`safe_record`, :meth:`safe_delete`, and
    :meth:`safe_restore` so a settings or document operation never fails just
    because its audit trail is unavailable.
    """

    def __init__(self, root: str | os.PathLike[str] | None = None):
        self.root = (
            Path(root).expanduser().resolve()
            if root is not None
            else default_history_root()
        )
        self.events_dir = self.root / "events"
        self.records_dir = self.root / "records"
        self._lock = threading.RLock()
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            self.events_dir.mkdir(exist_ok=True)
            self.records_dir.mkdir(exist_ok=True)
            self._initialise_repository()
        except (OSError, LocalHistoryError, subprocess.SubprocessError) as exc:
            raise LocalHistoryError(
                f"unable to initialise local history at {self.root}"
            ) from exc

    @classmethod
    def try_create(
        cls, root: str | os.PathLike[str] | None = None
    ) -> "LocalHistory | None":
        """Create a store or return ``None`` without affecting the caller."""

        try:
            return cls(root)
        except Exception:
            return None

    def _git(
        self, args: Sequence[str], *, check: bool = True
    ) -> subprocess.CompletedProcess[str]:
        try:
            result = subprocess.run(
                ["git", *args],
                cwd=self.root,
                text=True,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
        except OSError as exc:
            raise LocalHistoryError("git is unavailable for local history") from exc
        if check and result.returncode:
            detail = (result.stderr or result.stdout).strip()[:400]
            raise LocalHistoryError(f"git local history operation failed: {detail}")
        return result

    def _initialise_repository(self) -> None:
        if not (self.root / ".git").exists():
            self._git(["init", "--quiet"])
            self._git(["config", "user.name", "Amulet Map Editor (local history)"])
            self._git(["config", "user.email", "history@localhost"])
            self._write_json(
                self.root / "history.json", {"schema_version": SCHEMA_VERSION}
            )
            self._commit("Initialize local history")

    @staticmethod
    def _key(record_id: str) -> str:
        return hashlib.sha256(record_id.encode("utf-8")).hexdigest()

    @staticmethod
    def _event_path(events_dir: Path, event_id: str) -> Path:
        return events_dir / f"{event_id}.json"

    @staticmethod
    def _write_json(
        path: Path, value: Any, *, max_bytes: int = MAX_PAYLOAD_BYTES
    ) -> None:
        encoded = _json_bytes(value, max_bytes=max_bytes)
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            temporary.write_bytes(encoded)
            os.replace(temporary, path)
        finally:
            if temporary.exists():
                temporary.unlink()

    def _read_current(self, record_id: str) -> Any:
        path = self.records_dir / f"{self._key(record_id)}.json"
        if not path.exists():
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            _json_bytes(value)
            return value
        except (OSError, json.JSONDecodeError, HistoryValidationError) as exc:
            raise LocalHistoryError("local history record is corrupt") from exc

    def _commit(self, message: str) -> str | None:
        self._git(["add", "--all"])
        staged = self._git(["diff", "--cached", "--quiet"], check=False)
        if staged.returncode == 0:
            return None
        result = self._git(["commit", "--quiet", "-m", message])
        return self._git(["rev-parse", "HEAD"]).stdout.strip()

    def record(
        self,
        record_id: str,
        payload: Any,
        *,
        record_type: str = "record",
        action: str | None = None,
    ) -> HistoryEvent | None:
        """Append a created, updated, restored, or deleted snapshot event."""

        record_id = _validate_text(record_id, "record_id", MAX_IDENTIFIER_LENGTH)
        record_type = _validate_text(record_type, "record_type", MAX_TYPE_LENGTH)
        if action is not None and action not in _ACTIONS:
            raise HistoryValidationError(f"action must be one of {sorted(_ACTIONS)}")
        if payload is not None:
            _json_bytes(payload)
        with self._lock:
            before = self._read_current(record_id)
            if action is None:
                action = "created" if before is None else "updated"
            if action == "created" and before is not None:
                action = "updated"
            if action == "updated" and before is None:
                action = "created"
            if action == "deleted":
                payload = None
            if before == payload and action != "restored":
                return None
            event = HistoryEvent(
                event_id=uuid.uuid4().hex,
                record_id=record_id,
                record_type=record_type,
                action=action,
                timestamp=_utc_now(),
                before=before,
                after=payload,
            )
            self._write_json(
                self._event_path(self.events_dir, event.event_id),
                event.to_dict(),
                max_bytes=MAX_EVENT_BYTES,
            )
            record_path = self.records_dir / f"{self._key(record_id)}.json"
            if payload is None:
                record_path.unlink(missing_ok=True)
            else:
                self._write_json(record_path, payload)
            self._commit(f"{action.capitalize()} {record_type} {record_id[:48]}")
            return event

    def delete(
        self, record_id: str, *, record_type: str = "record"
    ) -> HistoryEvent | None:
        return self.record(record_id, None, record_type=record_type, action="deleted")

    def restore(self, event_id: str) -> HistoryEvent:
        """Restore the state immediately before an event, as a new event."""

        event = self.get_event(event_id)
        if event is None:
            raise LocalHistoryError("history event was not found")
        return (
            self.record(
                event.record_id,
                event.before,
                record_type=event.record_type,
                action="restored",
            )
            or event
        )

    def get_event(self, event_id: str) -> HistoryEvent | None:
        event_id = _validate_text(event_id, "event_id", 64)
        path = self._event_path(self.events_dir, event_id)
        if not path.exists():
            return None
        try:
            return HistoryEvent.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError, LocalHistoryError) as exc:
            raise LocalHistoryError("local history event is corrupt") from exc

    def events(
        self,
        query: str = "",
        *,
        actions: Iterable[str] | None = None,
        record_type: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        regex: bool = False,
        limit: int = MAX_EXPORT_EVENTS,
    ) -> tuple[HistoryEvent, ...]:
        """Return filtered events; plain text is the default search mode."""

        if len(query) > MAX_QUERY_LENGTH:
            raise HistoryValidationError(
                f"query is limited to {MAX_QUERY_LENGTH} characters"
            )
        if limit < 1 or limit > MAX_EXPORT_EVENTS:
            raise HistoryValidationError(
                f"limit must be between 1 and {MAX_EXPORT_EVENTS}"
            )
        action_set = None if actions is None else frozenset(actions)
        if action_set is not None and not action_set.issubset(_ACTIONS):
            raise HistoryValidationError("actions contains an unsupported value")
        if record_type is not None:
            record_type = _validate_text(record_type, "record_type", MAX_TYPE_LENGTH)
        matcher = None
        if query and regex:
            try:
                matcher = re.compile(query)
            except re.error as exc:
                raise HistoryValidationError(
                    "query is not a valid regular expression"
                ) from exc
        since_utc = (
            (
                since.astimezone(timezone.utc)
                if since.tzinfo
                else since.replace(tzinfo=timezone.utc)
            )
            if since
            else None
        )
        until_utc = (
            (
                until.astimezone(timezone.utc)
                if until.tzinfo
                else until.replace(tzinfo=timezone.utc)
            )
            if until
            else None
        )
        found: list[HistoryEvent] = []
        with self._lock:
            for path in sorted(self.events_dir.glob("*.json")):
                event = self.get_event(path.stem)
                if event is None:
                    continue
                if action_set is not None and event.action not in action_set:
                    continue
                if record_type is not None and event.record_type != record_type:
                    continue
                stamp = _parse_time(event.timestamp)
                if since_utc and stamp < since_utc:
                    continue
                if until_utc and stamp > until_utc:
                    continue
                if query:
                    haystack = " ".join(
                        (event.record_id, event.record_type, event.action)
                    )
                    if matcher is not None:
                        if matcher.search(haystack) is None:
                            continue
                    elif query.casefold() not in haystack.casefold():
                        continue
                found.append(event)
        found.sort(key=lambda item: (item.timestamp, item.event_id), reverse=True)
        return tuple(found[:limit])

    def export_json(self, **filters: Any) -> str:
        events = self.events(**filters)
        return json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "events": [event.to_dict() for event in events],
            },
            ensure_ascii=False,
            indent=2,
        )

    def export_markdown(self, **filters: Any) -> str:
        events = self.events(**filters)
        lines = ["# Local history", "", f"Events: {len(events)}", ""]
        for event in events:
            lines.extend(
                [
                    f"## {event.action.title()} — `{event.record_id}`",
                    f"- Type: `{event.record_type}`",
                    f"- Time: `{event.timestamp}`",
                    f"- Event: `{event.event_id}`",
                    "",
                ]
            )
        return "\n".join(lines)

    def export(
        self, path: str | os.PathLike[str], *, format: str = "json", **filters: Any
    ) -> Path:
        target = Path(path).expanduser().resolve()
        if format not in {"json", "markdown"}:
            raise HistoryValidationError("format must be json or markdown")
        content = (
            self.export_json(**filters)
            if format == "json"
            else self.export_markdown(**filters)
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")
        return target

    # Safe wrappers are intentionally broad: history is audit support, never
    # a reason to fail the operation that changed the user's data.
    def safe_record(self, *args: Any, **kwargs: Any) -> HistoryEvent | None:
        try:
            return self.record(*args, **kwargs)
        except Exception:
            return None

    def safe_delete(self, *args: Any, **kwargs: Any) -> HistoryEvent | None:
        try:
            return self.delete(*args, **kwargs)
        except Exception:
            return None

    def safe_restore(self, *args: Any, **kwargs: Any) -> HistoryEvent | None:
        try:
            return self.restore(*args, **kwargs)
        except Exception:
            return None


def safe_record(
    record_id: str,
    payload: Any,
    *,
    record_type: str = "record",
    root: str | os.PathLike[str] | None = None,
) -> HistoryEvent | None:
    """One-shot, non-blocking helper for primary operations."""

    store = LocalHistory.try_create(root)
    return (
        store.safe_record(record_id, payload, record_type=record_type)
        if store
        else None
    )
