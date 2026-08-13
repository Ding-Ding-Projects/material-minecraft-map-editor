"""The sidecar's stdio loop: reads requests, dispatches them, writes responses.

Run as a script (``python -m amulet_map_editor.api.sidecar``) this becomes
the child process an Electron main process spawns and supervises. It never
writes anything to stdout except one JSON response line per request; nothing
else may share that stream, or the host's line-delimited reader breaks.
"""

from __future__ import annotations

import io
import sys
import threading
import traceback
from typing import Any, Dict, Optional, TextIO

from amulet_map_editor.api.sidecar.methods import METHODS
from amulet_map_editor.api.sidecar.protocol import (
    DEFAULT_TIMEOUT_SECONDS,
    ERR_INTERNAL,
    ERR_TIMEOUT,
    ERR_UNKNOWN_METHOD,
    ERR_VERSION_MISMATCH,
    PROTOCOL_VERSION,
    ProtocolError,
    Request,
    encode_error,
    encode_result,
    parse_request,
)


class _TimedCall:
    """Runs a handler on a daemon thread and reports whether it finished.

    A handler that genuinely hangs must not hang the whole sidecar: the
    calling thread gives up after ``timeout_seconds`` and reports
    :data:`ERR_TIMEOUT` while the stuck thread is abandoned as a daemon (it
    cannot keep the process alive, and it will never get a response written
    for it since the id has already been answered).
    """

    def __init__(self, timeout_seconds: float):
        self._timeout_seconds = timeout_seconds

    def run(self, handler, params: Dict[str, Any]):
        result: Dict[str, Any] = {}

        def _target() -> None:
            try:
                result["value"] = handler(params)
            except BaseException as exc:  # noqa: BLE001 - reported, not re-raised here
                result["exc"] = exc

        thread = threading.Thread(target=_target, daemon=True)
        thread.start()
        thread.join(self._timeout_seconds)
        if thread.is_alive():
            raise ProtocolError(
                ERR_TIMEOUT,
                f"Handler did not finish within {self._timeout_seconds:.0f}s",
            )
        if "exc" in result:
            raise result["exc"]
        return result.get("value")


def dispatch(request: Request, timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS) -> str:
    """Handle one parsed :class:`Request` and return the response line."""
    if request.protocol_version != PROTOCOL_VERSION:
        return encode_error(
            request.id,
            ERR_VERSION_MISMATCH,
            (
                f"Caller speaks protocol version {request.protocol_version}, "
                f"sidecar speaks {PROTOCOL_VERSION}"
            ),
        )

    handler = METHODS.get(request.method)
    if handler is None:
        return encode_error(
            request.id, ERR_UNKNOWN_METHOD, f"No such method: {request.method!r}"
        )

    try:
        result = _TimedCall(timeout_seconds).run(handler, request.params)
    except ProtocolError as exc:
        return encode_error(request.id, exc.code, exc.message)
    except Exception:
        # Never leak a traceback (which can quote source paths, environment
        # detail, or -- worse -- a value under discussion) onto the wire.
        # The full traceback still goes to stderr for local diagnosis.
        print(
            f"[sidecar] unhandled exception in {request.method!r}:\n"
            + traceback.format_exc(),
            file=sys.stderr,
        )
        return encode_error(
            request.id, ERR_INTERNAL, "The sidecar failed to handle that request"
        )

    return encode_result(request.id, result)


def handle_line(
    line: str, timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
) -> Optional[str]:
    """Parse and dispatch one input line; ``None`` for a blank line."""
    line = line.rstrip("\r\n")
    if not line:
        return None
    try:
        request = parse_request(line)
    except ProtocolError as exc:
        # A request that failed to parse has no reliable id; reply with
        # ``None`` so the caller still receives a keyed response rather than
        # nothing, and the caller's own request tracking can time it out --
        # id is intentionally null here, distinct from any real request id.
        return encode_error(None, exc.code, exc.message)
    return dispatch(request, timeout_seconds=timeout_seconds)


def serve(
    in_stream: TextIO = sys.stdin,
    out_stream: TextIO = sys.stdout,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> None:
    """Run the read-dispatch-write loop until stdin closes."""
    for line in in_stream:
        response = handle_line(line, timeout_seconds=timeout_seconds)
        if response is None:
            continue
        out_stream.write(response + "\n")
        out_stream.flush()


def main() -> None:
    # Force UTF-8, newline-normalized text streams regardless of the host
    # platform's console code page -- Windows in particular can default a
    # child process's stdio to a legacy code page that mangles non-ASCII
    # display names and Cantonese copy round-tripping through this pipe.
    stdin = io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8", newline="\n")
    stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", newline="\n")
    serve(in_stream=stdin, out_stream=stdout)


if __name__ == "__main__":
    main()
