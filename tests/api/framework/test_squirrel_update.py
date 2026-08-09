import json
from pathlib import Path
import sys
import importlib.util

import pytest

_MODULE_PATH = (
    Path(__file__).parents[3] / "amulet_map_editor/api/framework/squirrel_update.py"
)
_SPEC = importlib.util.spec_from_file_location("squirrel_update", _MODULE_PATH)
assert _SPEC and _SPEC.loader
squirrel_update = importlib.util.module_from_spec(_SPEC)
sys.modules["squirrel_update"] = squirrel_update
_SPEC.loader.exec_module(squirrel_update)

SquirrelUpdateState = squirrel_update.SquirrelUpdateState
check_for_update = squirrel_update.check_for_update
find_update_exe = squirrel_update.find_update_exe
stage_update = squirrel_update.stage_update
validate_feed_url = squirrel_update.validate_feed_url
validate_release_notes_url = squirrel_update.validate_release_notes_url
release_version = squirrel_update._release_version
resolve_latest_feed = squirrel_update._resolve_latest_feed

FIXTURE = (
    Path(__file__).parents[2] / "fixtures" / "squirrel_release_inventory_20260809.json"
)


class _Response:
    def __init__(
        self,
        payload: object,
        *,
        final_url: str = squirrel_update.RELEASES_API_URL,
        status: int = 200,
        content_type: str = "application/json; charset=utf-8",
    ):
        self._body = json.dumps(payload).encode("utf-8")
        self._final_url = final_url
        self.status = status
        self.headers = {"Content-Type": content_type}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, limit: int) -> bytes:
        return self._body[:limit]

    def geturl(self) -> str:
        return self._final_url


def _live_inventory() -> list[object]:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return list(reversed(payload["releases"]))


def _check_output(
    current: str,
    future: str,
    releases: tuple[str, ...],
    *,
    progress: tuple[int, ...] = (0, 50, 100),
) -> str:
    payload = {
        "currentVersion": current,
        "futureVersion": future,
        "releasesToApply": [
            {"version": version, "releaseNotes": f"Notes for {version}"}
            for version in releases
        ],
    }
    return (
        "\n".join(
            [
                *(str(value) for value in progress),
                json.dumps(payload, separators=(",", ":")),
            ]
        )
        + "\n"
    )


def test_feed_requires_https_and_no_credentials():
    feed = "https://github.com/Ding-Ding-Projects/material-minecraft-map-editor/releases/download/0.10.0-dev.426/"
    assert validate_feed_url(feed).startswith("https://")
    rejected = (
        "http://github.com/Ding-Ding-Projects/material-minecraft-map-editor/releases/download/0.10.0-dev.426/",
        "https://user:pass@github.com/Ding-Ding-Projects/material-minecraft-map-editor/releases/download/0.10.0-dev.426/",
        "https://github.com/Other/material-minecraft-map-editor/releases/download/0.10.0-dev.426/",
        "https://github.com/Ding-Ding-Projects/other/releases/download/0.10.0-dev.426/",
        "https://github.com/Ding-Ding-Projects/material-minecraft-map-editor/releases/latest/download/",
        "https://raw.githubusercontent.com/Ding-Ding-Projects/material-minecraft-map-editor/main/RELEASES",
        squirrel_update.RELEASES_API_URL,
        feed + "?download=1",
    )
    for candidate in rejected:
        with pytest.raises(ValueError):
            validate_feed_url(candidate)

    notes = "https://github.com/Ding-Ding-Projects/material-minecraft-map-editor/releases/tag/0.10.0-dev.426"
    assert validate_release_notes_url(notes) == notes
    with pytest.raises(ValueError):
        validate_release_notes_url(notes + "?download=1")
    with pytest.raises(ValueError):
        validate_release_notes_url("https://example.test/releases/tag/0.10.0-dev.426")


