"""wx-independent changelog catalog, filtering, and export helpers.

The bundled catalog is generated from reachable Git tags.  This module does not
import wx and deliberately contains no presentation or runtime-window claims.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from datetime import date
from importlib.resources import files
from typing import Callable, Iterable, Mapping, Optional, Tuple

CATALOG_SCHEMA_VERSION = 1
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_ACTION_RE = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
_CATALOG_RESOURCE = "changelog_catalog.json"


class ChangelogValidationError(ValueError):
    """Raised when changelog data violates the versioned catalog contract."""


class UnsupportedChangelogVersion(ChangelogValidationError):
    """Raised when a newer or otherwise unsupported schema is encountered."""


def _require_keys(
    value: Mapping[str, object], required: set[str], context: str
) -> None:
    actual = set(value)
    if actual != required:
        missing = sorted(required - actual)
        unknown = sorted(actual - required)
        raise ChangelogValidationError(
            f"{context} fields do not match the schema; "
            f"missing={missing}, unknown={unknown}"
        )


def _parse_date(value: object, context: str) -> date:
    if not isinstance(value, str):
        raise ChangelogValidationError(f"{context} must be an ISO date string")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ChangelogValidationError(
            f"{context} must use the YYYY-MM-DD form"
        ) from exc


def _validate_sha(value: object, context: str) -> str:
    if not isinstance(value, str) or not _SHA_RE.fullmatch(value):
        raise ChangelogValidationError(
            f"{context} must be a full lowercase 40-character Git SHA"
        )
    return value


def _validate_repository_url(value: object) -> str:
    if not isinstance(value, str):
        raise ChangelogValidationError("repository_url must be text")
    normalized = value.removesuffix("/").removesuffix(".git")
    if not re.fullmatch(
        r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", normalized
    ):
        raise ChangelogValidationError(
            "repository_url must be an HTTPS GitHub repository URL"
        )
    return normalized


@dataclass(frozen=True)
class ChangelogChange:
    """One factual Git-subject change attached to a release tag."""

    action: str
    summary: str
    commit_sha: str

    def __post_init__(self) -> None:
        if not isinstance(self.action, str) or not _ACTION_RE.fullmatch(self.action):
            raise ChangelogValidationError(
                "change action must be a lowercase stable identifier"
            )
        if not isinstance(self.summary, str) or not self.summary.strip():
            raise ChangelogValidationError("change summary must not be empty")
        if len(self.summary) > 500:
            raise ChangelogValidationError(
                "change summary is limited to 500 characters"
            )
        _validate_sha(self.commit_sha, "change commit_sha")

    @classmethod
    def from_dict(cls, value: object) -> "ChangelogChange":
        if not isinstance(value, Mapping):
            raise ChangelogValidationError("change must be an object")
        _require_keys(value, {"action", "summary", "commit_sha"}, "change")
        return cls(
            action=value["action"],  # type: ignore[arg-type]
            summary=value["summary"],  # type: ignore[arg-type]
            commit_sha=value["commit_sha"],  # type: ignore[arg-type]
        )


@dataclass(frozen=True)
class ChangelogEntry:
    """A release tag and the factual subject on its tagged commit."""

    version: str
    released_on: date
    commit_sha: str
    changes: Tuple[ChangelogChange, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.version, str) or not self.version.strip():
            raise ChangelogValidationError("entry version must not be empty")
        if len(self.version) > 100:
            raise ChangelogValidationError("entry version is limited to 100 characters")
        if not isinstance(self.released_on, date):
            raise ChangelogValidationError("entry released_on must be a date")
        _validate_sha(self.commit_sha, "entry commit_sha")
        if not isinstance(self.changes, tuple) or not self.changes:
            raise ChangelogValidationError("entry must contain at least one change")
        if any(not isinstance(change, ChangelogChange) for change in self.changes):
            raise ChangelogValidationError(
                "entry changes must be ChangelogChange values"
            )

    @classmethod
    def from_dict(cls, value: object) -> "ChangelogEntry":
        if not isinstance(value, Mapping):
            raise ChangelogValidationError("entry must be an object")
        _require_keys(
            value, {"version", "released_on", "commit_sha", "changes"}, "entry"
        )
        changes = value["changes"]
        if not isinstance(changes, list):
            raise ChangelogValidationError("entry changes must be a list")
        return cls(
            version=value["version"],  # type: ignore[arg-type]
            released_on=_parse_date(value["released_on"], "entry released_on"),
            commit_sha=value["commit_sha"],  # type: ignore[arg-type]
            changes=tuple(ChangelogChange.from_dict(change) for change in changes),
        )


@dataclass(frozen=True)
class ChangelogCatalog:
    """Versioned release history loaded from the bundled generated catalog."""

    repository_url: str
    source_revision: str
    entries: Tuple[ChangelogEntry, ...]
    schema_version: int = CATALOG_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != CATALOG_SCHEMA_VERSION:
            raise UnsupportedChangelogVersion(
                f"unsupported changelog schema version {self.schema_version!r}"
            )
        object.__setattr__(
            self, "repository_url", _validate_repository_url(self.repository_url)
        )
        _validate_sha(self.source_revision, "source_revision")
        if not isinstance(self.entries, tuple):
            raise ChangelogValidationError("catalog entries must be a tuple")
        versions = [entry.version for entry in self.entries]
        if len(versions) != len(set(versions)):
            raise ChangelogValidationError("catalog versions must be unique")
        if any(not isinstance(entry, ChangelogEntry) for entry in self.entries):
            raise ChangelogValidationError(
                "catalog entries must be ChangelogEntry values"
            )

    @classmethod
    def from_dict(cls, value: object) -> "ChangelogCatalog":
        if not isinstance(value, Mapping):
            raise ChangelogValidationError("catalog must be an object")
        _require_keys(
            value,
            {"schema_version", "repository_url", "source_revision", "entries"},
            "catalog",
        )
        schema_version = value["schema_version"]
        if type(schema_version) is not int or schema_version != CATALOG_SCHEMA_VERSION:
            raise UnsupportedChangelogVersion(
                f"unsupported changelog schema version {schema_version!r}"
            )
        entries = value["entries"]
        if not isinstance(entries, list):
            raise ChangelogValidationError("catalog entries must be a list")
        return cls(
            repository_url=value["repository_url"],  # type: ignore[arg-type]
            source_revision=value["source_revision"],  # type: ignore[arg-type]
            entries=tuple(ChangelogEntry.from_dict(entry) for entry in entries),
            schema_version=schema_version,
        )


@dataclass(frozen=True)
class ChangelogQuery:
    """Composable hooks for inclusive date, action, and text filtering."""

    start_date: Optional[date] = None
    end_date: Optional[date] = None
    actions: Tuple[str, ...] = ()
    text: str = ""

    def __post_init__(self) -> None:
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ChangelogValidationError("start_date must not be after end_date")
        if any(
            not isinstance(action, str) or not _ACTION_RE.fullmatch(action)
            for action in self.actions
        ):
            raise ChangelogValidationError(
                "query actions must be stable action identifiers"
            )
        if not isinstance(self.text, str):
            raise ChangelogValidationError("query text must be text")
        if len(self.text) > 4096:
            raise ChangelogValidationError("query text is limited to 4096 characters")


def load_bundled_catalog() -> ChangelogCatalog:
    """Load and validate the generated catalog without importing wx."""

    payload = (
        files("amulet_map_editor.api")
        .joinpath(_CATALOG_RESOURCE)
        .read_text(encoding="utf-8")
    )
    return ChangelogCatalog.from_dict(json.loads(payload))


def commit_url(repository_url: str, commit_sha: str) -> str:
    """Return a canonical commit link after validating both components."""

    repository = _validate_repository_url(repository_url)
    revision = _validate_sha(commit_sha, "commit_sha")
    return f"{repository}/commit/{revision}"


def validate_commit_links(
    catalog: ChangelogCatalog, commit_exists: Callable[[str], bool]
) -> Tuple[str, ...]:
    """Return missing SHAs using a caller-supplied local or forge resolver."""

    missing = []
    seen = set()
    commit_url(catalog.repository_url, catalog.source_revision)
    if not commit_exists(catalog.source_revision):
        missing.append(catalog.source_revision)
    seen.add(catalog.source_revision)
    for entry in catalog.entries:
        for revision in (
            entry.commit_sha,
            *(change.commit_sha for change in entry.changes),
        ):
            commit_url(catalog.repository_url, revision)
            if revision not in seen and not commit_exists(revision):
                missing.append(revision)
            seen.add(revision)
    return tuple(missing)


TextMatcher = Callable[[str], bool]


def filter_changelog(
    catalog: ChangelogCatalog,
    query: ChangelogQuery,
    *,
    text_matcher: Optional[TextMatcher] = None,
) -> ChangelogCatalog:
    """Filter releases and their changes while preserving catalog order.

    ``text_matcher`` lets a UI supply the project's bounded regex builder.  If
    omitted, text filtering is a case-insensitive literal substring search.
    """

    selected_actions = set(query.actions)
    if text_matcher is None:
        needle = query.text.casefold()

        def matches_text(value: str) -> bool:
            return needle in value.casefold()

    else:
        matches_text = text_matcher

    filtered = []
    for entry in catalog.entries:
        if query.start_date and entry.released_on < query.start_date:
            continue
        if query.end_date and entry.released_on > query.end_date:
            continue
        changes = tuple(
            change
            for change in entry.changes
            if (not selected_actions or change.action in selected_actions)
            and (
                not query.text
                or matches_text(entry.version)
                or matches_text(change.summary)
                or matches_text(change.commit_sha)
            )
        )
        if changes:
            filtered.append(replace(entry, changes=changes))
    return replace(catalog, entries=tuple(filtered))


def available_actions(entries: Iterable[ChangelogEntry]) -> Tuple[Tuple[str, int], ...]:
    """Derive action choices and counts from the current history."""

    counts: dict[str, int] = {}
    for entry in entries:
        for change in entry.changes:
            counts[change.action] = counts.get(change.action, 0) + 1
    return tuple(sorted(counts.items()))


def _escape_markdown(value: str) -> str:
    for character in "\\[]*_<>`":
        value = value.replace(character, f"\\{character}")
    return value.replace("\r", " ").replace("\n", " ")


def export_markdown(catalog: ChangelogCatalog, *, title: str = "Changelog") -> str:
    """Export the supplied (possibly filtered) catalog as deterministic Markdown."""

    lines = [
        f"# {_escape_markdown(title)}",
        "",
        f"Catalog schema: `{catalog.schema_version}`  ",
        f"Source revision: [`{catalog.source_revision[:12]}`]({commit_url(catalog.repository_url, catalog.source_revision)})  ",
        f"Repository: {catalog.repository_url}",
        "",
    ]
    if not catalog.entries:
        lines.extend(("No changelog entries match the active filters.", ""))
        return "\n".join(lines)
    for entry in catalog.entries:
        lines.extend(
            (
                f"## {_escape_markdown(entry.version)} — {entry.released_on.isoformat()}",
                "",
            )
        )
        for change in entry.changes:
            label = change.action.replace("-", " ").title()
            url = commit_url(catalog.repository_url, change.commit_sha)
            lines.append(
                f"- **{_escape_markdown(label)}:** {_escape_markdown(change.summary)} "
                f"([`{change.commit_sha[:12]}`]({url}))"
            )
        lines.append("")
    return "\n".join(lines)
