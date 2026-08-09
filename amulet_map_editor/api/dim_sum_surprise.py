"""wx-independent startup foundation for the dim-sum surprise.

The catalog is read only from the canonical public catalog URL.  This module
never downloads or stores an image; a presentation adapter must resolve the
returned catalog image path against a published ``catalog-v1*`` release asset.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import random
import secrets
from threading import Lock, Thread
from typing import Any, Callable, Optional, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

CATALOG_URL = (
    "https://raw.githubusercontent.com/Ding-Ding-Projects/"
    "dim-sum-photos/main/catalog/index.json"
)
CATALOG_TIMEOUT_SECONDS = 3.0
MAX_CATALOG_BYTES = 8 * 1024 * 1024
SURPRISE_PROBABILITY = 0.10
LANGUAGE_MODES = ("english", "cantonese", "bilingual")


@dataclass(frozen=True)
class DishMetadata:
    """The bounded subset of authoritative catalog metadata used by the UI."""

    dish_id: str
    name_english: str
    name_cantonese: str
    alt_english: str
    alt_cantonese: str
    image_asset_path: str


@dataclass(frozen=True)
class DimSumSurprisePayload:
    """A focus-safe state that a UI may present as an auto-dismissing notice."""

    status: str
    dish_id: str
    title: str
    alt_text: str
    image_asset_path: str
    catalog_url: str = CATALOG_URL
    non_blocking: bool = True
    steal_focus: bool = False
    auto_dismiss_seconds: int = 8


def notification_copy(payload: DimSumSurprisePayload) -> Tuple[str, str]:
    """Return factual, presentation-neutral copy for a non-blocking toast.

    The consumer application must not fetch or vendor the image here.  The
    second line intentionally names the catalog asset path and alt text so a
    native adapter can expose an honest accessible projection while an
    application-data/public-release image resolver is unavailable.
    """

    if payload.status != "ready":
        raise ValueError("only ready payloads can be projected")
    title = f"Dim-sum surprise: {payload.title}"
    body = f"{payload.alt_text} · Public catalog image: {payload.image_asset_path}"
    return title, body


def should_show(draw: float) -> bool:
    """Return whether a fresh random draw falls in the exact ten-percent band."""

    if isinstance(draw, bool) or not isinstance(draw, (int, float)):
        raise TypeError("draw must be a number in the half-open interval [0, 1)")
    if not 0 <= draw < 1:
        raise ValueError("draw must be in the half-open interval [0, 1)")
    return draw < SURPRISE_PROBABILITY


def _bounded_text(value: Any, *, maximum: int = 240) -> Optional[str]:
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value or len(value) > maximum or any(ord(char) < 32 for char in value):
        return None
    return value


def _dish_from_document(value: Any) -> Optional[DishMetadata]:
    if not isinstance(value, dict):
        return None
    name = value.get("name")
    image = value.get("image")
    if not isinstance(name, dict) or not isinstance(image, dict):
        return None
    alt = image.get("alt")
    if not isinstance(alt, dict):
        return None

    dish_id = _bounded_text(value.get("id"), maximum=64)
    name_english = _bounded_text(name.get("en"))
    name_cantonese = _bounded_text(name.get("zhHant"))
    alt_english = _bounded_text(alt.get("en"), maximum=500)
    alt_cantonese = _bounded_text(alt.get("yue"), maximum=500)
    image_path = _bounded_text(image.get("path"), maximum=180)
    if None in (
        dish_id,
        name_english,
        name_cantonese,
        alt_english,
        alt_cantonese,
        image_path,
    ):
        return None
    assert image_path is not None
    path_parts = image_path.replace("\\", "/").split("/")
    if (
        path_parts[0] != "images"
        or any(part in ("", ".", "..") for part in path_parts)
        or not image_path.lower().endswith(".png")
    ):
        return None
    return DishMetadata(
        dish_id=dish_id,
        name_english=name_english,
        name_cantonese=name_cantonese,
        alt_english=alt_english,
        alt_cantonese=alt_cantonese,
        image_asset_path=image_path,
    )


def fetch_public_catalog(
    *,
    timeout: float = CATALOG_TIMEOUT_SECONDS,
    opener: Callable[..., Any] = urlopen,
) -> Tuple[DishMetadata, ...]:
    """Fetch the bounded public catalog, returning no dishes on any failure."""

    if timeout <= 0 or timeout > CATALOG_TIMEOUT_SECONDS:
        raise ValueError(
            f"timeout must be greater than zero and at most {CATALOG_TIMEOUT_SECONDS}"
        )
    request = Request(
        CATALOG_URL,
        headers={"Accept": "application/json", "User-Agent": "Amulet-Map-Editor"},
    )
    try:
        with opener(request, timeout=timeout) as response:
            final_url = (
                response.geturl() if hasattr(response, "geturl") else CATALOG_URL
            )
            if final_url != CATALOG_URL:
                return ()
            content_length = response.headers.get("Content-Length")
            if content_length is not None and int(content_length) > MAX_CATALOG_BYTES:
                return ()
            raw = response.read(MAX_CATALOG_BYTES + 1)
        if len(raw) > MAX_CATALOG_BYTES:
            return ()
        document = json.loads(raw.decode("utf-8"))
        if not isinstance(document, dict) or document.get("schemaVersion") != "1.0.0":
            return ()
        values = document.get("dishes")
        if not isinstance(values, list):
            return ()
        dishes = tuple(
            dish for dish in (_dish_from_document(value) for value in values) if dish
        )
        return dishes
    except (
        HTTPError,
        URLError,
        TimeoutError,
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        TypeError,
        ValueError,
    ):
        return ()


def build_payload(dish: DishMetadata, language_mode: str) -> DimSumSurprisePayload:
    """Build localized, factual copy without changing catalog dish names."""

    if language_mode not in LANGUAGE_MODES:
        raise ValueError("unsupported language mode")
    if language_mode == "english":
        title = dish.name_english
        alt_text = dish.alt_english
    elif language_mode == "cantonese":
        title = dish.name_cantonese
        alt_text = dish.alt_cantonese
    else:
        title = f"{dish.name_english} · {dish.name_cantonese}"
        alt_text = f"{dish.alt_english} / {dish.alt_cantonese}"
    return DimSumSurprisePayload(
        status="ready",
        dish_id=dish.dish_id,
        title=title,
        alt_text=alt_text,
        image_asset_path=dish.image_asset_path,
    )


class StartupDimSumSurprise:
    """Perform at most one startup draw and resolve a winner off the UI thread."""

    def __init__(
        self,
        *,
        random_value: Callable[[], float] = random.random,
        chooser: Callable[[Sequence[DishMetadata]], DishMetadata] = secrets.choice,
        catalog_fetcher: Callable[[], Tuple[DishMetadata, ...]] = fetch_public_catalog,
    ) -> None:
        self._random_value = random_value
        self._chooser = chooser
        self._catalog_fetcher = catalog_fetcher
        self._attempted = False
        self._lock = Lock()

    @property
    def attempted(self) -> bool:
        with self._lock:
            return self._attempted

    def begin(
        self,
        language_mode: str,
        on_ready: Callable[[DimSumSurprisePayload], None],
        *,
        eligible: bool = True,
    ) -> bool:
        """Start one eligible draw; return immediately without touching wx.

        ``eligible`` lets the application suppress first-run, update, error, or
        mid-task launches before any presentation work is scheduled.
        """

        if language_mode not in LANGUAGE_MODES:
            raise ValueError("unsupported language mode")
        with self._lock:
            if self._attempted:
                return False
            self._attempted = True
        if not eligible or not should_show(self._random_value()):
            return False
        Thread(
            target=self._resolve,
            args=(language_mode, on_ready),
            name="amulet-dim-sum-surprise",
            daemon=True,
        ).start()
        return True

    def _resolve(
        self,
        language_mode: str,
        on_ready: Callable[[DimSumSurprisePayload], None],
    ) -> None:
        try:
            dishes = self._catalog_fetcher()
            if dishes:
                on_ready(build_payload(self._chooser(dishes), language_mode))
        except Exception:
            # Startup delight is optional. Network, selection, or presentation
            # failures must remain an offline-safe no-op and never gate launch.
            return