def test_release_version_is_numeric_and_channel_explicit():
    assert release_version("0.10.0-dev.100", "automated") > release_version(
        "0.10.0-dev.99", "automated"
    )
    assert release_version("0.10.76", "stable") > release_version("0.10.49", "stable")
    assert release_version("0.10.76", "automated") is None
    assert release_version("0.10.0-dev.899999", "automated") is not None
    assert release_version("0.10.0-dev.900000", "automated") is None
    with pytest.raises(ValueError, match="reserved automated range"):
        release_version("0.10.100427", "stable")
    with pytest.raises(ValueError, match="patch zero"):
        release_version("0.10.1-dev.427", "automated")
    with pytest.raises(ValueError):
        release_version("0.10.76", "unknown")


@pytest.mark.parametrize(
    "tag",
    (
        "v0.10.0-dev.426",
        "0.10.0-dev426",
        "0.10.0-dev-426",
        "0.10.0-Dev.426",
        "0.10.0-dev.0426",
        "v0.10.76",
        "0.10.076",
    ),
)
def test_noncanonical_release_tag_aliases_fail_closed(tag):
    channel = "automated" if "dev" in tag.lower() else "stable"
    with pytest.raises(ValueError, match="not canonical"):
        release_version(tag, channel)


def test_live_inventory_resolves_latest_feed_within_explicit_channel(monkeypatch):
    inventory = _live_inventory()
    monkeypatch.setattr(
        squirrel_update, "urlopen", lambda *_args, **_kwargs: _Response(inventory)
    )

    automated_feed, automated_notes = resolve_latest_feed(10.0, "automated")
    stable_feed, stable_notes = resolve_latest_feed(10.0, "stable")

    assert automated_feed.endswith("/releases/download/0.10.0-dev.426/")
    assert automated_notes.endswith("/releases/tag/0.10.0-dev.426")
    assert stable_feed.endswith("/releases/download/0.10.76/")
    assert stable_notes.endswith("/releases/tag/0.10.76")


def test_release_inventory_binds_full_package_identity_to_tag(monkeypatch):
    inventory = _live_inventory()
    release = next(
        item
        for item in inventory
        if isinstance(item, dict) and item.get("tag_name") == "0.10.0-dev.426"
    )
    release["assets"][0]["name"] = "Amulet-0.10.100425-full.nupkg"
    monkeypatch.setattr(
        squirrel_update, "urlopen", lambda *_args, **_kwargs: _Response(inventory)
    )

    with pytest.raises(ValueError, match="mismatched full package identity"):
        resolve_latest_feed(10.0, "automated")


@pytest.mark.parametrize(
    ("response", "message"),
    (
        (
            _Response(
                [],
                final_url="https://example.test/redirected-releases",
            ),
            "redirected unexpectedly",
        ),
        (_Response([], status=206), "HTTP 206"),
        (_Response([], content_type="text/html"), "was not JSON"),
    ),
)
def test_release_inventory_rejects_redirect_status_and_content_type(
    monkeypatch, response, message
):
    monkeypatch.setattr(squirrel_update, "urlopen", lambda *_args, **_kwargs: response)
    with pytest.raises(ValueError, match=message):
        resolve_latest_feed(10.0, "automated")


def test_release_inventory_paginates_to_a_candidate_after_first_100(monkeypatch):
    page_one = [
        {"tag_name": f"9.9.{index + 1}", "draft": False, "assets": []}
        for index in range(squirrel_update.RELEASES_PER_PAGE)
    ]
    candidate = next(
        release
        for release in _live_inventory()
        if isinstance(release, dict) and release.get("tag_name") == "0.10.0-dev.426"
    )
    calls: list[str] = []

    def open_page(request, **_kwargs):
        calls.append(request.full_url)
        page = 1 if request.full_url.endswith("page=1") else 2
        return _Response(
            page_one if page == 1 else [candidate],
            final_url=request.full_url,
        )

    monkeypatch.setattr(squirrel_update, "urlopen", open_page)
    feed, _notes = resolve_latest_feed(10.0, "automated")

    assert feed.endswith("/releases/download/0.10.0-dev.426/")
    assert calls == [
        squirrel_update._release_inventory_url(1),
        squirrel_update._release_inventory_url(2),
    ]


