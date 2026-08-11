"""Every record the application owns, written out in every format it fits.

The rule this module exists to keep is that a surface which can *show* data can
also *hand it over*: a list, a table, a log, a settings page, a generated
report.  A single favourite format is not enough, because the right format
depends on the datum -- a rectangular table wants CSV, a nested record wants
JSON or YAML, a narrative wants Markdown -- so the catalogue below is offered
per dataset rather than per application.

Two contracts hold everywhere:

*Nothing is dropped quietly.*  :func:`describe_fidelity` inspects the real
values of a real dataset and returns every field the requested format cannot
carry faithfully, with the reason and the number of records affected.  The
writers refuse to run against a lossy report unless the caller passes
``accept_loss=True``, so "say what will be lost before the export runs" is a
mechanical property of the API rather than a habit a caller has to remember.

*Every file says what it is.*  Each export states UTF-8, LF line endings, the
dataset's schema name and version, the envelope contract version, the export
timestamp, and the field list -- in the file itself, in whatever the format
gives us for the purpose (an envelope object, a comment preamble, an XML
attribute set).  Something other than this application can therefore read it,
and :func:`read_text` reads it back for every format whose shape allows a round
trip.

The module imports no wx and no world library.  ``PyYAML`` and ``py7zr`` are
optional: their formats report themselves unavailable with the exact import
failure rather than silently degrading into a different format.
"""

from __future__ import annotations

import base64
import csv
import decimal
import enum
import io
import json
import os
import re
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from pathlib import Path, PurePath, PurePosixPath
from typing import Any, Callable, Iterable, Mapping, Sequence
from xml.etree import ElementTree

try:  # pragma: no cover - exercised by whichever environment is in use
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python < 3.11
    tomllib = None  # type: ignore[assignment]

try:
    import yaml as _yaml
except Exception as _yaml_error:  # pragma: no cover - depends on the install
    _yaml = None  # type: ignore[assignment]
    YAML_UNAVAILABLE_REASON = (
        "PyYAML is not importable in this Python environment "
        f"(import yaml failed: {_yaml_error})."
    )
else:
    YAML_UNAVAILABLE_REASON = ""

try:
    import py7zr as _py7zr
except Exception as _py7zr_error:  # pragma: no cover - depends on the install
    _py7zr = None  # type: ignore[assignment]
    SEVEN_ZIP_UNAVAILABLE_REASON = (
        "py7zr is not importable in this Python environment "
        f"(import py7zr failed: {_py7zr_error}).  7z archives, including "
        "AES-256 encryption and encrypted headers, cannot be written until it "
        "is installed."
    )
else:
    SEVEN_ZIP_UNAVAILABLE_REASON = ""


__all__ = [
    "ENCODING",
    "ENCODING_NAME",
    "EXPORT_CONTRACT_VERSION",
    "FORMATS",
    "FORMATS_BY_ID",
    "FORMAT_IDS",
    "GENERATOR",
    "LINE_ENDING",
    "LINE_ENDING_NAME",
    "SEVEN_ZIP_LEVELS",
    "SEVEN_ZIP_METHODS",
    "SEVEN_ZIP_UNAVAILABLE_REASON",
    "VALUE_TYPES",
    "YAML_UNAVAILABLE_REASON",
    "ZIP_METHODS",
    "ArchiveMember",
    "ArchiveOptionError",
    "ArchivePlan",
    "ArchiveProtectionError",
    "ArchiveResult",
    "ArchiveUnavailableError",
    "Dataset",
    "ExportError",
    "ExportFormat",
    "ExportImportError",
    "Field",
    "FieldProfile",
    "FidelityReport",
    "FormatOffer",
    "FormatUnavailableError",
    "ImportedDataset",
    "Loss",
    "LossyExportError",
    "MemberNameError",
    "SevenZipOptions",
    "UnknownFormatError",
    "ZipOptions",
    "bundle_members",
    "coerce_value",
    "describe_fidelity",
    "describe_seven_zip",
    "describe_zip",
    "envelope",
    "export_bytes",
    "export_text",
    "format_extension",
    "format_offers",
    "parse_size",
    "read_text",
    "recommended_format",
    "resolve_format",
    "round_trip",
    "safe_member_name",
    "seven_zip_available",
    "write_archive",
    "write_export",
    "write_seven_zip",
    "write_zip",
]


# ---------------------------------------------------------------------------
# constants
# ---------------------------------------------------------------------------
ENCODING = "utf-8"
ENCODING_NAME = "utf-8"
LINE_ENDING = "\n"
LINE_ENDING_NAME = "lf"
GENERATOR = "amulet-map-editor/studio-exporters"

#: Version of the envelope this module writes.  A reader keys off this, not off
#: the dataset's own ``schema_version``, when deciding how to find the records.
EXPORT_CONTRACT_VERSION = 1

ENVELOPE_KEY = "amulet_export"
RECORDS_KEY = "records"
COMMENT_PREFIX = "#"

_TYPE_STRING = "string"
_TYPE_INTEGER = "integer"
_TYPE_NUMBER = "number"
_TYPE_BOOLEAN = "boolean"
_TYPE_NULL = "null"
_TYPE_ARRAY = "array"
_TYPE_OBJECT = "object"
_TYPE_ANY = "any"

VALUE_TYPES = (
    _TYPE_STRING,
    _TYPE_INTEGER,
    _TYPE_NUMBER,
    _TYPE_BOOLEAN,
    _TYPE_NULL,
    _TYPE_ARRAY,
    _TYPE_OBJECT,
    _TYPE_ANY,
)

FAMILY_TABULAR = "tabular"
FAMILY_STRUCTURED = "structured"
FAMILY_PROSE = "prose"
FAMILY_INTERCHANGE = "interchange"

# Characters XML 1.0 cannot carry at all, whatever escaping is applied.
_XML_FORBIDDEN = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_CONTROL_CHARACTERS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_TOML_BARE_KEY = re.compile(r"^[A-Za-z0-9_-]+$")
_SQL_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_WINDOWS_RESERVED = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{index}" for index in range(1, 10)}
    | {f"lpt{index}" for index in range(1, 10)}
)


# ---------------------------------------------------------------------------
# errors
# ---------------------------------------------------------------------------
class ExportError(Exception):
    """Base class for every refusal this module raises."""


class UnknownFormatError(ExportError):
    """Raised for a format id that is not in the catalogue."""


class FormatUnavailableError(ExportError):
    """Raised when a format needs a package this environment does not have."""


class LossyExportError(ExportError):
    """Raised when a format cannot carry the data and nobody said that is fine.

    The report is attached so a caller can show exactly which fields, for which
    reason, in how many records -- before anything is written.
    """

    def __init__(self, report: "FidelityReport") -> None:
        super().__init__(report.refusal_message())
        self.report = report


class ArchiveOptionError(ExportError):
    """Raised for an archive option this writer cannot honour as asked."""


class ArchiveUnavailableError(ExportError):
    """Raised when an archive format needs a package that is not installed."""


class ArchiveProtectionError(ExportError):
    """Raised rather than present an archive as protected when it is not."""


class MemberNameError(ExportError):
    """Raised for an archive member name that could escape its directory."""


class ExportImportError(ExportError):
    """Raised when an exported file cannot be read back into records."""


# ---------------------------------------------------------------------------
# value normalisation
# ---------------------------------------------------------------------------
def coerce_value(value: Any) -> tuple[Any, tuple[str, ...]]:
    """Return ``value`` as JSON-native data plus a note for every conversion.

    Every writer below works from the same normalised value space -- null,
    boolean, integer, float, string, list, dict -- so a conversion is described
    once, for the dataset, instead of differently by each format.
    """

    notes: list[str] = []

    def convert(item: Any) -> Any:
        if item is None or isinstance(item, (bool, str)):
            return item
        if isinstance(item, int):
            return item
        if isinstance(item, float):
            if item != item or item in (float("inf"), float("-inf")):
                notes.append(
                    "A non-finite float was written as text; JSON, TOML and "
                    "CSV have no way to carry NaN or infinity as a number."
                )
                return repr(item)
            return item
        if isinstance(item, decimal.Decimal):
            notes.append(
                "A Decimal was written as text so its exact digits survive; a "
                "reader that wants a number must parse it."
            )
            return str(item)
        if isinstance(item, (datetime, date, time)):
            notes.append(
                "A date or time was written as an ISO-8601 string, which is "
                "the one spelling every format here reads the same way."
            )
            return item.isoformat()
        if isinstance(item, (bytes, bytearray, memoryview)):
            notes.append(
                "Binary data was written as standard base64 text; a reader "
                "must decode it to get the original bytes back."
            )
            return base64.b64encode(bytes(item)).decode("ascii")
        if isinstance(item, PurePath):
            return str(item)
        if isinstance(item, enum.Enum):
            return convert(item.value)
        if isinstance(item, Mapping):
            converted: dict[str, Any] = {}
            for key, sub in item.items():
                if not isinstance(key, str):
                    notes.append(
                        "A mapping key that was not text was written as text; "
                        "no export format here has non-text keys."
                    )
                converted[str(key)] = convert(sub)
            return converted
        if isinstance(item, (set, frozenset)):
            notes.append(
                "A set was written as a list in sorted text order; the "
                "formats here have no set type and no unordered collection."
            )
            return [convert(sub) for sub in sorted(item, key=repr)]
        if isinstance(item, (list, tuple)):
            return [convert(sub) for sub in item]
        notes.append(
            f"A value of type {type(item).__name__!r} was written as text by "
            "repr(); no export format here can carry it structurally."
        )
        return repr(item)

    return convert(value), tuple(dict.fromkeys(notes))


def _value_type(value: Any) -> str:
    if value is None:
        return _TYPE_NULL
    if isinstance(value, bool):
        return _TYPE_BOOLEAN
    if isinstance(value, int):
        return _TYPE_INTEGER
    if isinstance(value, float):
        return _TYPE_NUMBER
    if isinstance(value, str):
        return _TYPE_STRING
    if isinstance(value, list):
        return _TYPE_ARRAY
    if isinstance(value, dict):
        return _TYPE_OBJECT
    return _TYPE_ANY


def _merge_types(seen: Iterable[str]) -> str:
    kinds = {kind for kind in seen if kind != _TYPE_NULL}
    if not kinds:
        return _TYPE_NULL
    if len(kinds) == 1:
        return next(iter(kinds))
    if kinds == {_TYPE_INTEGER, _TYPE_NUMBER}:
        return _TYPE_NUMBER
    return _TYPE_ANY


# ---------------------------------------------------------------------------
# dataset
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Field:
    """One column of a dataset, named so a reader can key off it."""

    name: str
    type: str = _TYPE_STRING
    label: str = ""
    description: str = ""
    nullable: bool = False
    sensitive: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "type": self.type,
            "label": self.label or self.name,
            "description": self.description,
            "nullable": self.nullable,
            "sensitive": self.sensitive,
        }


@dataclass(frozen=True)
class FieldProfile:
    """What a field's real values actually contain, counted not guessed."""

    name: str
    types: tuple[str, ...]
    total: int
    nulls: int = 0
    empty_strings: int = 0
    nested: int = 0
    nested_nulls: int = 0
    line_breaks: int = 0
    tabs: int = 0
    control_characters: int = 0
    xml_forbidden: int = 0
    missing: int = 0


