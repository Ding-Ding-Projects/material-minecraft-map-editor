"""Every format the application writes, and what it refuses to write quietly."""

from __future__ import annotations

import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from amulet_map_editor.api import export_actions
from amulet_map_editor.api.studio import exporters

FIXED = datetime(2026, 8, 11, 3, 0, 0, tzinfo=timezone.utc)


def flat_dataset() -> exporters.Dataset:
    """A rectangular record set every format can carry whole."""

    return exporters.Dataset.build(
        "block_histogram",
        "Block histogram",
        [
            {
                "block": "minecraft:stone",
                "count": 148213,
                "percent": 41.2,
                "ore": False,
            },
            {"block": "minecraft:dirt", "count": 39120, "percent": 10.9, "ore": False},
            {
                "block": "minecraft:diamond_ore",
                "count": 61,
                "percent": 0.02,
                "ore": True,
            },
        ],
        schema_version="3",
        description="Counted over the current selection.",
        source="selection box 1",
    )


def nested_dataset() -> exporters.Dataset:
    """A record set with structure, nulls, and a line break in a value."""

    return exporters.Dataset.build(
        "waypoints",
        "Waypoints",
        [
            {
                "label": "Spawn arch",
                "position": {"x": 12, "y": 68, "z": -430},
                "tags": ["build", "public"],
                "note": None,
            },
            {
                "label": "Rail hub",
                "position": {"x": -800, "y": 12, "z": 96},
                "tags": [],
                "note": "two lines\nof note",
            },
        ],
        schema_version="2",
    )


# ---------------------------------------------------------------------------
# the catalogue is offered per datum
# ---------------------------------------------------------------------------
def test_every_catalogue_format_is_offered_for_a_dataset():
    offers = export_actions.offer_formats(flat_dataset())

    assert {offer.format_id for offer in offers} == set(exporters.FORMAT_IDS)
    assert {"csv", "tsv", "json", "jsonl", "yaml", "toml", "xml"} <= set(
        exporters.FORMAT_IDS
    )
    assert {"markdown", "html", "sql", "jsonschema"} <= set(exporters.FORMAT_IDS)


def test_offers_put_the_formats_that_carry_the_datum_whole_first():
    offers = export_actions.offer_formats(nested_dataset())

    assert offers[0].lossless and offers[0].available
    assert not offers[-1].lossless
    # The default is a property of this datum, not one favourite format.
    assert export_actions.recommended_format(nested_dataset()) == "json"
    assert export_actions.recommended_format(flat_dataset()) == "csv"


def test_a_lossy_format_is_still_offered_with_its_cost_stated():
    report = export_actions.preview_export(nested_dataset(), "toml")

    assert not report.lossless
    reasons = {loss.reason for loss in report.losses}
    assert "no_null" in reasons
    assert any(loss.field == "note" for loss in report.losses)
    assert "TOML has no null" in report.summary()


# ---------------------------------------------------------------------------
# round trips
# ---------------------------------------------------------------------------
def test_json_round_trip_returns_the_same_records():
    dataset = nested_dataset()

    text = exporters.export_text(dataset, "json", timestamp=FIXED)
    back = exporters.read_text(text, "json")

    assert list(back.records) == list(dataset.rows())
    assert back.schema == "waypoints"
    assert back.schema_version == "2"
    assert back.metadata["encoding"] == "utf-8"
    assert back.metadata["line_endings"] == "lf"
    assert back.metadata["contract"] == exporters.EXPORT_CONTRACT_VERSION


def test_csv_round_trip_returns_the_same_records():
    dataset = flat_dataset()

    text = exporters.export_text(dataset, "csv", timestamp=FIXED)
    back = exporters.read_text(text, "csv")

    assert list(back.records) == list(dataset.rows())
    assert back.metadata["schema"] == "block_histogram"
    assert back.metadata["schema_version"] == "3"
    assert back.metadata["encoding"] == "utf-8"
    assert back.metadata["line_endings"] == "lf"
    # Types survive the trip through a file whose cells are all text.
    assert back.records[0]["count"] == 148213
    assert back.records[2]["ore"] is True


