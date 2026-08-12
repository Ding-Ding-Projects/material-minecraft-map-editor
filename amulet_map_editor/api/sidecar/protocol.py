"""The versioned, newline-delimited JSON wire protocol.

One line of JSON in, one line of JSON out. A request carries an ``id``, a
``method`` and ``params``; a response carries the same ``id`` and either a
``result`` or a structured ``error`` -- never a crash, never a bare string,
never an unhandled exception serialized as a stack trace to a caller.

The protocol is versioned so a mismatched sidecar and host are reported as a
structured error rather than guessed at or silently misinterpreted. Bump
:data:`PROTOCOL_VERSION` whenever a request or response shape changes in a
way that is not purely additive.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

#: Bumped on any breaking change to the request/response shape below.
PROTOCOL_VERSION = 1

#: The longest single line (request or response) this protocol will parse or
#: emit, in bytes of UTF-8 encoded JSON. A message over this bound is
#: rejected before it is ever decoded, so a hostile or corrupt sender cannot
#: force an unbounded ``json.loads`` call.
MAX_MESSAGE_BYTES = 8 * 1024 * 1024

#: How long the server will run a single request's handler before reporting
#: a timeout error instead. Handlers here are local, in-process reads and
#: writes (preferences, language, the converter's own format catalog) so a
#: generous-but-bounded ceiling catches a genuinely hung handler without
#: punishing a slow disk.
DEFAULT_TIMEOUT_SECONDS = 10.0

#: Structured error codes. A caller can branch on these without parsing the
#: (bilingual-unaware, English-only, deliberately internal) message text.
ERR_INVALID_MESSAGE = "invalid_message"
ERR_MESSAGE_TOO_LARGE = "message_too_large"
ERR_VERSION_MISMATCH = "version_mismatch"
ERR_UNKNOWN_METHOD = "unknown_method"
ERR_INVALID_PARAMS = "invalid_params"
ERR_TIMEOUT = "timeout"
ERR_INTERNAL = "internal_error"


class ProtocolError(Exception):
    """A structured error to report back to the caller as ``error``.

    Raising this from inside a method handler is the sanctioned way to
    report a well-understood failure (bad params, out-of-range value); any
    other exception is caught by the dispatcher and reported as
    :data:`ERR_INTERNAL` with no traceback leaked to the wire.
    """

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class Request:
    id: Any
    method: str
    params: Dict[str, Any] = field(default_factory=dict)
    protocol_version: int = PROTOCOL_VERSION


def parse_request(line: str) -> Request:
    """Parse one line of input into a :class:`Request`.

    Raises :class:`ProtocolError` for anything that is not a well-shaped
    request -- never lets a malformed line reach ``json.loads`` unbounded,
    never lets a missing field surface as a raw ``KeyError``.
    """
    encoded = line.encode("utf-8", errors="replace")
    if len(encoded) > MAX_MESSAGE_BYTES:
        raise ProtocolError(
            ERR_MESSAGE_TOO_LARGE,
            f"Request is {len(encoded)} bytes, over the {MAX_MESSAGE_BYTES}-byte limit",
        )
    try:
        payload = json.loads(line)
    except json.JSONDecodeError as exc:
        raise ProtocolError(ERR_INVALID_MESSAGE, f"Request was not valid JSON: {exc}")

    if not isinstance(payload, dict):
        raise ProtocolError(ERR_INVALID_MESSAGE, "Request must be a JSON object")

    if "id" not in payload:
        raise ProtocolError(ERR_INVALID_MESSAGE, "Request is missing an 'id' field")
    method = payload.get("method")
    if not isinstance(method, str) or not method:
        raise ProtocolError(ERR_INVALID_MESSAGE, "Request is missing a 'method' string")
    params = payload.get("params", {})
    if params is None:
        params = {}
    if not isinstance(params, dict):
        raise ProtocolError(ERR_INVALID_MESSAGE, "Request 'params' must be an object")

    protocol_version = payload.get("protocol_version", PROTOCOL_VERSION)
    if not isinstance(protocol_version, int):
        raise ProtocolError(
            ERR_INVALID_MESSAGE, "Request 'protocol_version' must be an integer"
        )

    return Request(
        id=payload["id"],
        method=method,
        params=params,
        protocol_version=protocol_version,
    )


def encode_result(request_id: Any, result: Any) -> str:
    return json.dumps(
        {"id": request_id, "protocol_version": PROTOCOL_VERSION, "result": result},
        ensure_ascii=False,
    )


def encode_error(request_id: Any, code: str, message: str) -> str:
    return json.dumps(
        {
            "id": request_id,
            "protocol_version": PROTOCOL_VERSION,
            "error": {"code": code, "message": message},
        },
        ensure_ascii=False,
    )
