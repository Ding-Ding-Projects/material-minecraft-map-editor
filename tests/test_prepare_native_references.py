"""Reference preparation must preserve callers and reject incomplete inputs."""
import hashlib
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import prepare_native_references as preparation


@pytest.fixture
def inputs(tmp_path, monkeypatch):
    reports = tmp_path / "input"
    reports.mkdir()
    metadata = tmp_path / "source/docs/compatibility"
    metadata.mkdir(parents=True)
    payloads = [b"blocks", b"registries", b"receipt\n", b"shapes\n"]
    paths = [reports / "blocks.json", reports / "registries.json",
             metadata / "java-1201-registry-producer-receipt.json",
             metadata / "java-geometry-reference-evidence.json"]
    for path, data in zip(paths, payloads):
        path.write_bytes(data)
    files = tuple((original[0], len(data), hashlib.sha256(data).hexdigest())
                  for original, data in zip(preparation.FILES, payloads))
    monkeypatch.setattr(preparation, "FILES", files)
    monkeypatch.setattr(preparation, "ROOT", tmp_path / "source")
    return reports, tmp_path / "output", paths, payloads


def test_prepared_bytes_and_source_unchanged(inputs):
    reports, destination, sources, data = inputs
    result = preparation.prepare(reports, destination)
    assert result["status"] == "prepared"
    assert result["filesVerified"] == 4
    assert not result["generatorExecuted"]
    assert not result["worldCompatibilityVerified"]
    for source, expected, (relative, _, _) in zip(sources, data, preparation.FILES):
        assert source.read_bytes() == expected
        assert (destination / relative).read_bytes() == expected


@pytest.mark.parametrize("existing", ["file", "directory"])
def test_existing_destination_is_not_replaced(inputs, existing):
    reports, destination, _, _ = inputs
    if existing == "directory":
        destination.mkdir()
        sentinel = destination / "keep"
    else:
        sentinel = destination
    sentinel.write_bytes(b"retain")
    with pytest.raises(preparation.PreparationError, match="destination_exists"):
        preparation.prepare(reports, destination)
    assert sentinel.read_bytes() == b"retain"


@pytest.mark.parametrize("index", range(4))
def test_any_corrupt_input_prevents_output_creation(inputs, index):
    reports, destination, sources, data = inputs
    sources[index].write_bytes(b"!" + data[index][1:])
    with pytest.raises(preparation.PreparationError, match="reference_hash_mismatch"):
        preparation.prepare(reports, destination)
    assert not destination.exists()


def test_short_input_is_not_normalized_or_padded(inputs):
    reports, destination, sources, _ = inputs
    sources[2].write_bytes(b"receipt")
    with pytest.raises(preparation.PreparationError, match="reference_type_or_size_mismatch"):
        preparation.prepare(reports, destination)
    assert not destination.exists()


def test_failure_retains_only_new_partial_destination(inputs, monkeypatch):
    reports, destination, sources, data = inputs
    original = preparation.read_pinned

    def reject_readback(path, size, digest):
        if destination in path.parents:
            raise preparation.PreparationError("reference_changed")
        return original(path, size, digest)

    monkeypatch.setattr(preparation, "read_pinned", reject_readback)
    with pytest.raises(preparation.PreparationError, match="incomplete_destination_retained"):
        preparation.prepare(reports, destination)
    assert (destination / "reports/blocks.json").read_bytes() == data[0]
    assert not (destination / "reports/registries.json").exists()
    assert [source.read_bytes() for source in sources] == data


def test_cli_errors_do_not_print_selected_paths(tmp_path, capsys):
    missing = tmp_path / "private-selected-folder"
    assert preparation.main(["--reports", str(missing),
                             "--destination", str(tmp_path / "output")]) == 1
    output = capsys.readouterr().out
    assert "private-selected-folder" not in output
    assert '"reason":"reference_io_unavailable"' in output


def test_checked_in_metadata_matches_exact_pins():
    metadata = preparation.ROOT / "docs/compatibility"
    names = ["java-1201-registry-producer-receipt.json",
             "java-geometry-reference-evidence.json"]
    for name, (_, size, digest) in zip(names, preparation.FILES[2:]):
        assert preparation.read_pinned(metadata / name, size, digest)
