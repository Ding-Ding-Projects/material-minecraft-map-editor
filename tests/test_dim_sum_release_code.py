import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "resolve_dim_sum_code_name", ROOT / "scripts/resolve_dim_sum_code_name.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def test_resolver_selects_unused_published_bilingual_dish():
    catalog = {
        "dishes": [
            {
                "name": {"en": "Used", "zhHant": "已用"},
                "image": {"path": "images/used.png"},
            },
            {
                "name": {"en": "Fresh Bao", "zhHant": "新鮮包"},
                "image": {"path": "images/fresh.png"},
            },
        ]
    }
    releases = [
        {
            "tag_name": "batch-1",
            "body": "Dim-sum code name: Used · 已用",
            "assets": [{"name": "used.png"}],
        },
        {"tag_name": "batch-2", "body": "", "assets": [{"name": "fresh.png"}]},
    ]
    assert MODULE.resolve(catalog, releases) == (
        "Fresh Bao",
        "新鮮包",
        "https://github.com/Ding-Ding-Projects/dim-sum-photos/releases/download/batch-2/fresh.png",
    )


def test_resolver_fails_when_no_published_unused_image_exists():
    catalog = {
        "dishes": [
            {
                "name": {"en": "No Photo", "zhHant": "無相"},
                "image": {"path": "images/no.png"},
            }
        ]
    }
    try:
        MODULE.resolve(catalog, [])
    except RuntimeError as exc:
        assert "No unused catalog dish" in str(exc)
    else:
        raise AssertionError("resolver should fail closed")


def test_resolver_skips_names_used_by_consumer_releases():
    catalog = {
        "dishes": [
            {
                "name": {"en": "Classic Har Gow", "zhHant": "蝦餃"},
                "image": {"path": "images/har.png"},
            },
            {
                "name": {"en": "Fresh Bao", "zhHant": "新鮮包"},
                "image": {"path": "images/fresh.png"},
            },
        ]
    }
    public_releases = [
        {
            "tag_name": "catalog-v1",
            "body": "",
            "assets": [{"name": "har.png"}, {"name": "fresh.png"}],
        }
    ]
    consumer_releases = [
        {
            "tag_name": "0.10.0-dev.302",
            "body": "Dim-sum code name: Classic Har Gow · 蝦餃",
            "assets": [],
        }
    ]
    assert MODULE.resolve(
        catalog, public_releases, used_releases=public_releases + consumer_releases
    ) == (
        "Fresh Bao",
        "新鮮包",
        "https://github.com/Ding-Ding-Projects/dim-sum-photos/releases/download/catalog-v1/fresh.png",
    )


def test_workflow_parses_resolver_output_without_eval():
    # The dim-sum resolver call moved to the publish job in
    # build-electron-windows.yml, the only workflow that still creates a
    # release; build-windows.yml no longer resolves a code name at all.
    workflow = (ROOT / ".github/workflows/build-electron-windows.yml").read_text(
        encoding="utf-8"
    )
    assert 'eval "$(python3 scripts/resolve_dim_sum_code_name.py)"' not in workflow
    assert "while IFS='=' read -r key value" in workflow
    assert 'case "$key" in' in workflow