@dataclass(frozen=True)
class Dataset:
    """A named, ordered record set with a stated field schema.

    ``name`` is the stable identifier a reader keys off (it becomes the SQL
    table name and the JSON Schema ``$id``); ``title`` is what a person reads.
    ``sensitive`` marks a record set the surrounding flow has decided carries
    secrets, which is what the archive writers check before they will put it in
    a file that travels.
    """

    name: str
    title: str
    fields: tuple[Field, ...]
    records: tuple[Mapping[str, Any], ...]
    schema_version: str = "1"
    description: str = ""
    source: str = ""
    sensitive: bool = False
    notes: tuple[str, ...] = ()
    unavailable: str = ""

    # -- construction --------------------------------------------------------
    @classmethod
    def build(
        cls,
        name: str,
        title: str,
        records: Iterable[Mapping[str, Any]],
        *,
        fields: Sequence[Field] | Sequence[str] | None = None,
        schema_version: str = "1",
        description: str = "",
        source: str = "",
        sensitive: bool = False,
        notes: Iterable[str] = (),
        unavailable: str = "",
    ) -> "Dataset":
        """Normalise records and infer the field schema that is not given.

        Field order follows the declared order, or first appearance across the
        records, so an export is stable between runs rather than following a
        dictionary's iteration accident.

        A declared field keeps its label, description and sensitivity.  Its
        type is inferred from the values unless the caller declared something
        other than the ``string`` default, and it becomes nullable if any
        record is missing it or holds ``None`` there -- because what a format
        has to carry is what the records really contain, not what they were
        expected to.
        """

        rows: list[dict[str, Any]] = []
        collected: list[str] = list(notes)
        for record in records:
            if not isinstance(record, Mapping):
                raise ExportError(
                    "Every record must be a mapping of field name to value; "
                    f"got {type(record).__name__!r}."
                )
            row: dict[str, Any] = {}
            for key, value in record.items():
                converted, value_notes = coerce_value(value)
                collected.extend(value_notes)
                row[str(key)] = converted
            rows.append(row)

        order: list[str] = []
        declared: dict[str, Field] = {}
        if fields:
            for entry in fields:
                declared_field = (
                    entry if isinstance(entry, Field) else Field(name=str(entry))
                )
                if declared_field.name in declared:
                    continue
                declared[declared_field.name] = declared_field
                order.append(declared_field.name)
        for row in rows:
            for key in row:
                if key not in declared:
                    declared[key] = Field(name=key)
                    order.append(key)

        resolved: list[Field] = []
        for key in order:
            base = declared[key]
            seen = [_value_type(row[key]) for row in rows if key in row]
            nullable = any(kind == _TYPE_NULL for kind in seen) or any(
                key not in row for row in rows
            )
            inferred = _merge_types(seen) if seen else base.type
            resolved.append(
                Field(
                    name=base.name,
                    type=base.type if base.type != _TYPE_STRING else inferred,
                    label=base.label,
                    description=base.description,
                    nullable=base.nullable or nullable,
                    sensitive=base.sensitive,
                )
            )

        return cls(
            name=str(name),
            title=str(title),
            fields=tuple(resolved),
            records=tuple(rows),
            schema_version=str(schema_version),
            description=str(description),
            source=str(source),
            sensitive=bool(sensitive),
            notes=tuple(dict.fromkeys(collected)),
            unavailable=str(unavailable),
        )

    @classmethod
    def unreadable(
        cls,
        name: str,
        title: str,
        reason: str,
        *,
        fields: Sequence[Field] | Sequence[str] = (),
        schema_version: str = "1",
        source: str = "",
    ) -> "Dataset":
        """Return an export that states why there is nothing in it.

        A record set that could not be read is not the same thing as one that
        was read and was empty, and an export must never let the two look
        alike -- nor invent a plausible row to fill the gap.
        """

        if not str(reason).strip():
            raise ExportError(
                "An unreadable dataset must name the reason it could not be "
                "read; an unexplained empty export is indistinguishable from "
                "an empty record set."
            )
        return cls.build(
            name,
            title,
            (),
            fields=fields,
            schema_version=schema_version,
            source=source,
            unavailable=str(reason).strip(),
        )

    @classmethod
    def from_mapping(
        cls,
        name: str,
        title: str,
        values: Mapping[str, Any],
        *,
        key_field: str = "setting",
        value_field: str = "value",
        schema_version: str = "1",
        description: str = "",
        source: str = "",
        sensitive: bool = False,
        sensitive_keys: Iterable[str] = (),
    ) -> "Dataset":
        """Turn a settings-shaped mapping into a two-column record set.

        A settings page holds key/value pairs rather than rows, which is the
        one common shape :meth:`build` does not read directly; without this a
        surface that owns settings ends up writing its own flattening and
        getting the ordering or the nesting subtly different from the next one.

        ``sensitive_keys`` marks the individual settings that carry secrets, so
        an archive of them has to be created sensitive even when the rest of
        the page is ordinary.
        """

        secret = {str(key) for key in sensitive_keys}
        records = [
            {key_field: str(key), value_field: value} for key, value in values.items()
        ]
        dataset = cls.build(
            name,
            title,
            records,
            fields=[
                Field(key_field, _TYPE_STRING, label="Setting"),
                Field(value_field, _TYPE_ANY, label="Value"),
            ],
            schema_version=schema_version,
            description=description,
            source=source,
            sensitive=sensitive or bool(secret & {str(key) for key in values}),
        )
        return dataset

    @classmethod
    def from_lines(
        cls,
        name: str,
        title: str,
        lines: Iterable[str],
        *,
        schema_version: str = "1",
        description: str = "",
        source: str = "",
    ) -> "Dataset":
        """Turn a log or a plain document into numbered line records.

        A log is data even though it looks like prose: numbering the lines lets
        it go out as CSV or JSON for a machine and as Markdown or HTML for a
        person, from the same one call.
        """

        return cls.build(
            name,
            title,
            [
                {"line": number, "text": text}
                for number, text in enumerate(lines, start=1)
            ],
            fields=[
                Field("line", _TYPE_INTEGER, label="Line"),
                Field("text", _TYPE_STRING, label="Text"),
            ],
            schema_version=schema_version,
            description=description,
            source=source,
        )

    # -- reading -------------------------------------------------------------
    @property
    def field_names(self) -> tuple[str, ...]:
        return tuple(item.name for item in self.fields)

    @property
    def carries_secrets(self) -> bool:
        """True when this record set has been marked as carrying secrets."""
        return bool(self.sensitive) or any(item.sensitive for item in self.fields)

    def value(self, record: Mapping[str, Any], name: str) -> Any:
        return record.get(name)

    def profile(self, name: str) -> FieldProfile:
        """Count what this field's values really contain, across every record."""

        types: list[str] = []
        nulls = empty = nested = nested_nulls = 0
        breaks = tabs = controls = forbidden = missing = 0
        for record in self.records:
            if name not in record:
                missing += 1
                nulls += 1
                continue
            value = record[name]
            kind = _value_type(value)
            types.append(kind)
            if value is None:
                nulls += 1
            elif isinstance(value, str):
                if not value:
                    empty += 1
                if "\n" in value or "\r" in value:
                    breaks += 1
                if "\t" in value:
                    tabs += 1
                if _CONTROL_CHARACTERS.search(value):
                    controls += 1
                if _XML_FORBIDDEN.search(value):
                    forbidden += 1
            elif isinstance(value, (list, dict)):
                nested += 1
                inner_nulls, inner_text = _walk_nested(value)
                nested_nulls += inner_nulls
                if any("\n" in text or "\r" in text for text in inner_text):
                    breaks += 1
                if any(_XML_FORBIDDEN.search(text) for text in inner_text):
                    forbidden += 1
        return FieldProfile(
            name=name,
            types=tuple(dict.fromkeys(types)),
            total=len(self.records),
            nulls=nulls,
            empty_strings=empty,
            nested=nested,
            nested_nulls=nested_nulls,
            line_breaks=breaks,
            tabs=tabs,
            control_characters=controls,
            xml_forbidden=forbidden,
            missing=missing,
        )

    def profiles(self) -> tuple[FieldProfile, ...]:
        return tuple(self.profile(item.name) for item in self.fields)

    def rows(self) -> tuple[dict[str, Any], ...]:
        """Return every record widened to the full field list, in field order."""
        names = self.field_names
        return tuple(
            {name: record.get(name) for name in names} for record in self.records
        )


def _walk_nested(value: Any) -> tuple[int, list[str]]:
    """Return the null count and every string inside a nested container."""

    nulls = 0
    texts: list[str] = []
    stack: list[Any] = [value]
    while stack:
        item = stack.pop()
        if item is None:
            nulls += 1
        elif isinstance(item, str):
            texts.append(item)
        elif isinstance(item, dict):
            for key, sub in item.items():
                texts.append(str(key))
                stack.append(sub)
        elif isinstance(item, list):
            stack.extend(item)
    return nulls, texts


# ---------------------------------------------------------------------------
# format catalogue
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ExportFormat:
    """One writable format, with what it is good for stated plainly."""

    id: str
    label: str
    extension: str
    media_type: str
    family: str
    round_trip: bool
    carries_records: bool
    summary: str
    aliases: tuple[str, ...] = ()
    requires: str = ""

    @property
    def available(self) -> bool:
        return not self.unavailable_reason

    @property
    def unavailable_reason(self) -> str:
        if self.requires == "yaml":
            return YAML_UNAVAILABLE_REASON
        if self.requires == "tomllib" and tomllib is None:
            return (
                "This Python build has no tomllib, so a TOML export could be "
                "written but never read back by this application."
            )
        return ""


FORMATS: tuple[ExportFormat, ...] = (
    ExportFormat(
        id="csv",
        label="CSV",
        extension=".csv",
        media_type="text/csv; charset=utf-8",
        family=FAMILY_TABULAR,
        round_trip=True,
        carries_records=True,
        summary=(
            "One header row and one row per record, RFC 4180 quoting, with the "
            "schema and field types in a leading comment block."
        ),
    ),
    ExportFormat(
        id="tsv",
        label="TSV",
        extension=".tsv",
        media_type="text/tab-separated-values; charset=utf-8",
        family=FAMILY_TABULAR,
        round_trip=True,
        carries_records=True,
        summary=(
            "The same table separated by tabs, for a reader that splits on "
            "tabs rather than parsing quotes."
        ),
    ),
    ExportFormat(
        id="json",
        label="JSON",
        extension=".json",
        media_type="application/json",
        family=FAMILY_STRUCTURED,
        round_trip=True,
        carries_records=True,
        summary=(
            "An envelope object stating encoding, line endings, schema and "
            "fields, with every record under 'records'."
        ),
    ),
    ExportFormat(
        id="jsonl",
        label="JSON Lines (NDJSON)",
        extension=".jsonl",
        media_type="application/x-ndjson",
        family=FAMILY_STRUCTURED,
        round_trip=True,
        carries_records=True,
        aliases=("ndjson",),
        summary=(
            "One JSON object per line after a header line, so a very large "
            "export streams a record at a time instead of loading whole."
        ),
    ),
    ExportFormat(
        id="yaml",
        label="YAML",
        extension=".yaml",
        media_type="application/yaml",
        family=FAMILY_STRUCTURED,
        round_trip=True,
        carries_records=True,
        requires="yaml",
        summary=(
            "The JSON envelope written as YAML, with the encoding and schema "
            "repeated in leading comments a person reads first."
        ),
    ),
    ExportFormat(
        id="toml",
        label="TOML",
        extension=".toml",
        media_type="application/toml",
        family=FAMILY_STRUCTURED,
        round_trip=True,
        carries_records=True,
        requires="tomllib",
        summary=(
            "A configuration-shaped export: an [amulet_export] table and one "
            "[[records]] table per record.  TOML has no null."
        ),
    ),
    ExportFormat(
        id="xml",
        label="XML",
        extension=".xml",
        media_type="application/xml",
        family=FAMILY_STRUCTURED,
        round_trip=True,
        carries_records=True,
        summary=(
            "Typed elements, so null, boolean, number and nested values come "
            "back as themselves rather than as text."
        ),
    ),
    ExportFormat(
        id="markdown",
        label="Markdown",
        extension=".md",
        media_type="text/markdown; charset=utf-8",
        family=FAMILY_PROSE,
        round_trip=False,
        carries_records=True,
        summary=(
            "A readable document: a stated export range, the field list, and "
            "the records as a table.  For reading, not for re-importing."
        ),
    ),
    ExportFormat(
        id="html",
        label="HTML",
        extension=".html",
        media_type="text/html; charset=utf-8",
        family=FAMILY_PROSE,
        round_trip=False,
        carries_records=True,
        summary=(
            "One self-contained page with no external assets, for sending to "
            "somebody who will open it in a browser."
        ),
    ),
    ExportFormat(
        id="sql",
        label="SQL insert statements",
        extension=".sql",
        media_type="application/sql",
        family=FAMILY_INTERCHANGE,
        round_trip=False,
        carries_records=True,
        summary=(
            "CREATE TABLE plus one INSERT per record, for loading the export "
            "into a database rather than reading it."
        ),
    ),
    ExportFormat(
        id="jsonschema",
        label="JSON Schema",
        extension=".schema.json",
        media_type="application/schema+json",
        family=FAMILY_INTERCHANGE,
        round_trip=False,
        carries_records=False,
        summary=(
            "The shape of the JSON export -- field names, types and which are "
            "nullable.  It describes the data; it does not contain it."
        ),
    ),
)