@pytest.mark.parametrize(
    "format_id", [item.id for item in exporters.FORMATS if item.round_trip]
)
@pytest.mark.parametrize("factory", [flat_dataset, nested_dataset])
def test_a_lossless_report_means_an_identical_round_trip(format_id, factory):
    dataset = factory()
    report = exporters.describe_fidelity(dataset, format_id)
    if not report.available:
        pytest.skip(report.unavailable_reason)

    back = exporters.round_trip(dataset, format_id, accept_loss=True, timestamp=FIXED)

    if report.lossless:
        assert list(back.records) == list(dataset.rows())
    else:
        # A stated loss is allowed to differ -- that is what it stated.
        assert report.losses


def test_a_presentation_format_refuses_to_pretend_it_reads_back():
    text = exporters.export_text(flat_dataset(), "markdown", timestamp=FIXED)

    with pytest.raises(exporters.ExportError) as caught:
        exporters.read_text(text, "markdown")

    assert "cannot read it back" in str(caught.value)


# ---------------------------------------------------------------------------
# every file says what it is
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("format_id", [item.id for item in exporters.FORMATS])
def test_every_export_states_encoding_line_endings_and_schema_version(format_id):
    dataset = flat_dataset()
    report = exporters.describe_fidelity(dataset, format_id)
    if not report.available:
        pytest.skip(report.unavailable_reason)

    text = exporters.export_text(dataset, format_id, accept_loss=True, timestamp=FIXED)

    lowered = text.lower()
    assert "utf-8" in lowered
    assert "lf" in lowered
    assert "block_histogram" in text
    assert any(
        marker in text
        for marker in (
            '"schema_version": "3"',
            'schema_version = "3"',
            'schema-version="3"',
            "block_histogram` v3",
            "block_histogram v3",
            ":block_histogram:3",
        )
    ), text[:400]
    assert "\r\n" not in text


@pytest.mark.parametrize("format_id", [item.id for item in exporters.FORMATS])
def test_every_export_writes_lf_endings_to_disk(tmp_path, format_id):
    dataset = flat_dataset()
    if not exporters.resolve_format(format_id).available:
        pytest.skip(exporters.resolve_format(format_id).unavailable_reason)

    target = exporters.write_export(
        dataset,
        tmp_path / f"histogram{exporters.resolve_format(format_id).extension}",
        format_id,
        accept_loss=True,
        timestamp=FIXED,
    )

    assert b"\r\n" not in target.read_bytes()
    assert target.read_bytes().decode("utf-8")


def test_json_schema_says_it_carries_no_record_values():
    dataset = flat_dataset()
    report = exporters.describe_fidelity(dataset, "jsonschema")

    assert not report.lossless
    assert report.losses[0].reason == "no_record_values"
    assert report.losses[0].records == 3

    document = json.loads(
        exporters.export_text(dataset, "jsonschema", accept_loss=True, timestamp=FIXED)
    )
    assert document["x-amulet-export"]["carries_record_values"] is False
    assert document["x-amulet-export"]["record_count"] == 3
    assert set(document["properties"]["records"]["items"]["properties"]) == {
        "block",
        "count",
        "percent",
        "ore",
    }


# ---------------------------------------------------------------------------
# nothing is dropped quietly
# ---------------------------------------------------------------------------
def test_a_lossy_format_refuses_until_the_loss_is_acknowledged(tmp_path):
    dataset = nested_dataset()

    with pytest.raises(exporters.LossyExportError) as caught:
        exporters.export_text(dataset, "toml", timestamp=FIXED)

    assert "note" in str(caught.value)
    assert caught.value.report.format_id == "toml"

    refused = tmp_path / "refused.toml"
    with pytest.raises(exporters.LossyExportError):
        exporters.write_export(dataset, refused, "toml", timestamp=FIXED)
    assert not refused.exists(), "the refusal must happen before anything is written"

    written = exporters.write_export(
        dataset, tmp_path / "waypoints.toml", "toml", accept_loss=True, timestamp=FIXED
    )
    assert written.exists()


