"""Bounded protocol framing, independent of the GUI runtime."""

import json
import os
from pathlib import Path

MAX_FRAME = 1024 * 1024


def world_identity(path: str) -> str:
    return os.path.normcase(str(Path(path).resolve(strict=True)))


def encode_request(identifier: str, method: str, params: dict | None = None) -> bytes:
    data = json.dumps({"version": 1, "id": identifier, "method": method,
                       "params": params or {}}, ensure_ascii=False).encode("utf-8")
    if not 0 < len(data) <= MAX_FRAME:
        raise ValueError("Request exceeds frame limit")
    return len(data).to_bytes(4, "big") + data


class Decoder:
    def __init__(self, max_frame=MAX_FRAME):
        self.buffer = bytearray()
        self.max_frame = max_frame
        self.last_frame_sizes = []

    def feed(self, data: bytes) -> list[dict]:
        self.last_frame_sizes = []
        # The transport supplies bounded chunks. A peer cannot build an
        # unlimited backlog of completed or incomplete frames here.
        if len(self.buffer) + len(data) > self.max_frame + 4:
            raise ValueError("Response buffer exceeds limit")
        self.buffer.extend(data)
        result = []
        while len(self.buffer) >= 4:
            length = int.from_bytes(self.buffer[:4], "big")
            if not 0 < length <= self.max_frame:
                raise ValueError("Invalid response frame length")
            if len(self.buffer) < length + 4:
                break
            payload = bytes(self.buffer[4:length + 4])
            del self.buffer[:length + 4]
            response = json.loads(payload)
            if (not isinstance(response, dict) or type(response.get("version")) is not int
                    or response.get("version") != 1):
                raise ValueError("Invalid response envelope")
            if ("result" in response) == ("error" in response):
                raise ValueError("Expected exactly one response outcome")
            result.append(response)
            self.last_frame_sizes.append(length)
        return result


def accepts_reply(reply: dict, expected: str, generation: int,
                  current_generation: int, identity: str, current_identity: str) -> bool:
    return (reply.get("id") == expected and generation == current_generation
            and identity == current_identity)


def probe_facts(result: dict) -> dict:
    if not isinstance(result, dict) or result.get("edition") != "java":
        raise ValueError("Engine did not report a Java world")
    version = result.get("dataVersion")
    if version is not None and (not isinstance(version, int) or isinstance(version, bool)):
        raise ValueError("Invalid world data version")
    if result.get("readOnly") is not True or result.get("editingSupported") is not False:
        raise ValueError("Unexpected editing capability from read-only probe")
    if result.get("versionSupport") != "structural-probe-only":
        raise ValueError("Unsupported probe capability contract")
    return {"edition": "Java", "dataVersion": "Unavailable" if version is None else str(version),
            "support": "Structural metadata only", "editing": "Unavailable"}
