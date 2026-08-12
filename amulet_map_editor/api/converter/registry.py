"""The documented adapter registry.

Every adapter this build ships is one entry here, and nothing is offered to
a user that is not in this list. Each entry declares, in one place, exactly
what the shared instructions require an adapter to declare: its source
signatures, its target format, a localized display name, what it does to
metadata/encoding, whether it is lossy, its resource limits, and the
validator that must accept its output before that output is ever shown.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional, Sequence, Tuple

from amulet_map_editor.api.converter import adapters
from amulet_map_editor.api.converter.signatures import display_name as _fmt_name


@dataclass(frozen=True)
class Limits:
    """Resource bounds enforced by the sandbox around one adapter call."""

    max_input_bytes: int = 32 * 1024 * 1024
    max_output_bytes: int = 64 * 1024 * 1024
    timeout_seconds: float = 20.0
    #: Pixels, pages, frames, or top-level items -- whatever unit the
    #: adapter itself bounds internally (images use it as a pixel cap).
    max_items: int = 64_000_000


@dataclass(frozen=True)
class Adapter:
    #: Stable id, e.g. ``"json_to_gzip_nbt"``.
    id: str
    #: The detected source format id this adapter accepts (see
    #: :mod:`signatures`).
    source_format: str
    #: The format id this adapter produces.
    target_format: str
    #: What a user sees for this conversion, already bilingual-labelled by
    #: the calling surface via its own language-mode copy; this is the
    #: factual (English) label the surface localises around.
    display_name: str
    #: Pure ``bytes -> bytes`` implementation, run inside the sandbox.
    convert: Callable[[bytes], bytes]
    #: Whether this conversion can lose information, and what.
    lossy: bool
    loss_disclosure: str
    #: What happens to metadata/encoding on this conversion.
    metadata_behaviour: str
    #: A second pure function that must return True for the adapter's own
    #: output before that output is offered to the user.
    validate_output: Callable[[bytes], bool]
    limits: Limits = field(default_factory=Limits)


def _valid_nbt_json(data: bytes) -> bool:
    import json

    try:
        doc = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return False
    return isinstance(doc, dict) and "root" in doc and "__nbt_root_name__" in doc


def _valid_gzip_nbt(data: bytes) -> bool:
    try:
        adapters.nbt_to_json(data, compressed=True)
    except ValueError:
        return False
    return True


def _valid_nbt(data: bytes) -> bool:
    try:
        adapters.nbt_to_json(data, compressed=False)
    except ValueError:
        return False
    return True


def _valid_image(target: str):
    magic = {
        "png": b"\x89PNG\r\n\x1a\n",
        "jpeg": b"\xff\xd8\xff",
        "bmp": b"BM",
        "gif": b"GIF",
    }[target]

    def _check(data: bytes) -> bool:
        return data.startswith(magic)

    return _check


def _pair(source: str, target: str, lossy: bool, disclosure: str) -> Adapter:
    return Adapter(
        id=f"image_{source}_to_{target}",
        source_format=source,
        target_format=target,
        display_name=f"{_fmt_name(source)} → {_fmt_name(target)}",
        convert=adapters.make_image_adapter(target),
        lossy=lossy,
        loss_disclosure=disclosure,
        metadata_behaviour=(
            "EXIF/ICC metadata and animation frames beyond the first are not "
            "carried across; pixel colour data is preserved."
        ),
        validate_output=_valid_image(target),
        limits=Limits(),
    )


_IMAGE_FORMATS: Tuple[str, ...] = ("png", "jpeg", "bmp", "gif")

_IMAGE_LOSS = {
    "jpeg": "Recompresses with lossy quantisation; transparency is flattened onto white.",
    "png": "Lossless pixel data; palette/animation source frames beyond the first are dropped.",
    "bmp": "Lossless pixel data; alpha and any animation beyond the first frame are dropped.",
    "gif": "Reduces to a 256-colour palette and drops full alpha to binary transparency.",
}


def _build_image_adapters() -> Tuple[Adapter, ...]:
    out = []
    for source in _IMAGE_FORMATS:
        for target in _IMAGE_FORMATS:
            if source == target:
                continue
            lossy = target in ("jpeg", "gif") or source in ("jpeg", "gif")
            out.append(_pair(source, target, lossy, _IMAGE_LOSS[target]))
    return tuple(out)


ADAPTERS: Tuple[Adapter, ...] = (
    Adapter(
        id="gzip_nbt_to_json",
        source_format="gzip_nbt",
        target_format="json",
        display_name="Compressed NBT → JSON",
        convert=adapters.gzip_nbt_to_json,
        lossy=False,
        loss_disclosure=(
            "None: every NBT tag's exact type and value is preserved in the "
            "JSON representation, so converting back reproduces the original."
        ),
        metadata_behaviour="The root tag's name and gzip framing are recorded in the JSON so a round trip is exact.",
        validate_output=_valid_nbt_json,
        limits=Limits(max_input_bytes=64 * 1024 * 1024, timeout_seconds=30.0),
    ),
    Adapter(
        id="json_to_gzip_nbt",
        source_format="json",
        target_format="gzip_nbt",
        display_name="JSON → Compressed NBT",
        convert=adapters.json_to_gzip_nbt,
        lossy=False,
        loss_disclosure=(
            "None for JSON produced by this converter's own NBT export. "
            "Hand-written JSON must use the {'type', 'value'} tag shape or "
            "conversion is refused rather than guessing NBT types."
        ),
        metadata_behaviour="Recompresses with gzip; the declared root tag name is restored exactly.",
        validate_output=_valid_gzip_nbt,
        limits=Limits(max_input_bytes=64 * 1024 * 1024, timeout_seconds=30.0),
    ),
    Adapter(
        id="nbt_to_json",
        source_format="nbt",
        target_format="json",
        display_name="Uncompressed NBT → JSON",
        convert=adapters.nbt_uncompressed_to_json,
        lossy=False,
        loss_disclosure="None: exact type-preserving round trip, as with compressed NBT.",
        metadata_behaviour="The root tag's name is recorded in the JSON.",
        validate_output=_valid_nbt_json,
        limits=Limits(max_input_bytes=64 * 1024 * 1024, timeout_seconds=30.0),
    ),
    Adapter(
        id="json_to_nbt",
        source_format="json",
        target_format="nbt",
        display_name="JSON → Uncompressed NBT",
        convert=adapters.json_to_nbt_uncompressed,
        lossy=False,
        loss_disclosure="None for JSON produced by this converter's own NBT export.",
        metadata_behaviour="Writes uncompressed NBT with the declared root tag name restored.",
        validate_output=_valid_nbt,
        limits=Limits(max_input_bytes=64 * 1024 * 1024, timeout_seconds=30.0),
    ),
) + _build_image_adapters()


def adapters_for_source(source_format: Optional[str]) -> Sequence[Adapter]:
    """Every adapter this build can offer for a detected source format."""
    if source_format is None:
        return ()
    return tuple(a for a in ADAPTERS if a.source_format == source_format)


def get_adapter(adapter_id: str) -> Optional[Adapter]:
    for a in ADAPTERS:
        if a.id == adapter_id:
            return a
    return None
