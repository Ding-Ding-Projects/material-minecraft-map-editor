import multiprocessing
from pathlib import Path
import pickle
import re
import threading
import time

from amulet_map_editor.api import regex_builder
from amulet_map_editor.api.regex_builder import (
    MAX_CAPTURE_MATCHES,
    MAX_PATTERN_LENGTH,
    MAX_RESULT_PAYLOAD_BYTES,
    MAX_RESULT_TEXT_LENGTH,
    RegexBuilder,
    RegexEvaluationController,
    plain_text_match_indices,
)


def _wait_for_pid(controller: RegexEvaluationController, timeout: float = 2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        pid = controller.active_worker_pid
        if pid is not None:
            return pid
        time.sleep(0.01)
    return None


def _active_child_pids():
    return {process.pid for process in multiprocessing.active_children()}


def test_adversarial_regex_times_out_and_worker_is_reaped():
    before = _active_child_pids()
    started = time.monotonic()
    result = RegexBuilder(r"(a|aa)+$", regex_enabled=True).evaluate(
        "a" * 256 + "!", timeout=0.25
    )
    elapsed = time.monotonic() - started
    assert result.timed_out
    assert not result.valid
    assert elapsed < 2.0
    assert _active_child_pids() <= before


def test_zero_width_capture_groups_and_payload_are_bounded():
    result = RegexBuilder(r"(?=(a))", regex_enabled=True).evaluate("aa")
    assert result.valid
    assert result.matches == ("", "")
    assert result.groups == (("a",), ("a",))
    assert not result.truncated

    many = RegexBuilder(r"(?=.)", regex_enabled=True).evaluate("x" * 1000)
    assert many.valid
    assert len(many.matches) == MAX_CAPTURE_MATCHES
    assert len(many.groups) == MAX_CAPTURE_MATCHES
    assert many.truncated

    duplicated = RegexBuilder(r"((.*))", regex_enabled=True).evaluate("x" * 100_000)
    assert duplicated.valid
    assert duplicated.truncated
    assert (
        sum(map(len, duplicated.matches))
        + sum(len(group) for groups in duplicated.groups for group in groups)
        <= MAX_RESULT_TEXT_LENGTH
    )
    assert (
        len(pickle.dumps(duplicated, protocol=pickle.HIGHEST_PROTOCOL))
        <= MAX_RESULT_PAYLOAD_BYTES
    )


def test_supported_flags_survive_the_worker_request_round_trip():
    flags = re.IGNORECASE | re.MULTILINE | re.DOTALL
    builder = RegexBuilder(r"^alpha.*omega$", flags=flags, regex_enabled=True)
    request = builder.request(("ALPHA\ninside\nOMEGA",), capture_matches=True)
    assert request.flags == flags
    result = builder.evaluate("ALPHA\ninside\nOMEGA")
    assert result.valid
    assert result.matches == ("ALPHA\ninside\nOMEGA",)


def test_plain_text_path_never_starts_a_regex_worker(monkeypatch):
    def fail_if_spawned(_request):
        raise AssertionError("plain text unexpectedly spawned a regex worker")

    monkeypatch.setattr(regex_builder, "_new_worker", fail_if_spawned)
    assert plain_text_match_indices(
        ("Theme", "Density", "External editor"), "theme", ignore_case=True
    ) == (0,)


def test_parent_preflight_rejects_oversize_without_starting_a_worker(monkeypatch):
    def fail_if_spawned(_request):
        raise AssertionError("oversize request unexpectedly spawned a worker")

    monkeypatch.setattr(regex_builder, "_new_worker", fail_if_spawned)
    result = RegexBuilder("x" * (MAX_PATTERN_LENGTH + 1), regex_enabled=True).validate()
    assert not result.valid
    assert "limited" in (result.error or "")

    callback_threads = []
    completed = threading.Event()
    submitting_thread = threading.get_ident()
    controller = RegexEvaluationController(lambda callback: callback())
    controller.submit(
        RegexBuilder("x" * (MAX_PATTERN_LENGTH + 1), regex_enabled=True).request(),
        lambda result: (
            callback_threads.append((threading.get_ident(), result)),
            completed.set(),
        ),
        immediate=True,
    )
    assert completed.wait(2.0)
    assert callback_threads[0][0] != submitting_thread
    assert not callback_threads[0][1].valid
    assert controller.wait_for_idle(2.0)
    controller.close()


def test_controller_debounces_supersedes_and_reaps_workers():
    delivered = []
    completed = threading.Event()
    controller = RegexEvaluationController(
        lambda callback: callback(), debounce_seconds=0.03, timeout_seconds=1.5
    )
    controller.submit(
        RegexBuilder(r"(a|aa)+$", regex_enabled=True).request(
            ("a" * 256 + "!",), capture_matches=True
        ),
        delivered.append,
        immediate=True,
    )
    replaced_pid = _wait_for_pid(controller)
    assert replaced_pid is not None
    controller.submit(
        RegexBuilder(r"(?=(b))", regex_enabled=True).request(
            ("bb",), capture_matches=True
        ),
        lambda result: (delivered.append(result), completed.set()),
    )
    assert completed.wait(3.0)
    assert controller.wait_for_idle(3.0)
    assert len(delivered) == 1
    assert delivered[0].matches == ("", "")
    assert replaced_pid not in _active_child_pids()
    assert controller.active_worker_pid is None
    controller.close()


def test_controller_timeout_and_close_destroy_active_workers():
    timeout_results = []
    completed = threading.Event()
    controller = RegexEvaluationController(
        lambda callback: callback(), debounce_seconds=0, timeout_seconds=0.2
    )
    controller.submit(
        RegexBuilder(r"(a|aa)+$", regex_enabled=True).request(
            ("a" * 256 + "!",), capture_matches=True
        ),
        lambda result: (timeout_results.append(result), completed.set()),
        immediate=True,
    )
    assert completed.wait(3.0)
    assert timeout_results[0].timed_out
    assert controller.wait_for_idle(3.0)
    assert controller.active_worker_pid is None

    callbacks_after_close = []
    controller = RegexEvaluationController(
        lambda callback: callback(), debounce_seconds=0, timeout_seconds=2.0
    )
    controller.submit(
        RegexBuilder(r"(a|aa)+$", regex_enabled=True).request(
            ("a" * 256 + "!",), capture_matches=True
        ),
        callbacks_after_close.append,
        immediate=True,
    )
    active_pid = _wait_for_pid(controller)
    assert active_pid is not None
    controller.close()
    assert controller.wait_for_idle(3.0)
    assert callbacks_after_close == []
    assert active_pid not in _active_child_pids()


def test_queued_dispatch_rechecks_close_and_supersession_before_callback():
    queued = []
    delivered = []
    controller = RegexEvaluationController(
        queued.append, debounce_seconds=0, timeout_seconds=1.0
    )
    controller.submit(
        RegexBuilder("first", regex_enabled=True).request(
            ("first",), capture_matches=True
        ),
        lambda result: delivered.append(("first", result)),
        immediate=True,
    )
    assert controller.wait_for_idle(3.0)
    assert len(queued) == 1

    controller.submit(
        RegexBuilder("second", regex_enabled=True).request(
            ("second",), capture_matches=True
        ),
        lambda result: delivered.append(("second", result)),
        immediate=True,
    )
    assert controller.wait_for_idle(3.0)
    assert len(queued) == 2
    queued.pop(0)()
    assert delivered == []

    controller.close()
    queued.pop(0)()
    assert delivered == []


def test_frozen_entry_calls_freeze_support_and_worker_target_is_importable():
    source = Path("amulet_map_editor/__main__.py").read_text(encoding="utf-8")
    assert "multiprocessing.freeze_support()" in source
    assert regex_builder._regex_worker.__module__ == (
        "amulet_map_editor.api.regex_builder"
    )
