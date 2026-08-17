import importlib.util
import json
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "resolve_dim_sum_code_name", ROOT / "scripts/resolve_dim_sum_code_name.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def _asset(name: str, tag: str = "catalog-v1") -> dict:
    return {
        "name": name,
        "size": 1234,
        "state": "uploaded",
        "browser_download_url": (
            "https://github.com/Ding-Ding-Projects/dim-sum-photos/"
            f"releases/download/{tag}/{name}"
        ),
    }


def _catalog_release(*names: str, tag: str = "catalog-v1") -> dict:
    return {
        "tag_name": tag,
        "draft": False,
        "published_at": "2026-08-01T00:00:00Z",
        "assets": [_asset(name, tag) for name in names],
    }


def _dish(en: object, zh: object, image: object) -> dict:
    return {"name": {"en": en, "zhHant": zh}, "image": {"path": image}}


class _FakeResponse:
    def __init__(
        self,
        url: str,
        value: object = None,
        *,
        payload: bytes | None = None,
        status: int = 200,
        content_type: str = "application/json; charset=utf-8",
        link: str = "",
        final_url: str | None = None,
        declared_length: int | str | None = None,
    ):
        self.status = status
        self._url = final_url or url
        self._payload = (
            json.dumps(value).encode("utf-8") if payload is None else payload
        )
        self.headers = {"Content-Type": content_type, "Link": link}
        self.headers["Content-Length"] = str(
            len(self._payload) if declared_length is None else declared_length
        )

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def getcode(self) -> int:
        return self.status

    def geturl(self) -> str:
        return self._url

    def read(self, limit: int) -> bytes:
        return self._payload[:limit]


def test_resolver_selects_first_unused_published_bilingual_dish():
    catalog = {
        "dishes": [
            _dish("Classic Har Gow", "蝦餃", "images/har.png"),
            _dish("Fresh Bao", "新鮮包", "images/fresh.png"),
        ]
    }
    project_releases = [
        {
            "body": (
                "Dim-sum code name:  CLASSIC   HAR GOW  ·  蝦餃\n"
                "Dim-sum code name: Classic Har Gow · 蝦餃"
            )
        }
    ]
    assert MODULE.resolve(
        catalog,
        [_catalog_release("har.png", "fresh.png")],
        project_releases=project_releases,
    ) == (
        "Fresh Bao",
        "新鮮包",
        "https://github.com/Ding-Ding-Projects/dim-sum-photos/"
        "releases/download/catalog-v1/fresh.png",
    )


def test_resolver_requires_published_catalog_v1_uploaded_asset():
    catalog = {"dishes": [_dish("Dish", "點心", "images/dish.png")]}
    non_catalog = _catalog_release("dish.png", tag="photos-2026")
    draft = _catalog_release("dish.png")
    draft["draft"] = True
    unpublished = _catalog_release("dish.png")
    unpublished["published_at"] = None
    assert (
        MODULE.resolve(
            catalog,
            [non_catalog, draft, unpublished],
            project_releases=[],
        )
        is None
    )

    invalid_state = _catalog_release("dish.png")
    invalid_state["assets"][0]["state"] = "new"
    with pytest.raises(MODULE.CatalogBoundaryError, match="uploaded"):
        MODULE.resolve(catalog, [invalid_state], project_releases=[])


def test_resolver_rejects_malformed_names_instead_of_stringifying_them():
    catalog = {"dishes": [_dish(["Dish"], {"name": "點心"}, "images/dish.png")]}
    with pytest.raises(MODULE.CatalogBoundaryError, match="not text"):
        MODULE.resolve(
            catalog,
            [_catalog_release("dish.png")],
            project_releases=[],
        )


def test_resolver_rejects_mismatched_asset_download_url():
    catalog = {"dishes": [_dish("Dish", "點心", "images/dish.png")]}
    release = _catalog_release("dish.png")
    release["assets"][0]["browser_download_url"] = "https://example.com/dish.png"
    with pytest.raises(MODULE.CatalogBoundaryError, match="URL"):
        MODULE.resolve(catalog, [release], project_releases=[])


