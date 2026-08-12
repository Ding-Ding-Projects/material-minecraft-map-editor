"""Optional, local text-to-speech narration for user-facing events.

The narrator is deliberately wx-independent.  It is disabled by default and
has a no-op backend when no platform speech provider is available.  A caller
can therefore wire events without making startup, updates, or tests depend on
an installed voice or on network access.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
import logging
import threading
import hashlib
import time
from typing import Callable, Dict, Optional, Protocol, Tuple

from amulet_map_editor.api import config

log = logging.getLogger(__name__)

SETTINGS_ID = "amulet_tts_narrator"
SETTINGS_VERSION = 1
LANGUAGES: Tuple[str, ...] = ("english", "cantonese", "both")
MIN_COOLDOWN_SECONDS = 0.0
MAX_COOLDOWN_SECONDS = 3600.0
MIN_DEBOUNCE_SECONDS = 0.0
MAX_DEBOUNCE_SECONDS = 10.0


@dataclass
class NarratorSettings:
    """Persisted narrator settings; narration is opt-in."""

    version: int = SETTINGS_VERSION
    enabled: bool = False
    language: str = "english"
    category_cooldown_seconds: float = 15.0
    debounce_seconds: float = 0.25

    def normalised(self) -> "NarratorSettings":
        self.version = SETTINGS_VERSION
        self.enabled = bool(self.enabled)
        if self.language not in LANGUAGES:
            self.language = "english"
        try:
            self.category_cooldown_seconds = min(
                MAX_COOLDOWN_SECONDS,
                max(MIN_COOLDOWN_SECONDS, float(self.category_cooldown_seconds)),
            )
        except (TypeError, ValueError):
            self.category_cooldown_seconds = 15.0
        try:
            self.debounce_seconds = min(
                MAX_DEBOUNCE_SECONDS,
                max(MIN_DEBOUNCE_SECONDS, float(self.debounce_seconds)),
            )
        except (TypeError, ValueError):
            self.debounce_seconds = 0.25
        return self


def load_settings() -> NarratorSettings:
    """Load bounded settings; malformed state falls back safely to off."""
    raw = config.get(SETTINGS_ID, {})
    if not isinstance(raw, dict):
        raw = {}
    fields = {key: raw[key] for key in asdict(NarratorSettings()) if key in raw}
    return NarratorSettings(**fields).normalised()


def save_settings(settings: NarratorSettings) -> NarratorSettings:
    """Persist settings without storing voice data or credentials."""
    settings = settings.normalised()
    config.put(SETTINGS_ID, asdict(settings))
    return settings


def update_settings(**changes: object) -> NarratorSettings:
    """Apply known narrator settings atomically."""
    settings = load_settings()
    unknown = set(changes) - set(asdict(settings))
    if unknown:
        raise KeyError("Unknown narrator setting(s): " + ", ".join(sorted(unknown)))
    for key, value in changes.items():
        setattr(settings, key, value)
    return save_settings(settings)


class SpeechBackend(Protocol):
    """Small backend boundary used by the serialized queue."""

    def speak(self, text: str, language: str) -> None:
        """Speak one utterance synchronously, or return when unavailable."""


class NullSpeechBackend:
    """Safe no-op backend used when platform TTS is unavailable."""

    available = False

    def speak(self, text: str, language: str) -> None:
        del text, language


def default_backend() -> SpeechBackend:
    """Return a backend without importing optional speech packages.

    A future platform adapter may be injected by the application.  Until then,
    returning a no-op keeps the feature honest: no Cantonese voice is claimed
    and no dependency is downloaded or invoked implicitly.
    """
    return NullSpeechBackend()


#: Asides by language and level.  Several per level, deliberately.
#:
#: This was one fixed string per level, and that is not humour -- it is a tag.
#: At level five every message in the application ended with the identical
#: seven words, so a window carrying six sentences said "the code is dancing;
#: the facts stay put" six times.  Repetition turns a joke into a rendering
#: fault: a reader stops seeing it as voice and starts seeing it as something
#: the application is stuck on.  It also added roughly forty characters to
#: every string at once, which is a large part of why so much of this interface
#: was overflowing its controls.
#:
#: Each pool keeps the same promise the single line made: the aside comments on
#: the telling and never on the facts, and it is short enough that the sentence
#: it follows is still the thing being read.
_ASIDES: Dict[str, Dict[int, Tuple[str, ...]]] = {
    "english": {
        3: (
            " (small flourish, same facts)",
            " (lightly said, unchanged)",
            " (a little polish, nothing moved)",
        ),
        4: (
            " (the code is doing a tiny victory lap)",
            " (said with a small flourish)",
            " (the numbers are unimpressed)",
            " (delivered with feeling)",
        ),
        5: (
            " (the code is dancing; the facts stay put)",
            " (said with jazz hands; the facts did not join in)",
            " (announced with confetti, meaning unchanged)",
            " (the facts are wearing a party hat and nothing else changed)",
            " (delivered enthusiastically by a program with no stake in it)",
        ),
    },
    "cantonese": {
        3: (
            "（輕輕講，件事仍然係呢件事。）",
            "（講得鬆啲,內容一樣。）",
            "（順口講講,冇變過。）",
        ),
        4: (
            "（個程式行緊小小花式，但資料冇變。）",
            "（講得誇少少,數字照舊。）",
            "（語氣加咗料,事實冇加。）",
            "（有啲得戚,不過講嘅嘢一樣。）",
        ),
        5: (
            "（程式扭兩扭，事實照樣企喺度。）",
            "（又唱又跳咁報,件事一個字都冇改。）",
            "（撒花咁講,內容原封不動。）",
            "（好興奮咁講,雖然佢自己都冇份。）",
            "（戴住派對帽讀出嚟,數據依然係數據。）",
        ),
    },
}


def asides(language: str, funny_level: int) -> Tuple[str, ...]:
    """Return every aside :func:`style_text` may append at this level.

    Public so a guard can enumerate the whole pool instead of transcribing it.
    A test that styles one sentinel discovers only the single aside that
    sentinel happens to hash to, and would then read the other four as "no
    tone applied" -- which is exactly what happened when the pools replaced the
    one fixed string per level.
    """
    level = min(5, max(1, int(funny_level)))
    pool = _ASIDES.get(
        "cantonese" if language == "cantonese" else "english", _ASIDES["english"]
    )
    return pool.get(level, ())


def style_text(text: str, language: str, funny_level: int) -> str:
    """Style voice without changing the facts in the event text.

    Levels 1 and 2 remain professional.  Higher levels add a short, bounded
    aside after the supplied factual sentence; callers own the actual facts.

    The aside is chosen from the level's pool by hashing the sentence, which
    matters for two reasons.  It VARIES, so a window full of messages does not
    read as one phrase stuck on repeat.  And it is STABLE: the same sentence
    always draws the same aside, so a repaint, a resize or a re-render cannot
    change the words on screen underneath the reader -- a random choice here
    would make text shimmer on every mouse-move in an owner-drawn interface
    that repaints constantly.
    """
    text = str(text).strip()
    level = min(5, max(1, int(funny_level)))
    if level <= 2 or not text:
        return text
    pool = _ASIDES.get(
        "cantonese" if language == "cantonese" else "english", _ASIDES["english"]
    )[level]
    # blake2b rather than hash(): the built-in is salted per process, so the
    # same sentence would draw a different aside on every launch.
    digest = hashlib.blake2b(text.encode("utf-8"), digest_size=8).digest()
    return text + pool[int.from_bytes(digest, "big") % len(pool)]


@dataclass
class _Pending:
    category: str
    english: str
    cantonese: str
    english_level: int
    cantonese_level: int
    due: float


class Narrator:
    """Serialized, debounced narrator with per-category cooldowns.

    ``announce`` replaces an older pending event from the same category.  The
    worker speaks one utterance at a time and, for ``both``, always completes
    English before Cantonese.  ``close`` is safe during application shutdown.
    """

    def __init__(
        self,
        backend: Optional[SpeechBackend] = None,
        settings: Optional[NarratorSettings] = None,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.backend = backend or default_backend()
        self.settings = (settings or load_settings()).normalised()
        self._clock = clock
        self._condition = threading.Condition()
        self._pending: Dict[str, _Pending] = {}
        self._last_spoken: Dict[str, float] = {}
        self._speaking = False
        self._closed = False
        self._worker = threading.Thread(
            target=self._run, name="amulet-tts-narrator", daemon=True
        )
        self._worker.start()

    def announce(
        self,
        category: str,
        english: str,
        cantonese: str,
        *,
        funny_level_english: int = 1,
        funny_level_cantonese: int = 1,
    ) -> bool:
        """Queue one event, returning ``False`` when narration is disabled."""
        category = str(category).strip()
        if not category or not self.settings.enabled:
            return False
        pending = _Pending(
            category,
            str(english).strip(),
            str(cantonese).strip(),
            min(5, max(1, int(funny_level_english))),
            min(5, max(1, int(funny_level_cantonese))),
            self._clock() + self.settings.debounce_seconds,
        )
        with self._condition:
            if self._closed:
                return False
            self._pending[category] = pending
            self._condition.notify_all()
        return True

    def _run(self) -> None:
        while True:
            with self._condition:
                if self._closed:
                    return
                now = self._clock()
                ready = [item for item in self._pending.values() if item.due <= now]
                if not ready:
                    timeout = 0.5
                    if self._pending:
                        timeout = max(
                            0.0, min(item.due - now for item in self._pending.values())
                        )
                    self._condition.wait(timeout)
                    continue
                item = min(ready, key=lambda candidate: candidate.due)
                cooldown_until = (
                    self._last_spoken.get(item.category, 0.0)
                    + self.settings.category_cooldown_seconds
                )
                if cooldown_until > now:
                    if self._pending.get(item.category) is item:
                        item.due = cooldown_until
                        self._pending[item.category] = item
                    self._condition.wait(max(0.0, cooldown_until - now))
                    continue
                # Remove only the object currently pending. A concurrent announce
                # may replace it while the backend is speaking.
                if self._pending.get(item.category) is item:
                    del self._pending[item.category]
                self._speaking = True
            self._speak(item)
            with self._condition:
                self._last_spoken[item.category] = self._clock()
                self._speaking = False
                self._condition.notify_all()

    def _speak(self, item: _Pending) -> None:
        language = self.settings.language
        utterances = []
        if language in {"english", "both"} and item.english:
            utterances.append(
                (style_text(item.english, "english", item.english_level), "english")
            )
        if language in {"cantonese", "both"} and item.cantonese:
            utterances.append(
                (
                    style_text(item.cantonese, "cantonese", item.cantonese_level),
                    "cantonese",
                )
            )
        for text, voice_language in utterances:
            try:
                self.backend.speak(text, voice_language)
            except Exception:  # pragma: no cover - defensive platform boundary
                log.exception("Narrator backend failed; continuing without narration")

    def flush(self, timeout: float = 2.0) -> bool:
        """Wait until currently queued items are spoken or timeout expires."""
        deadline = self._clock() + max(0.0, timeout)
        with self._condition:
            while (self._pending or self._speaking) and not self._closed:
                remaining = deadline - self._clock()
                if remaining <= 0:
                    return False
                self._condition.wait(remaining)
            return not self._pending

    def close(self) -> None:
        with self._condition:
            self._closed = True
            self._pending.clear()
            self._condition.notify_all()
        if self._worker.is_alive():
            self._worker.join(timeout=1.0)


def announce_event(
    narrator: Narrator,
    category: str,
    english: str,
    cantonese: str,
    *,
    funny_level_english: Optional[int] = None,
    funny_level_cantonese: Optional[int] = None,
) -> bool:
    """Minimal app-event hook using the shared persisted funny-level settings."""
    if funny_level_english is None or funny_level_cantonese is None:
        from amulet_map_editor.api import preferences

        current = preferences.load()
        funny_level_english = current.funny_level_english
        funny_level_cantonese = current.funny_level_cantonese
    return narrator.announce(
        category,
        english,
        cantonese,
        funny_level_english=funny_level_english,
        funny_level_cantonese=funny_level_cantonese,
    )
