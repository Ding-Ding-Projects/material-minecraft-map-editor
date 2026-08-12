"""The universal local file converter.

A guided, entirely local pipeline that detects a source file's real format
from its bytes (never trusts the extension), offers only the targets a
documented adapter can genuinely produce, converts through a bounded,
least-privileged sandbox, validates the result before it is ever offered, and
never touches or overwrites the original file.

Submodules
----------
``signatures``
    Bounded byte-signature detection -- the thing an extension cannot be
    trusted to say.
``registry``
    The adapter registry: every adapter this build ships, and what it
    declares about itself (lossiness, metadata handling, limits).
``sandbox``
    Runs one adapter call in an isolated child process with bounded time,
    input size and output size, and reports cancellation and failure
    honestly instead of guessing.
``adapters``
    The adapter implementations themselves.
``core``
    ``convert_one`` / ``convert_batch`` -- the orchestration a UI calls, plus
    the local conversion history record.
"""

from amulet_map_editor.api.converter.registry import (
    Adapter,
    ADAPTERS,
    adapters_for_source,
    get_adapter,
)
from amulet_map_editor.api.converter.signatures import detect_format
from amulet_map_editor.api.converter.core import (
    BatchOutcome,
    BatchResult,
    ConvertOutcome,
    ConvertResult,
    convert_batch,
    convert_one,
)

__all__ = [
    "Adapter",
    "ADAPTERS",
    "adapters_for_source",
    "get_adapter",
    "detect_format",
    "BatchOutcome",
    "BatchResult",
    "ConvertOutcome",
    "ConvertResult",
    "convert_batch",
    "convert_one",
]