def test_release_inventory_validates_every_page_final_route(monkeypatch):
    page_one = [
        {"tag_name": f"9.9.{index + 1}", "draft": False, "assets": []}
        for index in range(squirrel_update.RELEASES_PER_PAGE)
    ]

    def open_page(request, **_kwargs):
        if request.full_url.endswith("page=1"):
            return _Response(page_one, final_url=request.full_url)
        return _Response([], final_url=squirrel_update._release_inventory_url(1))

    monkeypatch.setattr(squirrel_update, "urlopen", open_page)
    with pytest.raises(ValueError, match="redirected unexpectedly"):
        resolve_latest_feed(10.0, "automated")


def test_release_inventory_fails_at_bounded_pagination_ceiling(monkeypatch):
    full_page = [
        {"tag_name": f"9.9.{index + 1}", "draft": False, "assets": []}
        for index in range(squirrel_update.RELEASES_PER_PAGE)
    ]
    monkeypatch.setattr(
        squirrel_update,
        "urlopen",
        lambda request, **_kwargs: _Response(full_page, final_url=request.full_url),
    )
    with pytest.raises(ValueError, match="bounded page limit"):
        resolve_latest_feed(10.0, "automated")


def test_release_inventory_enforces_aggregate_byte_limit(monkeypatch):
    page_one = [
        {"tag_name": f"9.9.{index + 1}", "draft": False, "assets": []}
        for index in range(squirrel_update.RELEASES_PER_PAGE)
    ]
    page_one_size = len(json.dumps(page_one).encode("utf-8"))
    monkeypatch.setattr(
        squirrel_update, "_MAX_RELEASES_AGGREGATE_BYTES", page_one_size + 1
    )

    def open_page(request, **_kwargs):
        payload = page_one if request.full_url.endswith("page=1") else []
        return _Response(payload, final_url=request.full_url)

    monkeypatch.setattr(squirrel_update, "urlopen", open_page)
    with pytest.raises(ValueError, match="inventory exceeded the byte limit"):
        resolve_latest_feed(10.0, "automated")


def test_release_inventory_rejects_noncanonical_channel_alias(monkeypatch):
    alias = {"tag_name": "v0.10.0-dev.426", "draft": False, "assets": []}
    monkeypatch.setattr(
        squirrel_update,
        "urlopen",
        lambda request, **_kwargs: _Response([alias], final_url=request.full_url),
    )
    with pytest.raises(ValueError, match="not canonical"):
        resolve_latest_feed(10.0, "automated")


def test_update_detection_is_explicit(tmp_path):
    install_root = tmp_path / "Amulet"
    app_directory = install_root / "app-0.10.100426"
    app_directory.mkdir(parents=True)
    app_executable = app_directory / "Amulet.exe"
    app_executable.write_bytes(b"fixture")
    updater = install_root / "Update.exe"
    updater.write_bytes(b"fixture")
    assert find_update_exe(app_executable) == updater
    assert find_update_exe(install_root) == updater


def test_update_detection_does_not_walk_to_stray_ancestor(tmp_path):
    stray = tmp_path / "Update.exe"
    stray.write_bytes(b"not this application")
    source_tree = tmp_path / "checkout" / "src"
    source_tree.mkdir(parents=True)
    source_executable = source_tree / "python.exe"
    source_executable.write_bytes(b"fixture")

    assert find_update_exe(source_executable) is None
    assert find_update_exe(source_tree) is None


def test_source_build_keeps_not_installed_state(monkeypatch):
    monkeypatch.setattr(squirrel_update, "find_update_exe", lambda *_args: None)
    feed = "https://github.com/Ding-Ding-Projects/material-minecraft-map-editor/releases/download/0.10.0-dev.426/"

    checked = check_for_update(feed)
    staged = stage_update(feed)

    assert checked.status == "not_installed"
    assert staged.status == "not_installed"
    assert checked.feed_url == feed
    assert staged.feed_url == feed


