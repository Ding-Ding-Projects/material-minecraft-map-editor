from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "docs" / "site"


def test_every_search_field_is_in_the_hand_written_full_builder_inventory():
    html = (SITE / "index.html").read_text(encoding="utf-8")
    inventory = json.loads(
        (SITE / "search-surfaces.json").read_text(encoding="utf-8")
    )
    search_ids = set(
        re.findall(r'<input\s+id="([^"]+)"\s+type="search"', html)
    )
    records = inventory["surfaces"]
    assert inventory["schemaVersion"] == 1
    assert len(records) == 4
    assert {record["searchId"] for record in records} == search_ids
    assert {record["name"] for record in records} == {
        "features",
        "documentation",
        "settings",
        "palette",
    }
    for record in records:
        assert set(record) == {
            "name",
            "searchId",
            "builderId",
            "toggleId",
            "patternId",
            "flagsId",
            "sampleId",
            "feedbackId",
            "capturesId",
        }
        for key, value in record.items():
            if key != "name":
                assert f'id="{value}"' in html


def test_one_shared_worker_module_enforces_timeout_cancellation_and_bounds():
    app = (SITE / "app.js").read_text(encoding="utf-8")
    worker = (SITE / "regex-worker.mjs").read_text(encoding="utf-8")
    assert "new Worker(new URL('./regex-worker.mjs'" in app
    assert "worker.terminate()" in app
    assert "const REGEX_WORKER_TIMEOUT_MS = 900" in app
    assert "REGEX_WORKER_TIMEOUT_MS," in app
    assert "currentGeneration !== generation" in app
    assert "debounce = setTimeout" in app
    assert "new RegExp" not in app
    assert "new RegExp" in worker
    assert "MAX_PATTERN = 256" in worker
    assert "MAX_SAMPLE = 512" in worker
    assert "MAX_RECORDS = 128" in worker
    assert "MAX_RECORD_BYTES = 1024 * 1024" in worker


def test_full_builder_has_guided_blocks_copy_export_sample_and_focus_return():
    app = (SITE / "app.js").read_text(encoding="utf-8")
    for label in (
        "Literal",
        "Character class",
        "Anchors",
        "Group",
        "Alternation",
        "Quantifier",
        "Copy pattern",
        "Export pattern",
    ):
        assert f"'{label}'" in app
    assert "pattern.setRangeText" in app
    assert "navigator.clipboard.writeText" in app
    assert "URL.createObjectURL" in app
    assert "details.open = false" in app
    assert "search.focus()" in app
    assert "sample.addEventListener('input'" in app


def test_worker_cases_include_adversarial_unicode_multiline_and_zero_width():
    node = shutil.which("node")
    assert node, "Node is required for the regex Worker contract"
    result = subprocess.run(
        [node, "scripts/test_site_regex_worker.mjs"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert "delayed safe completion" in result.stdout
    assert "adversarial termination" in result.stdout


def test_every_mjs_module_has_javascript_mime_under_nosniff():
    nginx = (SITE / "nginx.conf").read_text(encoding="utf-8")
    dockerfile = (SITE / "Dockerfile").read_text(encoding="utf-8")
    assert "location ~ \\.mjs$" in nginx
    assert "default_type application/javascript" in nginx
    assert 'X-Content-Type-Options "nosniff"' in nginx
    assert "theme.mjs regex-worker.mjs" in dockerfile