FORMATS_BY_ID: dict[str, ExportFormat] = {}
for _format in FORMATS:
    FORMATS_BY_ID[_format.id] = _format
    for _alias in _format.aliases:
        FORMATS_BY_ID[_alias] = _format
del _format

FORMAT_IDS: tuple[str, ...] = tuple(item.id for item in FORMATS)


def resolve_format(format_id: str) -> ExportFormat:
    """Return the catalogue entry for an id or alias, or refuse by name."""

    key = str(format_id).strip().lower().lstrip(".")
    found = FORMATS_BY_ID.get(key)
    if found is None:
        raise UnknownFormatError(
            f"Unknown export format {format_id!r}; this application writes "
            + ", ".join(FORMAT_IDS)
            + "."
        )
    return found


def format_extension(format_id: str) -> str:
    """Return the file extension a format writes."""
    return resolve_format(format_id).extension


# ---------------------------------------------------------------------------
# fidelity
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Loss:
    """One thing a format cannot carry, with the count it affects."""

    field: str
    reason: str
    detail: str
    records: int = 0

    def describe(self) -> str:
        where = f"{self.field}: " if self.field else ""
        if self.records:
            return f"{where}{self.detail} ({self.records} affected)"
        return f"{where}{self.detail}"


@dataclass(frozen=True)
class FidelityReport:
    """What a named format will and will not carry for a named dataset."""

    dataset: str
    format_id: str
    format_label: str
    available: bool
    unavailable_reason: str
    round_trip: bool
    carries_records: bool
    record_count: int
    losses: tuple[Loss, ...] = ()
    notes: tuple[str, ...] = ()

    @property
    def lossless(self) -> bool:
        return not self.losses

    def summary(self) -> str:
        if not self.available:
            return self.unavailable_reason
        if self.lossless:
            trip = (
                "reads back into the same records"
                if self.round_trip
                else "is for reading, not for re-importing"
            )
            return f"Carries every field of {self.record_count} records and {trip}."
        return (
            f"Carries {self.record_count} records with "
            f"{len(self.losses)} stated "
            f"{'loss' if len(self.losses) == 1 else 'losses'}: "
            + "; ".join(loss.describe() for loss in self.losses)
        )

    def refusal_message(self) -> str:
        return (
            f"{self.format_label} cannot carry this data faithfully: "
            + "; ".join(loss.describe() for loss in self.losses)
            + ".  Pass accept_loss=True to write it anyway, having said so."
        )


@dataclass(frozen=True)
class FormatOffer:
    """A catalogue entry paired with what it costs for this dataset."""

    format: ExportFormat
    report: FidelityReport

    @property
    def format_id(self) -> str:
        return self.format.id

    @property
    def label(self) -> str:
        return self.format.label

    @property
    def available(self) -> bool:
        return self.report.available

    @property
    def lossless(self) -> bool:
        return self.report.lossless


def describe_fidelity(dataset: Dataset, format_id: str) -> FidelityReport:
    """Return every field the format cannot carry, from the real values.

    The counts come from the dataset in hand rather than from the declared
    types, so "CSV cannot tell your empty string from your missing value"
    appears only when that dataset genuinely contains both.
    """

    fmt = resolve_format(format_id)
    losses: list[Loss] = []
    notes: list[str] = list(dataset.notes)
    count = len(dataset.records)

    if fmt.id in {"csv", "tsv"}:
        notes.append(
            "The schema, field types, encoding and line endings are written as "
            f"'{COMMENT_PREFIX}' comment lines above the header row; tell a "
            f"strict reader that '{COMMENT_PREFIX}' starts a comment, or write "
            "with preamble=False."
        )
    if fmt.id == "jsonl":
        notes.append(
            "The first line is a header object holding the envelope; every "
            "later line is one record."
        )
    if not fmt.round_trip and fmt.carries_records:
        notes.append(
            f"{fmt.label} is a presentation format: this application writes it "
            "but cannot read it back into records."
        )

    if not fmt.carries_records and count:
        losses.append(
            Loss(
                "",
                "no_record_values",
                f"{fmt.label} describes the shape of this export only; none of "
                "the record values are written to the file",
                count,
            )
        )

    profiles = dataset.profiles()
    for profile in profiles:
        name = profile.name
        if fmt.id in {"csv", "tsv", "markdown", "html", "sql"} and profile.nested:
            tail = (
                "a reader that ignores the declared field types sees text "
                "where the record has structure"
                if fmt.id in {"csv", "tsv"}
                else "the file has no field types, so a reader sees text where "
                "the record has structure"
            )
            losses.append(
                Loss(
                    name,
                    "structure_flattened",
                    f"nested values are written as JSON text in one cell and "
                    f"{tail}",
                    profile.nested,
                )
            )
        if fmt.id in {"csv", "tsv", "markdown", "html"}:
            if profile.nulls and profile.empty_strings:
                losses.append(
                    Loss(
                        name,
                        "null_ambiguity",
                        "this column holds both empty text and missing values, "
                        "and this format writes both as an empty cell",
                        profile.nulls + profile.empty_strings,
                    )
                )
        if fmt.id in {"csv", "tsv"} and _merge_types(profile.types) == _TYPE_ANY:
            losses.append(
                Loss(
                    name,
                    "mixed_types",
                    "this column holds more than one kind of value and a "
                    "delimited file carries one type per column, so a reader "
                    "cannot tell which row held which",
                    profile.total,
                )
            )
        if fmt.id in {"csv", "tsv"}:
            if profile.control_characters:
                losses.append(
                    Loss(
                        name,
                        "control_characters",
                        "control characters survive only if the reader honours "
                        "quoting exactly; many spreadsheet importers do not",
                        profile.control_characters,
                    )
                )
        if fmt.id == "tsv" and (profile.tabs or profile.line_breaks):
            losses.append(
                Loss(
                    name,
                    "delimiter_in_value",
                    "values contain a tab or a line break and the "
                    "tab-separated convention has no quoting, so a reader that "
                    "splits on tabs will misread the row",
                    profile.tabs + profile.line_breaks,
                )
            )
        if fmt.id == "toml" and profile.nulls:
            losses.append(
                Loss(
                    name,
                    "no_null",
                    "TOML has no null, so the key is omitted in those records "
                    "and a reader cannot tell it apart from a field that was "
                    "never there",
                    profile.nulls,
                )
            )
        if fmt.id == "toml" and profile.nested_nulls:
            losses.append(
                Loss(
                    name,
                    "no_null_in_container",
                    "null entries inside nested arrays and tables are dropped, "
                    "which shortens those arrays",
                    profile.nested_nulls,
                )
            )
        if fmt.id == "xml" and profile.xml_forbidden:
            losses.append(
                Loss(
                    name,
                    "xml_forbidden_characters",
                    "XML 1.0 cannot carry these control characters under any "
                    "escaping, so they are replaced with U+FFFD",
                    profile.xml_forbidden,
                )
            )
        if fmt.id == "markdown" and profile.line_breaks:
            losses.append(
                Loss(
                    name,
                    "line_breaks_replaced",
                    "line breaks become <br> so the row stays one table row",
                    profile.line_breaks,
                )
            )

    if fmt.id == "sql":
        measured = {profile.name: profile for profile in profiles}
        boolean_fields = [
            item.name
            for item in dataset.fields
            if item.type == _TYPE_BOOLEAN or _TYPE_BOOLEAN in measured[item.name].types
        ]
        for name in boolean_fields:
            losses.append(
                Loss(
                    name,
                    "boolean_narrowed",
                    "booleans are written as 1 and 0 in an INTEGER column, "
                    "which is what portable SQL has",
                    count,
                )
            )
        if dataset.name != _sql_identifier(dataset.name):
            notes.append(
                f"The table is named {_sql_identifier(dataset.name)!r}; "
                f"{dataset.name!r} is not a portable SQL identifier."
            )

    if dataset.carries_secrets:
        notes.append(
            "This record set is marked as carrying secrets; an archive of it "
            "must be created as sensitive."
        )
    if dataset.unavailable:
        notes.append(_empty_state(dataset))

    return FidelityReport(
        dataset=dataset.name,
        format_id=fmt.id,
        format_label=fmt.label,
        available=fmt.available,
        unavailable_reason=fmt.unavailable_reason,
        round_trip=fmt.round_trip,
        carries_records=fmt.carries_records,
        record_count=count,
        losses=tuple(losses),
        notes=tuple(dict.fromkeys(notes)),
    )


def format_offers(dataset: Dataset) -> tuple[FormatOffer, ...]:
    """Return every format for this datum, best fit first.

    Ordering puts what is available, lossless and re-importable at the top;
    nothing is hidden, because a caller may want Markdown for a person even
    though it cannot be read back.
    """

    offers = [
        FormatOffer(item, describe_fidelity(dataset, item.id)) for item in FORMATS
    ]
    offers.sort(
        key=lambda offer: (
            not offer.available,
            not offer.lossless,
            not offer.format.round_trip,
            not offer.format.carries_records,
            FORMAT_IDS.index(offer.format.id),
        )
    )
    return tuple(offers)


def recommended_format(dataset: Dataset) -> ExportFormat:
    """Return the first format that carries this datum whole and reads back."""

    for offer in format_offers(dataset):
        if offer.available and offer.lossless and offer.format.round_trip:
            return offer.format
    return FORMATS_BY_ID["json"]


# ---------------------------------------------------------------------------
# envelope
# ---------------------------------------------------------------------------
def _iso(moment: datetime | None = None) -> str:
    value = moment or datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    text = value.astimezone(timezone.utc).replace(microsecond=0).isoformat()
    return text.replace("+00:00", "Z")


def envelope(
    dataset: Dataset, fmt: ExportFormat, *, timestamp: datetime | None = None
) -> dict[str, Any]:
    """Return the self-describing header every export carries."""

    header: dict[str, Any] = {
        "generator": GENERATOR,
        "contract": EXPORT_CONTRACT_VERSION,
        "schema": dataset.name,
        "schema_version": dataset.schema_version,
        "title": dataset.title,
        "description": dataset.description,
        "source": dataset.source,
        "format": fmt.id,
        "media_type": fmt.media_type,
        "encoding": ENCODING_NAME,
        "line_endings": LINE_ENDING_NAME,
        "exported": _iso(timestamp),
        "count": len(dataset.records),
        "sensitive": dataset.carries_secrets,
    }
    if dataset.unavailable:
        header["unavailable"] = _empty_state(dataset)
    header["fields"] = [item.to_dict() for item in dataset.fields]
    header["notes"] = list(dataset.notes)
    return header


