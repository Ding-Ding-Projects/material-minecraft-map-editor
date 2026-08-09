"""Small, wx-independent bridge for Squirrel.Windows updates.

Squirrel owns downloading and applying release packages.  This module only
discovers ``Update.exe``, validates an HTTPS feed, and reports a non-blocking
state that a UI can turn into a ready-to-restart notification.  No signing
tool or signing credential is ever invoked.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
import subprocess
import sys
from typing import Any, Dict, Optional
from urllib.request import Request, urlopen
from urllib.parse import urlparse

DEFAULT_FEED_URL = "https://github.com/Ding-Ding-Projects/material-minecraft-map-editor/releases/"
RELEASES_API_URL = "https://api.github.com/repos/Ding-Ding-Projects/material-minecraft-map-editor/releases?per_page=100"
ALLOWED_FEED_HOSTS = {"github.com", "raw.githubusercontent.com", "api.github.com"}


@dataclass(frozen=True)
class SquirrelUpdateState:
    status: str
    version: Optional[str] = None
    feed_url: Optional[str] = None
    unsigned_warning: bool = True
    detail: Optional[str] = None


def validate_feed_url(feed_url: str) -> str:
    """Return *feed_url* when it is an HTTPS URL, otherwise raise ValueError."""

    parsed = urlparse(feed_url)
    if parsed.scheme.lower() != "https" or not parsed.netloc:
        raise ValueError("Squirrel update feeds must use HTTPS")
    if parsed.hostname not in ALLOWED_FEED_HOSTS:
        raise ValueError("Squirrel update feeds must use an allowlisted host")
    if parsed.username or parsed.password:
        raise ValueError("Squirrel update feeds cannot embed credentials")
    return feed_url


def find_update_exe(start: Optional[Path] = None) -> Optional[Path]:
    """Find the Squirrel updater beside a frozen executable or in its parents."""

    current = (start or Path(sys.executable)).resolve()
    if current.is_file():
        current = current.parent
    for directory in (current, *current.parents):
        for name in ("Update.exe", "update.exe"):
            path = directory / name
            if path.is_file():
                return path
    return None


def _release_version(tag: object) -> tuple[int, int, int, int, str]:
    """Sort stable and prerelease tags without trusting publication order."""

    text = str(tag).lstrip("v")
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)(?:[-.]?(.*))?", text)
    if not match:
        return (-1, -1, -1, -1, "")
    suffix = match.group(4) or ""
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)), 0 if suffix else 1, suffix)


def _resolve_latest_feed(timeout: float) -> str:
    """Choose the highest published release, not GitHub's completion-order latest."""

    request = Request(RELEASES_API_URL, headers={"Accept": "application/vnd.github+json"})
    with urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read(1_000_000).decode("utf-8"))
    if not isinstance(payload, list):
        raise ValueError("GitHub releases response was not a list")
    candidates = []
    for release in payload:
        if not isinstance(release, dict) or release.get("draft"):
            continue
        tag = release.get("tag_name")
        assets = release.get("assets")
        if not isinstance(tag, str) or not isinstance(assets, list):
            continue
        if not any(isinstance(asset, dict) and asset.get("name") == "RELEASES" for asset in assets):
            continue
        version = _release_version(tag)
        if version[0] >= 0:
            candidates.append((version, tag))
    if not candidates:
        raise ValueError("No published Squirrel release feed was found")
    tag = max(candidates)[1]
    return f"https://github.com/Ding-Ding-Projects/material-minecraft-map-editor/releases/download/{tag}/"


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
) -> SquirrelUpdateState:
    """Check the Squirrel feed and return a state suitable for a notification."""

    try:
        feed = validate_feed_url(feed_url or DEFAULT_FEED_URL)
        if feed == DEFAULT_FEED_URL:
            feed = validate_feed_url(_resolve_latest_feed(timeout))
    except ValueError as exc:
        return SquirrelUpdateState("failed", detail=str(exc))
    updater = update_exe or find_update_exe()
    if updater is None:
        return SquirrelUpdateState(
            "not_installed", feed_url=feed, detail="Squirrel install not detected"
        )
    try:
        payload = _run_update(updater, "--checkForUpdate=" + feed, timeout)
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        return SquirrelUpdateState("failed", feed_url=feed, detail=str(exc))
    future = payload.get("futureReleaseEntry")
    if not isinstance(future, dict):
        return SquirrelUpdateState("up_to_date", feed_url=feed)
    version = future.get("version") or future.get("Version")
    if current_version and str(version) == str(current_version):
        return SquirrelUpdateState("up_to_date", feed_url=feed)
    return SquirrelUpdateState(
        "available", version=str(version) if version else None, feed_url=feed
    )


def stage_update(
    feed_url: str,
    update_exe: Optional[Path] = None,
    timeout: float = 120.0,
) -> SquirrelUpdateState:
    """Download/apply the selected update; restart remains an explicit UI action."""

    try:
        feed = validate_feed_url(feed_url)
    except ValueError as exc:
        return SquirrelUpdateState("failed", detail=str(exc))
    updater = update_exe or find_update_exe()
    if updater is None:
        return SquirrelUpdateState(
            "not_installed", feed_url=feed, detail="Squirrel install not detected"
        )
    try:
        _run_update(updater, "--update=" + feed, timeout)
        verification = _run_update(updater, "--checkForUpdate=" + feed, timeout)
        if verification.get("futureReleaseEntry"):
            raise RuntimeError("Squirrel did not finish staging the selected update")
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        return SquirrelUpdateState("failed", feed_url=feed, detail=str(exc))
    return SquirrelUpdateState(
        "ready_to_restart",
        feed_url=feed,
        detail="Unsigned update staged; restart only after user confirmation",
    )
