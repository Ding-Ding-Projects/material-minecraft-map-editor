from __future__ import annotations

import json
from pathlib import Path

import pytest
import scripts.select_squirrel_delta_candidates as selector

from scripts.select_squirrel_delta_candidates import (
    parse_channel_version,
    select_candidates,
)

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


def test_reserved_stable_patch_collision_fails_closed():
    with pytest.raises(ValueError, match="reserved automated range"):
        select_candidates(
            [{"tag_name": "0.10.100427", "draft": False}],
            current_source="0.10.1000000",
            channel="stable",
            limit=8,
        )


def test_automated_source_range_is_bounded():
    assert parse_channel_version("0.10.0-dev.899999", "automated") is not None
    with pytest.raises(ValueError, match="supported maximum"):
        parse_channel_version("0.10.0-dev.900000", "automated")
    with pytest.raises(ValueError, match="patch zero"):
        parse_channel_version("0.10.1-dev.427", "automated")


def test_predecessor_after_first_100_inventory_entries_is_selected():
    inventory = [
        {"tagName": f"9.9.{index + 1}", "isDraft": False} for index in range(100)
    ]
    inventory.append({"tagName": "0.10.0-dev.426", "isDraft": False})

    assert select_candidates(
        inventory,
        current_source="0.10.0-dev.427",
        channel="automated",
        limit=8,
    ) == ("0.10.0-dev.426",)


@pytest.mark.parametrize(
    "tag",
    (
        "v0.10.0-dev.426",
        "0.10.0-dev426",
        "0.10.0-dev-426",
        "0.10.0-Dev.426",
        "0.10.0-dev.0426",
    ),
)
def test_noncanonical_delta_tag_aliases_fail_closed(tag):
    with pytest.raises(ValueError, match="noncanonical"):
        select_candidates(
            [{"tagName": tag, "isDraft": False}],
            current_source="0.10.0-dev.427",
            channel="automated",
            limit=8,
        )


def test_semantic_version_collision_fails_closed(monkeypatch):
    real_parse = selector.parse_channel_version
    collision = selector.ChannelVersion(0, 10, 0, 426)

    def collide(tag: str, channel: str):
        if tag in {"0.10.0-dev.425", "0.10.0-dev.426"}:
            return collision
        return real_parse(tag, channel)

    monkeypatch.setattr(selector, "parse_channel_version", collide)
    with pytest.raises(ValueError, match="identify the same version"):
        selector.select_candidates(
            [
                {"tagName": "0.10.0-dev.425", "isDraft": False},
                {"tagName": "0.10.0-dev.426", "isDraft": False},
            ],
            current_source="0.10.0-dev.427",
            channel="automated",
            limit=8,
        )