def _empty_state(dataset: Dataset) -> str:
    """Say why there are no records, without either inventing or implying any."""

    if dataset.unavailable:
        return (
            "This export contains no records because the record set could not "
            f"be read: {dataset.unavailable}  Nothing has been substituted for "
            "it."
        )
    return (
        "This export contains no records.  The record set was read "
        "successfully and was empty; nothing has been left out."
    )


def _preamble_lines(meta: Mapping[str, Any]) -> list[str]:
    header = {key: value for key, value in meta.items() if key != "fields"}
    return [
        f"{COMMENT_PREFIX} amulet-export: "
        + json.dumps(header, ensure_ascii=False, sort_keys=True),
        f"{COMMENT_PREFIX} fields: "
        + json.dumps(meta.get("fields", []), ensure_ascii=False),
    ]


# ---------------------------------------------------------------------------
# writers
# ---------------------------------------------------------------------------
def export_text(
    dataset: Dataset,
    format_id: str,
    *,
    accept_loss: bool = False,
    timestamp: datetime | None = None,
    preamble: bool = True,
) -> str:
    """Return the export as text, refusing a lossy format nobody agreed to."""

    fmt = resolve_format(format_id)
    if not fmt.available:
        raise FormatUnavailableError(fmt.unavailable_reason)
    report = describe_fidelity(dataset, fmt.id)
    if report.losses and not accept_loss:
        raise LossyExportError(report)
    writer = _WRITERS[fmt.id]
    return writer(dataset, fmt, timestamp, preamble)


def export_bytes(dataset: Dataset, format_id: str, **kwargs: Any) -> bytes:
    """Return the export as the UTF-8 bytes that go into a file or archive."""
    return export_text(dataset, format_id, **kwargs).encode(ENCODING)


def write_export(
    dataset: Dataset,
    target: str | os.PathLike[str],
    format_id: str,
    **kwargs: Any,
) -> Path:
    """Write one export to disk as UTF-8 with LF endings, and return the path."""

    path = Path(target).expanduser()
    text = export_text(dataset, format_id, **kwargs)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding=ENCODING, newline=LINE_ENDING)
    return path


def _write_json(
    dataset: Dataset,
    fmt: ExportFormat,
    timestamp: datetime | None,
    preamble: bool,
) -> str:
    document = {
        ENVELOPE_KEY: envelope(dataset, fmt, timestamp=timestamp),
        RECORDS_KEY: list(dataset.rows()),
    }
    return (
        json.dumps(document, ensure_ascii=False, indent=2, allow_nan=False)
        + LINE_ENDING
    )


def _write_jsonl(
    dataset: Dataset,
    fmt: ExportFormat,
    timestamp: datetime | None,
    preamble: bool,
) -> str:
    lines = [
        json.dumps(
            {ENVELOPE_KEY: envelope(dataset, fmt, timestamp=timestamp)},
            ensure_ascii=False,
            allow_nan=False,
        )
    ]
    for row in dataset.rows():
        lines.append(json.dumps(row, ensure_ascii=False, allow_nan=False))
    return LINE_ENDING.join(lines) + LINE_ENDING


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value) if isinstance(value, float) else str(value)
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _write_delimited(delimiter: str) -> Callable[..., str]:
    def write(
        dataset: Dataset,
        fmt: ExportFormat,
        timestamp: datetime | None,
        preamble: bool,
    ) -> str:
        buffer = io.StringIO()
        if preamble:
            for line in _preamble_lines(envelope(dataset, fmt, timestamp=timestamp)):
                buffer.write(line + LINE_ENDING)
        writer = csv.writer(
            buffer,
            delimiter=delimiter,
            lineterminator=LINE_ENDING,
            quoting=csv.QUOTE_MINIMAL,
        )
        writer.writerow(list(dataset.field_names))
        for row in dataset.rows():
            writer.writerow([_cell(row[name]) for name in dataset.field_names])
        return buffer.getvalue()

    return write


def _write_yaml(
    dataset: Dataset,
    fmt: ExportFormat,
    timestamp: datetime | None,
    preamble: bool,
) -> str:
    if _yaml is None:  # pragma: no cover - guarded by export_text
        raise FormatUnavailableError(YAML_UNAVAILABLE_REASON)
    meta = envelope(dataset, fmt, timestamp=timestamp)
    head = ""
    if preamble:
        head = (
            LINE_ENDING.join(
                [
                    f"{COMMENT_PREFIX} {dataset.title}",
                    f"{COMMENT_PREFIX} encoding: {ENCODING_NAME}  line endings: "
                    f"{LINE_ENDING_NAME}",
                    f"{COMMENT_PREFIX} schema: {dataset.name} v{dataset.schema_version}"
                    f"  export contract: {EXPORT_CONTRACT_VERSION}",
                    f"{COMMENT_PREFIX} exported: {meta['exported']}  records: "
                    f"{meta['count']}",
                ]
            )
            + LINE_ENDING
        )
    body = _yaml.safe_dump(
        {ENVELOPE_KEY: meta, RECORDS_KEY: list(dataset.rows())},
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
        width=100000,
    )
    return head + body


def _toml_key(name: str) -> str:
    if _TOML_BARE_KEY.match(name):
        return name
    return _toml_string(name)


def _toml_string(value: str) -> str:
    out = ['"']
    for char in value:
        if char == '"':
            out.append('\\"')
        elif char == "\\":
            out.append("\\\\")
        elif char == "\n":
            out.append("\\n")
        elif char == "\r":
            out.append("\\r")
        elif char == "\t":
            out.append("\\t")
        elif ord(char) < 0x20 or ord(char) == 0x7F:
            out.append(f"\\u{ord(char):04X}")
        else:
            out.append(char)
    out.append('"')
    return "".join(out)


def _toml_value(value: Any) -> str | None:
    """Return the TOML literal, or None for a value TOML cannot hold."""

    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, str):
        return _toml_string(value)
    if isinstance(value, list):
        parts = [_toml_value(item) for item in value]
        return "[" + ", ".join(part for part in parts if part is not None) + "]"
    if isinstance(value, dict):
        pieces = []
        for key, sub in value.items():
            literal = _toml_value(sub)
            if literal is None:
                continue
            pieces.append(f"{_toml_key(str(key))} = {literal}")
        return "{" + ", ".join(pieces) + "}"
    return _toml_string(str(value))


def _write_toml(
    dataset: Dataset,
    fmt: ExportFormat,
    timestamp: datetime | None,
    preamble: bool,
) -> str:
    meta = envelope(dataset, fmt, timestamp=timestamp)
    lines: list[str] = []
    if preamble:
        lines.extend(
            [
                f"{COMMENT_PREFIX} {dataset.title}",
                f"{COMMENT_PREFIX} encoding: {ENCODING_NAME}  line endings: "
                f"{LINE_ENDING_NAME}",
                f"{COMMENT_PREFIX} TOML has no null: a field with no value is "
                "written by leaving its key out.",
                "",
            ]
        )
    lines.append(f"[{ENVELOPE_KEY}]")
    for key, value in meta.items():
        if key in {"fields", "notes"}:
            continue
        literal = _toml_value(value)
        if literal is not None:
            lines.append(f"{_toml_key(key)} = {literal}")
    notes = _toml_value(meta.get("notes", []))
    if notes is not None:
        lines.append(f"notes = {notes}")
    lines.append("")
    for item in meta.get("fields", []):
        lines.append(f"[[{ENVELOPE_KEY}.fields]]")
        for key, value in item.items():
            literal = _toml_value(value)
            if literal is not None:
                lines.append(f"{_toml_key(key)} = {literal}")
        lines.append("")
    for row in dataset.rows():
        lines.append(f"[[{RECORDS_KEY}]]")
        for name in dataset.field_names:
            literal = _toml_value(row[name])
            if literal is None:
                continue
            lines.append(f"{_toml_key(name)} = {literal}")
        lines.append("")
    return LINE_ENDING.join(lines).rstrip(LINE_ENDING) + LINE_ENDING


def _xml_text(value: str) -> str:
    return _XML_FORBIDDEN.sub("�", value)


def _xml_value(parent: ElementTree.Element, tag: str, value: Any, **attrs: str) -> None:
    element = ElementTree.SubElement(parent, tag, {**attrs, "type": _value_type(value)})
    if value is None:
        return
    if isinstance(value, bool):
        element.text = "true" if value else "false"
    elif isinstance(value, (int, float)):
        element.text = repr(value) if isinstance(value, float) else str(value)
    elif isinstance(value, str):
        element.text = _xml_text(value)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _xml_value(element, "item", item, index=str(index))
    elif isinstance(value, dict):
        for key, item in value.items():
            _xml_value(element, "value", item, name=_xml_text(str(key)))


def _write_xml(
    dataset: Dataset,
    fmt: ExportFormat,
    timestamp: datetime | None,
    preamble: bool,
) -> str:
    meta = envelope(dataset, fmt, timestamp=timestamp)
    root = ElementTree.Element(
        "amulet-export",
        {
            "generator": GENERATOR,
            "contract": str(EXPORT_CONTRACT_VERSION),
            "schema": _xml_text(dataset.name),
            "schema-version": _xml_text(dataset.schema_version),
            "format": fmt.id,
            "encoding": ENCODING_NAME,
            "line-endings": LINE_ENDING_NAME,
            "exported": meta["exported"],
            "count": str(meta["count"]),
            "sensitive": "true" if meta["sensitive"] else "false",
        },
    )
    title = ElementTree.SubElement(root, "title")
    title.text = _xml_text(dataset.title)
    if dataset.unavailable:
        unavailable = ElementTree.SubElement(root, "unavailable")
        unavailable.text = _xml_text(_empty_state(dataset))
    if dataset.description:
        description = ElementTree.SubElement(root, "description")
        description.text = _xml_text(dataset.description)
    fields = ElementTree.SubElement(root, "fields")
    for item in dataset.fields:
        ElementTree.SubElement(
            fields,
            "field",
            {
                "name": _xml_text(item.name),
                "type": item.type,
                "label": _xml_text(item.label or item.name),
                "nullable": "true" if item.nullable else "false",
            },
        )
    if dataset.notes:
        notes = ElementTree.SubElement(root, "notes")
        for entry in dataset.notes:
            note = ElementTree.SubElement(notes, "note")
            note.text = _xml_text(entry)
    records = ElementTree.SubElement(root, RECORDS_KEY)
    for index, row in enumerate(dataset.rows()):
        record = ElementTree.SubElement(records, "record", {"index": str(index)})
        for name in dataset.field_names:
            _xml_value(record, "value", row[name], name=_xml_text(name))
    ElementTree.indent(root, space="  ")
    body = ElementTree.tostring(root, encoding="unicode")
    return f'<?xml version="1.0" encoding="UTF-8"?>{LINE_ENDING}{body}{LINE_ENDING}'


def _markdown_cell(value: Any) -> str:
    text = _cell(value)
    text = text.replace("\\", "\\\\").replace("|", "\\|")
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "<br>")
    return text or "&nbsp;"