def test_paginated_inventory_reads_all_477_releases_and_late_duplicate():
    base = "https://api.github.com/repos/example/project/releases?per_page=100"
    pages: dict[str, _FakeResponse] = {}
    for page_number, count in enumerate((100, 100, 100, 100, 77), start=1):
        url = base if page_number == 1 else f"{base}&page={page_number}"
        values = [
            {"body": "", "page": page_number, "item": item} for item in range(count)
        ]
        if page_number == 5:
            values[-1]["body"] = "Dim-sum code name: Classic Har Gow · 蝦餃"
        next_url = f"{base}&page={page_number + 1}" if page_number < 5 else None
        link = f'<{next_url}>; rel="next"' if next_url else ""
        pages[url] = _FakeResponse(url, values, link=link)
    requests: list[Request] = []

    def open_url(request: Request, timeout: int):
        requests.append(request)
        assert timeout == MODULE.REQUEST_TIMEOUT_SECONDS
        return pages[request.full_url]

    releases = MODULE._get_paginated_releases(base, open_url=open_url)
    assert len(releases) == 477
    assert len(requests) == 5
    assert "Classic Har Gow" in releases[-1]["body"]
    assert (
        MODULE.resolve(
            {
                "dishes": [
                    _dish("Classic Har Gow", "蝦餃", "images/har.png"),
                    _dish("Fresh Bao", "新鮮包", "images/fresh.png"),
                ]
            },
            [_catalog_release("har.png", "fresh.png")],
            project_releases=releases,
        )[0]
        == "Fresh Bao"
    )


def test_paginated_inventory_rejects_cross_host_and_repeated_next_links():
    base = "https://api.github.com/repos/example/project/releases?per_page=100"

    def cross_host(request: Request, timeout: int):
        return _FakeResponse(
            request.full_url,
            [],
            link='<https://evil.example/releases?per_page=100&page=2>; rel="next"',
        )

    with pytest.raises(MODULE.CatalogBoundaryError, match="unexpected host"):
        MODULE._get_paginated_releases(base, open_url=cross_host)

    repeated_link = f'<{base}>; rel="next"'

    def repeated(request: Request, timeout: int):
        return _FakeResponse(request.full_url, [], link=repeated_link)

    with pytest.raises(MODULE.CatalogBoundaryError, match="repeated"):
        MODULE._get_paginated_releases(base, open_url=repeated)


def test_paginated_inventory_binds_github_numeric_canonical_path():
    base = "https://api.github.com/repos/example/project/releases?per_page=100"
    canonical_two = (
        "https://api.github.com/repositories/123456/releases?per_page=100&page=2"
    )
    canonical_three = (
        "https://api.github.com/repositories/123456/releases?per_page=100&page=3"
    )
    responses = {
        base: _FakeResponse(base, [], link=f'<{canonical_two}>; rel="next"'),
        canonical_two: _FakeResponse(
            canonical_two, [], link=f'<{canonical_three}>; rel="next"'
        ),
        canonical_three: _FakeResponse(canonical_three, []),
    }

    def open_url(request: Request, timeout: int):
        return responses[request.full_url]

    assert MODULE._get_paginated_releases(base, open_url=open_url) == []

    wrong_repo = (
        "https://api.github.com/repositories/999999/releases?per_page=100&page=3"
    )
    responses[canonical_two] = _FakeResponse(
        canonical_two, [], link=f'<{wrong_repo}>; rel="next"'
    )
    with pytest.raises(MODULE.CatalogBoundaryError, match="endpoint path"):
        MODULE._get_paginated_releases(base, open_url=open_url)


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (
            _FakeResponse(
                MODULE.CATALOG_URL,
                {},
                content_type="text/html",
            ),
            "content type",
        ),
        (
            _FakeResponse(
                MODULE.CATALOG_URL,
                {},
                final_url="https://evil.example/catalog.json",
            ),
            "redirect",
        ),
        (
            _FakeResponse(
                MODULE.CATALOG_URL,
                {},
                declared_length=MODULE.MAX_RESPONSE_BYTES + 1,
            ),
            "size limit",
        ),
        (
            _FakeResponse(MODULE.CATALOG_URL, payload=b"{not-json"),
            "malformed JSON",
        ),
    ],
)
def test_json_boundary_rejects_content_redirect_size_and_malformed_json(
    response: _FakeResponse, message: str
):
    with pytest.raises(MODULE.CatalogBoundaryError, match=message):
        MODULE._get_json(
            MODULE.CATALOG_URL,
            expected_type=dict,
            authorize_api=False,
            open_url=lambda request, timeout: response,
        )


