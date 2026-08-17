"""Resolve one unused public dim-sum code name for release notes.

Resolution is deliberately optional.  A release must keep shipping when the
public catalog is unavailable, malformed, or exhausted; in those cases this
script emits a bounded ``unavailable`` status and exits successfully.
"""

from __future__ import annotations

import json
import os
import re
import sys
import unicodedata
from pathlib import PurePosixPath
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

CATALOG_URL = (
    "https://raw.githubusercontent.com/"
    "Ding-Ding-Projects/dim-sum-photos/main/catalog/index.json"
)
RELEASES_URL = (
    "https://api.github.com/repos/"
    "Ding-Ding-Projects/dim-sum-photos/releases?per_page=100"
)
PROJECT_RELEASES_URL = "https://api.github.com/repos/{repo}/releases?per_page=100"
ASSET_URL = (
    "https://github.com/Ding-Ding-Projects/dim-sum-photos/"
    "releases/download/{tag}/{name}"
)

REQUEST_TIMEOUT_SECONDS = 15
MAX_RESPONSE_BYTES = 16 * 1024 * 1024
MAX_LINK_HEADER_BYTES = 16 * 1024
MAX_PAGES = 20
MAX_RELEASES = 2_000
MAX_DISHES = 5_000
MAX_RELEASE_BODY_CHARS = 1_000_000
MAX_NAME_CHARS = 160
MAX_WARNING_CHARS = 360

CATALOG_TAG_RE = re.compile(r"^catalog-v1[A-Za-z0-9._-]*$")
REPOSITORY_RE = re.compile(
    r"^[A-Za-z0-9](?:[A-Za-z0-9_.-]{0,99})/" r"[A-Za-z0-9](?:[A-Za-z0-9_.-]{0,99})$"
)
SAFE_ASSET_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ -]{0,254}$")
CODE_NAME_RE = re.compile(
    r"^\s*Dim[- ]sum code name:\s*([^\r\n\u00b7]+?)\s*\u00b7\s*([^\r\n]+?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp")


class CatalogBoundaryError(RuntimeError):
    """A bounded catalog or release-inventory validation failed."""