def test_the_null_ambiguity_is_reported_only_when_the_data_is_ambiguous():
    unambiguous = exporters.Dataset.build(
        "tags", "Tags", [{"tag": None}, {"tag": "build"}]
    )
    ambiguous = exporters.Dataset.build(
        "tags", "Tags", [{"tag": None}, {"tag": ""}, {"tag": "build"}]
    )

    assert exporters.describe_fidelity(unambiguous, "csv").lossless
    # A rendered table cannot show the difference either, so it says so too.
    for format_id in ("csv", "tsv", "markdown", "html"):
        assert exporters.describe_fidelity(unambiguous, format_id).lossless, format_id
        reasons = {
            loss.reason
            for loss in exporters.describe_fidelity(ambiguous, format_id).losses
        }
        assert "null_ambiguity" in reasons, format_id
    # A format that can carry the difference does not claim a loss.
    assert exporters.describe_fidelity(ambiguous, "json").lossless


def test_a_line_break_inside_a_csv_value_survives_the_round_trip():
    # Reading the file back by splitting it into lines first would turn every
    # embedded carriage return into a line feed, changing the value while the
    # report still claimed the format carried it whole.
    dataset = exporters.Dataset.build(
        "signs",
        "Sign text",
        [
            {"text": "line one\r\nline two", "author": "#not-a-comment"},
            {"text": "bare\rreturn", "author": "ok"},
        ],
    )

    report = exporters.describe_fidelity(dataset, "csv")
    back = exporters.read_text(
        exporters.export_text(dataset, "csv", timestamp=FIXED), "csv"
    )

    assert report.lossless
    assert list(back.records) == list(dataset.rows())
    assert back.records[0]["text"] == "line one\r\nline two"
    assert back.records[0]["author"] == "#not-a-comment"


def test_a_tab_inside_a_value_is_a_stated_loss_for_tab_separated_output():
    dataset = exporters.Dataset.build("notes", "Notes", [{"body": "left\tright"}])

    report = exporters.describe_fidelity(dataset, "tsv")

    assert {loss.reason for loss in report.losses} == {"delimiter_in_value"}
    assert exporters.describe_fidelity(dataset, "csv").lossless


def test_a_column_of_several_kinds_cannot_survive_a_delimited_file():
    dataset = exporters.Dataset.build(
        "settings", "Settings", [{"value": "dark"}, {"value": 1.25}, {"value": False}]
    )

    report = exporters.describe_fidelity(dataset, "csv")

    assert {loss.reason for loss in report.losses} == {"mixed_types"}
    # A format with a type per value carries it without complaint.
    assert exporters.describe_fidelity(dataset, "json").lossless


def test_a_column_of_integers_and_floats_still_round_trips_through_csv():
    dataset = exporters.Dataset.build("m", "Measurements", [{"v": 1284}, {"v": 2.5}])

    report = exporters.describe_fidelity(dataset, "csv")
    back = exporters.read_text(
        exporters.export_text(dataset, "csv", timestamp=FIXED), "csv"
    )

    assert report.lossless
    assert list(back.records) == list(dataset.rows())
    assert back.records[0]["v"] == 1284 and isinstance(back.records[0]["v"], int)


def test_a_settings_mapping_exports_as_a_two_column_record_set():
    dataset = exporters.Dataset.from_mapping(
        "appearance",
        "Appearance settings",
        {"theme": "dark", "density": "comfortable", "ui_scale": 1.25},
        source="preferences.json",
    )

    assert dataset.field_names == ("setting", "value")
    assert [record["setting"] for record in dataset.records] == [
        "theme",
        "density",
        "ui_scale",
    ]
    back = exporters.read_text(
        exporters.export_text(dataset, "json", timestamp=FIXED), "json"
    )
    assert list(back.records) == list(dataset.rows())


def test_a_setting_that_holds_a_secret_marks_the_whole_record_set():
    dataset = exporters.Dataset.from_mapping(
        "account", "Account", {"user": "a", "token": "b"}, sensitive_keys=["token"]
    )

    assert dataset.carries_secrets is True
    assert (
        exporters.Dataset.from_mapping(
            "account", "Account", {"user": "a"}, sensitive_keys=["token"]
        ).carries_secrets
        is False
    )