def test_api_token_is_never_sent_to_raw_catalog(monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "private-test-token")
    requests: list[Request] = []

    def open_url(request: Request, timeout: int):
        requests.append(request)
        value = [] if request.full_url == MODULE.RELEASES_URL else {}
        content_type = (
            "application/json"
            if request.full_url == MODULE.RELEASES_URL
            else "text/plain"
        )
        return _FakeResponse(request.full_url, value, content_type=content_type)

    MODULE._get_json(
        MODULE.CATALOG_URL,
        expected_type=dict,
        authorize_api=False,
        open_url=open_url,
    )
    MODULE._get_json(
        MODULE.RELEASES_URL,
        expected_type=list,
        authorize_api=True,
        open_url=open_url,
    )
    assert requests[0].get_header("Authorization") is None
    assert requests[1].get_header("Authorization") == "Bearer private-test-token"
    assert all("private-test-token" not in request.full_url for request in requests)


def test_network_boundary_and_exhaustion_emit_version_only_status(monkeypatch, capsys):
    monkeypatch.setenv("GITHUB_REPOSITORY", "example/project")

    def unavailable(repository: str):
        raise MODULE.CatalogBoundaryError("catalog endpoint was unreachable")

    monkeypatch.setattr(MODULE, "_resolve_for_repository", unavailable)
    assert MODULE.main() == 0
    captured = capsys.readouterr()
    assert "DIM_SUM_STATUS=unavailable" in captured.out
    assert "DIM_SUM_WARNING=" in captured.out
    assert "version only" in captured.out
    assert "DIM_SUM_CODE_NAME=" not in captured.out
    assert "DIM_SUM_PHOTO_URL=" not in captured.out
    assert "warning:" in captured.err

    monkeypatch.setattr(MODULE, "_resolve_for_repository", lambda repository: None)
    assert MODULE.main() == 0
    captured = capsys.readouterr()
    assert "DIM_SUM_STATUS=unavailable" in captured.out
    assert "no unused catalog dish" in captured.out


def test_unexpected_network_exception_does_not_leak_detail(monkeypatch, capsys):
    monkeypatch.setenv("GITHUB_REPOSITORY", "example/project")

    def unexpected(repository: str):
        raise URLError("private-test-token")

    monkeypatch.setattr(MODULE, "_resolve_for_repository", unexpected)
    assert MODULE.main() == 0
    captured = capsys.readouterr()
    assert "DIM_SUM_STATUS=unavailable" in captured.out
    assert "URLError" in captured.out
    assert "private-test-token" not in captured.out + captured.err
    warning_line = next(
        line
        for line in captured.out.splitlines()
        if line.startswith("DIM_SUM_WARNING=")
    )
    assert len(warning_line) <= MODULE.MAX_WARNING_CHARS + len("DIM_SUM_WARNING=")


def test_available_output_contract(monkeypatch, capsys):
    monkeypatch.setenv("GITHUB_REPOSITORY", "example/project")
    monkeypatch.setattr(
        MODULE,
        "_resolve_for_repository",
        lambda repository: (
            "Fresh Bao",
            "新鮮包",
            "https://github.com/Ding-Ding-Projects/dim-sum-photos/"
            "releases/download/catalog-v1/fresh.png",
        ),
    )
    assert MODULE.main() == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out.splitlines() == [
        "DIM_SUM_STATUS=available",
        "DIM_SUM_CODE_NAME=Fresh Bao · 新鮮包",
        "DIM_SUM_PHOTO_URL=https://github.com/Ding-Ding-Projects/"
        "dim-sum-photos/releases/download/catalog-v1/fresh.png",
    ]


def test_release_publisher_parses_resolver_output_without_eval():
    workflow = (ROOT / ".github/workflows/build-windows.yml").read_text(
        encoding="utf-8"
    )
    publisher = (ROOT / "scripts/publish_release.sh").read_text(encoding="utf-8")
    assert "eval" not in workflow
    assert 'eval "$(python3 scripts/resolve_dim_sum_code_name.py)"' not in publisher
    assert (
        'dim_sum_result="$(python3 scripts/resolve_dim_sum_code_name.py)"' in publisher
    )
    assert "while IFS='=' read -r key value" in publisher
    assert "DIM_SUM_STATUS" in publisher
    assert "version only" in publisher.lower()