def test_check_reports_available_without_wx(tmp_path, monkeypatch):
    updater = tmp_path / "Update.exe"
    updater.write_bytes(b"fixture")
    monkeypatch.setattr(
        squirrel_update,
        "_run_check_for_update",
        lambda *_args, **_kwargs: squirrel_update.SquirrelCheckResult(
            "1.2.2", "1.2.3", ("1.2.3",)
        ),
    )
    feed = "https://github.com/Ding-Ding-Projects/material-minecraft-map-editor/releases/download/0.10.0-dev.426/"
    state = check_for_update(feed, update_exe=updater)
    assert state == SquirrelUpdateState(
        "available",
        version="1.2.3",
        feed_url=feed,
        release_notes_url="https://github.com/Ding-Ding-Projects/material-minecraft-map-editor/releases/tag/0.10.0-dev.426",
    )


def test_check_reports_up_to_date_only_when_releases_to_apply_is_empty(
    tmp_path, monkeypatch
):
    updater = tmp_path / "Update.exe"
    updater.write_bytes(b"fixture")
    monkeypatch.setattr(
        squirrel_update,
        "_run_check_for_update",
        lambda *_args, **_kwargs: squirrel_update.SquirrelCheckResult(
            "1.2.3", "1.2.3", ()
        ),
    )
    feed = "https://github.com/Ding-Ding-Projects/material-minecraft-map-editor/releases/download/0.10.0-dev.426/"

    state = check_for_update(feed, update_exe=updater)

    assert state.status == "up_to_date"


def test_default_check_carries_validated_live_release_notes(tmp_path, monkeypatch):
    updater = tmp_path / "Update.exe"
    updater.write_bytes(b"fixture")
    inventory = _live_inventory()
    monkeypatch.setattr(
        squirrel_update, "urlopen", lambda *_args, **_kwargs: _Response(inventory)
    )
    monkeypatch.setattr(
        squirrel_update,
        "_run_check_for_update",
        lambda *_args, **_kwargs: squirrel_update.SquirrelCheckResult(
            "0.10.100424", "0.10.100426", ("0.10.100426",)
        ),
    )

    state = check_for_update(update_exe=updater)

    assert state.status == "available"
    assert state.feed_url and state.feed_url.endswith("/0.10.0-dev.426/")
    assert state.release_notes_url and state.release_notes_url.endswith(
        "/tag/0.10.0-dev.426"
    )


def test_stage_update_is_ready_and_unsigned(tmp_path, monkeypatch):
    updater = tmp_path / "Update.exe"
    updater.write_bytes(b"fixture")
    calls = []

    def apply(*args, **_kwargs):
        calls.append(args)

    def check(*args, **_kwargs):
        calls.append(args)
        return squirrel_update.SquirrelCheckResult("0.10.100426", "0.10.100426", ())

    monkeypatch.setattr(squirrel_update, "_run_apply_update", apply)
    monkeypatch.setattr(squirrel_update, "_run_check_for_update", check)
    notes = "https://github.com/Ding-Ding-Projects/material-minecraft-map-editor/releases/tag/0.10.0-dev.426"
    state = stage_update(
        "https://github.com/Ding-Ding-Projects/material-minecraft-map-editor/releases/download/0.10.0-dev.426/",
        update_exe=updater,
        version="0.10.100426",
        release_notes_url=notes,
    )
    assert state.status == "ready_to_restart"
    assert state.unsigned_warning is True
    assert state.version == "0.10.100426"
    assert state.release_notes_url == notes
    assert len(calls) == 2
    assert all(
        call[2] == squirrel_update.UPDATE_STAGE_TIMEOUT_SECONDS for call in calls
    )