class _RejectRedirects(HTTPRedirectHandler):
    """Reject redirects so an API authorization header cannot leave its host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


_URL_OPENER = build_opener(_RejectRedirects())


def _open_url(request: Request, timeout: int):
    return _URL_OPENER.open(request, timeout=timeout)


def _endpoint_label(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.netloc}{parsed.path}"


def _validate_source_url(url: str, *, expected_host: str | None = None) -> None:
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise CatalogBoundaryError("catalog source URL is not bounded HTTPS")
    if expected_host is not None and parsed.hostname != expected_host:
        raise CatalogBoundaryError("catalog source changed to an unexpected host")


def _response_content_type(headers) -> str:  # noqa: ANN001
    value = str(headers.get("Content-Type", "")).split(";", 1)[0]
    return value.strip().lower()


def _get_json(
    url: str,
    *,
    expected_type: type,
    authorize_api: bool,
    open_url: Callable[[Request, int], object] | None = None,
):
    parsed = urlparse(url)
    expected_host = "api.github.com" if authorize_api else parsed.hostname
    _validate_source_url(url, expected_host=expected_host)

    headers = {
        "Accept": (
            "application/vnd.github+json" if authorize_api else "application/json"
        ),
        "User-Agent": "material-minecraft-map-editor-release-resolver",
    }
    token = os.environ.get("GH_TOKEN", "").strip()
    if authorize_api and token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(url, headers=headers)
    opener = open_url or _open_url
    try:
        with opener(request, REQUEST_TIMEOUT_SECONDS) as response:
            status = getattr(response, "status", None)
            if status is None:
                status = response.getcode()
            if status != 200:
                raise CatalogBoundaryError(
                    f"catalog endpoint returned HTTP status {status}"
                )
            final_url = response.geturl()
            if final_url != url:
                raise CatalogBoundaryError("catalog endpoint attempted a redirect")
            content_type = _response_content_type(response.headers)
            allowed_types = {"application/json", "application/vnd.github+json"}
            if not authorize_api:
                allowed_types.add("text/plain")
            if content_type not in allowed_types:
                raise CatalogBoundaryError(
                    f"catalog endpoint returned content type {content_type or 'missing'}"
                )
            content_length = response.headers.get("Content-Length")
            if content_length is not None:
                try:
                    declared_length = int(content_length)
                except (TypeError, ValueError) as exc:
                    raise CatalogBoundaryError(
                        "catalog endpoint returned an invalid Content-Length"
                    ) from exc
                if declared_length < 0 or declared_length > MAX_RESPONSE_BYTES:
                    raise CatalogBoundaryError(
                        "catalog response exceeded the size limit"
                    )
            payload = response.read(MAX_RESPONSE_BYTES + 1)
            if len(payload) > MAX_RESPONSE_BYTES:
                raise CatalogBoundaryError("catalog response exceeded the size limit")
            link_header = str(response.headers.get("Link", ""))
    except HTTPError as exc:
        raise CatalogBoundaryError(
            f"catalog endpoint returned HTTP status {exc.code} at {_endpoint_label(url)}"
        ) from exc
    except URLError as exc:
        raise CatalogBoundaryError(
            f"catalog endpoint was unreachable at {_endpoint_label(url)}"
        ) from exc

    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CatalogBoundaryError("catalog endpoint returned malformed JSON") from exc
    if not isinstance(value, expected_type):
        raise CatalogBoundaryError(
            f"catalog endpoint returned {type(value).__name__}, expected "
            f"{expected_type.__name__}"
        )
    return value, link_header


def _next_page_url(link_header: str) -> str | None:
    if len(link_header.encode("utf-8")) > MAX_LINK_HEADER_BYTES:
        raise CatalogBoundaryError("pagination Link header exceeded the size limit")
    next_urls: list[str] = []
    for item in link_header.split(","):
        match = re.fullmatch(r'\s*<([^<>]{1,2048})>\s*;\s*rel="([A-Za-z ]+)"\s*', item)
        if not match:
            continue
        if "next" in match.group(2).split():
            next_urls.append(match.group(1))
    if len(next_urls) > 1:
        raise CatalogBoundaryError("pagination returned multiple next links")
    return next_urls[0] if next_urls else None


def _validate_page_url(
    url: str,
    *,
    initial_url: str,
    canonical_path: str | None = None,
) -> str | None:
    current = urlparse(url)
    initial = urlparse(initial_url)
    _validate_source_url(url, expected_host="api.github.com")
    if current.path != initial.path:
        if canonical_path is not None:
            if current.path != canonical_path:
                raise CatalogBoundaryError(
                    "pagination changed the release endpoint path"
                )
        elif not re.fullmatch(r"/repositories/[1-9][0-9]*/releases", current.path):
            raise CatalogBoundaryError("pagination changed the release endpoint path")
        else:
            canonical_path = current.path
    try:
        query = parse_qs(current.query, keep_blank_values=True, strict_parsing=True)
    except ValueError as exc:
        raise CatalogBoundaryError("pagination returned an invalid query") from exc
    if set(query) - {"per_page", "page"}:
        raise CatalogBoundaryError("pagination added an unexpected query field")
    if query.get("per_page") != ["100"]:
        raise CatalogBoundaryError("pagination changed the bounded page size")
    if "page" in query:
        values = query["page"]
        if (
            len(values) != 1
            or not values[0].isdigit()
            or not 1 <= int(values[0]) <= MAX_PAGES
        ):
            raise CatalogBoundaryError("pagination returned an invalid page number")
    return canonical_path


def _get_paginated_releases(
    initial_url: str,
    *,
    open_url: Callable[[Request, int], object] | None = None,
) -> list[dict]:
    _validate_page_url(initial_url, initial_url=initial_url)
    releases: list[dict] = []
    seen_urls: set[str] = set()
    page_url: str | None = initial_url
    canonical_path: str | None = None
    for page_number in range(1, MAX_PAGES + 1):
        if page_url is None:
            break
        if page_url in seen_urls:
            raise CatalogBoundaryError("pagination repeated a release page")
        seen_urls.add(page_url)
        page, link_header = _get_json(
            page_url,
            expected_type=list,
            authorize_api=True,
            open_url=open_url,
        )
        if len(releases) + len(page) > MAX_RELEASES:
            raise CatalogBoundaryError("release inventory exceeded the item limit")
        if any(not isinstance(release, dict) for release in page):
            raise CatalogBoundaryError("release inventory contained a non-object item")
        releases.extend(page)
        next_url = _next_page_url(link_header)
        if next_url is None:
            page_url = None
            break
        if page_number == MAX_PAGES:
            raise CatalogBoundaryError("release inventory exceeded the page limit")
        canonical_path = _validate_page_url(
            next_url,
            initial_url=initial_url,
            canonical_path=canonical_path,
        )
        page_url = next_url
    if page_url is not None:
        raise CatalogBoundaryError("release inventory did not terminate")
    return releases


def _bounded_text(value: object, *, label: str) -> str:
    if not isinstance(value, str):
        raise CatalogBoundaryError(f"{label} was not text")
    text = value.strip()
    if (
        not text
        or len(text) > MAX_NAME_CHARS
        or "=" in text
        or any(ord(character) < 32 for character in text)
    ):
        raise CatalogBoundaryError(f"{label} was empty or outside its size bounds")
    return text


def _normalized_name(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).split()).casefold()


def _used_code_names(releases: list[dict]) -> set[tuple[str, str]]:
    used: set[tuple[str, str]] = set()
    for release in releases:
        body = release.get("body")
        if body is None:
            continue
        if not isinstance(body, str) or len(body) > MAX_RELEASE_BODY_CHARS:
            raise CatalogBoundaryError(
                "project release body was malformed or oversized"
            )
        for match in CODE_NAME_RE.finditer(body):
            en = _bounded_text(match.group(1), label="used English dish name")
            zh = _bounded_text(match.group(2), label="used Chinese dish name")
            used.add((_normalized_name(en), _normalized_name(zh)))
    return used


def _published_images(releases: list[dict]) -> dict[str, str]:
    published: dict[str, str] = {}
    for release in releases:
        tag = release.get("tag_name")
        if not isinstance(tag, str) or not CATALOG_TAG_RE.fullmatch(tag):
            continue
        published_at = release.get("published_at")
        if (
            release.get("draft") is not False
            or not isinstance(published_at, str)
            or not published_at.strip()
        ):
            continue
        assets = release.get("assets")
        if not isinstance(assets, list):
            raise CatalogBoundaryError("catalog release assets were malformed")
        for asset in assets:
            if not isinstance(asset, dict):
                raise CatalogBoundaryError(
                    "catalog release contained a malformed asset"
                )
            name = asset.get("name")
            size = asset.get("size")
            state = asset.get("state")
            browser_url = asset.get("browser_download_url")
            if not isinstance(name, str):
                raise CatalogBoundaryError("catalog release asset name was malformed")
            if not name.lower().endswith(IMAGE_EXTENSIONS):
                continue
            if (
                not SAFE_ASSET_NAME_RE.fullmatch(name)
                or isinstance(size, bool)
                or not isinstance(size, int)
                or size <= 0
                or state != "uploaded"
            ):
                raise CatalogBoundaryError(
                    "catalog image asset was not a verified uploaded file"
                )
            expected_url = ASSET_URL.format(
                tag=quote(tag, safe=""), name=quote(name, safe="")
            )
            if browser_url != expected_url:
                raise CatalogBoundaryError(
                    "catalog image asset URL did not match its published release"
                )
            published.setdefault(name, expected_url)
    return published


def resolve(
    catalog: dict,
    catalog_releases: list[dict],
    *,
    project_releases: list[dict],
) -> tuple[str, str, str] | None:
    dishes = catalog.get("dishes")
    if not isinstance(dishes, list) or len(dishes) > MAX_DISHES:
        raise CatalogBoundaryError("catalog dishes were missing or outside item bounds")
    used = _used_code_names(project_releases)
    published = _published_images(catalog_releases)
    for dish in dishes:
        if not isinstance(dish, dict):
            raise CatalogBoundaryError("catalog contained a malformed dish")
        name = dish.get("name")
        image = dish.get("image")
        if not isinstance(name, dict) or not isinstance(image, dict):
            raise CatalogBoundaryError("catalog dish metadata was malformed")
        en = _bounded_text(name.get("en"), label="English dish name")
        zh = _bounded_text(name.get("zhHant"), label="Chinese dish name")
        image_path = image.get("path")
        if not isinstance(image_path, str) or "\\" in image_path:
            raise CatalogBoundaryError("catalog image path was malformed")
        path = PurePosixPath(image_path)
        if path.is_absolute() or ".." in path.parts or not path.name:
            raise CatalogBoundaryError(
                "catalog image path escaped its bounded location"
            )
        if (_normalized_name(en), _normalized_name(zh)) in used:
            continue
        photo_url = published.get(path.name)
        if photo_url is None:
            continue
        return en, zh, photo_url
    return None


def _resolve_for_repository(repository: str) -> tuple[str, str, str] | None:
    if not REPOSITORY_RE.fullmatch(repository):
        raise CatalogBoundaryError("GITHUB_REPOSITORY was missing or malformed")
    catalog, _ = _get_json(
        CATALOG_URL,
        expected_type=dict,
        authorize_api=False,
    )
    catalog_releases = _get_paginated_releases(RELEASES_URL)
    project_releases = _get_paginated_releases(
        PROJECT_RELEASES_URL.format(repo=repository)
    )
    return resolve(
        catalog,
        catalog_releases,
        project_releases=project_releases,
    )


def _warning_text(message: str) -> str:
    single_line = re.sub(r"[\x00-\x1f=]+", " ", message)
    return " ".join(single_line.split())[:MAX_WARNING_CHARS]


def _emit_unavailable(message: str) -> int:
    warning = _warning_text(message)
    print("DIM_SUM_STATUS=unavailable")
    print(f"DIM_SUM_WARNING={warning}")
    print(f"warning: {warning}", file=sys.stderr)
    return 0


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    repository = os.environ.get("GITHUB_REPOSITORY", "").strip()
    try:
        result = _resolve_for_repository(repository)
    except CatalogBoundaryError as exc:
        return _emit_unavailable(
            f"Dim-sum code name unavailable; release will use its version only: {exc}"
        )
    except Exception as exc:  # noqa: BLE001 - fallback must never block publication
        return _emit_unavailable(
            "Dim-sum code name unavailable; release will use its version only "
            f"because the catalog boundary raised {type(exc).__name__}."
        )
    if result is None:
        return _emit_unavailable(
            "Dim-sum code name unavailable; release will use its version only: "
            "no unused catalog dish has a verified published catalog-v1 image asset."
        )
    en, zh, url = result
    print("DIM_SUM_STATUS=available")
    print(f"DIM_SUM_CODE_NAME={en} \u00b7 {zh}")
    print(f"DIM_SUM_PHOTO_URL={url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