def test_a_log_exports_as_numbered_lines_for_a_machine_or_a_person():
    dataset = exporters.Dataset.from_lines(
        "session_log", "Session log", ["opened world", "2 chunks edited", "saved"]
    )

    assert dataset.field_names == ("line", "text")
    assert dataset.records[2] == {"line": 3, "text": "saved"}
    assert exporters.describe_fidelity(dataset, "csv").lossless
    assert "# Session log" in exporters.export_text(
        dataset, "markdown", timestamp=FIXED
    )


def test_values_that_are_not_json_native_are_converted_with_a_note():
    dataset = exporters.Dataset.build(
        "mixed",
        "Mixed",
        [
            {
                "when": datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc),
                "where": Path("worlds") / "flat",
                "blob": b"\x00\x01",
            }
        ],
    )

    assert dataset.records[0]["when"] == "2026-01-02T03:04:05+00:00"
    assert "flat" in dataset.records[0]["where"]
    assert dataset.records[0]["blob"] == "AAE="
    assert any("ISO-8601" in note for note in dataset.notes)
    assert any("base64" in note for note in dataset.notes)


# ---------------------------------------------------------------------------
# honest empty states
# ---------------------------------------------------------------------------
def test_an_empty_record_set_says_it_was_read_and_was_empty():
    dataset = exporters.Dataset.build("players", "Players", [])

    text = exporters.export_text(dataset, "markdown", timestamp=FIXED)

    assert "read successfully and was empty" in text
    assert "no records" in text


def test_an_unreadable_record_set_names_the_reason_instead_of_inventing_rows():
    dataset = exporters.Dataset.unreadable(
        "players",
        "Players",
        "level.dat could not be opened: permission denied.",
    )

    assert dataset.records == ()
    for format_id in ("markdown", "html", "sql", "json"):
        text = exporters.export_text(
            dataset, format_id, accept_loss=True, timestamp=FIXED
        )
        assert "permission denied" in text
    assert "Nothing has been substituted" in exporters.export_text(
        dataset, "markdown", timestamp=FIXED
    )


def test_an_unreadable_record_set_must_name_a_reason():
    with pytest.raises(exporters.ExportError):
        exporters.Dataset.unreadable("players", "Players", "   ")


# ---------------------------------------------------------------------------
# archive member names stay inside the archive
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "name",
    [
        "../escape.txt",
        "nested/../../escape.txt",
        "/absolute.txt",
        "C:/drive.txt",
        "\\\\server\\share\\file.txt",
        "con.txt",
        "",
    ],
)
def test_a_member_name_that_could_escape_is_refused(name):
    with pytest.raises(exporters.MemberNameError):
        exporters.safe_member_name(name)


def test_a_relative_member_name_is_normalised_to_posix():
    assert exporters.safe_member_name("waypoints\\waypoints.json") == (
        "waypoints/waypoints.json"
    )
    assert exporters.safe_member_name("./a/./b.json") == "a/b.json"


# ---------------------------------------------------------------------------
# ZIP
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("method", exporters.ZIP_METHODS)
def test_zip_writes_every_method_with_relative_members(tmp_path, method):
    members = exporters.bundle_members(
        [flat_dataset()], ["json", "csv"], timestamp=FIXED
    )

    result = exporters.write_zip(
        members, tmp_path / f"bundle-{method}.zip", exporters.ZipOptions(method=method)
    )

    with zipfile.ZipFile(result.path) as archive:
        names = archive.namelist()
        manifest = json.loads(archive.read("MANIFEST.json"))
    assert names == list(result.members)
    assert all(not name.startswith("/") and ".." not in name for name in names)
    assert {entry["format"] for entry in manifest["files"]} == {"json", "csv"}
    assert manifest["encoding"] == "utf-8"


def test_the_zip_plan_never_claims_protection_it_does_not_have():
    plan = exporters.describe_zip()

    assert plan.encrypted is False
    assert plan.names_hidden is False
    assert "Not protected" in plan.protection
    assert "cannot write encrypted entries" in plan.protection


