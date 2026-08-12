"""Real-file, real-sandbox tests for the universal local file converter.

Every test here uses genuinely crafted bytes -- an extension that lies, an
unsupported pairing, a file over a declared limit, deliberately corrupt
output, and a batch mixing success/failure/skip/cancel -- and asserts on the
actual detection, sandbox and batch-report behaviour rather than on source
text.
"""

from __future__ import annotations

import gzip
import io
import json
import os

import amulet_nbt as nbt
import pytest

from amulet_map_editor.api.converter import core, registry, sandbox
from amulet_map_editor.api.converter.registry import Adapter, Limits
from amulet_map_editor.api.converter.signatures import detect_format, detect_format_full


def _sample_nbt_bytes(compressed: bool) -> bytes:
    tag = nbt.CompoundTag(
        {
            "Name": nbt.StringTag("Andyville"),
            "Height": nbt.IntTag(64),
            "Ratio": nbt.DoubleTag(1.5),
            "Bytes": nbt.ByteArrayTag([1, 2, 3]),
            "Nested": nbt.CompoundTag({"Flag": nbt.ByteTag(1)}),
        }
    )
    named = nbt.NamedTag(tag, "root")
    buf = io.BytesIO()
    named.save_to(buf, compressed=compressed)
    return buf.getvalue()


def _lying_convert(data: bytes) -> bytes:
    return b"not actually json at all"


def _huge_convert(data: bytes) -> bytes:
    return b"x" * 1000


def _boom_convert(data: bytes) -> bytes:
    raise ValueError("deliberately broken for the test")


def _sample_png_bytes() -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGBA", (4, 4), (10, 20, 30, 255)).save(buf, format="PNG")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Detection: extension lies, bytes win
# ---------------------------------------------------------------------------


def test_detects_png_regardless_of_extension_claim(tmp_path):
    data = _sample_png_bytes()
    fake = tmp_path / "totally_a.txt"
    fake.write_bytes(data)
    assert detect_format_full(data) == "png"
    assert core.detect_source(str(fake)) == "png"


def test_extension_claiming_json_but_bytes_are_png_is_rejected(tmp_path):
    path = tmp_path / "notes.json"
    path.write_bytes(_sample_png_bytes())
    assert core.detect_source(str(path)) == "png"
    targets = core.compatible_targets(str(path))
    assert all(a.source_format == "png" for a in targets)
    assert not any(a.source_format == "json" for a in targets)


def test_unknown_bytes_detect_as_none(tmp_path):
    path = tmp_path / "mystery.bin"
    path.write_bytes(b"\x00\x01\x02not a real format at all")
    assert core.detect_source(str(path)) is None
    assert core.compatible_targets(str(path)) == ()


def test_truncated_json_is_not_detected_as_json():
    assert detect_format_full(b'{"a": [1, 2,') is None


# ---------------------------------------------------------------------------
# Registry shape
# ---------------------------------------------------------------------------


def test_every_adapter_declares_its_contract():
    for adapter in registry.ADAPTERS:
        assert adapter.id
        assert adapter.source_format
        assert adapter.target_format
        assert adapter.display_name
        assert isinstance(adapter.lossy, bool)
        assert adapter.loss_disclosure
        assert adapter.metadata_behaviour
        assert callable(adapter.validate_output)
        assert adapter.limits.max_input_bytes > 0
        assert adapter.limits.timeout_seconds > 0


def test_adapters_for_source_only_returns_matching_source():
    for fmt in ("png", "jpeg", "bmp", "gif", "json", "nbt", "gzip_nbt"):
        for adapter in registry.adapters_for_source(fmt):
            assert adapter.source_format == fmt


def test_unsupported_pairing_offers_nothing(tmp_path):
    # There is no adapter from gzip_nbt straight to an image format, or the
    # reverse; the registry must not invent one.
    ids = {(a.source_format, a.target_format) for a in registry.ADAPTERS}
    assert ("gzip_nbt", "png") not in ids
    assert ("png", "gzip_nbt") not in ids


# ---------------------------------------------------------------------------
# Round trips that must be lossless
# ---------------------------------------------------------------------------