@pytest.mark.parametrize(
    ("verification", "message"),
    (
        (
            squirrel_update.SquirrelCheckResult(
                "0.10.100425", "0.10.100426", ("0.10.100426",)
            ),
            "did not finish staging",
        ),
        (
            squirrel_update.SquirrelCheckResult("0.10.100425", "0.10.100426", ()),
            "currentVersion and futureVersion differed",
        ),
        (
            squirrel_update.SquirrelCheckResult("0.10.100425", "0.10.100425", ()),
            "did not match the selected update",
        ),
    ),
)
def test_stage_update_requires_exact_post_update_state(
    tmp_path, monkeypatch, verification, message
):
    updater = tmp_path / "Update.exe"
    updater.write_bytes(b"fixture")
    monkeypatch.setattr(squirrel_update, "_run_apply_update", lambda *_args: None)
    monkeypatch.setattr(
        squirrel_update, "_run_check_for_update", lambda *_args: verification
    )

    state = stage_update(
        "https://github.com/Ding-Ding-Projects/material-minecraft-map-editor/releases/download/0.10.0-dev.426/",
        update_exe=updater,
        version="0.10.100426",
    )

    assert state.status == "failed"
    assert message in (state.detail or "")


def test_stage_update_rejects_invalid_release_notes_before_running(
    tmp_path, monkeypatch
):
    updater = tmp_path / "Update.exe"
    updater.write_bytes(b"fixture")
    monkeypatch.setattr(
        squirrel_update,
        "_run_update_process",
        lambda *_args, **_kwargs: pytest.fail("Update.exe must not run"),
    )
    state = stage_update(
        "https://github.com/Ding-Ding-Projects/material-minecraft-map-editor/releases/download/0.10.0-dev.426/",
        update_exe=updater,
        release_notes_url="https://example.test/not-release-notes",
    )
    assert state.status == "failed"
    assert "immutable project GitHub URL" in (state.detail or "")


@pytest.mark.parametrize(
    "feed",
    (
        "https://github.com/Other/material-minecraft-map-editor/releases/download/0.10.0-dev.426/",
        "https://github.com/Ding-Ding-Projects/other/releases/download/0.10.0-dev.426/",
        "https://github.com/Ding-Ding-Projects/material-minecraft-map-editor/releases/latest/download/",
        "https://raw.githubusercontent.com/Ding-Ding-Projects/material-minecraft-map-editor/main/RELEASES",
    ),
)
def test_stage_update_rejects_non_project_feed_before_running(
    tmp_path, monkeypatch, feed
):
    updater = tmp_path / "Update.exe"
    updater.write_bytes(b"fixture")
    monkeypatch.setattr(
        squirrel_update,
        "_run_update_process",
        lambda *_args, **_kwargs: pytest.fail("Update.exe must not run"),
    )

    state = stage_update(feed, update_exe=updater)

    assert state.status == "failed"
    assert "immutable project GitHub route" in (state.detail or "")


def test_stage_update_rejects_release_notes_for_different_tag_before_running(
    tmp_path, monkeypatch
):
    updater = tmp_path / "Update.exe"
    updater.write_bytes(b"fixture")
    monkeypatch.setattr(
        squirrel_update,
        "_run_update_process",
        lambda *_args, **_kwargs: pytest.fail("Update.exe must not run"),
    )
    state = stage_update(
        "https://github.com/Ding-Ding-Projects/material-minecraft-map-editor/releases/download/0.10.0-dev.426/",
        update_exe=updater,
        release_notes_url="https://github.com/Ding-Ding-Projects/material-minecraft-map-editor/releases/tag/0.10.0-dev.424",
    )
    assert state.status == "failed"
    assert "do not match" in (state.detail or "")


def test_official_check_shape_is_progress_then_strict_json():
    result = squirrel_update._parse_check_output(
        _check_output("0.10.100425", "0.10.100426", ("0.10.100426",))
    )
    assert result == squirrel_update.SquirrelCheckResult(
        "0.10.100425", "0.10.100426", ("0.10.100426",)
    )


def test_official_check_shape_allows_no_progress_callback():
    output = _check_output("0.10.100426", "0.10.100426", (), progress=())
    assert squirrel_update._parse_check_output(output) == (
        squirrel_update.SquirrelCheckResult("0.10.100426", "0.10.100426", ())
    )


