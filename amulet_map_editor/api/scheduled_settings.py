"""Validated, persisted local schedules for user-facing preferences.

This module intentionally has no wx dependency and performs no network access.
It defines the storage and resolution contract that a future wx surface can use
without making that surface responsible for schedule semantics.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
import re
from typing import Any, Dict, Iterable, Mapping, Optional, Tuple

from amulet_map_editor.api import config

SCHEDULES_ID = "amulet_scheduled_settings"
SCHEDULES_VERSION = 1
MAX_RULES = 256
MAX_RULE_ID_LENGTH = 64
MAX_RULE_LABEL_LENGTH = 120

LANGUAGE_MODES: Tuple[str, ...] = ("english", "cantonese", "bilingual")
THEMES: Tuple[str, ...] = ("light", "dark", "system")
DENSITIES: Tuple[str, ...] = ("compact", "comfortable", "spacious")
SETTING_KEYS: Tuple[str, ...] = ("language_mode", "theme", "density", "accent")
ALL_WEEKDAYS: Tuple[int, ...] = tuple(range(7))

_RULE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
_ACCENT = re.compile(r"#[0-9A-Fa-f]{6}(?:[0-9A-Fa-f]{2})?")
_CLOCK = re.compile(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]")


class ScheduleValidationError(ValueError):
    """Raised when a schedule document cannot be represented safely."""


class UnsupportedScheduleVersion(ScheduleValidationError):
    """Raised instead of guessing how to read a newer storage schema."""


def _parse_date(value: Optional[str], name: str) -> Optional[date]:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ScheduleValidationError(f"{name} must be an ISO date or null")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ScheduleValidationError(f"{name} must use YYYY-MM-DD") from exc
    if parsed.isoformat() != value:
        raise ScheduleValidationError(f"{name} must use YYYY-MM-DD")
    return parsed


def _parse_time(value: str, name: str) -> time:
    if not isinstance(value, str) or _CLOCK.fullmatch(value) is None:
        raise ScheduleValidationError(f"{name} must use 24-hour HH:MM")
    return time.fromisoformat(value)


def _validated_weekdays(values: Iterable[int]) -> Tuple[int, ...]:
    if isinstance(values, (str, bytes)):
        raise ScheduleValidationError("weekdays must be a list of integers")
    weekdays = tuple(values)
    if not weekdays:
        raise ScheduleValidationError("weekdays must contain at least one day")
    if any(isinstance(day, bool) or not isinstance(day, int) for day in weekdays):
        raise ScheduleValidationError("weekdays must contain only integers")
    if any(day < 0 or day > 6 for day in weekdays):
        raise ScheduleValidationError("weekdays must be between 0 and 6")
    if len(set(weekdays)) != len(weekdays):
        raise ScheduleValidationError("weekdays must not contain duplicates")
    return tuple(sorted(weekdays))


@dataclass(frozen=True)
class ScheduledValues:
    """A partial, validated scheduled override."""

    language_mode: Optional[str] = None
    theme: Optional[str] = None
    density: Optional[str] = None
    accent: Optional[str] = None

    def __post_init__(self) -> None:
        if self.language_mode is not None and self.language_mode not in LANGUAGE_MODES:
            raise ScheduleValidationError("language_mode is not supported")
        if self.theme is not None and self.theme not in THEMES:
            raise ScheduleValidationError("theme is not supported")
        if self.density is not None and self.density not in DENSITIES:
            raise ScheduleValidationError("density is not supported")
        if self.accent is not None and (
            not isinstance(self.accent, str) or _ACCENT.fullmatch(self.accent) is None
        ):
            raise ScheduleValidationError("accent must be #RRGGBB or #RRGGBBAA")
        if not self.as_dict():
            raise ScheduleValidationError("a rule must override at least one setting")

    def as_dict(self) -> Dict[str, str]:
        return {
            key: value
            for key in SETTING_KEYS
            if (value := getattr(self, key)) is not None
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "ScheduledValues":
        if not isinstance(raw, Mapping):
            raise ScheduleValidationError("values must be an object")
        unknown = set(raw) - set(SETTING_KEYS)
        if unknown:
            raise ScheduleValidationError(
                "unknown scheduled setting(s): " + ", ".join(sorted(unknown))
            )
        return cls(**dict(raw))


@dataclass(frozen=True)
class ScheduleRule:
    """One local-time window and its partial setting override."""

    rule_id: str
    label: str
    values: ScheduledValues
    enabled: bool = True
    priority: int = 0
    weekdays: Tuple[int, ...] = ALL_WEEKDAYS
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    start_time: str = "00:00"
    end_time: str = "00:00"
    source: Optional[Mapping[str, Any]] = None
    _start_date_value: Optional[date] = field(init=False, repr=False, compare=False)
    _end_date_value: Optional[date] = field(init=False, repr=False, compare=False)
    _start_time_value: time = field(init=False, repr=False, compare=False)
    _end_time_value: time = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if (
            not isinstance(self.rule_id, str)
            or _RULE_ID.fullmatch(self.rule_id) is None
        ):
            raise ScheduleValidationError(
                "rule_id must be 1-64 letters, numbers, dots, underscores, or hyphens"
            )
        if not isinstance(self.label, str) or not self.label.strip():
            raise ScheduleValidationError("label must not be blank")
        if len(self.label) > MAX_RULE_LABEL_LENGTH:
            raise ScheduleValidationError("label must be at most 120 characters")
        if not isinstance(self.enabled, bool):
            raise ScheduleValidationError("enabled must be a boolean")
        if isinstance(self.priority, bool) or not isinstance(self.priority, int):
            raise ScheduleValidationError("priority must be an integer")
        if self.priority < -10_000 or self.priority > 10_000:
            raise ScheduleValidationError("priority must be between -10000 and 10000")

        weekdays = _validated_weekdays(self.weekdays)
        start_date_value = _parse_date(self.start_date, "start_date")
        end_date_value = _parse_date(self.end_date, "end_date")
        if (
            start_date_value is not None
            and end_date_value is not None
            and start_date_value > end_date_value
        ):
            raise ScheduleValidationError("start_date must not be after end_date")

        object.__setattr__(self, "weekdays", weekdays)
        object.__setattr__(self, "_start_date_value", start_date_value)
        object.__setattr__(self, "_end_date_value", end_date_value)
        object.__setattr__(
            self, "_start_time_value", _parse_time(self.start_time, "start_time")
        )
        object.__setattr__(
            self, "_end_time_value", _parse_time(self.end_time, "end_time")
        )
        # Validate the optional external-source contract lazily to avoid a
        # module cycle: scheduled_sources validates ScheduledValues from this
        # module, while this rule only needs its public source shape.
        from amulet_map_editor.api.scheduled_sources import ScheduleSource

        raw_source = self.source or {
            "kind": "local",
            "url": "",
            "entity_id": "",
            "refresh_seconds": 300,
        }
        if not isinstance(raw_source, Mapping):
            raise ScheduleValidationError("source must be an object")
        try:
            source = ScheduleSource(
                kind=raw_source.get("kind", "local"),
                url=raw_source.get("url", ""),
                entity_id=raw_source.get("entity_id", ""),
                refresh_seconds=raw_source.get("refresh_seconds", 300),
            )
        except (TypeError, ValueError) as exc:
            raise ScheduleValidationError(str(exc)) from exc
        object.__setattr__(self, "source", source.as_dict())

    def matches(self, moment: datetime) -> bool:
        """Return whether *moment*, interpreted in caller-supplied local time, matches."""
        if not isinstance(moment, datetime):
            raise TypeError("moment must be a datetime")
        if not self.enabled:
            return False

        clock = moment.time().replace(tzinfo=None)
        overnight = self._end_time_value < self._start_time_value
        all_day = self._end_time_value == self._start_time_value

        if all_day:
            effective_date = moment.date()
        elif overnight:
            if clock >= self._start_time_value:
                effective_date = moment.date()
            elif clock < self._end_time_value:
                effective_date = moment.date() - timedelta(days=1)
            else:
                return False
        else:
            if not (self._start_time_value <= clock < self._end_time_value):
                return False
            effective_date = moment.date()

        if effective_date.weekday() not in self.weekdays:
            return False
        if (
            self._start_date_value is not None
            and effective_date < self._start_date_value
        ):
            return False
        if self._end_date_value is not None and effective_date > self._end_date_value:
            return False
        return True

    def as_dict(self) -> Dict[str, Any]:
        return {
            "id": self.rule_id,
            "label": self.label,
            "enabled": self.enabled,
            "priority": self.priority,
            "weekdays": list(self.weekdays),
            "start_date": self.start_date,
            "end_date": self.end_date,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "source": dict(self.source or {}),
            "values": self.values.as_dict(),
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "ScheduleRule":
        if not isinstance(raw, Mapping):
            raise ScheduleValidationError("each rule must be an object")
        expected = {
            "id",
            "label",
            "enabled",
            "priority",
            "weekdays",
            "start_date",
            "end_date",
            "start_time",
            "end_time",
            "source",
            "values",
        }
        unknown = set(raw) - expected
        if unknown:
            raise ScheduleValidationError(
                "unknown rule field(s): " + ", ".join(sorted(unknown))
            )
        required = {"id", "label", "values"}
        missing = required - set(raw)
        if missing:
            raise ScheduleValidationError(
                "missing rule field(s): " + ", ".join(sorted(missing))
            )
        return cls(
            rule_id=raw["id"],
            label=raw["label"],
            values=ScheduledValues.from_dict(raw["values"]),
            enabled=raw.get("enabled", True),
            priority=raw.get("priority", 0),
            weekdays=tuple(raw.get("weekdays", ALL_WEEKDAYS)),
            start_date=raw.get("start_date"),
            end_date=raw.get("end_date"),
            start_time=raw.get("start_time", "00:00"),
            end_time=raw.get("end_time", "00:00"),
            source=raw.get("source"),
        )


@dataclass(frozen=True)
class ScheduleDocument:
    """The complete versioned schedule document persisted for one profile."""

    rules: Tuple[ScheduleRule, ...] = ()
    version: int = SCHEDULES_VERSION

    def __post_init__(self) -> None:
        if (
            isinstance(self.version, bool)
            or not isinstance(self.version, int)
            or self.version != SCHEDULES_VERSION
        ):
            raise UnsupportedScheduleVersion(
                f"schedule version {self.version!r} is not supported"
            )
        rules = tuple(self.rules)
        if any(not isinstance(rule, ScheduleRule) for rule in rules):
            raise ScheduleValidationError("rules must contain only ScheduleRule values")
        object.__setattr__(self, "rules", rules)
        if len(self.rules) > MAX_RULES:
            raise ScheduleValidationError(f"at most {MAX_RULES} rules are supported")
        identifiers = [rule.rule_id for rule in self.rules]
        if len(set(identifiers)) != len(identifiers):
            raise ScheduleValidationError("rule ids must be unique")

    def resolve(
        self, moment: datetime, base_values: Mapping[str, str]
    ) -> "ScheduleResolution":
        """Resolve rules deterministically over validated base values.

        Lower-priority matches apply first. Higher priorities override them and,
        for equal priorities, a rule later in stored order wins per setting.
        """
        if not isinstance(base_values, Mapping):
            raise ScheduleValidationError("base values must be an object")
        unknown = set(base_values) - set(SETTING_KEYS)
        if unknown:
            raise ScheduleValidationError(
                "unknown base setting(s): " + ", ".join(sorted(unknown))
            )
        resolved = dict(base_values)
        matched = [
            (index, rule)
            for index, rule in enumerate(self.rules)
            if rule.matches(moment)
        ]
        matched.sort(key=lambda item: (item[1].priority, item[0]))
        for _, rule in matched:
            resolved.update(rule.values.as_dict())
        return ScheduleResolution(
            values=resolved,
            matched_rule_ids=tuple(rule.rule_id for _, rule in matched),
        )

    def as_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "rules": [rule.as_dict() for rule in self.rules],
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "ScheduleDocument":
        if not isinstance(raw, Mapping):
            raise ScheduleValidationError("schedule document must be an object")
        unknown = set(raw) - {"version", "rules"}
        if unknown:
            raise ScheduleValidationError(
                "unknown schedule field(s): " + ", ".join(sorted(unknown))
            )
        version = raw.get("version")
        if (
            isinstance(version, bool)
            or not isinstance(version, int)
            or version != SCHEDULES_VERSION
        ):
            raise UnsupportedScheduleVersion(
                f"schedule version {version!r} is not supported"
            )
        rules = raw.get("rules")
        if not isinstance(rules, list):
            raise ScheduleValidationError("rules must be a list")
        return cls(
            rules=tuple(ScheduleRule.from_dict(rule) for rule in rules),
            version=version,
        )


@dataclass(frozen=True)
class ScheduleResolution:
    """Resolved values plus an auditable low-to-high precedence trace."""

    values: Dict[str, str]
    matched_rule_ids: Tuple[str, ...]


def load() -> ScheduleDocument:
    """Load and validate the local schedule document.

    Missing or unreadable config uses an empty version-1 document. Structurally
    invalid readable data raises so callers cannot mistake ignored rules for an
    applied schedule.
    """
    raw = config.get(SCHEDULES_ID, None)
    if raw is None:
        return ScheduleDocument()
    return ScheduleDocument.from_dict(raw)


def save(document: ScheduleDocument) -> ScheduleDocument:
    """Validate and persist a schedule document using the existing local store."""
    if not isinstance(document, ScheduleDocument):
        raise TypeError("document must be a ScheduleDocument")
    validated = ScheduleDocument.from_dict(document.as_dict())
    config.put(SCHEDULES_ID, validated.as_dict())
    return validated


def replace_rules(rules: Iterable[ScheduleRule]) -> ScheduleDocument:
    """Replace all rules in one validated persistence operation."""
    return save(ScheduleDocument(rules=tuple(rules)))
