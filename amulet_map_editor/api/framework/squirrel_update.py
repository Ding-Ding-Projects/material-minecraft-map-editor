"""Small, wx-independent bridge for Squirrel.Windows updates.

Squirrel owns downloading and applying release packages.  This module only
discovers ``Update.exe``, validates an HTTPS feed, and reports a non-blocking
state that a UI can turn into a ready-to-restart notification.  No signing
tool or signing credential is ever invoked.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
import subprocess
import sys
from typing import Any, Dict, Optional
from urllib.request import Request, urlopen
from urllib.parse import urlparse

DEFAULT_FEED_URL = (
    "https://github.com/Ding-Ding-Projects/material-minecraft-map-editor/releases/"
)
RELEASES_API_URL = "https://api.github.com/repos/Ding-Ding-Projects/material-minecraft-map-editor/releases?per_page=100"
DEFAULT_UPDATE_CHANNEL = "automated"
UPDATE_STAGE_TIMEOUT_SECONDS = 15 * 60
_MAX_RELEASES_RESPONSE_BYTES = 1_000_000
_MAX_RELEASES = 100
_MAX_RELEASE_ASSETS = 32
_AUTOMATED_PATCH_BASE = 100_000
_AUTOMATED_RUN_LIMIT = 899_999
_AUTOMATED_PATCH_LIMIT = _AUTOMATED_PATCH_BASE + _AUTOMATED_RUN_LIMIT
_AUTOMATED_TAG = re.compile(
    r"^v?(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)" r"-dev[.-]?(?P<run>\d+)$",
    re.IGNORECASE,
)
_STABLE_TAG = re.compile(r"^v?(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)$")
_RELEASE_NOTES_PATH = re.compile(
    r"^/Ding-Ding-Projects/material-minecraft-map-editor/releases/tag/"
    r"(?P<tag>[0-9A-Za-z._-]{1,128})$"
)
_RELEASE_DOWNLOAD_PATH = re.compile(
    r"^/Ding-Ding-Projects/material-minecraft-map-editor/releases/download/"
    r"(?P<tag>[0-9A-Za-z._-]{1,128})/$"
)
_SQUIRREL_APP_DIRECTORY = re.compile(
    r"^app-\d+\.\d+\.\d+(?:-[0-9A-Za-z-]+)?$", re.IGNORECASE
)


@dataclass(frozen=True)
class SquirrelUpdateState:
    status: str
    version: Optional[str] = None
    feed_url: Optional[str] = None
    release_notes_url: Optional[str] = None
    unsigned_warning: bool = True
    detail: Optional[str] = None


def validate_feed_url(feed_url: str) -> str:
    """Require this project's immutable GitHub release-download directory."""

    parsed = urlparse(feed_url)
    if (
        parsed.scheme.lower() != "https"
        or parsed.hostname != "github.com"
        or parsed.port is not None
        or parsed.username
        or parsed.password
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            "Squirrel update feeds must use the immutable project GitHub route"
        )
    match = _RELEASE_DOWNLOAD_PATH.fullmatch(parsed.path)
    if match is None:
        raise ValueError(
            "Squirrel update feeds must use the immutable project GitHub route"
        )
    tag = match.group("tag")
    _validate_release_tag(tag)
    expected = (
        "https://github.com/Ding-Ding-Projects/material-minecraft-map-editor/"
        f"releases/download/{tag}/"
    )
    if feed_url != expected:
        raise ValueError("Squirrel update feed URL is not canonical")
    return feed_url


