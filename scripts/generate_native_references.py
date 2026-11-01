"""Generate pinned reports with an explicitly selected trusted Java runtime.

This invokes the official data-generator entrypoint, not the game server.
It never downloads, accepts a licence, overwrites output, or removes partial work.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time

from prepare_native_references import PreparationError, prepare, read_pinned, validate_directory

SERVER_SIZE = 47791053
SERVER_SHA256 = "3af73a9dc5a102e38147946360dd27d4d70bae7055bf91cf2151cd5d121b79e0"
MAX_LOG = 2 * 1024 * 1024
GENERATOR_ARGS = ["-Xmx1G", "-DbundlerMainClass=net.minecraft.data.Main",
                  "-jar", "server.jar", "--reports", "--output", "generated"]


class GenerationError(ValueError):
    pass


def process_environment():
    allowed = {"PATH", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC",
               "PATHEXT", "TEMP", "TMP", "LANG", "LC_ALL"}
    # Do not inherit Java argument injection, agent credentials or application
    # configuration variables. This is not an operating-system sandbox.
    return {key: value for key, value in os.environ.items() if key.upper() in allowed}


def run_bounded(command, directory, log, timeout):
    process = subprocess.Popen(command, cwd=directory, env=process_environment(),
                               stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT,
                               creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    errors = []
    finished = threading.Event()

    def drain():
        total = 0
        try:
            with log.open("xb") as output:
                while chunk := process.stdout.read1(65536):
                    remaining = MAX_LOG - total
                    output.write(chunk[:remaining])
                    total += min(len(chunk), remaining)
                    if len(chunk) > remaining:
                        errors.append("generator_output_limit")
                        break
        except OSError:
            errors.append("generator_log_unavailable")
        finally:
            process.stdout.close()
            finished.set()

    reader = threading.Thread(target=drain, daemon=True)
    reader.start()
    deadline = time.monotonic() + timeout
    try:
        while process.poll() is None:
            if errors:
                raise GenerationError(errors[0])
            if time.monotonic() >= deadline:
                raise GenerationError("generator_timeout")
            time.sleep(0.05)
        if not finished.wait(timeout=5):
            raise GenerationError("generator_output_unconfirmed")
        if errors:
            raise GenerationError(errors[0])
        return process.returncode
    finally:
        if process.poll() is None:
            process.kill()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                raise GenerationError("generator_exit_unconfirmed") from None
        if not finished.wait(timeout=5):
            raise GenerationError("generator_output_unconfirmed")


def generate(java: Path, archive: Path, work: Path, destination: Path):
    if not all(path.is_absolute() for path in (java, archive, work, destination)):
        raise GenerationError("absolute_paths_required")
    validate_directory(work.parent)
    validate_directory(destination.parent)
    if any(path.exists() or path.is_symlink() for path in (work, destination)):
        raise GenerationError("output_exists")
    if work == destination or work in destination.parents or destination in work.parents:
        raise GenerationError("output_directories_overlap")
    java_info = java.lstat()
    if java.is_symlink() or not java.is_file() or java_info.st_size > 32 * 1024 * 1024:
        raise GenerationError("java_executable_unavailable")
    archive_bytes = read_pinned(archive, SERVER_SIZE, SERVER_SHA256)
    work.mkdir(exist_ok=False)
    copied_archive = work / "server.jar"
    with copied_archive.open("xb") as output:
        output.write(archive_bytes)
    read_pinned(copied_archive, SERVER_SIZE, SERVER_SHA256)
    version_log = work / "java-version.log"
    if run_bounded([str(java), "-version"], work, version_log, 10) != 0:
        raise GenerationError("java_version_unavailable")
    if not re.search(rb'\bversion "17\.0\.19"', version_log.read_bytes()):
        raise GenerationError("java_version_mismatch")
    generation_log = work / "generation.log"
    code = run_bounded([str(java), *GENERATOR_ARGS], work, generation_log, 120)
    receipt = {"schemaVersion": 1, "release": "1.20.1", "dataVersion": 3465,
               "serverSha256": SERVER_SHA256, "javaVersion": "17.0.19",
               "arguments": GENERATOR_ARGS, "exitCode": code,
               "logSha256": hashlib.sha256(generation_log.read_bytes()).hexdigest(),
               "generationTimestamp": None, "reportVerification": "pending",
               "serverStarted": False, "licenceAccepted": False}
    with (work / "generation-receipt.json").open("x", encoding="utf-8", newline="\n") as output:
        json.dump(receipt, output, indent=2)
        output.write("\n")
    if code != 0:
        raise GenerationError("generator_failed")
    result = prepare(work / "generated/reports", destination)
    # Keep the original execution record unchanged; completion is a separate
    # record, not a rewrite of an earlier pending verdict.
    with (work / "preparation-receipt.json").open("x", encoding="utf-8", newline="\n") as output:
        json.dump({"schemaVersion": 1, "reportVerification": "passed", **result}, output, indent=2)
        output.write("\n")
    return {**result, "generatorExecuted": True, "serverStarted": False,
            "licenceAccepted": False, "newExecutionReceiptRetained": True}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--java", required=True, type=Path,
                        help="Explicit trusted existing Java 17.0.19 executable")
    parser.add_argument("--server-archive", required=True, type=Path)
    parser.add_argument("--work-directory", required=True, type=Path)
    parser.add_argument("--destination", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        result = generate(args.java, args.server_archive, args.work_directory, args.destination)
    except (GenerationError, PreparationError) as error:
        result = {"status": "unavailable", "reason": str(error), "partialOutputMayExist": True}
    except KeyboardInterrupt:
        result = {"status": "unavailable", "reason": "cancelled_result_unconfirmed",
                  "partialOutputMayExist": True}
    except OSError:
        result = {"status": "unavailable", "reason": "generation_io_unavailable",
                  "partialOutputMayExist": True}
    print(json.dumps(result, separators=(",", ":")))
    return 0 if result["status"] == "prepared" else 1


if __name__ == "__main__":
    sys.exit(main())
