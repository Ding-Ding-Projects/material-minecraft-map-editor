from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.select_squirrel_delta_candidates import select_candidates

FIXTURE = (
    Path(__file__).parent / "fixtures" / "squirrel_release_inventory_20260809.json"
)


def _inventory() -> object:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_live_inventory_selects_nearest_older_automated_release():
    assert select_candidates(
        _inventory(),
        current_source="0.10.0-dev.427",
        channel="automated",
        limit=8,
    ) == ("0.10.0-dev.426", "0.10.0-dev.424")


def test_live_inventory_keeps_stable_and_automated_channels_separate():
    assert select_candidates(
        _inventory(),
        current_source="0.10.77",
        channel="stable",
        limit=8,
    ) == ("0.10.76",)


def test_invalid_current_channel_fails_closed():
    with pytest.raises(ValueError, match="does not belong"):
        select_candidates(
            _inventory(),
            current_source="0.10.77",
            channel="automated",
            limit=8,
        )


def test_duplicate_inventory_tag_fails_closed():
    inventory = _inventory()
    assert isinstance(inventory, dict)
    releases = inventory["releases"]
    releases.append(dict(releases[0]))
    with pytest.raises(ValueError, match="duplicate tag"):
        select_candidates(
            inventory,
            current_source="0.10.0-dev.427",
            channel="automated",
            limit=8,
        )