def _write_markdown(
    dataset: Dataset,
    fmt: ExportFormat,
    timestamp: datetime | None,
    preamble: bool,
) -> str:
    meta = envelope(dataset, fmt, timestamp=timestamp)
    lines = [
        f"# {dataset.title}",
        "",
        f"Exported {meta['exported']} · {meta['count']} "
        f"{'record' if meta['count'] == 1 else 'records'} · UTF-8 · LF line "
        f"endings · schema `{dataset.name}` v{dataset.schema_version} · export "
        f"contract {EXPORT_CONTRACT_VERSION}",
        "",
    ]
    if dataset.description:
        lines.extend([dataset.description, ""])
    if dataset.source:
        lines.extend([f"Source: `{dataset.source}`", ""])
    if not dataset.records:
        lines.extend([_empty_state(dataset), ""])
        return LINE_ENDING.join(lines)
    lines.append("## Fields")
    lines.append("")
    lines.append("| Field | Type | Nullable | Description |")
    lines.append("| --- | --- | --- | --- |")
    for item in dataset.fields:
        lines.append(
            f"| `{item.name}` | {item.type} | "
            f"{'yes' if item.nullable else 'no'} | "
            f"{_markdown_cell(item.description or item.label or '')} |"
        )
    lines.extend(["", "## Records", ""])
    lines.append("| " + " | ".join(dataset.field_names) + " |")
    lines.append("| " + " | ".join("---" for _ in dataset.field_names) + " |")
    for row in dataset.rows():
        lines.append(
            "| "
            + " | ".join(_markdown_cell(row[name]) for name in dataset.field_names)
            + " |"
        )
    lines.append("")
    if dataset.notes:
        lines.extend(["## Notes", ""])
        lines.extend(f"- {note}" for note in dataset.notes)
        lines.append("")
    return LINE_ENDING.join(lines)


def _html_escape(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _write_html(
    dataset: Dataset,
    fmt: ExportFormat,
    timestamp: datetime | None,
    preamble: bool,
) -> str:
    meta = envelope(dataset, fmt, timestamp=timestamp)
    title = _html_escape(dataset.title)
    parts = [
        "<!DOCTYPE html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{title}</title>",
        "<style>",
        "body{font-family:system-ui,sans-serif;margin:2rem;line-height:1.5}",
        "table{border-collapse:collapse;width:100%}",
        "th,td{border:1px solid #bfc9c7;padding:.4rem .6rem;text-align:left;"
        "vertical-align:top}",
        "th{background:#edf3f2}",
        "td.value{white-space:pre-wrap}",
        "dl{display:grid;grid-template-columns:max-content 1fr;gap:.2rem 1rem}",
        "dt{font-weight:600}",
        "code{font-family:ui-monospace,monospace}",
        "@media (prefers-color-scheme:dark){body{background:#0e1514;color:#dde4e2}"
        "th{background:#182020}th,td{border-color:#3f4948}}",
        "</style>",
        "</head>",
        "<body>",
        f"<h1>{title}</h1>",
    ]
    if dataset.description:
        parts.append(f"<p>{_html_escape(dataset.description)}</p>")
    parts.append("<dl>")
    for label, value in (
        ("Exported", meta["exported"]),
        ("Records", str(meta["count"])),
        ("Encoding", ENCODING_NAME),
        ("Line endings", LINE_ENDING_NAME),
        ("Schema", f"{dataset.name} v{dataset.schema_version}"),
        ("Export contract", str(EXPORT_CONTRACT_VERSION)),
        ("Source", dataset.source or "not recorded"),
    ):
        parts.append(
            f"<dt>{_html_escape(label)}</dt><dd><code>{_html_escape(value)}</code></dd>"
        )
    parts.append("</dl>")
    if not dataset.records:
        parts.append(f"<p>{_html_escape(_empty_state(dataset))}</p>")
    else:
        parts.append(f"<table><caption>{title}</caption><thead><tr>")
        for item in dataset.fields:
            parts.append(
                f'<th scope="col" title="{_html_escape(item.type)}">'
                f"{_html_escape(item.label or item.name)}</th>"
            )
        parts.append("</tr></thead><tbody>")
        for row in dataset.rows():
            parts.append("<tr>")
            for name in dataset.field_names:
                parts.append(f'<td class="value">{_html_escape(_cell(row[name]))}</td>')
            parts.append("</tr>")
        parts.append("</tbody></table>")
    if dataset.notes:
        parts.append("<h2>Notes</h2><ul>")
        parts.extend(f"<li>{_html_escape(note)}</li>" for note in dataset.notes)
        parts.append("</ul>")
    parts.extend(["</body>", "</html>"])
    return LINE_ENDING.join(parts) + LINE_ENDING


def _sql_identifier(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_]", "_", str(name)) or "export"
    if not _SQL_IDENTIFIER.match(cleaned):
        cleaned = f"_{cleaned}"
    return cleaned


def _sql_type(field: Field) -> str:
    return {
        _TYPE_INTEGER: "INTEGER",
        _TYPE_NUMBER: "REAL",
        _TYPE_BOOLEAN: "INTEGER",
    }.get(field.type, "TEXT")


def _sql_literal(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return repr(value) if isinstance(value, float) else str(value)
    if isinstance(value, str):
        text = value
    else:
        text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return "'" + text.replace("'", "''") + "'"


def _write_sql(
    dataset: Dataset,
    fmt: ExportFormat,
    timestamp: datetime | None,
    preamble: bool,
) -> str:
    meta = envelope(dataset, fmt, timestamp=timestamp)
    table = _sql_identifier(dataset.name)
    lines = [
        f"-- {dataset.title}",
        f"-- generator: {GENERATOR}  export contract: {EXPORT_CONTRACT_VERSION}",
        f"-- encoding: {ENCODING_NAME}  line endings: {LINE_ENDING_NAME}",
        f"-- schema: {dataset.name} v{dataset.schema_version}",
        f"-- exported: {meta['exported']}  records: {meta['count']}",
        "-- Dialect: portable ANSI/SQLite.  Booleans are 1 and 0; nested "
        "values are JSON text.",
        "",
        "BEGIN;",
        f'CREATE TABLE IF NOT EXISTS "{table}" (',
    ]
    columns = []
    for item in dataset.fields:
        null_clause = "" if item.nullable else " NOT NULL"
        columns.append(
            f'    "{_sql_identifier(item.name)}" {_sql_type(item)}{null_clause}'
        )
    lines.append(",\n".join(columns))
    lines.append(");")
    if not dataset.records:
        lines.append(f"-- {_empty_state(dataset)}")
    column_list = ", ".join(
        f'"{_sql_identifier(name)}"' for name in dataset.field_names
    )
    for row in dataset.rows():
        values = ", ".join(_sql_literal(row[name]) for name in dataset.field_names)
        lines.append(f'INSERT INTO "{table}" ({column_list}) VALUES ({values});')
    lines.extend(["COMMIT;", ""])
    return LINE_ENDING.join(lines)


def _json_schema_type(field: Field) -> dict[str, Any]:
    mapping = {
        _TYPE_STRING: "string",
        _TYPE_INTEGER: "integer",
        _TYPE_NUMBER: "number",
        _TYPE_BOOLEAN: "boolean",
        _TYPE_ARRAY: "array",
        _TYPE_OBJECT: "object",
        _TYPE_NULL: "null",
    }
    kind = mapping.get(field.type)
    if kind is None:
        # A column holding several kinds of value constrains nothing; saying so
        # is more useful than picking one of them and being wrong.
        return {
            "comment": (
                "This column holds more than one kind of value, so the schema "
                "does not constrain its type."
            )
        }
    if field.nullable and kind != "null":
        return {"type": [kind, "null"]}
    return {"type": kind}


def _write_json_schema(
    dataset: Dataset,
    fmt: ExportFormat,
    timestamp: datetime | None,
    preamble: bool,
) -> str:
    meta = envelope(dataset, fmt, timestamp=timestamp)
    properties: dict[str, Any] = {}
    for item in dataset.fields:
        entry: dict[str, Any] = {
            "title": item.label or item.name,
            **_json_schema_type(item),
        }
        if item.description:
            entry["description"] = item.description
        properties[item.name] = entry
    document = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"urn:amulet-map-editor:export:{dataset.name}:{dataset.schema_version}",
        "title": dataset.title,
        "description": (
            dataset.description
            or f"Shape of the {dataset.name} export written by {GENERATOR}."
        ),
        "type": "object",
        "required": [RECORDS_KEY],
        "properties": {
            ENVELOPE_KEY: {
                "type": "object",
                "description": (
                    "Self-describing header: generator, contract version, "
                    "schema name and version, encoding, line endings, export "
                    "timestamp, record count and field list."
                ),
            },
            RECORDS_KEY: {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": properties,
                    "required": [
                        item.name for item in dataset.fields if not item.nullable
                    ],
                    "additionalProperties": False,
                },
            },
        },
        "x-amulet-export": {
            "generator": GENERATOR,
            "contract": EXPORT_CONTRACT_VERSION,
            "encoding": ENCODING_NAME,
            "line_endings": LINE_ENDING_NAME,
            "exported": meta["exported"],
            "describes_format": "json",
            "record_count": meta["count"],
            "carries_record_values": False,
        },
    }
    return json.dumps(document, ensure_ascii=False, indent=2) + LINE_ENDING


_WRITERS: dict[str, Callable[..., str]] = {
    "csv": _write_delimited(","),
    "tsv": _write_delimited("\t"),
    "json": _write_json,
    "jsonl": _write_jsonl,
    "yaml": _write_yaml,
    "toml": _write_toml,
    "xml": _write_xml,
    "markdown": _write_markdown,
    "html": _write_html,
    "sql": _write_sql,
    "jsonschema": _write_json_schema,
}


# ---------------------------------------------------------------------------
# readers -- the round trip
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ImportedDataset:
    """What came back out of an exported file."""

    metadata: Mapping[str, Any]
    records: tuple[Mapping[str, Any], ...]
    format_id: str

    @property
    def schema(self) -> str:
        return str(self.metadata.get("schema", ""))

    @property
    def schema_version(self) -> str:
        return str(self.metadata.get("schema_version", ""))

    def field_names(self) -> tuple[str, ...]:
        fields = self.metadata.get("fields")
        if isinstance(fields, list):
            return tuple(
                str(item.get("name"))
                for item in fields
                if isinstance(item, Mapping) and item.get("name") is not None
            )
        names: list[str] = []
        for record in self.records:
            for key in record:
                if key not in names:
                    names.append(key)
        return tuple(names)


def read_text(text: str, format_id: str) -> ImportedDataset:
    """Read an export back into records, for the formats whose shape allows it."""

    fmt = resolve_format(format_id)
    if not fmt.round_trip:
        raise ExportImportError(
            f"{fmt.label} is a presentation format; this application writes it "
            "but cannot read it back into records."
        )
    if not fmt.available:
        raise FormatUnavailableError(fmt.unavailable_reason)
    return _READERS[fmt.id](text)


def round_trip(dataset: Dataset, format_id: str, **kwargs: Any) -> ImportedDataset:
    """Export and immediately read back, which is what the tests assert on."""
    return read_text(export_text(dataset, format_id, **kwargs), format_id)


def _read_json(text: str) -> ImportedDataset:
    document = json.loads(text)
    if isinstance(document, list):
        return ImportedDataset({}, tuple(document), "json")
    if not isinstance(document, dict):
        raise ExportImportError("A JSON export must be an object or an array.")
    records = document.get(RECORDS_KEY, [])
    if not isinstance(records, list):
        raise ExportImportError("'records' must be an array of objects.")
    return ImportedDataset(document.get(ENVELOPE_KEY, {}) or {}, tuple(records), "json")


