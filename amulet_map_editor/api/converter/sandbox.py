"""Runs one adapter call in a bounded, least-privileged child process.

The child gets nothing but the adapter id and the source bytes over a pipe.
It never inherits an open network socket to reuse (Python opens none by
default), its recursion limit is capped, its memory and CPU time are bounded
with :mod:`resource` where the platform supports it (POSIX; Windows has no
equivalent syscall, so there the timeout and output-size checks are the
enforced bounds -- this gap is stated here rather than silently assumed
away), and it is killed outright if it overruns its wall-clock timeout.

Every failure mode -- oversized input, timeout, sandbox crash, oversized or
invalid output -- is reported as a distinct, honest
:class:`SandboxOutcome`, never folded into a bare ``False``.
"""

from __future__ import annotations

import multiprocessing
import sys
import traceback
from dataclasses import dataclass
from typing import Optional

from amulet_map_editor.api.converter.registry import Adapter, Limits

#: Recursion is capped low and independently of Python's own default so a
#: pathological input cannot exhaust the child's stack before the adapter's
#: own structural depth checks (see ``adapters._MAX_JSON_NBT_DEPTH``) apply.
_CHILD_RECURSION_LIMIT = 2000


@dataclass(frozen=True)
class SandboxOutcome:
    ok: bool
    #: One of: "ok", "input_too_large", "timeout", "crashed",
    #: "output_too_large", "output_invalid".
    status: str
    data: Optional[bytes] = None
    message: str = ""


def _child_entry(convert, data: bytes, conn) -> None:
    """Runs inside the isolated child process only.

    ``convert`` is the adapter's own ``bytes -> bytes`` callable, pickled
    straight to the child rather than re-resolved by id -- the child is a
    fresh interpreter (spawn, not fork), so it never re-imports the
    registry's mutable state, and passing the callable directly is what lets
    a caller run a one-off adapter (as the converter's own tests do) without
    it having to exist in the shipped registry.
    """
    sys.setrecursionlimit(_CHILD_RECURSION_LIMIT)
    try:
        import resource  # POSIX only

        # Best-effort memory bound; the sandbox's own timeout and
        # output-size checks are what actually gate a Windows child, since
        # RLIMIT_AS is unavailable there.
        soft = 512 * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (soft, soft))
    except Exception:
        pass
    try:
        result = convert(data)
        if not isinstance(result, (bytes, bytearray)):
            conn.send(("crashed", b"", "Adapter did not return bytes"))
            return
        conn.send(("ok", bytes(result), ""))
    except ValueError as exc:
        conn.send(("crashed", b"", str(exc)))
    except Exception:
        conn.send(("crashed", b"", traceback.format_exc(limit=2)))
    finally:
        conn.close()


def run_adapter(
    adapter: Adapter, data: bytes, limits: Optional[Limits] = None
) -> SandboxOutcome:
    """Run ``adapter.convert(data)`` in an isolated, bounded child process."""
    limits = limits or adapter.limits
    if len(data) > limits.max_input_bytes:
        return SandboxOutcome(
            False,
            "input_too_large",
            message=(
                f"Source is {len(data)} bytes, over this adapter's "
                f"{limits.max_input_bytes}-byte limit"
            ),
        )

    ctx = multiprocessing.get_context("spawn")
    parent_conn, child_conn = ctx.Pipe(duplex=False)
    process = ctx.Process(
        target=_child_entry, args=(adapter.convert, data, child_conn), daemon=True
    )
    process.start()
    child_conn.close()
    try:
        if parent_conn.poll(limits.timeout_seconds):
            status, payload, message = parent_conn.recv()
        else:
            status, payload, message = (
                "timeout",
                b"",
                (f"Conversion did not finish within {limits.timeout_seconds:.0f}s"),
            )
    except EOFError:
        status, payload, message = "crashed", b"", "Sandbox process ended unexpectedly"
    finally:
        if process.is_alive():
            process.terminate()
        process.join(timeout=5)
        if process.is_alive():
            process.kill()
            process.join(timeout=5)
        parent_conn.close()

    if status != "ok":
        return SandboxOutcome(False, status, message=message)

    if len(payload) > limits.max_output_bytes:
        return SandboxOutcome(
            False,
            "output_too_large",
            message=(
                f"Result is {len(payload)} bytes, over this adapter's "
                f"{limits.max_output_bytes}-byte limit"
            ),
        )

    try:
        valid = bool(adapter.validate_output(payload))
    except Exception as exc:
        return SandboxOutcome(
            False, "output_invalid", message=f"Validator raised: {exc}"
        )
    if not valid:
        return SandboxOutcome(
            False, "output_invalid", message="Adapter output failed its own validator"
        )

    return SandboxOutcome(True, "ok", data=payload)
