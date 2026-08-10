"""Headless model for bounded, searchable Material 3 command menus.

The wxPython view lives in :mod:`amulet_map_editor.api.wx.components`.  Keeping
normalisation, filtering, and keyboard selection here makes the behaviour easy
to test without importing wx or constructing a GUI.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
import unicodedata

MAX_QUERY_CHARS = 256
MAX_RESULTS = 200


def visible_menu_label(label: str) -> str:
    """Return a display label without wx mnemonic or accelerator markup."""

    text = str(label).split("\t", 1)[0]
    # Preserve escaped ampersands while removing single mnemonic markers.
    marker = "\0"
    return text.replace("&&", marker).replace("&", "").replace(marker, "&").strip()


def _normalise(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value))
    return " ".join(text.casefold().split())


@dataclass(frozen=True, slots=True)
class MaterialMenuItem:
    """One command presented by a Material menu.

    ``identifier`` retains the legacy wx command ID where one exists.  The
    callback stays opaque to this model and is invoked by the wx view.
    """

    label: str
    callback: Callable[..., object]
    description: str = ""
    identifier: int = -1
    section: str = ""
    enabled: bool = True
    keywords: tuple[str, ...] = field(default_factory=tuple)
    shortcut: str = ""

    def __post_init__(self) -> None:
        raw_label = str(self.label)
        clean_label = visible_menu_label(raw_label)
        if not clean_label:
            raise ValueError("Material menu items require a non-empty label")
        if not callable(self.callback):
            raise TypeError("Material menu item callback must be callable")
        object.__setattr__(self, "label", clean_label)
        object.__setattr__(self, "description", str(self.description or "").strip())
        object.__setattr__(self, "section", str(self.section or "").strip())
        derived_shortcut = (
            raw_label.split("\t", 1)[1].strip() if "\t" in raw_label else ""
        )
        object.__setattr__(
            self, "shortcut", str(self.shortcut or derived_shortcut).strip()
        )
        object.__setattr__(
            self,
            "keywords",
            tuple(
                str(keyword).strip()
                for keyword in self.keywords
                if str(keyword).strip()
            ),
        )

    @property
    def search_fields(self) -> tuple[str, ...]:
        return (
            _normalise(self.label),
            _normalise(self.description),
            _normalise(self.section),
            _normalise(self.shortcut),
            *(_normalise(keyword) for keyword in self.keywords),
        )


def _item_score(item: MaterialMenuItem, tokens: Sequence[str]) -> tuple[int, int]:
    fields = item.search_fields
    label = fields[0]
    combined = " ".join(field for field in fields if field)
    score = 0
    for token in tokens:
        if label == token:
            score += 0
        elif label.startswith(token):
            score += 1
        elif any(word.startswith(token) for word in label.split()):
            score += 2
        elif token in label:
            score += 3
        elif token in combined:
            score += 4
        else:
            return (10_000, 10_000)
    # Prefer shorter labels only after semantic match quality.  Input order is
    # added by the caller as the final stable tiebreaker.
    return score, len(label)


def filter_menu_items(
    items: Iterable[MaterialMenuItem],
    query: object = "",
    *,
    limit: int = MAX_RESULTS,
) -> tuple[MaterialMenuItem, ...]:
    """Filter menu items with literal, case-insensitive, bounded matching.

    No regular expression is compiled from user input.  Every whitespace-
    separated query token must occur in at least one searchable field.
    """

    bounded_limit = max(0, min(int(limit), MAX_RESULTS))
    if bounded_limit == 0:
        return ()
    candidates = tuple(items)
    raw_query = str(query)[:MAX_QUERY_CHARS]
    normalised_query = _normalise(raw_query)[:MAX_QUERY_CHARS]
    if not normalised_query:
        return candidates[:bounded_limit]
    tokens = tuple(token for token in normalised_query.split(" ") if token)
    ranked: list[tuple[tuple[int, int], int, MaterialMenuItem]] = []
    for index, item in enumerate(candidates):
        score = _item_score(item, tokens)
        if score[0] < 10_000:
            ranked.append((score, index, item))
    ranked.sort(key=lambda row: (row[0], row[1]))
    return tuple(row[2] for row in ranked[:bounded_limit])


@dataclass(slots=True)
class MenuSelection:
    """Roving selection index that skips disabled commands."""

    index: int = -1

    @staticmethod
    def _enabled_indices(enabled: Sequence[bool]) -> tuple[int, ...]:
        return tuple(index for index, value in enumerate(enabled) if value)

    def reset(self, enabled: Sequence[bool]) -> int:
        indices = self._enabled_indices(enabled)
        self.index = indices[0] if indices else -1
        return self.index

    def clamp(self, enabled: Sequence[bool]) -> int:
        indices = self._enabled_indices(enabled)
        if not indices:
            self.index = -1
        elif self.index not in indices:
            self.index = indices[0]
        return self.index

    def move(self, delta: int, enabled: Sequence[bool]) -> int:
        indices = self._enabled_indices(enabled)
        if not indices:
            self.index = -1
            return self.index
        if self.index not in indices:
            self.index = indices[0 if delta >= 0 else -1]
            return self.index
        current = indices.index(self.index)
        self.index = indices[(current + (1 if delta >= 0 else -1)) % len(indices)]
        return self.index


__all__ = [
    "MAX_QUERY_CHARS",
    "MAX_RESULTS",
    "MaterialMenuItem",
    "MenuSelection",
    "filter_menu_items",
    "visible_menu_label",
]