def test_a_record_set_marked_sensitive_refuses_an_archive_that_is_not(tmp_path):
    secret = exporters.Dataset.build(
        "credentials", "Credentials", [{"account": "a", "token": "b"}], sensitive=True
    )
    members = exporters.bundle_members([secret], ["json"], timestamp=FIXED)

    with pytest.raises(exporters.ArchiveProtectionError):
        exporters.write_zip(members, tmp_path / "secret.zip")

    with pytest.raises(exporters.ArchiveProtectionError) as caught:
        exporters.write_zip(members, tmp_path / "secret.zip", sensitive=True)
    assert "cannot encrypt" in str(caught.value)

    result = exporters.write_zip(
        members, tmp_path / "secret.zip", sensitive=True, accept_unencrypted=True
    )
    assert result.sensitive is True


# ---------------------------------------------------------------------------
# 7z
# ---------------------------------------------------------------------------
def test_the_seven_zip_plan_exposes_what_seven_zip_actually_offers():
    assert exporters.SEVEN_ZIP_METHODS == (
        "lzma2",
        "lzma",
        "ppmd",
        "bzip2",
        "deflate",
        "copy",
    )
    assert exporters.SEVEN_ZIP_LEVELS == (
        "store",
        "fastest",
        "fast",
        "normal",
        "maximum",
        "ultra",
    )
    for method in exporters.SEVEN_ZIP_METHODS:
        plan = exporters.describe_seven_zip(
            exporters.SevenZipOptions(method=method, level="ultra")
        )
        assert plan.costs, method
        assert any(
            "memory" in cost or "compression" in cost or "size of its contents" in cost
            for cost in plan.costs
        ), method


def test_the_seven_zip_plan_prices_the_dictionary_in_time_and_memory():
    plan = exporters.describe_seven_zip(
        exporters.SevenZipOptions(
            method="lzma2",
            level="ultra",
            dictionary_size="64m",
            word_size=273,
            solid=True,
            solid_block_size="4g",
            threads=8,
            volume_size="100m",
        )
    )

    joined = " ".join(plan.costs)
    assert "64 MiB" in joined
    assert "11.5x" in joined
    assert "thread" in joined
    assert "volume" in joined.lower()
    assert "solid" in joined.lower()


def test_encrypting_the_contents_without_the_names_says_so(tmp_path):
    plan = exporters.describe_seven_zip(
        exporters.SevenZipOptions(password="x", encrypt_headers=False)
    )

    assert plan.encrypted is True
    assert plan.names_hidden is False
    assert "in the clear" in plan.protection
    assert any("readable" in warning for warning in plan.warnings)

    hidden = exporters.describe_seven_zip(
        exporters.SevenZipOptions(password="x", encrypt_headers=True)
    )
    assert hidden.names_hidden is True
    assert "encrypted headers" in hidden.protection


def test_bad_archive_options_are_refused_by_name():
    with pytest.raises(exporters.ArchiveOptionError):
        exporters.SevenZipOptions(method="brotli").validate()
    with pytest.raises(exporters.ArchiveOptionError):
        exporters.SevenZipOptions(level="turbo").validate()
    with pytest.raises(exporters.ArchiveOptionError):
        exporters.SevenZipOptions(word_size=4000).validate()
    with pytest.raises(exporters.ArchiveOptionError):
        exporters.SevenZipOptions(dictionary_size="64 parsecs").validate()
    assert exporters.parse_size("64m") == 64 * 1024 * 1024
    assert exporters.parse_size("4g") == 4 * 1024**3


@pytest.mark.skipif(
    exporters.seven_zip_available()[0], reason="py7zr is installed here"
)
def test_a_missing_py7zr_refuses_by_name_instead_of_writing_a_zip(tmp_path):
    members = exporters.bundle_members([flat_dataset()], ["json"], timestamp=FIXED)
    target = tmp_path / "bundle.7z"

    with pytest.raises(exporters.ArchiveUnavailableError) as caught:
        exporters.write_seven_zip(
            members, target, exporters.SevenZipOptions(password="secret")
        )

    assert "py7zr" in str(caught.value)
    assert not target.exists()
    assert not list(tmp_path.glob("*.zip"))