def _read_jsonl(text: str) -> ImportedDataset:
    metadata: Mapping[str, Any] = {}
    records: list[Mapping[str, Any]] = []
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            value = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise ExportImportError(
                f"Line {number} of the JSON Lines export is not valid JSON: {exc}"
            ) from exc
        if isinstance(value, dict) and ENVELOPE_KEY in value and not records:
            metadata = value[ENVELOPE_KEY]
            continue
        if not isinstance(value, dict):
            raise ExportImportError(
                f"Line {number} of the JSON Lines export is not an object."
            )
        records.append(value)
    return ImportedDataset(metadata, tuple(records), "jsonl")


def _coerce_cell(text: str, kind: str, nullable: bool = False) -> Any:
    """Turn one cell back into a value, using the declared type and nullability.

    An empty cell is genuinely ambiguous in a delimited file, which is why
    :func:`describe_fidelity` reports a loss for any column holding both empty
    text and missing values.  When it reports none, this restores the original
    exactly: an empty cell in a nullable column was a missing value, and in a
    column that is not nullable it was an empty string.
    """

    if kind == _TYPE_STRING:
        return None if (text == "" and nullable) else text
    if kind == _TYPE_NULL:
        return None if text == "" else text
    if kind == _TYPE_BOOLEAN:
        if text == "true":
            return True
        if text == "false":
            return False
        return None if text == "" else text
    if kind == _TYPE_INTEGER:
        if text == "":
            return None
        try:
            return int(text)
        except ValueError:
            return text
    if kind == _TYPE_NUMBER:
        if text == "":
            return None
        # A column of mixed integers and floats is declared 'number'; reading
        # an integral cell back as a float would change 1284 into 1284.0 and
        # quietly break a round trip the report called lossless.
        if re.fullmatch(r"-?\d+", text):
            return int(text)
        try:
            return float(text)
        except ValueError:
            return text
    if kind in {_TYPE_ARRAY, _TYPE_OBJECT}:
        if text == "":
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text
    return text


_PREAMBLE_METADATA = f"{COMMENT_PREFIX} amulet-export:"
_PREAMBLE_FIELDS = f"{COMMENT_PREFIX} fields:"


def _split_preamble(text: str) -> tuple[dict[str, Any], list[Mapping[str, Any]], str]:
    """Take the comment header off the front, leaving the table untouched.

    Only the two headers this module writes are consumed, and only while they
    are still at the very front: a data row whose first cell begins with a hash
    is a data row, not a comment.
    """

    metadata: dict[str, Any] = {}
    fields: list[Mapping[str, Any]] = []
    index = 0
    while text.startswith(_PREAMBLE_METADATA, index) or text.startswith(
        _PREAMBLE_FIELDS, index
    ):
        end = text.find(LINE_ENDING, index)
        line = text[index:] if end == -1 else text[index:end]
        index = len(text) if end == -1 else end + 1
        payload = line.split(":", 1)[1] if ":" in line else ""
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if line.startswith(_PREAMBLE_METADATA) and isinstance(parsed, dict):
            metadata = parsed
        elif line.startswith(_PREAMBLE_FIELDS) and isinstance(parsed, list):
            fields = parsed
    return metadata, fields, text[index:]


def _read_delimited(delimiter: str, format_id: str) -> Callable[[str], ImportedDataset]:
    def read(text: str) -> ImportedDataset:
        metadata, fields, body = _split_preamble(text)
        if fields:
            metadata = {**metadata, "fields": fields}
        # newline="" is what keeps a line break *inside* a quoted value intact;
        # splitting the text into lines first would turn a CR into an LF and
        # quietly change the value on the way back in.
        reader = csv.reader(io.StringIO(body, newline=""), delimiter=delimiter)
        rows = list(reader)
        if not rows:
            return ImportedDataset(metadata, (), format_id)
        header = rows[0]
        declared = {
            str(item.get("name")): (
                str(item.get("type", _TYPE_STRING)),
                bool(item.get("nullable", False)),
            )
            for item in fields
            if isinstance(item, Mapping)
        }
        records = []
        for row in rows[1:]:
            if not row:
                continue
            record: dict[str, Any] = {}
            for index, name in enumerate(header):
                cell = row[index] if index < len(row) else ""
                kind, nullable = declared.get(name, (_TYPE_STRING, False))
                record[name] = _coerce_cell(cell, kind, nullable)
            records.append(record)
        return ImportedDataset(metadata, tuple(records), format_id)

    return read


def _read_yaml(text: str) -> ImportedDataset:
    if _yaml is None:  # pragma: no cover - guarded by read_text
        raise FormatUnavailableError(YAML_UNAVAILABLE_REASON)
    document = _yaml.safe_load(text) or {}
    if isinstance(document, list):
        return ImportedDataset({}, tuple(document), "yaml")
    if not isinstance(document, dict):
        raise ExportImportError("A YAML export must be a mapping or a sequence.")
    return ImportedDataset(
        document.get(ENVELOPE_KEY, {}) or {},
        tuple(document.get(RECORDS_KEY, []) or ()),
        "yaml",
    )


def _read_toml(text: str) -> ImportedDataset:
    if tomllib is None:  # pragma: no cover - guarded by read_text
        raise FormatUnavailableError(
            "This Python build has no tomllib, so a TOML export cannot be read "
            "back here."
        )
    document = tomllib.loads(text)
    return ImportedDataset(
        document.get(ENVELOPE_KEY, {}) or {},
        tuple(document.get(RECORDS_KEY, []) or ()),
        "toml",
    )


def _read_xml_value(element: ElementTree.Element) -> Any:
    kind = element.get("type", _TYPE_STRING)
    if kind == _TYPE_NULL:
        return None
    if kind == _TYPE_BOOLEAN:
        return (element.text or "") == "true"
    if kind == _TYPE_INTEGER:
        return int(element.text or "0")
    if kind == _TYPE_NUMBER:
        return float(element.text or "0")
    if kind == _TYPE_ARRAY:
        return [_read_xml_value(child) for child in element.findall("item")]
    if kind == _TYPE_OBJECT:
        return {
            child.get("name", ""): _read_xml_value(child)
            for child in element.findall("value")
        }
    return element.text or ""


def _read_xml(text: str) -> ImportedDataset:
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError as exc:
        raise ExportImportError(f"The XML export is not well formed: {exc}") from exc
    metadata: dict[str, Any] = {
        "schema": root.get("schema", ""),
        "schema_version": root.get("schema-version", ""),
        "format": root.get("format", ""),
        "encoding": root.get("encoding", ""),
        "line_endings": root.get("line-endings", ""),
        "exported": root.get("exported", ""),
        "contract": root.get("contract", ""),
        "count": int(root.get("count", "0") or 0),
        "fields": [
            {
                "name": item.get("name", ""),
                "type": item.get("type", _TYPE_STRING),
                "label": item.get("label", ""),
                "nullable": item.get("nullable") == "true",
            }
            for item in root.findall("./fields/field")
        ],
    }
    records = []
    for record in root.findall(f"./{RECORDS_KEY}/record"):
        row: dict[str, Any] = {}
        for value in record.findall("value"):
            row[value.get("name", "")] = _read_xml_value(value)
        records.append(row)
    return ImportedDataset(metadata, tuple(records), "xml")


_READERS: dict[str, Callable[[str], ImportedDataset]] = {
    "csv": _read_delimited(",", "csv"),
    "tsv": _read_delimited("\t", "tsv"),
    "json": _read_json,
    "jsonl": _read_jsonl,
    "yaml": _read_yaml,
    "toml": _read_toml,
    "xml": _read_xml,
}


# ---------------------------------------------------------------------------
# archives
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ArchiveMember:
    """One file inside an archive, named relative to the archive root."""

    name: str
    data: bytes
    sensitive: bool = False


def safe_member_name(name: str) -> str:
    """Return a relative POSIX name, refusing anything that could escape.

    Extraction safety is a property of the names in the archive, so the check
    happens on the way in rather than being left to whichever extractor the
    person on the other end happens to use.
    """

    text = str(name).replace("\\", "/").strip()
    if not text:
        raise MemberNameError("An archive member must have a name.")
    if text.startswith("/") or text.startswith("//"):
        raise MemberNameError(
            f"{name!r} is an absolute path; archive members are relative so "
            "extraction cannot write outside its own directory."
        )
    if re.match(r"^[A-Za-z]:", text):
        raise MemberNameError(
            f"{name!r} names a drive; archive members are relative paths."
        )
    parts = [part for part in PurePosixPath(text).parts if part not in (".",)]
    if not parts:
        raise MemberNameError(f"{name!r} does not name a file.")
    for part in parts:
        if part == "..":
            raise MemberNameError(
                f"{name!r} walks up out of the archive with '..'; that is how "
                "an extracted file lands somewhere it was never meant to."
            )
        if "\x00" in part or _CONTROL_CHARACTERS.search(part):
            raise MemberNameError(f"{name!r} contains a control character.")
        if len(part.encode(ENCODING)) > 255:
            raise MemberNameError(f"{name!r} has a path component over 255 bytes.")
        if part.split(".")[0].lower() in _WINDOWS_RESERVED:
            raise MemberNameError(
                f"{name!r} uses {part!r}, a reserved device name on Windows; "
                "the archive would not extract there."
            )
    return "/".join(parts)


ZIP_METHODS: tuple[str, ...] = ("store", "deflate", "bzip2", "lzma")
SEVEN_ZIP_METHODS: tuple[str, ...] = (
    "lzma2",
    "lzma",
    "ppmd",
    "bzip2",
    "deflate",
    "copy",
)
SEVEN_ZIP_LEVELS: tuple[str, ...] = (
    "store",
    "fastest",
    "fast",
    "normal",
    "maximum",
    "ultra",
)
_LEVEL_PRESETS: dict[str, int] = {
    "store": 0,
    "fastest": 1,
    "fast": 3,
    "normal": 5,
    "maximum": 7,
    "ultra": 9,
}
_LEVEL_DICTIONARY: dict[str, int] = {
    "store": 64 * 1024,
    "fastest": 64 * 1024,
    "fast": 1024 * 1024,
    "normal": 16 * 1024 * 1024,
    "maximum": 32 * 1024 * 1024,
    "ultra": 64 * 1024 * 1024,
}

_SIZE_UNITS = {
    "b": 1,
    "k": 1024,
    "kb": 1024,
    "m": 1024**2,
    "mb": 1024**2,
    "g": 1024**3,
    "gb": 1024**3,
}


def parse_size(text: str) -> int:
    """Return a byte count for '64m', '4g', '512k' or a plain number."""

    value = str(text).strip().lower().replace(" ", "")
    if not value:
        raise ArchiveOptionError("A size cannot be empty.")
    match = re.fullmatch(r"(\d+)([a-z]*)", value)
    if match is None:
        raise ArchiveOptionError(
            f"{text!r} is not a size; write a number optionally followed by "
            "k, m or g."
        )
    number, unit = match.groups()
    factor = _SIZE_UNITS.get(unit or "b")
    if factor is None:
        raise ArchiveOptionError(
            f"{text!r} uses an unknown unit {unit!r}; use b, k, m or g."
        )
    return int(number) * factor


def _size_text(value: int) -> str:
    """Return a byte count as the '24m' form py7zr's PPMd filter parses."""

    for unit, factor in (("g", 1024**3), ("m", 1024**2), ("k", 1024)):
        if value >= factor and value % factor == 0:
            return f"{value // factor}{unit}"
    return str(value)


def _human_size(value: int) -> str:
    for unit, factor in (("GiB", 1024**3), ("MiB", 1024**2), ("KiB", 1024)):
        if value >= factor:
            amount = value / factor
            return f"{amount:.0f} {unit}" if amount >= 10 else f"{amount:.1f} {unit}"
    return f"{value} bytes"


