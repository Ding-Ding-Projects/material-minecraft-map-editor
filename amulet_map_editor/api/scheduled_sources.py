"""Fail-safe external sources for scheduled settings.

The source layer is deliberately independent from wx and persistence. Remote
values are validated before use and are never written back as a user's base
preferences. Callers provide Home Assistant tokens from an OS credential
vault; this module never stores or logs them.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from amulet_map_editor.api.scheduled_settings import ScheduledValues, ScheduleValidationError

SOURCE_VERSION = 1
MAX_URL_LENGTH = 2048
MAX_ENTITY_LENGTH = 256
MAX_RESPONSE_BYTES = 64 * 1024
DEFAULT_TIMEOUT_SECONDS = 3
ALLOWED_KINDS = ("local", "api", "home_assistant")
_ALLOWED_KEYS = {"language_mode", "theme", "density", "accent"}
_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}


class SourceValidationError(ValueError):
    """Raised when a source cannot be represented safely."""


@dataclass(frozen=True)
class ScheduleSource:
    kind: str = "local"
    url: str = ""
    entity_id: str = ""
    refresh_seconds: int = 300

    def __post_init__(self) -> None:
        if self.kind not in ALLOWED_KINDS:
            raise SourceValidationError("source kind is unsupported")
        if not isinstance(self.refresh_seconds, int) or isinstance(self.refresh_seconds, bool):
            raise SourceValidationError("refresh_seconds must be an integer")
        if not 30 <= self.refresh_seconds <= 86_400:
            raise SourceValidationError("refresh_seconds must be between 30 and 86400")
        if self.kind == "local":
            if self.url or self.entity_id:
                raise SourceValidationError("local sources cannot carry a URL or entity")
            return
        validate_source_url(self.url)
        if self.kind == "home_assistant":
            if not self.entity_id or len(self.entity_id) > MAX_ENTITY_LENGTH:
                raise SourceValidationError("entity_id must be bounded text")
            if re.fullmatch(r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", self.entity_id) is None:
                raise SourceValidationError("entity_id must look like domain.object")

    def as_dict(self) -> dict[str, Any]:
        return {"version": SOURCE_VERSION, "kind": self.kind, "url": self.url, "entity_id": self.entity_id, "refresh_seconds": self.refresh_seconds}


@dataclass(frozen=True)
class SourceResult:
    ok: bool
    values: dict[str, str]
    detail: str = ""


def validate_source_url(url: str) -> str:
    if not isinstance(url, str) or not url or len(url) > MAX_URL_LENGTH:
        raise SourceValidationError("source URL is required and bounded")
    parsed = urlsplit(url)
    if parsed.scheme not in {"https", "http"} or not parsed.hostname:
        raise SourceValidationError("source URL must use HTTPS")
    if parsed.username or parsed.password:
        raise SourceValidationError("source URL cannot contain credentials")
    if parsed.fragment or parsed.query:
        raise SourceValidationError("source URL cannot contain a query or fragment")
    host = parsed.hostname.lower().rstrip(".")
    if parsed.scheme == "http" and host not in _LOOPBACK_HOSTS:
        raise SourceValidationError("HTTP is allowed only for loopback development sources")
    return url.rstrip("/")


def validate_values(payload: Mapping[str, Any]) -> dict[str, str]:
    if not isinstance(payload, Mapping):
        raise SourceValidationError("source response must be an object")
    if payload.get("version") != SOURCE_VERSION:
        raise SourceValidationError("source response version is unsupported")
    raw = payload.get("values")
    if not isinstance(raw, Mapping) or set(raw) - _ALLOWED_KEYS:
        raise SourceValidationError("source response contains unknown setting fields")
    try:
        return ScheduledValues.from_dict(dict(raw)).as_dict()
    except ScheduleValidationError as exc:
        raise SourceValidationError(str(exc)) from exc


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise SourceValidationError("source redirects are not allowed")


def _read_json(response) -> Mapping[str, Any]:
    length = response.headers.get("Content-Length")
    if length and int(length) > MAX_RESPONSE_BYTES:
        raise SourceValidationError("source response is too large")
    body = response.read(MAX_RESPONSE_BYTES + 1)
    if len(body) > MAX_RESPONSE_BYTES:
        raise SourceValidationError("source response is too large")
    try:
        value = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SourceValidationError("source response is not UTF-8 JSON") from exc
    if not isinstance(value, Mapping):
        raise SourceValidationError("source response must be an object")
    return value


def fetch_source(source: ScheduleSource, *, token: str | None = None, opener=None, timeout: int = DEFAULT_TIMEOUT_SECONDS) -> SourceResult:
    """Fetch one source without raising network or validation errors to UI."""

    try:
        if source.kind == "local":
            return SourceResult(True, {})
        endpoint = source.url
        headers = {"Accept": "application/json"}
        if source.kind == "home_assistant":
            endpoint = f"{source.url}/api/states/{source.entity_id}"
            if token:
                headers["Authorization"] = f"Bearer {token}"
        request = Request(endpoint, headers=headers, method="GET")
        client = opener or build_opener(_NoRedirect())
        response = client.open(request, timeout=min(DEFAULT_TIMEOUT_SECONDS, max(1, int(timeout))))
        payload = _read_json(response)
        if source.kind == "home_assistant":
            if payload.get("state") != "on":
                return SourceResult(True, {}, "Home Assistant source is off")
            attributes = payload.get("attributes")
            return SourceResult(True, validate_values(attributes if isinstance(attributes, Mapping) else {}))
        return SourceResult(True, validate_values(payload))
    except (SourceValidationError, HTTPError, URLError, OSError, ValueError, TypeError) as exc:
        return SourceResult(False, {}, str(exc)[:240])


__all__ = ["ScheduleSource", "SourceResult", "SourceValidationError", "fetch_source", "validate_source_url", "validate_values"]