@pytest.mark.skipif(
    not exporters.seven_zip_available()[0], reason="py7zr is not installed here"
)
@pytest.mark.parametrize("method", exporters.SEVEN_ZIP_METHODS)
def test_seven_zip_writes_every_method(tmp_path, method):
    import py7zr

    members = exporters.bundle_members([flat_dataset()], ["json"], timestamp=FIXED)

    result = exporters.write_seven_zip(
        members,
        tmp_path / f"bundle-{method}.7z",
        exporters.SevenZipOptions(method=method, level="normal"),
    )

    with py7zr.SevenZipFile(result.path) as archive:
        assert archive.getnames() == list(result.members)


@pytest.mark.skipif(
    not exporters.seven_zip_available()[0], reason="py7zr is not installed here"
)
def test_encrypted_headers_hide_the_file_names(tmp_path):
    import py7zr

    secret = exporters.Dataset.build(
        "credentials", "Credentials", [{"account": "a", "token": "b"}], sensitive=True
    )
    members = exporters.bundle_members([secret], ["json"], timestamp=FIXED)

    result = exporters.write_seven_zip(
        members,
        tmp_path / "secret.7z",
        exporters.SevenZipOptions(password="pw", encrypt_headers=True),
        sensitive=True,
    )

    with pytest.raises(Exception):
        with py7zr.SevenZipFile(result.path) as archive:
            archive.getnames()
    with py7zr.SevenZipFile(result.path, password="pw") as archive:
        assert "credentials/credentials.json" in archive.getnames()


@pytest.mark.skipif(
    not exporters.seven_zip_available()[0], reason="py7zr is not installed here"
)
def test_clear_file_names_need_saying_out_loud(tmp_path):
    members = exporters.bundle_members([flat_dataset()], ["json"], timestamp=FIXED)
    options = exporters.SevenZipOptions(password="pw", encrypt_headers=False)

    with pytest.raises(exporters.ArchiveProtectionError) as caught:
        exporters.write_seven_zip(members, tmp_path / "clear.7z", options)
    assert "names" in str(caught.value)

    result = exporters.write_seven_zip(
        members, tmp_path / "clear.7z", options, accept_visible_names=True
    )
    assert result.plan.names_hidden is False


# ---------------------------------------------------------------------------
# the action layer
# ---------------------------------------------------------------------------
def test_export_dataset_defaults_to_the_format_that_carries_the_datum(tmp_path):
    result = export_actions.export_dataset(flat_dataset(), tmp_path)

    assert result.target.name == "block_histogram.csv"
    assert result.lossless
    assert result.bytes_written == result.target.stat().st_size
    assert result.editor is None


def test_export_dataset_can_open_the_result_without_an_editor_installed(tmp_path):
    from amulet_map_editor.api import external_editor

    seen: list[Path] = []

    def opener(path):
        seen.append(Path(path))
        return external_editor.EditorResult(False, "unavailable", "No editor.")

    result = export_actions.export_dataset(
        flat_dataset(), tmp_path, "json", open_after=True, opener=opener
    )

    assert seen == [result.target]
    assert result.editor is not None and not result.editor.ok
    assert result.target.exists()


def test_resolve_target_adds_the_format_extension_but_keeps_a_spelled_out_name(
    tmp_path,
):
    dataset = flat_dataset()

    assert export_actions.resolve_target(tmp_path, dataset, "csv").name == (
        "block_histogram.csv"
    )
    assert export_actions.resolve_target(tmp_path / "counts", dataset, "tsv").name == (
        "counts.tsv"
    )
    assert (
        export_actions.resolve_target(tmp_path / "counts.txt", dataset, "csv").name
        == "counts.txt"
    )


def test_export_bundle_writes_a_self_describing_archive(tmp_path):
    result = export_actions.export_bundle(
        [flat_dataset(), nested_dataset()],
        tmp_path / "exports.zip",
        formats=("json", "csv", "markdown"),
        accept_loss=True,
        timestamp=FIXED,
    )

    with zipfile.ZipFile(result.target) as archive:
        readme = archive.read("README.md").decode("utf-8")
        manifest = json.loads(archive.read("MANIFEST.json"))
    assert "UTF-8 · LF line endings" in readme
    assert "What these formats could not carry" in readme
    assert len(manifest["files"]) == 6
    assert len(result.reports) == 6
    assert result.archive.plan.encrypted is False