@dataclass(frozen=True)
class ZipOptions:
    """What the standard-library ZIP writer can actually be asked for."""

    method: str = "deflate"
    level: str = "normal"
    comment: str = ""

    def validate(self) -> None:
        if self.method not in ZIP_METHODS:
            raise ArchiveOptionError(
                f"Unknown ZIP method {self.method!r}; this writer offers "
                + ", ".join(ZIP_METHODS)
                + "."
            )
        if self.level not in SEVEN_ZIP_LEVELS:
            raise ArchiveOptionError(
                f"Unknown compression level {self.level!r}; use "
                + ", ".join(SEVEN_ZIP_LEVELS)
                + "."
            )


@dataclass(frozen=True)
class SevenZipOptions:
    """Every 7z control this writer exposes, not one hard-coded default.

    An empty string or a zero means "the level's own default", so a caller that
    only cares about the method does not have to invent a dictionary size.
    """

    method: str = "lzma2"
    level: str = "normal"
    dictionary_size: str = ""
    word_size: int = 0
    solid: bool = True
    solid_block_size: str = ""
    threads: int = 0
    volume_size: str = ""
    password: str = ""
    encrypt_headers: bool = True

    def validate(self) -> None:
        if self.method not in SEVEN_ZIP_METHODS:
            raise ArchiveOptionError(
                f"Unknown 7z method {self.method!r}; this writer offers "
                + ", ".join(SEVEN_ZIP_METHODS)
                + "."
            )
        if self.level not in SEVEN_ZIP_LEVELS:
            raise ArchiveOptionError(
                f"Unknown compression level {self.level!r}; use "
                + ", ".join(SEVEN_ZIP_LEVELS)
                + "."
            )
        if self.dictionary_size:
            parse_size(self.dictionary_size)
        if self.solid_block_size and self.solid_block_size.lower() != "off":
            parse_size(self.solid_block_size)
        if self.volume_size:
            parse_size(self.volume_size)
        if self.word_size and not 5 <= int(self.word_size) <= 273:
            raise ArchiveOptionError(
                "The word size (nice length) must be between 5 and 273; 7-Zip "
                "uses 32 at normal and 64 at maximum."
            )
        if int(self.threads) < 0:
            raise ArchiveOptionError("The thread count cannot be negative.")

    @property
    def preset(self) -> int:
        return _LEVEL_PRESETS[self.level]

    @property
    def dictionary_bytes(self) -> int:
        if self.dictionary_size:
            return parse_size(self.dictionary_size)
        return _LEVEL_DICTIONARY[self.level]

    @property
    def encrypted(self) -> bool:
        return bool(self.password)


@dataclass(frozen=True)
class ArchivePlan:
    """What an archive would be, said before it is written.

    ``costs`` explains what each chosen option buys and what it charges in time
    and memory; ``unhonoured`` names every request this writer cannot actually
    apply, so nothing is quietly written differently from what was asked.
    """

    kind: str
    available: bool
    unavailable_reason: str
    encrypted: bool
    names_hidden: bool
    protection: str
    costs: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    unhonoured: tuple[str, ...] = ()
    filters: tuple[Mapping[str, Any], ...] = ()

    @property
    def ok(self) -> bool:
        return self.available and not self.unhonoured


def seven_zip_available() -> tuple[bool, str]:
    """Return whether 7z can be written here, and why not when it cannot."""
    return (_py7zr is not None, SEVEN_ZIP_UNAVAILABLE_REASON)


def _seven_zip_supports(parameter: str) -> bool:
    if _py7zr is None:  # pragma: no cover - guarded by the caller
        return False
    try:
        import inspect

        signature = inspect.signature(_py7zr.SevenZipFile.__init__)
    except (TypeError, ValueError):  # pragma: no cover - defensive
        return False
    return parameter in signature.parameters


def describe_zip(options: ZipOptions | None = None) -> ArchivePlan:
    """Return what a ZIP written here would and would not do."""

    chosen = options or ZipOptions()
    chosen.validate()
    costs = {
        "store": "Store: no compression at all.  Fastest possible, and the "
        "archive is the size of its contents.",
        "deflate": "Deflate: a 32 KiB window, so a fraction of a megabyte of "
        "memory either way.  Fast, modest ratio, and every unzip tool "
        "ever written can read it.",
        "bzip2": "BZip2: block sorting up to 900 KiB per block.  Roughly 8x "
        "the block size while compressing and 4x while extracting; "
        "slower than Deflate for a better ratio on text.",
        "lzma": "LZMA in a ZIP container: the best ratio here, at LZMA's "
        "memory cost -- roughly 11x the dictionary while compressing.  "
        "Older unzip tools cannot read it.",
    }[chosen.method]
    return ArchivePlan(
        kind="zip",
        available=True,
        unavailable_reason="",
        encrypted=False,
        names_hidden=False,
        protection=(
            "Not protected.  The ZIP writer in the Python standard library "
            "cannot write encrypted entries at all -- not AES-256, and not "
            "the legacy ZipCrypto that would not be worth presenting as "
            "protection anyway.  Everything inside, including the file names, "
            "is readable by anyone who has the file."
        ),
        costs=(costs, f"Compression level: {chosen.level}."),
        warnings=(),
        unhonoured=(),
    )


def describe_seven_zip(options: SevenZipOptions | None = None) -> ArchivePlan:
    """Return what a 7z written here would cost, hide, and fail to honour."""

    chosen = options or SevenZipOptions()
    chosen.validate()
    available, reason = seven_zip_available()

    dictionary = chosen.dictionary_bytes
    costs: list[str] = []
    if chosen.method in {"lzma2", "lzma"}:
        compress = int(dictionary * 11.5)
        costs.append(
            f"{chosen.method.upper()} with a {_human_size(dictionary)} "
            f"dictionary: compressing needs roughly {_human_size(compress)} of "
            f"memory (about 11.5x the dictionary) and extracting needs a "
            f"little over {_human_size(dictionary)}.  A bigger dictionary "
            "finds matches further back, so the archive is smaller and both "
            "ends need more memory."
        )
    elif chosen.method == "ppmd":
        costs.append(
            f"PPMd with a {_human_size(dictionary)} model: compressing and "
            "extracting each need the whole model in memory, and extraction "
            "is about as slow as compression.  It beats LZMA on natural-"
            "language text and loses on binary data."
        )
    elif chosen.method == "bzip2":
        costs.append(
            "BZip2: blocks of up to 900 KiB, about 8x the block size in memory "
            "while compressing and 4x while extracting.  Memory does not grow "
            "with the archive, so it is the safe choice on a small machine."
        )
    elif chosen.method == "deflate":
        costs.append(
            "Deflate: a 32 KiB window and well under a megabyte of memory "
            "either way.  The weakest ratio here and the fastest to extract."
        )
    else:
        costs.append(
            "Copy: no compression.  The archive is the size of its contents "
            "and costs nothing but the read and the write."
        )
    costs.append(
        f"Level {chosen.level} (7-Zip preset {chosen.preset}): a higher level "
        "spends more time searching for matches; it does not change what the "
        "archive can hold, only how long it takes and how small it gets."
    )
    if chosen.word_size:
        costs.append(
            f"Word size {chosen.word_size}: longer matches are searched for "
            "before giving up, which costs time and usually a little size."
        )
    costs.append(
        "Solid: one block over many files compresses much better because it "
        "sees them together, but extracting one file decompresses everything "
        "before it in the block."
        if chosen.solid
        else "Non-solid: each file compresses on its own.  Bigger archive, but "
        "any single file can be extracted without touching the rest."
    )
    if chosen.solid and chosen.solid_block_size:
        costs.append(
            f"Solid block size {chosen.solid_block_size}: a bigger block means "
            "a better ratio and more work to reach a file near its end."
        )
    if chosen.threads:
        costs.append(
            f"{chosen.threads} threads: LZMA2 splits the input, so each thread "
            "holds its own dictionary and the memory above is multiplied by "
            "the thread count."
        )
    if chosen.volume_size:
        costs.append(
            f"Split volumes of {chosen.volume_size}: the archive becomes "
            ".7z.001, .7z.002 and so on, and none of it can be extracted "
            "until every part is present."
        )

    warnings: list[str] = []
    unhonoured: list[str] = []
    if not available:
        unhonoured.append(reason)
    else:
        if chosen.volume_size and not _seven_zip_supports("volume"):
            unhonoured.append(
                "This py7zr build takes no volume size, so split volumes "
                "cannot be written here.  7-Zip itself can; py7zr reads split "
                "archives but does not write them."
            )
        if chosen.threads > 1:
            if _seven_zip_supports("mp"):
                warnings.append(
                    f"py7zr has an on/off multiprocessing switch rather than a "
                    f"thread count: it will be turned on, and the worker count "
                    f"is the library's own rather than exactly "
                    f"{chosen.threads}."
                )
            else:
                warnings.append(
                    f"This py7zr build compresses on one thread; the request "
                    f"for {chosen.threads} threads cannot be applied."
                )
        if not chosen.solid:
            warnings.append(
                "py7zr does not expose a non-solid layout; the archive will be "
                "written solid, so extracting one file still decompresses what "
                "comes before it."
            )
        if chosen.solid_block_size and not _seven_zip_supports("blocksize"):
            warnings.append(
                "This py7zr build does not take a solid block size; it will "
                "use its own."
            )

    if chosen.encrypted:
        if chosen.encrypt_headers:
            protection = (
                "AES-256 with encrypted headers: the contents, the file names, "
                "the sizes and the folder structure are all unreadable without "
                "the password.  Losing the password loses the archive; there "
                "is no recovery path."
            )
        else:
            protection = (
                "AES-256 on the contents only.  The file names, their sizes "
                "and the folder structure stay in the clear, so anyone with "
                "the file can read what is in it even though they cannot read "
                "what it says."
            )
            warnings.append(
                "Encryption without encrypted headers leaves every file name "
                "readable."
            )
    else:
        protection = (
            "Not protected.  No password was given, so everything inside is "
            "readable by anyone who has the file."
        )

    return ArchivePlan(
        kind="7z",
        available=available,
        unavailable_reason=reason,
        encrypted=chosen.encrypted,
        names_hidden=chosen.encrypted and chosen.encrypt_headers,
        protection=protection,
        costs=tuple(costs),
        warnings=tuple(warnings),
        unhonoured=tuple(unhonoured),
        filters=tuple(_seven_zip_filters(chosen)),
    )


def _seven_zip_filters(options: SevenZipOptions) -> list[dict[str, Any]]:
    """Return the py7zr filter chain the options describe."""

    if _py7zr is None:
        # Named without the library so a plan can still be shown and read.
        identifiers: Mapping[str, str] = {
            "lzma2": "FILTER_LZMA2",
            "lzma": "FILTER_LZMA",
            "ppmd": "FILTER_PPMD",
            "bzip2": "FILTER_BZIP2",
            "deflate": "FILTER_DEFLATE",
            "copy": "FILTER_COPY",
        }
        chain: list[dict[str, Any]] = [
            {"id": identifiers[options.method], "preset": options.preset}
        ]
        if options.encrypted:
            chain.append({"id": "FILTER_CRYPTO_AES256_SHA256"})
        return chain

    identifiers = {
        "lzma2": _py7zr.FILTER_LZMA2,
        "lzma": _py7zr.FILTER_LZMA,
        "ppmd": _py7zr.FILTER_PPMD,
        "bzip2": _py7zr.FILTER_BZIP2,
        "deflate": _py7zr.FILTER_DEFLATE,
        "copy": _py7zr.FILTER_COPY,
    }
    entry: dict[str, Any] = {
        "id": identifiers[options.method],
        "preset": options.preset,
    }
    if options.method in {"lzma2", "lzma"}:
        if options.dictionary_size:
            entry["dict_size"] = options.dictionary_bytes
        if options.word_size:
            entry["nice_len"] = int(options.word_size)
    elif options.method == "ppmd" and options.dictionary_size:
        # py7zr's PPMd filter parses its model size as '24m' text, not as an
        # integer count of bytes, and raises an unrelated-looking error if it
        # is handed one.
        entry["mem"] = _size_text(options.dictionary_bytes)
    chain = [entry]
    if options.encrypted:
        chain.append({"id": _py7zr.FILTER_CRYPTO_AES256_SHA256})
    return chain