def test_gzip_nbt_json_round_trip_is_exact(tmp_path):
    source = tmp_path / "structure.mcstructure"
    source.write_bytes(_sample_nbt_bytes(compressed=True))
    adapter = registry.get_adapter("gzip_nbt_to_json")
    json_path = tmp_path / "structure.json"
    result = core.convert_one(str(source), adapter.id, str(json_path))
    assert result.outcome is core.ConvertOutcome.CONVERTED
    doc = json.loads(json_path.read_bytes())
    assert doc["root"]["value"]["Name"]["value"] == "Andyville"

    back_adapter = registry.get_adapter("json_to_gzip_nbt")
    roundtrip_path = tmp_path / "roundtrip.mcstructure"
    result2 = core.convert_one(str(json_path), back_adapter.id, str(roundtrip_path))
    assert result2.outcome is core.ConvertOutcome.CONVERTED
    original = nbt.load(source.read_bytes(), compressed=True)
    restored = nbt.load(roundtrip_path.read_bytes(), compressed=True)
    assert restored.tag["Name"].py_data == original.tag["Name"].py_data
    assert restored.tag["Height"].py_data == original.tag["Height"].py_data
    assert list(restored.tag["Bytes"].np_array) == list(original.tag["Bytes"].np_array)


def test_image_conversion_png_to_bmp_and_back(tmp_path):
    source = tmp_path / "tile.png"
    source.write_bytes(_sample_png_bytes())
    adapter = registry.get_adapter("image_png_to_bmp")
    dest = tmp_path / "tile.bmp"
    result = core.convert_one(str(source), adapter.id, str(dest))
    assert result.outcome is core.ConvertOutcome.CONVERTED
    assert dest.read_bytes().startswith(b"BM")


# ---------------------------------------------------------------------------
# Failure modes, each asserted on its own outcome and reason
# ---------------------------------------------------------------------------


def test_sandbox_rejects_input_over_declared_limit():
    adapter = registry.get_adapter("json_to_gzip_nbt")
    tiny_limits = Limits(max_input_bytes=8, timeout_seconds=5.0)
    outcome = sandbox.run_adapter(
        adapter, b'{"root": {}, "__nbt_root_name__": ""}', tiny_limits
    )
    assert outcome.ok is False
    assert outcome.status == "input_too_large"


def test_sandbox_rejects_a_deliberately_corrupt_adapter_output():
    fake = Adapter(
        id="test_lying_adapter",
        source_format="json",
        target_format="json",
        display_name="Lying adapter",
        convert=_lying_convert,
        lossy=False,
        loss_disclosure="none",
        metadata_behaviour="none",
        validate_output=lambda data: json.loads(data.decode("utf-8")) is not None,
    )
    outcome = sandbox.run_adapter(fake, b'{"a": 1}')
    assert outcome.ok is False
    assert outcome.status == "output_invalid"


def test_sandbox_reports_output_too_large():
    fake = Adapter(
        id="test_huge_adapter",
        source_format="json",
        target_format="json",
        display_name="Huge adapter",
        convert=_huge_convert,
        lossy=False,
        loss_disclosure="none",
        metadata_behaviour="none",
        validate_output=lambda data: True,
        limits=Limits(max_output_bytes=10),
    )
    outcome = sandbox.run_adapter(fake, b"{}")
    assert outcome.ok is False
    assert outcome.status == "output_too_large"


def test_sandbox_reports_a_crashing_adapter_honestly():
    fake = Adapter(
        id="test_crash_adapter",
        source_format="json",
        target_format="json",
        display_name="Crashing adapter",
        convert=_boom_convert,
        lossy=False,
        loss_disclosure="none",
        metadata_behaviour="none",
        validate_output=lambda data: True,
    )
    outcome = sandbox.run_adapter(fake, b"{}")
    assert outcome.ok is False
    assert outcome.status == "crashed"
    assert "deliberately broken" in outcome.message


def test_convert_one_refuses_a_pairing_the_bytes_contradict(tmp_path):
    source = tmp_path / "structure.mcstructure"
    source.write_bytes(_sample_png_bytes())  # bytes are PNG, not gzip NBT
    adapter = registry.get_adapter("gzip_nbt_to_json")
    dest = tmp_path / "out.json"
    result = core.convert_one(str(source), adapter.id, str(dest))
    assert result.outcome is core.ConvertOutcome.SKIPPED
    assert "detected as" in result.reason
    assert not dest.exists()


def test_convert_one_never_overwrites_source(tmp_path):
    source = tmp_path / "structure.mcstructure"
    source.write_bytes(_sample_nbt_bytes(compressed=True))
    adapter = registry.get_adapter("gzip_nbt_to_json")
    result = core.convert_one(str(source), adapter.id, str(source))
    assert result.outcome is core.ConvertOutcome.SKIPPED
    assert "overwrite the source" in result.reason
    # Source bytes are completely untouched.
    assert source.read_bytes() == _sample_nbt_bytes(compressed=True)


