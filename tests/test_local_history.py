import subprocess
from datetime import datetime, timedelta, timezone

import pytest

from amulet_map_editor.api.local_history import (
    HistoryValidationError,
    LocalHistory,
    default_history_root,
)


def test_default_history_root_is_application_data_not_current_project(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("AMULET_HISTORY_DIR", str(tmp_path / "profile" / "history"))
    assert default_history_root() == (tmp_path / "profile" / "history").resolve()


def test_snapshots_are_append_only_git_commits_and_restore_is_new_event(tmp_path):
    store = LocalHistory(tmp_path / "app-data" / "history")
    created = store.record("settings", {"theme": "light"}, record_type="settings")
    updated = store.record("settings", {"theme": "dark"}, record_type="settings")
    deleted = store.delete("settings", record_type="settings")

    assert created and created.action == "created"
    assert updated and updated.action == "updated"
    assert deleted and deleted.action == "deleted"
    restored = store.restore(deleted.event_id)
    assert restored.action == "restored"
    assert restored.payload == {"theme": "dark"}

    events = store.events(record_type="settings", limit=20)
    assert [event.action for event in reversed(events)] == [
        "created",
        "updated",
        "deleted",
        "restored",
    ]
    commits = subprocess.run(
        ["git", "rev-list", "--count", "HEAD"],
        cwd=store.root,
        check=True,
        capture_output=True,
        text=True,
    )
    assert int(commits.stdout.strip()) == 5  # init + four events
    assert not (tmp_path / "app-data" / "history" / ".git" / "objects").samefile(
        tmp_path
    )


def test_plain_search_and_regex_filter_are_bounded_and_exportable(tmp_path):
    store = LocalHistory(tmp_path / "history")
    store.record("alpha", {"value": 1}, record_type="settings")
    store.record("beta", {"value": 2}, record_type="notification")
    assert [event.record_id for event in store.events(query="ALPHA")] == ["alpha"]
    assert [event.record_id for event in store.events(query=r"^be", regex=True)] == [
        "beta"
    ]
    assert len(store.export_json(actions={"created"})) > 10
    assert "notification" in store.export_markdown(record_type="notification")
    with pytest.raises(HistoryValidationError):
        store.events(query="x" * 257)
    assert store.events(query="[") == ()  # plain text is safe; regex is explicit
    with pytest.raises(HistoryValidationError):
        store.events(query="[", regex=True)


def test_safe_wrapper_never_blocks_primary_operation(tmp_path):
    store = LocalHistory(tmp_path / "history")
    assert store.safe_record("ok", {"saved": True}) is not None
    assert store.safe_record("bad", object()) is None
    assert store.safe_delete("missing") is None
    assert store.safe_restore("missing-event") is None


def test_date_filters_use_utc_and_no_change_writes_nothing(tmp_path):
    store = LocalHistory(tmp_path / "history")
    event = store.record("one", {"v": 1})
    assert event is not None
    assert store.record("one", {"v": 1}) is None
    stamp = datetime.fromisoformat(event.timestamp.replace("Z", "+00:00"))
    assert len(store.events(since=stamp - timedelta(seconds=1))) == 1
    assert len(store.events(until=stamp - timedelta(seconds=1))) == 0


def test_payloads_reject_non_finite_and_oversized_values(tmp_path):
    store = LocalHistory(tmp_path / "history")
    with pytest.raises(HistoryValidationError):
        store.record("nan", float("nan"))
    with pytest.raises(HistoryValidationError):
        store.record("large", "x" * (1024 * 1024 + 1))