@dataclass(frozen=True)
class ArchiveResult:
    """The written archive, its plan, and what actually went into it."""

    path: Path
    kind: str
    members: tuple[str, ...]
    plan: ArchivePlan
    size: int
    sensitive: bool = False


def _prepare_members(
    members: Iterable[ArchiveMember], *, sensitive: bool
) -> tuple[ArchiveMember, ...]:
    prepared: list[ArchiveMember] = []
    seen: set[str] = set()
    for member in members:
        name = safe_member_name(member.name)
        if name in seen:
            raise MemberNameError(
                f"{name!r} appears twice; an archive member name must be unique."
            )
        seen.add(name)
        if member.sensitive and not sensitive:
            raise ArchiveProtectionError(
                f"{name!r} is marked as carrying secrets and this archive was "
                "not created as sensitive.  Create it with sensitive=True, "
                "having decided that these values may travel."
            )
        prepared.append(ArchiveMember(name, member.data, member.sensitive))
    if not prepared:
        raise ArchiveOptionError("An archive needs at least one member.")
    return tuple(prepared)


def write_zip(
    members: Iterable[ArchiveMember],
    target: str | os.PathLike[str],
    options: ZipOptions | None = None,
    *,
    sensitive: bool = False,
    accept_unencrypted: bool = False,
) -> ArchiveResult:
    """Write a ZIP, refusing to carry secrets it cannot protect."""

    chosen = options or ZipOptions()
    plan = describe_zip(chosen)
    prepared = _prepare_members(members, sensitive=sensitive)
    if sensitive and not accept_unencrypted:
        raise ArchiveProtectionError(
            "This bundle is marked as carrying secrets and ZIP here cannot "
            "encrypt anything.  Use 7z with a password and encrypted headers, "
            "or pass accept_unencrypted=True to write it in the clear having "
            "understood that."
        )
    compression = {
        "store": zipfile.ZIP_STORED,
        "deflate": zipfile.ZIP_DEFLATED,
        "bzip2": zipfile.ZIP_BZIP2,
        "lzma": zipfile.ZIP_LZMA,
    }[chosen.method]
    level = _LEVEL_PRESETS[chosen.level]
    path = Path(target).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    kwargs: dict[str, Any] = {}
    if chosen.method in {"deflate", "bzip2"}:
        kwargs["compresslevel"] = max(1, level) if chosen.method == "bzip2" else level
    with zipfile.ZipFile(path, "w", compression=compression, **kwargs) as archive:
        if chosen.comment:
            archive.comment = chosen.comment.encode(ENCODING)
        for member in prepared:
            info = zipfile.ZipInfo(member.name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = compression
            info.external_attr = 0o644 << 16
            archive.writestr(info, member.data)
    return ArchiveResult(
        path=path,
        kind="zip",
        members=tuple(member.name for member in prepared),
        plan=plan,
        size=path.stat().st_size,
        sensitive=sensitive,
    )


def write_seven_zip(
    members: Iterable[ArchiveMember],
    target: str | os.PathLike[str],
    options: SevenZipOptions | None = None,
    *,
    sensitive: bool = False,
    accept_visible_names: bool = False,
    accept_unhonoured: bool = False,
) -> ArchiveResult:
    """Write a 7z, or refuse by name -- never quietly write something else.

    Asking for encryption and getting a ZIP instead would be the worst possible
    outcome here, so a missing py7zr is a refusal with the import failure in
    it, not a fallback.
    """

    chosen = options or SevenZipOptions()
    plan = describe_seven_zip(chosen)
    if not plan.available:
        raise ArchiveUnavailableError(plan.unavailable_reason)
    if plan.unhonoured and not accept_unhonoured:
        raise ArchiveOptionError(
            "This 7z writer cannot honour part of what was asked for: "
            + "; ".join(plan.unhonoured)
            + ".  Change the options, or pass accept_unhonoured=True having "
            "read what will differ."
        )
    if chosen.encrypted and not chosen.encrypt_headers and not accept_visible_names:
        raise ArchiveProtectionError(
            "Encrypting the contents while leaving the file names in the clear "
            "would present this archive as protected when its names, sizes and "
            "folder structure are readable by anyone.  Set "
            "encrypt_headers=True, or pass accept_visible_names=True to say "
            "plainly that the names may be seen."
        )
    if sensitive and not chosen.encrypted:
        raise ArchiveProtectionError(
            "This bundle is marked as carrying secrets and no password was "
            "given, so the archive would protect nothing."
        )
    prepared = _prepare_members(members, sensitive=sensitive)
    path = Path(target).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)

    kwargs: dict[str, Any] = {
        "filters": list(plan.filters),
    }
    if chosen.encrypted:
        kwargs["password"] = chosen.password
        kwargs["header_encryption"] = bool(chosen.encrypt_headers)
    if chosen.volume_size and _seven_zip_supports("volume"):
        kwargs["volume"] = parse_size(chosen.volume_size)
    if chosen.threads > 1 and _seven_zip_supports("mp"):
        kwargs["mp"] = True
    if chosen.solid_block_size and _seven_zip_supports("blocksize"):
        lowered = chosen.solid_block_size.lower()
        if lowered != "off":
            kwargs["blocksize"] = parse_size(chosen.solid_block_size)
    try:
        with _py7zr.SevenZipFile(path, "w", **kwargs) as archive:
            for member in prepared:
                archive.writef(io.BytesIO(member.data), member.name)
    except Exception as exc:  # pragma: no cover - depends on py7zr at runtime
        raise ExportError(
            f"py7zr could not write {path.name}: {exc}.  Nothing was written "
            "in another format in its place."
        ) from exc
    return ArchiveResult(
        path=path,
        kind="7z",
        members=tuple(member.name for member in prepared),
        plan=plan,
        size=path.stat().st_size if path.exists() else 0,
        sensitive=sensitive,
    )


def write_archive(
    members: Iterable[ArchiveMember],
    target: str | os.PathLike[str],
    *,
    kind: str = "zip",
    zip_options: ZipOptions | None = None,
    seven_zip_options: SevenZipOptions | None = None,
    sensitive: bool = False,
    accept_unencrypted: bool = False,
    accept_visible_names: bool = False,
    accept_unhonoured: bool = False,
) -> ArchiveResult:
    """Write one archive of the named kind, refusing an unknown one."""

    key = str(kind).strip().lower().lstrip(".")
    if key == "zip":
        return write_zip(
            members,
            target,
            zip_options,
            sensitive=sensitive,
            accept_unencrypted=accept_unencrypted,
        )
    if key in {"7z", "sevenzip", "seven_zip"}:
        return write_seven_zip(
            members,
            target,
            seven_zip_options,
            sensitive=sensitive,
            accept_visible_names=accept_visible_names,
            accept_unhonoured=accept_unhonoured,
        )
    raise ArchiveOptionError(
        f"Unknown archive kind {kind!r}; this application writes zip and 7z."
    )


# ---------------------------------------------------------------------------
# bundles
# ---------------------------------------------------------------------------
def bundle_members(
    datasets: Sequence[Dataset],
    format_ids: Sequence[str],
    *,
    accept_loss: bool = False,
    timestamp: datetime | None = None,
    manifest: bool = True,
) -> tuple[ArchiveMember, ...]:
    """Render every dataset in every named format as archive members.

    A manifest and a README travel with them so the archive explains itself
    without this application: what each file is, its encoding and line endings,
    its schema version, and every loss that was accepted on the way in.
    """

    members: list[ArchiveMember] = []
    entries: list[dict[str, Any]] = []
    for dataset in datasets:
        for format_id in format_ids:
            fmt = resolve_format(format_id)
            report = describe_fidelity(dataset, fmt.id)
            if not report.available:
                raise FormatUnavailableError(report.unavailable_reason)
            if report.losses and not accept_loss:
                raise LossyExportError(report)
            text = export_text(
                dataset, fmt.id, accept_loss=accept_loss, timestamp=timestamp
            )
            name = f"{dataset.name}/{dataset.name}{fmt.extension}"
            members.append(
                ArchiveMember(
                    safe_member_name(name),
                    text.encode(ENCODING),
                    sensitive=dataset.carries_secrets,
                )
            )
            entries.append(
                {
                    "file": safe_member_name(name),
                    "dataset": dataset.name,
                    "title": dataset.title,
                    "schema_version": dataset.schema_version,
                    "format": fmt.id,
                    "media_type": fmt.media_type,
                    "encoding": ENCODING_NAME,
                    "line_endings": LINE_ENDING_NAME,
                    "records": len(dataset.records),
                    "re_importable": fmt.round_trip,
                    "carries_record_values": fmt.carries_records,
                    "sensitive": dataset.carries_secrets,
                    "losses": [
                        {
                            "field": loss.field,
                            "reason": loss.reason,
                            "detail": loss.detail,
                            "records": loss.records,
                        }
                        for loss in report.losses
                    ],
                }
            )
    if manifest and members:
        document = {
            "generator": GENERATOR,
            "contract": EXPORT_CONTRACT_VERSION,
            "created": _iso(timestamp),
            "encoding": ENCODING_NAME,
            "line_endings": LINE_ENDING_NAME,
            "files": entries,
        }
        members.append(
            ArchiveMember(
                "MANIFEST.json",
                (
                    json.dumps(document, ensure_ascii=False, indent=2) + LINE_ENDING
                ).encode(ENCODING),
                sensitive=any(entry["sensitive"] for entry in entries),
            )
        )
        members.append(
            ArchiveMember(
                "README.md",
                _bundle_readme(entries, timestamp).encode(ENCODING),
                sensitive=False,
            )
        )
    return tuple(members)


def _bundle_readme(
    entries: Sequence[Mapping[str, Any]], timestamp: datetime | None
) -> str:
    lines = [
        "# Amulet Studio export bundle",
        "",
        f"Created {_iso(timestamp)} · {len(entries)} "
        f"{'file' if len(entries) == 1 else 'files'} · UTF-8 · LF line endings "
        f"· export contract {EXPORT_CONTRACT_VERSION}",
        "",
        "Every file states its own schema, schema version, encoding and line "
        "endings in its header, so none of them needs this README to be read.",
        "",
        "| File | Dataset | Format | Records | Reads back |",
        "| --- | --- | --- | --- | --- |",
    ]
    for entry in entries:
        lines.append(
            f"| `{entry['file']}` | {entry['title']} | {entry['format']} | "
            f"{entry['records']} | {'yes' if entry['re_importable'] else 'no'} |"
        )
    lossy = [entry for entry in entries if entry["losses"]]
    if lossy:
        lines.extend(["", "## What these formats could not carry", ""])
        for entry in lossy:
            lines.append(f"- `{entry['file']}`")
            for loss in entry["losses"]:
                where = f"`{loss['field']}`: " if loss["field"] else ""
                lines.append(
                    f"  - {where}{loss['detail']} ({loss['records']} affected)"
                )
    lines.append("")
    return LINE_ENDING.join(lines)
