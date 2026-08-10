import json

import pytest

from amulet_map_editor.api.scheduled_sources import (
    ScheduleSource,
    SourceValidationError,
    fetch_source,
    validate_source_url,
    validate_values,
)


class _Response:
    def __init__(self, payload):
        self.headers = {}
        self._body = json.dumps(payload).encode()

    def read(self, _limit):
        return self._body


class _Opener:
    def __init__(self, payload):
        self.payload = payload

    def open(self, _request, timeout):
        assert timeout == 3
        return _Response(self.payload)


def test_source_validation_rejects_credentials_queries_and_public_http():
    with pytest.raises(SourceValidationError):
        validate_source_url("https://user:pass@example.test/feed")
    with pytest.raises(SourceValidationError):
        validate_source_url("https://example.test/feed?token=secret")
    with pytest.raises(SourceValidationError):
        validate_source_url("http://example.test/feed")
    assert (
        validate_source_url("http://127.0.0.1:8123/feed")
        == "http://127.0.0.1:8123/feed"
    )


def test_api_payload_is_versioned_and_field_allowlisted():
    source = ScheduleSource(kind="api", url="https://example.test/feed")
    result = fetch_source(
        source,
        opener=_Opener({"version": 1, "values": {"theme": "dark"}}),
    )
    assert result.ok is True
    assert result.values == {"theme": "dark"}
    assert validate_values({"version": 1, "values": {"density": "compact"}}) == {
        "density": "compact"
    }


def test_home_assistant_off_is_safe_and_on_uses_validated_attributes():
    source = ScheduleSource(
        kind="home_assistant",
        url="https://ha.example.test",
        entity_id="input_boolean.night",
    )
    off = fetch_source(source, token="vault-token", opener=_Opener({"state": "off"}))
    assert off.ok is True and off.values == {}
    on = fetch_source(
        source,
        token="vault-token",
        opener=_Opener(
            {
                "state": "on",
                "attributes": {"version": 1, "values": {"density": "spacious"}},
            }
        ),
    )
    assert on.ok is True and on.values == {"density": "spacious"}


def test_malformed_remote_data_is_non_blocking():
    source = ScheduleSource(kind="api", url="https://example.test/feed")
    result = fetch_source(
        source, opener=_Opener({"version": 99, "values": {"theme": "dark"}})
    )
    assert result.ok is False
    assert result.values == {}