def test_check_parser_accepts_real_cli_crlf_and_one_terminal_newline():
    output = _check_output("0.10.100426", "0.10.100427", ("0.10.100427",)).replace(
        "\n", "\r\n"
    )
    assert squirrel_update._parse_check_output(output).future_version == ("0.10.100427")


@pytest.mark.parametrize(
    "output",
    (
        # A pretty-printed whole-stdout document is not one strict final JSON line.
        json.dumps(
            {
                "currentVersion": "1.0.0",
                "futureVersion": "1.0.0",
                "releasesToApply": [],
            },
            indent=2,
        )
        + "\n",
        '0\n\n{"currentVersion":"1","futureVersion":"1","releasesToApply":[]}\n',
        '0\n{"currentVersion":"1","futureVersion":"1","releasesToApply":[]}\n\n',
        # The earlier fictional field must never be accepted as a Squirrel result.
        '0\n{"futureReleaseEntry":{"version":"1.0.1"}}\n',
        '0\n101\n{"currentVersion":"1","futureVersion":"1","releasesToApply":[]}\n',
        '0\n1.5\n{"currentVersion":"1","futureVersion":"1","releasesToApply":[]}\n',
        '0\n{"currentVersion":"1","futureVersion":"2","releasesToApply":[],"extra":true}\n',
        '0\n{"currentVersion":"1","futureVersion":"2","releasesToApply":[{"version":"2","releaseNotes":"","extra":true}]}\n',
    ),
)
def test_check_output_mutations_fail_closed(output):
    with pytest.raises(RuntimeError):
        squirrel_update._parse_check_output(output)


@pytest.mark.parametrize("output", ("0\n50\n100\n", ""))
def test_update_accepts_only_numeric_progress(output):
    squirrel_update._parse_update_output(output)


@pytest.mark.parametrize("output", ("{}\n", "-1\n", "101\n", "50 %\n"))
def test_update_rejects_non_progress_output(output):
    with pytest.raises(RuntimeError):
        squirrel_update._parse_update_output(output)


@pytest.mark.parametrize(
    "script",
    (
        f"print('x' * {squirrel_update._MAX_PROCESS_STDOUT_BYTES + 1})",
        (
            "import sys; sys.stderr.write('x' * "
            f"{squirrel_update._MAX_PROCESS_STDERR_BYTES + 1})"
        ),
    ),
)
def test_process_stdout_and_stderr_are_bounded(script):
    with pytest.raises(RuntimeError, match="size limit"):
        squirrel_update._run_update_process(
            Path(sys.executable),
            ("-c", script),
            10.0,
        )


def test_check_and_update_use_distinct_exact_arguments(monkeypatch, tmp_path):
    updater = tmp_path / "Update.exe"
    feed = "https://github.com/Ding-Ding-Projects/material-minecraft-map-editor/releases/download/0.10.0-dev.426/"
    calls: list[tuple[Path, tuple[str, ...], float]] = []

    def run(executable, arguments, timeout):
        calls.append((executable, tuple(arguments), timeout))
        if arguments[0].startswith("--checkForUpdate="):
            return _check_output("1.0.0", "1.0.0", ())
        return "0\n50\n100\n"

    monkeypatch.setattr(squirrel_update, "_run_update_process", run)
    squirrel_update._run_apply_update(updater, feed, 12.0)
    squirrel_update._run_check_for_update(updater, feed, 12.0)

    assert calls == [
        (updater, ("--update=" + feed,), 12.0),
        (updater, ("--checkForUpdate=" + feed,), 12.0),
    ]


def test_restart_command_uses_official_exact_argv(tmp_path):
    updater = tmp_path / "Update.exe"
    executable = tmp_path / "app-0.10.100426" / "Amulet.exe"
    assert squirrel_update.build_restart_command(updater, executable) == (
        str(updater),
        "--processStartAndWait",
        "Amulet.exe",
    )