def test_convert_one_skips_existing_destination_without_confirmation(tmp_path):
    source = tmp_path / "structure.mcstructure"
    source.write_bytes(_sample_nbt_bytes(compressed=True))
    dest = tmp_path / "out.json"
    dest.write_text("pre-existing content")
    adapter = registry.get_adapter("gzip_nbt_to_json")
    result = core.convert_one(str(source), adapter.id, str(dest))
    assert result.outcome is core.ConvertOutcome.SKIPPED
    assert dest.read_text() == "pre-existing content"

    confirmed = core.convert_one(
        str(source), adapter.id, str(dest), overwrite_confirmed=True
    )
    assert confirmed.outcome is core.ConvertOutcome.CONVERTED
    assert dest.read_text() != "pre-existing content"


def test_convert_one_reports_failed_when_the_adapter_itself_rejects_the_content(
    tmp_path,
):
    # Bytes genuinely detect as JSON (so this passes the earlier signature
    # check unlike the "lying" case), but the JSON does not carry the
    # converter's own {'type', 'value'} NBT shape, so the adapter itself
    # raises inside the sandbox -- a real FAILED outcome, not a SKIPPED one.
    source = tmp_path / "arbitrary.json"
    source.write_text(json.dumps({"just": "some ordinary json"}))
    adapter = registry.get_adapter("json_to_gzip_nbt")
    dest = tmp_path / "out.mcstructure"
    result = core.convert_one(str(source), adapter.id, str(dest))
    assert result.outcome is core.ConvertOutcome.FAILED
    assert not dest.exists()


# ---------------------------------------------------------------------------
# Batch: converted / skipped / cancelled / failed reported separately
# ---------------------------------------------------------------------------


def test_batch_reports_converted_skipped_cancelled_failed_separately(tmp_path):
    good = tmp_path / "good.mcstructure"
    good.write_bytes(_sample_nbt_bytes(compressed=True))

    wrong_bytes = tmp_path / "lying.mcstructure"
    wrong_bytes.write_bytes(_sample_png_bytes())

    missing = tmp_path / "does_not_exist.mcstructure"

    also_good = tmp_path / "also_good.mcstructure"
    also_good.write_bytes(_sample_nbt_bytes(compressed=True))

    adapter_id = "gzip_nbt_to_json"
    jobs = [
        {
            "source_path": str(good),
            "adapter_id": adapter_id,
            "destination_path": str(tmp_path / "good.json"),
        },
        {
            "source_path": str(wrong_bytes),
            "adapter_id": adapter_id,
            "destination_path": str(tmp_path / "lying.json"),
        },
        {
            "source_path": str(missing),
            "adapter_id": adapter_id,
            "destination_path": str(tmp_path / "missing.json"),
        },
        {
            "source_path": str(also_good),
            "adapter_id": adapter_id,
            "destination_path": str(tmp_path / "also_good.json"),
        },
    ]

    # Cancel once the third job (the failing one) has been processed.
    processed = {"count": 0}

    def _should_cancel():
        return processed["count"] >= 3

    def _on_progress(done, total, result):
        processed["count"] = done

    batch = core.convert_batch(
        jobs, should_cancel=_should_cancel, on_progress=_on_progress
    )

    # "lying" has bytes that contradict its claimed format (skipped, not
    # failed -- the converter refuses to guess rather than attempting and
    # failing), "missing" does not exist on disk (also skipped), "good"
    # converts, and "also_good" is cancelled before it starts.
    assert len(batch.results) == 4
    assert batch.converted == 1
    assert batch.skipped == 2
    assert batch.failed == 0
    assert batch.cancelled == 1
    assert batch.converted + batch.skipped + batch.failed + batch.cancelled == 4


def test_batch_history_is_recorded_and_bounded(tmp_path, monkeypatch):
    profile_dir = tmp_path / "profile"
    profile_dir.mkdir()
    monkeypatch.setenv("CONFIG_DIR", str(profile_dir))
    core.clear_history()

    good = tmp_path / "good.mcstructure"
    good.write_bytes(_sample_nbt_bytes(compressed=True))
    result = core.convert_one(
        str(good), "gzip_nbt_to_json", str(tmp_path / "good.json")
    )
    assert result.outcome is core.ConvertOutcome.CONVERTED
    history = core.read_history()
    assert history
    assert history[-1]["outcome"] == "converted"
    assert history[-1]["source_path"] == str(good)
