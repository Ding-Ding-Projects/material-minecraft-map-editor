"""Verify a direct interpreter and validate the bounded worker protocol."""

from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

MAX_OUTPUT = 65536


def identity(path):
    return os.path.normcase(str(Path(path).resolve(strict=True)))


@lru_cache(maxsize=1)
def direct_interpreter():
    candidate = Path(getattr(sys, "_base_executable", "")).resolve(strict=True)
    if os.name == "nt":
        # Use the actual installation's windowless executable, not the venv
        # redirector. The probe below verifies it rather than trusting its name.
        candidate = candidate.with_name("pythonw.exe").resolve(strict=True)
    if not candidate.is_file():
        raise ValueError("Direct Python interpreter unavailable")
    code = "import json,os,sys;print(json.dumps({'pid':os.getpid(),'executable':sys.executable,'version':list(sys.version_info[:3])}))"
    process = subprocess.Popen([str(candidate), "-I", "-S", "-c", code],
                               stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    try:
        stdout, stderr = process.communicate(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate(timeout=3)
        raise ValueError("Direct interpreter verification timed out")
    if process.returncode != 0 or stderr or len(stdout) > 4096:
        raise ValueError("Direct interpreter verification failed")
    facts = json.loads(stdout)
    if (type(facts.get("pid")) is not int or facts["pid"] != process.pid
            or identity(facts.get("executable", "")) != identity(candidate)
            or facts.get("version") != list(sys.version_info[:3])):
        raise ValueError("Interpreter is not the verified direct process")
    return {"path": str(candidate), "identity": identity(candidate),
            "sha256": hashlib.sha256(candidate.read_bytes()).hexdigest(),
            "version": list(sys.version_info[:3]), "verificationPid": process.pid}


class WorkerOutput:
    def __init__(self):
        self.total = 0
        self.data = bytearray()

    def append(self, data):
        self.total += len(data)
        if self.total > MAX_OUTPUT:
            raise ValueError("Regex output exceeds 64 KiB")
        self.data.extend(data)

    def take_hello(self):
        if b"\n" not in self.data:
            if len(self.data) > 4096:
                raise ValueError("Regex identity response exceeds limit")
            return None
        line, _, remaining = self.data.partition(b"\n")
        self.data = bytearray(remaining)
        return json.loads(line)


def validate_result(result, items, sample, engine_version):
    if not isinstance(result, dict):
        raise ValueError("Invalid regex response object")
    if set(result) == {"error"}:
        if not isinstance(result["error"], str) or len(result["error"]) > 300:
            raise ValueError("Invalid regex error response")
        raise ValueError(result["error"])
    if set(result) != {"indices", "matches", "engine"} or result["engine"] != engine_version:
        raise ValueError("Invalid regex response fields or engine version")
    indices, matches = result["indices"], result["matches"]
    if (not isinstance(indices, list) or len(indices) > len(items)
            or any(type(i) is not int or not 0 <= i < len(items) for i in indices)
            or indices != sorted(set(indices))):
        raise ValueError("Invalid regex result indices")
    if not isinstance(matches, list) or len(matches) > 64:
        raise ValueError("Invalid regex sample matches")
    previous = -1
    for match in matches:
        if not isinstance(match, dict) or set(match) != {"start", "end", "text"}:
            raise ValueError("Invalid regex match shape")
        start, end = match["start"], match["end"]
        if (type(start) is not int or type(end) is not int or not 0 <= start <= end <= len(sample)
                or start < previous or not isinstance(match["text"], str)
                or match["text"] != sample[start:end][:160]):
            raise ValueError("Invalid regex match bounds or text")
        previous = start
    return indices, matches