def validate_release_notes_url(release_notes_url: str) -> str:
    """Require the exact public GitHub release-notes route for this project."""

    parsed = urlparse(release_notes_url)
    if (
        parsed.scheme.lower() != "https"
        or parsed.hostname != "github.com"
        or parsed.port is not None
        or parsed.username
        or parsed.password
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Release notes must use an immutable project GitHub URL")
    match = _RELEASE_NOTES_PATH.fullmatch(parsed.path)
    if match is None:
        raise ValueError("Release notes must use an immutable project GitHub URL")
    tag = match.group("tag")
    _validate_release_tag(tag)
    expected = (
        "https://github.com/Ding-Ding-Projects/material-minecraft-map-editor/"
        f"releases/tag/{tag}"
    )
    if release_notes_url != expected:
        raise ValueError("Release notes URL is not canonical")
    return release_notes_url


def find_update_exe(start: Optional[Path] = None) -> Optional[Path]:
    """Find ``Update.exe`` only in an expected Squirrel install layout."""

    explicit_start = start is not None
    current = (start or Path(sys.executable)).resolve()
    if current.is_file():
        current = current.parent
    if _SQUIRREL_APP_DIRECTORY.fullmatch(current.name):
        install_root = current.parent
    elif explicit_start and current.is_dir():
        # An explicit install-root probe is useful to the updater tests and to
        # diagnostics, but it still has to contain a real app-* directory.
        try:
            has_app_directory = any(
                child.is_dir()
                and not child.is_symlink()
                and _SQUIRREL_APP_DIRECTORY.fullmatch(child.name)
                for child in current.iterdir()
            )
        except OSError:
            return None
        if not has_app_directory:
            return None
        install_root = current
    else:
        # Source checkouts and arbitrary executable trees are not installations.
        return None
    updater = install_root / "Update.exe"
    if updater.is_file() and not updater.is_symlink():
        return updater
    return None


def _release_version(tag: object, channel: str) -> tuple[int, int, int, int] | None:
    """Parse a release tag in one explicit channel using numeric ordering."""

    if channel == "automated":
        match = _AUTOMATED_TAG.fullmatch(str(tag))
    elif channel == "stable":
        match = _STABLE_TAG.fullmatch(str(tag))
    else:
        raise ValueError(f"Unsupported Squirrel update channel: {channel}")
    if match is None:
        return None
    patch = int(match.group("patch"))
    if channel == "automated":
        run = int(match.group("run"))
        if patch != 0:
            raise ValueError("Automated source tags must use patch zero")
        if run > _AUTOMATED_RUN_LIMIT:
            return None
    else:
        run = 0
        if _AUTOMATED_PATCH_BASE <= patch <= _AUTOMATED_PATCH_LIMIT:
            raise ValueError(
                "Stable patch enters the reserved automated range "
                f"{_AUTOMATED_PATCH_BASE}..{_AUTOMATED_PATCH_LIMIT}"
            )
    return (
        int(match.group("major")),
        int(match.group("minor")),
        patch,
        run,
    )


def _validate_release_tag(tag: str) -> None:
    """Require a bounded tag in exactly one supported release channel."""

    if _AUTOMATED_TAG.fullmatch(tag):
        if _release_version(tag, "automated") is None:
            raise ValueError("Automated release tag exceeds the supported run range")
        return
    if _STABLE_TAG.fullmatch(tag):
        _release_version(tag, "stable")
        return
    raise ValueError("Squirrel update feed tag is not a supported release tag")


def _allowed_package_versions(tag: str, channel: str) -> set[str]:
    """Return the exact legacy/current package identities allowed for *tag*."""

    if channel == "automated":
        match = _AUTOMATED_TAG.fullmatch(tag)
        assert match is not None
        run = int(match.group("run"))
        core = (
            f"{int(match.group('major'))}."
            f"{int(match.group('minor'))}."
            f"{int(match.group('patch'))}"
        )
        return {
            f"{core}-dev{run}",
            (
                f"{int(match.group('major'))}."
                f"{int(match.group('minor'))}."
                f"{_AUTOMATED_PATCH_BASE + run}"
            ),
        }
    match = _STABLE_TAG.fullmatch(tag)
    assert match is not None
    return {
        (
            f"{int(match.group('major'))}."
            f"{int(match.group('minor'))}."
            f"{int(match.group('patch'))}"
        )
    }


def _validate_inventory_response(response: object) -> None:
    """Fail closed when the GitHub inventory response changes route or shape."""

    geturl = getattr(response, "geturl", None)
    if not callable(geturl) or geturl() != RELEASES_API_URL:
        raise ValueError("GitHub releases inventory redirected unexpectedly")

    status = getattr(response, "status", None)
    if status is None:
        getcode = getattr(response, "getcode", None)
        status = getcode() if callable(getcode) else None
    if status != 200:
        raise ValueError(f"GitHub releases inventory returned HTTP {status}")

    headers = getattr(response, "headers", None)
    content_type: object = None
    if headers is not None:
        get_content_type = getattr(headers, "get_content_type", None)
        if callable(get_content_type):
            content_type = get_content_type()
        else:
            get_header = getattr(headers, "get", None)
            if callable(get_header):
                content_type = get_header("Content-Type")
    normalized = str(content_type or "").split(";", 1)[0].strip().lower()
    if normalized not in {"application/json", "application/vnd.github+json"}:
        raise ValueError("GitHub releases inventory was not JSON")


def _resolve_latest_feed(timeout: float, channel: str) -> tuple[str, str]:
    """Choose the numerically highest published feed in one explicit channel."""

    request = Request(
        RELEASES_API_URL, headers={"Accept": "application/vnd.github+json"}
    )
    with urlopen(request, timeout=timeout) as response:
        _validate_inventory_response(response)
        body = response.read(_MAX_RELEASES_RESPONSE_BYTES + 1)
    if len(body) > _MAX_RELEASES_RESPONSE_BYTES:
        raise ValueError("GitHub releases response exceeded the size limit")
    payload = json.loads(body.decode("utf-8"))
    if not isinstance(payload, list):
        raise ValueError("GitHub releases response was not a list")
    if len(payload) > _MAX_RELEASES:
        raise ValueError("GitHub releases response exceeded the release limit")
    candidates = []
    for release in payload:
        if not isinstance(release, dict) or release.get("draft"):
            continue
        tag = release.get("tag_name")
        assets = release.get("assets")
        if not isinstance(tag, str) or not isinstance(assets, list):
            continue
        if len(assets) > _MAX_RELEASE_ASSETS:
            raise ValueError(f"Release {tag} exceeded the asset limit")
        release_indexes = [
            asset
            for asset in assets
            if isinstance(asset, dict) and asset.get("name") == "RELEASES"
        ]
        full_packages = []
        for asset in assets:
            if not isinstance(asset, dict):
                continue
            package_match = re.fullmatch(
                r"Amulet-(?P<version>\d+\.\d+\.\d+(?:-[0-9A-Za-z-]+)?)-full\.nupkg",
                str(asset.get("name", "")),
            )
            if package_match:
                full_packages.append((asset, package_match.group("version")))
        if len(release_indexes) != 1 or len(full_packages) != 1:
            continue
        version = _release_version(tag, channel)
        if version is None:
            continue
        if full_packages[0][1] not in _allowed_package_versions(tag, channel):
            raise ValueError(f"Release {tag} had a mismatched full package identity")
        notes = release.get("html_url")
        if not isinstance(notes, str):
            raise ValueError(f"Release {tag} had no release-notes URL")
        notes = validate_release_notes_url(notes)
        expected_notes = (
            "https://github.com/Ding-Ding-Projects/material-minecraft-map-editor/"
            f"releases/tag/{tag}"
        )
        if notes != expected_notes:
            raise ValueError(f"Release {tag} had mismatched release-notes metadata")
        candidates.append((version, tag, notes))
    if not candidates:
        raise ValueError("No published Squirrel release feed was found")
    _version, tag, notes = max(candidates)
    feed = (
        "https://github.com/Ding-Ding-Projects/material-minecraft-map-editor/"
        f"releases/download/{tag}/"
    )
    return validate_feed_url(feed), notes


def _release_notes_from_feed(feed_url: str) -> Optional[str]:
    validate_feed_url(feed_url)
    parsed = urlparse(feed_url)
    match = _RELEASE_DOWNLOAD_PATH.fullmatch(parsed.path)
    assert match is not None
    return validate_release_notes_url(
        "https://github.com/Ding-Ding-Projects/material-minecraft-map-editor/"
        f"releases/tag/{match.group('tag')}"
    )


def _run_update(update_exe: Path, argument: str, timeout: float) -> Dict[str, Any]:
    result = subprocess.run(
        [str(update_exe), argument],
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode:
        raise RuntimeError("Squirrel Update.exe failed")
    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise RuntimeError("Squirrel Update.exe returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("Squirrel Update.exe returned an invalid payload")
    return payload


def check_for_update(
    feed_url: Optional[str] = None,
    current_version: Optional[str] = None,
    update_exe: Optional[Path] = None,
    timeout: float = 10.0,
    channel: str = DEFAULT_UPDATE_CHANNEL,
) -> SquirrelUpdateState:
    """Check the Squirrel feed and return a state suitable for a notification."""

    try:
        if feed_url is None or feed_url == DEFAULT_FEED_URL:
            feed, release_notes_url = _resolve_latest_feed(timeout, channel)
        else:
            feed = validate_feed_url(feed_url)
            release_notes_url = _release_notes_from_feed(feed)
            match = _RELEASE_DOWNLOAD_PATH.fullmatch(urlparse(feed).path)
            assert match is not None
            if _release_version(match.group("tag"), channel) is None:
                raise ValueError(
                    f"Squirrel feed tag does not belong to channel {channel}"
                )
    except (OSError, ValueError) as exc:
        return SquirrelUpdateState("failed", detail=str(exc))
    updater = update_exe or find_update_exe()
    if updater is None:
        return SquirrelUpdateState(
            "not_installed",
            feed_url=feed,
            release_notes_url=release_notes_url,
            detail="Squirrel install not detected",
        )
    try:
        payload = _run_update(updater, "--checkForUpdate=" + feed, timeout)
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        return SquirrelUpdateState(
            "failed",
            feed_url=feed,
            release_notes_url=release_notes_url,
            detail=str(exc),
        )
    future = payload.get("futureReleaseEntry")
    if not isinstance(future, dict):
        return SquirrelUpdateState(
            "up_to_date", feed_url=feed, release_notes_url=release_notes_url
        )
    version = future.get("version") or future.get("Version")
    if current_version and str(version) == str(current_version):
        return SquirrelUpdateState(
            "up_to_date", feed_url=feed, release_notes_url=release_notes_url
        )
    return SquirrelUpdateState(
        "available",
        version=str(version) if version else None,
        feed_url=feed,
        release_notes_url=release_notes_url,
    )


def stage_update(
    feed_url: str,
    update_exe: Optional[Path] = None,
    timeout: float = UPDATE_STAGE_TIMEOUT_SECONDS,
    version: Optional[str] = None,
    release_notes_url: Optional[str] = None,
) -> SquirrelUpdateState:
    """Download/apply the selected update; restart remains an explicit UI action."""

    try:
        feed = validate_feed_url(feed_url)
        notes = (
            validate_release_notes_url(release_notes_url)
            if release_notes_url
            else _release_notes_from_feed(feed)
        )
        feed_tag_match = _RELEASE_DOWNLOAD_PATH.fullmatch(urlparse(feed).path)
        notes_tag_match = _RELEASE_NOTES_PATH.fullmatch(urlparse(notes).path)
        assert feed_tag_match is not None and notes_tag_match is not None
        if feed_tag_match.group("tag") != notes_tag_match.group("tag"):
            raise ValueError("Release notes do not match the selected Squirrel feed")
    except ValueError as exc:
        return SquirrelUpdateState("failed", version=version, detail=str(exc))
    updater = update_exe or find_update_exe()
    if updater is None:
        return SquirrelUpdateState(
            "not_installed",
            version=version,
            feed_url=feed,
            release_notes_url=notes,
            detail="Squirrel install not detected",
        )
    try:
        _run_update(updater, "--update=" + feed, timeout)
        verification = _run_update(updater, "--checkForUpdate=" + feed, timeout)
        if verification.get("futureReleaseEntry"):
            raise RuntimeError("Squirrel did not finish staging the selected update")
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        return SquirrelUpdateState(
            "failed",
            version=version,
            feed_url=feed,
            release_notes_url=notes,
            detail=str(exc),
        )
    return SquirrelUpdateState(
        "ready_to_restart",
        version=version,
        feed_url=feed,
        release_notes_url=notes,
        detail="Unsigned update staged; restart only after user confirmation",
    )
