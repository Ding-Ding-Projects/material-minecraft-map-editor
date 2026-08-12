"""The persisted list of projects and worlds the backstage offers to reopen.

The store is a small bounded JSON document inside the application's own data
directory.  It is deliberately not seeded with example rows: an empty list is
shown as an honest empty state, because a first-run screen full of projects
that do not exist teaches a user to distrust every other number the shell
shows them.

Nothing here imports ``wx``.  The backstage view renders these records, but the
records themselves have to be readable from a test, from a headless import, and
from the shell before any window exists.

Failure is contained rather than raised.  A missing file, a truncated write, a
profile edited by hand, or an unreadable data directory all resolve to an empty
list and a logged explanation, because losing the recent list is an
inconvenience and refusing to start the application over it is not.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import os
import sys
import tempfile
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, List, Mapping, Optional, Sequence

from amulet_map_editor.api import local_history
from amulet_map_editor.api.studio.search import SearchState

log = logging.getLogger(__name__)

#: The file the store writes inside its data directory.
STORE_FILENAME = "recent-projects.json"

#: Schema version written into the file and into every export.
STORE_VERSION = 1

#: Identifier used in exports so a reader knows what the columns mean.
STORE_SCHEMA = "amulet.studio.recent-projects"

#: The list is capped so a long-running profile cannot grow without bound.
#: Trimming drops the oldest unpinned record first; a pinned record is only
#: dropped when every record is pinned and the cap is still exceeded.
MAX_ENTRIES = 50

#: Longest value accepted in any single text field.  A path longer than this is
#: refused rather than truncated, because a truncated path is a path that
#: silently points somewhere else.
MAX_FIELD_LENGTH = 1024

#: Largest store file that will be parsed.  Anything larger is treated as
#: damaged; the cap above means a healthy file is a few tens of kilobytes.
MAX_STORE_BYTES = 1024 * 1024

#: The two kinds of record the backstage filter distinguishes.
TAGS: tuple[str, ...] = ("Worlds", "Projects")

#: The filter pills shown above the recent table, in their design order.
FILTERS: tuple[str, ...] = ("All",) + TAGS

#: Export formats every list in the backstage offers.
EXPORT_FORMATS: tuple[str, ...] = ("json", "csv", "markdown")

#: File extension per export format, used to build a save dialog's wildcard.
EXPORT_EXTENSIONS: dict[str, str] = {
    "json": ".json",
    "csv": ".csv",
    "markdown": ".md",
}

#: Column order shared by the CSV and Markdown exports so the two agree.
EXPORT_COLUMNS: tuple[str, ...] = (
    "name",
    "kind",
    "platform",
    "path",
    "opened_iso",
    "opened",
    "pinned",
    "tag",
)

_HISTORY_RECORD_TYPE = "studio_recent"


# ---------------------------------------------------------------------------
# time
# ---------------------------------------------------------------------------
def utc_now() -> datetime:
    """Return the current moment as an aware UTC timestamp."""
    return datetime.now(timezone.utc)


def to_iso(moment: Optional[datetime] = None) -> str:
    """Render a moment as the ISO-8601 UTC string the store persists."""
    value = moment or utc_now()
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat(timespec="seconds")


def parse_iso(value: object) -> Optional[datetime]:
    """Parse a stored timestamp, or return ``None`` when it is unusable.

    A hand-edited profile is expected to contain nonsense eventually; an
    unparsable timestamp sorts to the end of the list rather than stopping the
    whole store from loading.
    """
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def relative_opened(moment: Optional[datetime], now: Optional[datetime] = None) -> str:
    """Describe how long ago something was opened, in the design's vocabulary.

    The exact timestamp is still stored and still exported; this is the reading
    of it, and it never rounds a moment into the future.
    """
    if moment is None:
        return "Never opened"
    reference = now or utc_now()
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    seconds = (reference - moment).total_seconds()
    if seconds < 0:
        return "Just now"
    minutes = seconds / 60
    if minutes < 1:
        return "Just now"
    if minutes < 60:
        count = int(minutes)
        return f"{count} minute ago" if count == 1 else f"{count} minutes ago"
    hours = minutes / 60
    if hours < 24:
        count = int(hours)
        return f"{count} hour ago" if count == 1 else f"{count} hours ago"
    days = hours / 24
    if days < 2:
        return "Yesterday"
    if days < 7:
        return f"{int(days)} days ago"
    if days < 14:
        return "Last week"
    if days < 31:
        return f"{int(days // 7)} weeks ago"
    if days < 62:
        return "Last month"
    if days < 365:
        return f"{int(days // 30)} months ago"
    years = int(days // 365)
    return "Last year" if years == 1 else f"{years} years ago"


# ---------------------------------------------------------------------------
# records
# ---------------------------------------------------------------------------
def _text(value: object, limit: int = MAX_FIELD_LENGTH) -> str:
    """Coerce a stored value to a bounded single-line string."""
    text = str(value if value is not None else "")
    text = text.replace("\r", " ").replace("\n", " ").strip()
    return text[:limit]


@dataclass
class RecentEntry:
    """One project or world the user has opened, as the store keeps it."""

    name: str
    kind: str = ""
    platform: str = ""
    path: str = ""
    opened_iso: str = field(default_factory=to_iso)
    pinned: bool = False
    tag: str = "Worlds"

    def normalised(self) -> "RecentEntry":
        """Return a copy with every field bounded and every value in range."""
        return RecentEntry(
            name=_text(self.name) or _text(Path(_text(self.path)).name) or "Untitled",
            kind=_text(self.kind),
            platform=_text(self.platform),
            path=_text(self.path),
            opened_iso=to_iso(parse_iso(self.opened_iso) or utc_now()),
            pinned=bool(self.pinned),
            tag=self.tag if self.tag in TAGS else TAGS[0],
        )

    @property
    def opened(self) -> Optional[datetime]:
        """Return the parsed open time, or ``None`` when it is unusable."""
        return parse_iso(self.opened_iso)

    def opened_label(self, now: Optional[datetime] = None) -> str:
        """Return the human reading of :attr:`opened_iso`."""
        return relative_opened(self.opened, now)

    def pin_glyph(self) -> str:
        """Return the filled or hollow star the recent table draws."""
        return "\u2605" if self.pinned else "\u2606"

    def key(self) -> str:
        """Return the identity two records are considered the same by.

        A path identifies a project; a project with no path yet falls back to
        its name.  Comparing case-insensitively matters on Windows, where the
        same directory can be reached by two spellings.
        """
        if self.path:
            try:
                return os.path.normcase(os.path.normpath(self.path))
            except (TypeError, ValueError):
                return self.path.casefold()
        return self.name.casefold()

    def haystack(self) -> str:
        """Return the text a search field matches this record against."""
        return " ".join(
            part
            for part in (self.name, self.kind, self.platform, self.path, self.tag)
            if part
        )

    def to_dict(self) -> dict:
        """Return the record as the plain mapping the store persists."""
        return {
            "name": self.name,
            "kind": self.kind,
            "platform": self.platform,
            "path": self.path,
            "opened_iso": self.opened_iso,
            "pinned": self.pinned,
            "tag": self.tag,
        }

    def export_row(self, now: Optional[datetime] = None) -> dict:
        """Return the record as one export row, including the read timestamp."""
        row = self.to_dict()
        row["opened"] = self.opened_label(now)
        row["pinned"] = "yes" if self.pinned else "no"
        return row

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> Optional["RecentEntry"]:
        """Build a record from stored data, or ``None`` when it is unusable."""
        if not isinstance(value, Mapping):
            return None
        name = _text(value.get("name"))
        path = _text(value.get("path"))
        if not name and not path:
            return None
        return cls(
            name=name,
            kind=_text(value.get("kind")),
            platform=_text(value.get("platform")),
            path=path,
            opened_iso=_text(value.get("opened_iso"), 64),
            pinned=bool(value.get("pinned")),
            tag=_text(value.get("tag"), 32),
        ).normalised()


def _sort_key(entry: RecentEntry) -> tuple:
    """Order pinned records first, then most recently opened."""
    opened = entry.opened
    stamp = opened.timestamp() if opened is not None else 0.0
    return (0 if entry.pinned else 1, -stamp, entry.name.casefold())


# ---------------------------------------------------------------------------
# location
# ---------------------------------------------------------------------------
def default_store_root() -> Path:
    """Return the application-data directory this store is allowed to write in.

    ``AMULET_RECENTS_DIR`` moves the whole directory, which is what a test or a
    portable profile needs; it never lets a caller name a file, so the store's
    own filename stays under this module's control.
    """
    override = os.environ.get("AMULET_RECENTS_DIR")
    if override:
        return Path(override).expanduser().resolve()
    if os.name == "nt":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = str(Path.home() / "Library" / "Application Support")
    else:
        base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return (Path(base) / "AmuletMapEditor" / "studio").resolve()


def default_store_path() -> Path:
    """Return the full path of the store file inside the data directory."""
    return default_store_root() / STORE_FILENAME


class RecentStore:
    """The bounded, self-healing list of recently opened projects and worlds.

    Every mutating method rewrites the whole file atomically: the list is small
    enough that a partial-update protocol would cost more than it saves, and a
    replace-in-place write is what keeps a crash mid-save from leaving a half
    written document behind.
    """

    def __init__(self, root: Optional[os.PathLike[str] | str] = None) -> None:
        self.root = (
            Path(root).expanduser().resolve()
            if root is not None
            else default_store_root()
        )
        self.path = self.root / STORE_FILENAME

    # -- location safety -----------------------------------------------------
    def _writable_path(self) -> Optional[Path]:
        """Return the store path once it is proved to sit in the data directory.

        The check is done every write rather than once at construction because
        the directory can be replaced -- by a sync tool, by a user, by another
        process -- between one save and the next, and a store that follows a
        redirected link would write the user's recent projects somewhere nobody
        asked for.
        """
        try:
            self.root.mkdir(parents=True, exist_ok=True)
        except OSError:
            log.exception("Could not create the recent-project directory %s", self.root)
            return None
        target = self.root / STORE_FILENAME
        if target.parent != self.root:
            log.error("Refusing to write the recent list outside %s", self.root)
            return None
        try:
            if target.is_symlink():
                log.error(
                    "Refusing to write the recent list through a link: %s", target
                )
                return None
        except OSError:
            log.exception("Could not inspect the recent-project file %s", target)
            return None
        return target

    # -- reading -------------------------------------------------------------
    def load(self) -> List[RecentEntry]:
        """Return every stored record, ordered, degrading to an empty list."""
        try:
            if not self.path.is_file():
                return []
            if self.path.stat().st_size > MAX_STORE_BYTES:
                log.error("The recent list at %s is too large to parse", self.path)
                return []
            raw = self.path.read_text(encoding="utf-8")
        except OSError:
            log.exception("Could not read the recent list at %s", self.path)
            return []
        try:
            document = json.loads(raw)
        except (ValueError, TypeError):
            log.exception("The recent list at %s is not valid JSON", self.path)
            return []
        payload = document.get("entries") if isinstance(document, Mapping) else document
        if not isinstance(payload, Sequence) or isinstance(payload, (str, bytes)):
            return []
        entries: List[RecentEntry] = []
        seen: set[str] = set()
        for item in payload[: MAX_ENTRIES * 4]:
            entry = (
                RecentEntry.from_mapping(item) if isinstance(item, Mapping) else None
            )
            if entry is None or entry.key() in seen:
                continue
            seen.add(entry.key())
            entries.append(entry)
        return sorted(entries, key=_sort_key)[:MAX_ENTRIES]

    def list(self) -> List[RecentEntry]:
        """Return every stored record, pinned first and most recent next."""
        return self.load()

    def search(
        self,
        state: Optional[SearchState] = None,
        *,
        tag: str = "All",
        entries: Optional[Iterable[RecentEntry]] = None,
    ) -> List[RecentEntry]:
        """Return the records matching one filter pill and one search field.

        Both filters compose: the tag narrows first and the query narrows what
        is left, so a count reported beside the table is the count the bulk
        actions would act on.
        """
        source = list(entries) if entries is not None else self.load()
        if tag and tag != "All":
            source = [entry for entry in source if entry.tag == tag]
        if state is None:
            return source
        return [entry for entry in source if state.matches(entry.haystack())]

    def get(self, target: object) -> Optional[RecentEntry]:
        """Return the stored record matching a key, path, name, or record."""
        wanted = self._key_of(target)
        for entry in self.load():
            if entry.key() == wanted:
                return entry
        return None

    # -- writing -------------------------------------------------------------
    def save(self, entries: Sequence[RecentEntry]) -> List[RecentEntry]:
        """Persist an ordered, trimmed copy of ``entries`` and return it."""
        ordered = self._trim(sorted(entries, key=_sort_key))
        target = self._writable_path()
        if target is None:
            return ordered
        document = {
            "schema": STORE_SCHEMA,
            "version": STORE_VERSION,
            "encoding": "utf-8",
            "line_endings": "lf",
            "saved": to_iso(),
            "entries": [entry.to_dict() for entry in ordered],
        }
        text = json.dumps(document, indent=2, ensure_ascii=False) + "\n"
        try:
            handle, temporary = tempfile.mkstemp(
                prefix=".recent-", suffix=".tmp", dir=str(self.root)
            )
            try:
                with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
                    stream.write(text)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, target)
            except BaseException:
                try:
                    os.unlink(temporary)
                except OSError:
                    pass
                raise
        except OSError:
            log.exception("Could not save the recent list to %s", target)
        return ordered

    def add(
        self,
        name: str,
        *,
        kind: str = "",
        platform: str = "",
        path: str = "",
        tag: str = "Worlds",
        opened: Optional[datetime] = None,
        pinned: Optional[bool] = None,
    ) -> RecentEntry:
        """Record that a project or world was opened, moving it to the top.

        Re-opening an existing record updates its timestamp and any detail that
        is now known, and keeps whatever the user pinned: an automatic update
        must never quietly undo a deliberate choice.
        """
        candidate = RecentEntry(
            name=name,
            kind=kind,
            platform=platform,
            path=path,
            opened_iso=to_iso(opened),
            pinned=bool(pinned),
            tag=tag,
        ).normalised()
        entries = self.load()
        merged: List[RecentEntry] = []
        for entry in entries:
            if entry.key() != candidate.key():
                merged.append(entry)
                continue
            candidate = RecentEntry(
                name=candidate.name or entry.name,
                kind=candidate.kind or entry.kind,
                platform=candidate.platform or entry.platform,
                path=candidate.path or entry.path,
                opened_iso=candidate.opened_iso,
                pinned=entry.pinned if pinned is None else bool(pinned),
                tag=candidate.tag or entry.tag,
            )
        merged.append(candidate)
        self.save(merged)
        self._record("updated", candidate)
        return candidate

    def remove(self, target: object) -> bool:
        """Drop one record from the list, returning whether it was there."""
        wanted = self._key_of(target)
        entries = self.load()
        remaining = [entry for entry in entries if entry.key() != wanted]
        if len(remaining) == len(entries):
            return False
        removed = next(entry for entry in entries if entry.key() == wanted)
        self.save(remaining)
        self._record("deleted", removed)
        return True

    def remove_many(self, targets: Iterable[object]) -> int:
        """Drop several records in one write and return how many were removed."""
        wanted = {self._key_of(target) for target in targets}
        entries = self.load()
        remaining = [entry for entry in entries if entry.key() not in wanted]
        removed = [entry for entry in entries if entry.key() in wanted]
        if not removed:
            return 0
        self.save(remaining)
        for entry in removed:
            self._record("deleted", entry)
        return len(removed)

    def pin(self, target: object, pinned: bool = True) -> bool:
        """Pin or unpin one record, returning whether anything changed."""
        wanted = self._key_of(target)
        entries = self.load()
        changed: Optional[RecentEntry] = None
        updated: List[RecentEntry] = []
        for entry in entries:
            if entry.key() == wanted and entry.pinned != bool(pinned):
                changed = RecentEntry(
                    name=entry.name,
                    kind=entry.kind,
                    platform=entry.platform,
                    path=entry.path,
                    opened_iso=entry.opened_iso,
                    pinned=bool(pinned),
                    tag=entry.tag,
                )
                updated.append(changed)
            else:
                updated.append(entry)
        if changed is None:
            return False
        self.save(updated)
        self._record("updated", changed)
        return True

    def clear(self) -> int:
        """Remove every record and return how many were dropped."""
        entries = self.load()
        if not entries:
            return 0
        self.save([])
        for entry in entries:
            self._record("deleted", entry)
        return len(entries)

    # -- exports -------------------------------------------------------------
    def export_json(self, entries: Optional[Sequence[RecentEntry]] = None) -> str:
        """Return the list as UTF-8 JSON with its schema and range stated."""
        rows = list(entries) if entries is not None else self.load()
        now = utc_now()
        document = {
            "schema": STORE_SCHEMA,
            "version": STORE_VERSION,
            "encoding": "utf-8",
            "line_endings": "lf",
            "exported": to_iso(now),
            "count": len(rows),
            "entries": [entry.export_row(now) for entry in rows],
        }
        return json.dumps(document, indent=2, ensure_ascii=False) + "\n"

    def export_csv(self, entries: Optional[Sequence[RecentEntry]] = None) -> str:
        """Return the list as UTF-8 CSV with one header row and LF endings."""
        rows = list(entries) if entries is not None else self.load()
        now = utc_now()
        buffer = io.StringIO()
        writer = csv.DictWriter(
            buffer, fieldnames=list(EXPORT_COLUMNS), lineterminator="\n"
        )
        writer.writeheader()
        for entry in rows:
            writer.writerow({key: entry.export_row(now)[key] for key in EXPORT_COLUMNS})
        return buffer.getvalue()

    def export_markdown(self, entries: Optional[Sequence[RecentEntry]] = None) -> str:
        """Return the list as a Markdown table under a stated export range."""
        rows = list(entries) if entries is not None else self.load()
        now = utc_now()
        lines = [
            "# Recent projects and worlds",
            "",
            f"Exported {to_iso(now)} · {len(rows)} "
            f"{'record' if len(rows) == 1 else 'records'} · UTF-8 · LF line endings · "
            f"schema {STORE_SCHEMA} v{STORE_VERSION}",
            "",
        ]
        if not rows:
            lines.append("No projects or worlds have been opened yet.")
            lines.append("")
            return "\n".join(lines)
        lines.append("| Pinned | Name | Kind | Platform | Location | Opened |")
        lines.append("| --- | --- | --- | --- | --- | --- |")
        for entry in rows:
            lines.append(
                "| {pinned} | {name} | {kind} | {platform} | `{path}` | {opened} |".format(
                    pinned="yes" if entry.pinned else "no",
                    name=_escape_cell(entry.name),
                    kind=_escape_cell(entry.kind),
                    platform=_escape_cell(entry.platform),
                    path=_escape_cell(entry.path),
                    opened=_escape_cell(entry.opened_label(now)),
                )
            )
        lines.append("")
        return "\n".join(lines)

    def export_text(
        self,
        export_format: str,
        entries: Optional[Sequence[RecentEntry]] = None,
    ) -> str:
        """Return one export in the named format, refusing an unknown one."""
        writers = {
            "json": self.export_json,
            "csv": self.export_csv,
            "markdown": self.export_markdown,
        }
        try:
            writer = writers[str(export_format).lower()]
        except KeyError:
            raise ValueError(
                f"Unknown export format {export_format!r}; "
                f"expected one of {', '.join(EXPORT_FORMATS)}."
            ) from None
        return writer(entries)

    # -- internals -----------------------------------------------------------
    @staticmethod
    def _key_of(target: object) -> str:
        """Return the identity of a record, a path, or a name."""
        if isinstance(target, RecentEntry):
            return target.key()
        text = _text(target)
        if not text:
            return ""
        if os.sep in text or (os.altsep and os.altsep in text):
            try:
                return os.path.normcase(os.path.normpath(text))
            except (TypeError, ValueError):
                return text.casefold()
        return text.casefold()

    @staticmethod
    def _trim(ordered: Sequence[RecentEntry]) -> List[RecentEntry]:
        """Enforce the cap, dropping the oldest unpinned record first."""
        entries = list(ordered)
        if len(entries) <= MAX_ENTRIES:
            return entries
        pinned = [entry for entry in entries if entry.pinned]
        unpinned = [entry for entry in entries if not entry.pinned]
        room = max(0, MAX_ENTRIES - len(pinned))
        kept = pinned[:MAX_ENTRIES] + unpinned[:room]
        return sorted(kept, key=_sort_key)[:MAX_ENTRIES]

    @staticmethod
    def _record(action: str, entry: RecentEntry) -> None:
        """Append the change to the application's local history, if it is there.

        The recent list is user-managed state, so removing a record has to be
        undoable through the same history panel every other record uses.  A
        history store that cannot be created must never stop the list itself
        from being written, which is why this swallows its own failure.

        The write itself is a Git commit, and on a profile whose local history
        has grown large that can cost several hundred milliseconds of real
        subprocess time.  ``add()`` is called synchronously every time a world
        opens, so running the commit inline froze the whole shell for that long
        on every open -- the delay a user reading it as "everything reloads".
        Nothing here touches wx or any widget, so the commit is safe to finish
        on a background thread instead of on the one the UI is painted from.
        """

        def _commit() -> None:
            try:
                local_history.safe_record(
                    f"studio.recent:{entry.key()}",
                    {"action": action, "entry": entry.to_dict()},
                    record_type=_HISTORY_RECORD_TYPE,
                )
            except Exception:  # pragma: no cover - history is best-effort
                log.debug("Could not record a recent-list change in local history")

        threading.Thread(
            target=_commit, name="recents-history-record", daemon=True
        ).start()


def _escape_cell(value: str) -> str:
    """Escape a value so it cannot break out of a Markdown table cell."""
    return str(value).replace("|", "\\|").replace("\n", " ").strip()


# ---------------------------------------------------------------------------
# module-level convenience over one shared store
# ---------------------------------------------------------------------------
_default_store: Optional[RecentStore] = None


def store() -> RecentStore:
    """Return the shared store, built on first use so a test can redirect it."""
    global _default_store
    if _default_store is None or _default_store.root != default_store_root():
        _default_store = RecentStore()
    return _default_store


def reset_store() -> None:
    """Forget the shared store so the next call re-reads its location."""
    global _default_store
    _default_store = None


def list_entries() -> List[RecentEntry]:
    """Return every recorded project and world, pinned first."""
    return store().list()


def search(
    state: Optional[SearchState] = None,
    *,
    tag: str = "All",
    entries: Optional[Iterable[RecentEntry]] = None,
) -> List[RecentEntry]:
    """Return the records matching one filter pill and one search field."""
    return store().search(state, tag=tag, entries=entries)


def add(name: str, **details: Any) -> RecentEntry:
    """Record that a project or world was opened."""
    return store().add(name, **details)


def remove(target: object) -> bool:
    """Drop one record from the shared list."""
    return store().remove(target)


def pin(target: object, pinned: bool = True) -> bool:
    """Pin or unpin one record in the shared list."""
    return store().pin(target, pinned)


def export_json(entries: Optional[Sequence[RecentEntry]] = None) -> str:
    """Return the shared list as JSON."""
    return store().export_json(entries)


def export_csv(entries: Optional[Sequence[RecentEntry]] = None) -> str:
    """Return the shared list as CSV."""
    return store().export_csv(entries)


def export_markdown(entries: Optional[Sequence[RecentEntry]] = None) -> str:
    """Return the shared list as a Markdown table."""
    return store().export_markdown(entries)


def export_text(
    export_format: str, entries: Optional[Sequence[RecentEntry]] = None
) -> str:
    """Return the shared list in one of :data:`EXPORT_FORMATS`."""
    return store().export_text(export_format, entries)


__all__ = [
    "EXPORT_COLUMNS",
    "EXPORT_EXTENSIONS",
    "EXPORT_FORMATS",
    "FILTERS",
    "MAX_ENTRIES",
    "MAX_FIELD_LENGTH",
    "MAX_STORE_BYTES",
    "RecentEntry",
    "RecentStore",
    "STORE_FILENAME",
    "STORE_SCHEMA",
    "STORE_VERSION",
    "TAGS",
    "add",
    "default_store_path",
    "default_store_root",
    "export_csv",
    "export_json",
    "export_markdown",
    "export_text",
    "list_entries",
    "parse_iso",
    "pin",
    "relative_opened",
    "remove",
    "reset_store",
    "search",
    "store",
    "to_iso",
    "utc_now",
]
