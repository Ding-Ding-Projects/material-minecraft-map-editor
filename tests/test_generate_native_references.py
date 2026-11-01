"""Bounded report-generation orchestration; no server execution in this suite."""
from pathlib import Path
import hashlib
import json
import sys
import time

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import generate_native_references as generation


def test_runner_captures_real_child_output(tmp_path):
    log = tmp_path / "output.log"
    code = generation.run_bounded([sys.executable, "-I", "-S", "-c", "print('observed')"],
                                  tmp_path, log, 5)
    assert code == 0
    assert log.read_bytes().strip() == b"observed"


def test_runner_output_limit_never_writes_excess(tmp_path, monkeypatch):
    monkeypatch.setattr(generation, "MAX_LOG", 32)
    log = tmp_path / "output.log"
    with pytest.raises(generation.GenerationError, match="generator_output_limit"):
        generation.run_bounded([sys.executable, "-I", "-S", "-c",
                                "import sys;sys.stdout.write('x'*1000);sys.stdout.flush()"],
                               tmp_path, log, 5)
    assert log.read_bytes() == b"x" * 32


def test_runner_timeout_waits_for_owned_child_exit(tmp_path):
    start = time.monotonic()
    with pytest.raises(generation.GenerationError, match="generator_timeout"):
        generation.run_bounded([sys.executable, "-I", "-S", "-c",
                                "import time;print('started',flush=True);time.sleep(30)"],
                               tmp_path, tmp_path / "output.log", 0.1)
    assert time.monotonic() - start < 6


def test_process_environment_excludes_java_injection(monkeypatch):
    monkeypatch.setenv("JAVA_TOOL_OPTIONS", "fixture-not-forwarded")
    monkeypatch.setenv("JDK_JAVA_OPTIONS", "fixture-not-forwarded")
    monkeypatch.setenv("UNRELATED_TEST_VALUE", "fixture-not-forwarded")
    environment = generation.process_environment()
    assert not {"JAVA_TOOL_OPTIONS", "JDK_JAVA_OPTIONS", "UNRELATED_TEST_VALUE"} & environment.keys()


@pytest.fixture
def selected(tmp_path, monkeypatch):
    java = tmp_path / "java.exe"
    java.write_bytes(b"fixture executable; never run")
    archive = tmp_path / "input.jar"
    archive.write_bytes(b"pinned archive fixture")
    monkeypatch.setattr(generation, "SERVER_SIZE", archive.stat().st_size)
    monkeypatch.setattr(generation, "SERVER_SHA256", hashlib.sha256(archive.read_bytes()).hexdigest())
    return java, archive, tmp_path / "work", tmp_path / "profile"


@pytest.mark.parametrize("index", [2, 3])
def test_existing_output_prevents_execution(selected, monkeypatch, index):
    selected[index].mkdir()
    sentinel = selected[index] / "keep"
    sentinel.write_bytes(b"retain")
    monkeypatch.setattr(generation, "run_bounded", lambda *args: pytest.fail("must not execute"))
    with pytest.raises(generation.GenerationError, match="output_exists"):
        generation.generate(*selected)
    assert sentinel.read_bytes() == b"retain"


def test_bad_archive_prevents_work_creation(selected, monkeypatch):
    selected[1].write_bytes(b"not the pinned archive")
    monkeypatch.setattr(generation, "run_bounded", lambda *args: pytest.fail("must not execute"))
    with pytest.raises(generation.PreparationError):
        generation.generate(*selected)
    assert not selected[2].exists()


def test_original_run_receipt_is_not_relabelled(selected, monkeypatch):
    def observed(command, directory, log, timeout):
        if command[-1] == "-version":
            log.write_bytes(b'openjdk version "17.0.19"\n')
        else:
            assert command[1:] == generation.GENERATOR_ARGS
            log.write_bytes(b"fixture observed completion\n")
        return 0

    monkeypatch.setattr(generation, "run_bounded", observed)
    monkeypatch.setattr(generation, "prepare", lambda source, dest: {
        "status": "prepared", "generatorExecuted": False,
        "worldCompatibilityVerified": False})
    result = generation.generate(*selected)
    pending = json.loads((selected[2] / "generation-receipt.json").read_text())
    complete = json.loads((selected[2] / "preparation-receipt.json").read_text())
    assert pending["exitCode"] == 0 and pending["reportVerification"] == "pending"
    assert complete["reportVerification"] == "passed"
    assert result["generatorExecuted"] and not result["worldCompatibilityVerified"]
    assert not result["serverStarted"] and not result["licenceAccepted"]


def test_failed_generator_cannot_prepare(selected, monkeypatch):
    def observed(command, directory, log, timeout):
        log.write_bytes(b'openjdk version "17.0.19"\n')
        return 0 if command[-1] == "-version" else 7
    monkeypatch.setattr(generation, "run_bounded", observed)
    monkeypatch.setattr(generation, "prepare", lambda *args: pytest.fail("must not prepare"))
    with pytest.raises(generation.GenerationError, match="generator_failed"):
        generation.generate(*selected)
    assert json.loads((selected[2] / "generation-receipt.json").read_text())["exitCode"] == 7
    assert not selected[3].exists()
