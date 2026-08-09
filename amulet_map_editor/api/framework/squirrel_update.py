"""Small, wx-independent bridge for Squirrel.Windows updates.

Squirrel owns downloading and applying release packages.  This module only
discovers ``Update.exe``, validates an HTTPS feed, and reports a non-blocking
state that a UI can turn into a ready-to-restart notification.  No signing
tool or signing credential is ever invoked.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
import subprocess
import sys
import threading
import time
from typing import BinaryIO, Optional, Sequence
from urllib.request import Request, urlopen
from urllib.parse import urlparse

DEFAULT_FEED_URL = (
    "https://github.com/Ding-Ding-Projects/material-minecraft-map-editor/releases/"
)
RELEASES_API_BASE_URL = (
    "https://api.github.com/repos/Ding-Ding-Projects/"
    "material-minecraft-map-editor/releases"
)
RELEASES_PER_PAGE = 100
RELEASES_API_URL = f"{RELEASES_API_BASE_URL}?per_page={RELEASES_PER_PAGE}&page=1"
DEFAULT_UPDATE_CHANNEL = "automated"
UPDATE_STAGE_TIMEOUT_SECONDS = 15 * 60
_MAX_RELEASES_RESPONSE_BYTES = 1_000_000
_MAX_RELEASES_AGGREGATE_BYTES = 5_000_000
_MAX_RELEASE_PAGES = 5
_MAX_RELEASES = RELEASES_PER_PAGE * _MAX_RELEASE_PAGES
_MAX_RELEASE_ASSETS = 32
_MAX_PROCESS_STDOUT_BYTES = 64 * 1024
_MAX_PROCESS_STDERR_BYTES = 64 * 1024
_MAX_PROGRESS_LINES = 4_096
_MAX_RELEASES_TO_APPLY = 128
_MAX_VERSION_LENGTH = 128
_AUTOMATED_PATCH_BASE = 100_000
_AUTOMATED_RUN_LIMIT = 899_999
_AUTOMATED_PATCH_LIMIT = _AUTOMATED_PATCH_BASE + _AUTOMATED_RUN_LIMIT
_VERSION_COMPONENT = r"(?:0|[1-9]\d*)"
_AUTOMATED_TAG = re.compile(
    rf"^(?P<major>{_VERSION_COMPONENT})\.(?P<minor>{_VERSION_COMPONENT})\."
    rf"(?P<patch>{_VERSION_COMPONENT})-dev\.(?P<run>{_VERSION_COMPONENT})$"
)
_STABLE_TAG = re.compile(
    rf"^(?P<major>{_VERSION_COMPONENT})\.(?P<minor>{_VERSION_COMPONENT})\."
    rf"(?P<patch>{_VERSION_COMPONENT})$"
)
_AUTOMATED_TAG_ALIAS = re.compile(r"^v?\d+\.\d+\.\d+-dev[.-]?\d+$", re.IGNORECASE)
_STABLE_TAG_ALIAS = re.compile(r"^v?\d+\.\d+\.\d+$", re.IGNORECASE)
_PROGRESS_LINE = re.compile(r"(?:0|[1-9]\d?|100)")
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


@dataclass(frozen=True)
class SquirrelCheckResult:
    """Strict projection of Squirrel 2.0.1 ``--checkForUpdate`` output."""

    current_version: str
    future_version: str
    releases_to_apply: tuple[str, ...]


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

    if not isinstance(tag, str):
        return None
    if channel == "automated":
        match = _AUTOMATED_TAG.fullmatch(tag)
        if match is None and _AUTOMATED_TAG_ALIAS.fullmatch(tag):
            raise ValueError(f"Automated release tag is not canonical: {tag}")
    elif channel == "stable":
        match = _STABLE_TAG.fullmatch(tag)
        if match is None and _STABLE_TAG_ALIAS.fullmatch(tag):
            raise ValueError(f"Stable release tag is not canonical: {tag}")
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

    automated_version = _release_version(tag, "automated")
    if automated_version is not None:
        return
    stable_version = _release_version(tag, "stable")
    if stable_version is not None:
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


def _release_inventory_url(page: int) -> str:
    if not 1 <= page <= _MAX_RELEASE_PAGES:
        raise ValueError("GitHub releases inventory page is outside the bounded range")
    return f"{RELEASES_API_BASE_URL}?per_page={RELEASES_PER_PAGE}&page={page}"


def _validate_inventory_response(response: object, expected_url: str) -> None:
    """Fail closed when the GitHub inventory response changes route or shape."""

    geturl = getattr(response, "geturl", None)
    if not callable(geturl) or geturl() != expected_url:
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

    payload: list[object] = []
    aggregate_bytes = 0
    for page in range(1, _MAX_RELEASE_PAGES + 1):
        page_url = _release_inventory_url(page)
        request = Request(page_url, headers={"Accept": "application/vnd.github+json"})
        with urlopen(request, timeout=timeout) as response:
            _validate_inventory_response(response, page_url)
            body = response.read(_MAX_RELEASES_RESPONSE_BYTES + 1)
        if len(body) > _MAX_RELEASES_RESPONSE_BYTES:
            raise ValueError(f"GitHub releases page {page} exceeded the size limit")
        aggregate_bytes += len(body)
        if aggregate_bytes > _MAX_RELEASES_AGGREGATE_BYTES:
            raise ValueError("GitHub releases inventory exceeded the byte limit")
        try:
            page_payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(
                f"GitHub releases page {page} was not valid UTF-8 JSON"
            ) from exc
        if not isinstance(page_payload, list):
            raise ValueError(f"GitHub releases page {page} was not a list")
        if len(page_payload) > RELEASES_PER_PAGE:
            raise ValueError(
                f"GitHub releases page {page} exceeded {RELEASES_PER_PAGE} entries"
            )
        payload.extend(page_payload)
        if len(payload) > _MAX_RELEASES:
            raise ValueError("GitHub releases inventory exceeded the release limit")
        if len(page_payload) < RELEASES_PER_PAGE:
            break
        if page == _MAX_RELEASE_PAGES:
            raise ValueError("GitHub releases inventory reached the bounded page limit")

    candidates = []
    seen_tags: set[str] = set()
    seen_versions: dict[tuple[int, int, int, int], str] = {}
    seen_package_versions: dict[str, str] = {}
    for release in payload:
        if not isinstance(release, dict) or release.get("draft"):
            continue
        tag = release.get("tag_name")
        assets = release.get("assets")
        if not isinstance(tag, str) or not isinstance(assets, list):
            continue
        if tag in seen_tags:
            raise ValueError(f"GitHub releases inventory repeated tag {tag}")
        seen_tags.add(tag)
        version = _release_version(tag, channel)
        if version is None:
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
        previous_tag = seen_versions.get(version)
        if previous_tag is not None and previous_tag != tag:
            raise ValueError(
                f"Release tags {previous_tag} and {tag} identify the same version"
            )
        seen_versions[version] = tag
        package_version = full_packages[0][1]
        if package_version not in _allowed_package_versions(tag, channel):
            raise ValueError(f"Release {tag} had a mismatched full package identity")
        previous_package_tag = seen_package_versions.get(package_version)
        if previous_package_tag is not None and previous_package_tag != tag:
            raise ValueError(
                f"Releases {previous_package_tag} and {tag} reuse package version "
                f"{package_version}"
            )
        seen_package_versions[package_version] = tag
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


def _read_bounded_stream(
    stream: BinaryIO,
    maximum: int,
    destination: bytearray,
    overflow: threading.Event,
) -> None:
    """Drain one child stream while retaining at most ``maximum + 1`` bytes."""

    try:
        while True:
            chunk = stream.read(4_096)
            if not chunk:
                break
            remaining = maximum + 1 - len(destination)
            if remaining > 0:
                destination.extend(chunk[:remaining])
            if len(destination) > maximum:
                overflow.set()
    finally:
        stream.close()


def _run_update_process(
    update_exe: Path,
    arguments: Sequence[str],
    timeout: float,
) -> str:
    """Run Update.exe with bounded output, time, and memory consumption."""

    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("Squirrel Update.exe timeout must be finite and positive")
    process = subprocess.Popen(
        [str(update_exe), *arguments],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        close_fds=True,
    )
    if process.stdout is None or process.stderr is None:
        process.kill()
        raise RuntimeError("Squirrel Update.exe output pipes were unavailable")

    stdout = bytearray()
    stderr = bytearray()
    overflow = threading.Event()
    readers = (
        threading.Thread(
            target=_read_bounded_stream,
            args=(process.stdout, _MAX_PROCESS_STDOUT_BYTES, stdout, overflow),
            name="squirrel-update-stdout",
            daemon=True,
        ),
        threading.Thread(
            target=_read_bounded_stream,
            args=(process.stderr, _MAX_PROCESS_STDERR_BYTES, stderr, overflow),
            name="squirrel-update-stderr",
            daemon=True,
        ),
    )
    for reader in readers:
        reader.start()

    deadline = time.monotonic() + timeout
    timed_out = False
    while process.poll() is None:
        if overflow.is_set():
            process.kill()
            break
        if time.monotonic() >= deadline:
            timed_out = True
            process.kill()
            break
        time.sleep(0.01)
    try:
        return_code = process.wait(timeout=5.0)
    except subprocess.TimeoutExpired:
        process.kill()
        raise RuntimeError("Squirrel Update.exe did not terminate after cancellation")
    for reader in readers:
        reader.join(timeout=1.0)
    if any(reader.is_alive() for reader in readers):
        raise RuntimeError("Squirrel Update.exe output readers did not finish")
    if timed_out:
        raise subprocess.TimeoutExpired([str(update_exe), *arguments], timeout)
    if overflow.is_set():
        raise RuntimeError("Squirrel Update.exe output exceeded the size limit")
    if return_code:
        raise RuntimeError("Squirrel Update.exe failed")
    try:
        return bytes(stdout).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RuntimeError("Squirrel Update.exe output was not UTF-8") from exc


def _validate_progress_line(line: str) -> None:
    if _PROGRESS_LINE.fullmatch(line) is None:
        raise RuntimeError(
            "Squirrel Update.exe returned a non-numeric or out-of-range progress line"
        )


def _parse_update_output(stdout: str) -> None:
    """Validate that ``--update`` emitted only bounded 0..100 progress lines."""

    if "\x00" in stdout:
        raise RuntimeError("Squirrel Update.exe returned a NUL byte")
    lines = stdout.splitlines()
    if len(lines) > _MAX_PROGRESS_LINES:
        raise RuntimeError("Squirrel Update.exe returned too many progress lines")
    for line in lines:
        _validate_progress_line(line)


def _bounded_version(value: object, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > _MAX_VERSION_LENGTH
        or any(ord(character) < 0x20 for character in value)
    ):
        raise RuntimeError(f"Squirrel Update.exe returned an invalid {field}")
    return value


def _no_duplicate_json_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _parse_check_output(stdout: str) -> SquirrelCheckResult:
    """Parse the exact Squirrel 2.0.1 progress-then-JSON check shape."""

    if "\x00" in stdout:
        raise RuntimeError("Squirrel Update.exe returned a NUL byte")
    lines = stdout.splitlines()
    if not lines:
        raise RuntimeError("Squirrel Update.exe check omitted final JSON")
    if len(lines) > _MAX_PROGRESS_LINES + 1:
        raise RuntimeError("Squirrel Update.exe returned too many check lines")
    for line in lines[:-1]:
        _validate_progress_line(line)
    try:
        payload = json.loads(lines[-1], object_pairs_hook=_no_duplicate_json_keys)
    except (json.JSONDecodeError, ValueError) as exc:
        raise RuntimeError("Squirrel Update.exe returned invalid final JSON") from exc
    if not isinstance(payload, dict) or set(payload) != {
        "currentVersion",
        "futureVersion",
        "releasesToApply",
    }:
        raise RuntimeError("Squirrel Update.exe returned an invalid check schema")
    current_version = _bounded_version(payload["currentVersion"], "currentVersion")
    future_version = _bounded_version(payload["futureVersion"], "futureVersion")
    releases = payload["releasesToApply"]
    if not isinstance(releases, list) or len(releases) > _MAX_RELEASES_TO_APPLY:
        raise RuntimeError("Squirrel Update.exe returned invalid releasesToApply")
    release_versions: list[str] = []
    for release in releases:
        if not isinstance(release, dict) or set(release) != {
            "version",
            "releaseNotes",
        }:
            raise RuntimeError("Squirrel Update.exe returned an invalid release entry")
        release_version = _bounded_version(release["version"], "release version")
        release_notes = release["releaseNotes"]
        if not isinstance(release_notes, str):
            raise RuntimeError("Squirrel Update.exe returned invalid release notes")
        release_versions.append(release_version)
    if release_versions and release_versions[-1] != future_version:
        raise RuntimeError(
            "Squirrel Update.exe futureVersion did not match releasesToApply"
        )
    return SquirrelCheckResult(
        current_version=current_version,
        future_version=future_version,
        releases_to_apply=tuple(release_versions),
    )


def _run_check_for_update(
    update_exe: Path, feed_url: str, timeout: float
) -> SquirrelCheckResult:
    stdout = _run_update_process(update_exe, ("--checkForUpdate=" + feed_url,), timeout)
    return _parse_check_output(stdout)


def _run_apply_update(update_exe: Path, feed_url: str, timeout: float) -> None:
    stdout = _run_update_process(update_exe, ("--update=" + feed_url,), timeout)
    _parse_update_output(stdout)


def build_restart_command(
    update_exe: Path, executable: Optional[Path] = None
) -> tuple[str, str, str]:
    """Build the official Squirrel 2.0.1 process-start-and-wait command."""

    executable_name = (executable or Path(sys.executable)).name
    if (
        not executable_name
        or executable_name in {".", ".."}
        or Path(executable_name).name != executable_name
        or any(character in executable_name for character in "\r\n\x00")
    ):
        raise ValueError("Application executable basename is invalid")
    return str(update_exe), "--processStartAndWait", executable_name


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
        result = _run_check_for_update(updater, feed, timeout)
        if current_version is not None and result.current_version != str(
            current_version
        ):
            raise RuntimeError(
                "Squirrel currentVersion did not match the running application"
            )
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
        return SquirrelUpdateState(
            "failed",
            feed_url=feed,
            release_notes_url=release_notes_url,
            detail=str(exc),
        )
    if not result.releases_to_apply:
        return SquirrelUpdateState(
            "up_to_date", feed_url=feed, release_notes_url=release_notes_url
        )
    return SquirrelUpdateState(
        "available",
        version=result.future_version,
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
        expected_version = _bounded_version(version, "expected update version")
        _run_apply_update(updater, feed, timeout)
        verification = _run_check_for_update(updater, feed, timeout)
        if verification.releases_to_apply:
            raise RuntimeError("Squirrel did not finish staging the selected update")
        if verification.current_version != verification.future_version:
            raise RuntimeError(
                "Squirrel post-update currentVersion and futureVersion differed"
            )
        if verification.current_version != expected_version:
            raise RuntimeError(
                "Squirrel post-update version did not match the selected update"
            )
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
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
