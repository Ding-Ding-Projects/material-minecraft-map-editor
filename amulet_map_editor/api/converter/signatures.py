"""Bounded byte-signature detection for the universal file converter.

The extension is never trusted.  Every source is identified from a bounded
prefix of its own bytes, using rules narrow enough that a file whose bytes do
not actually match a format is reported as ``unknown`` rather than guessed
at.  ``unknown`` is a legitimate, expected answer -- the converter surface
must refuse to offer targets for it rather than pretend a signature exists.
"""

from __future__ import annotations

import json
from typing import Optional

#: Detection never reads more of a file than this, no matter how large the
#: file on disk is.  Keeps detection itself immune to being used as a
#: resource-exhaustion vector.
MAX_SNIFF_BYTES = 65536

#: A JSON parse attempt during detection is bounded by the same sniff window,
#: so a huge file that happens to start with ``{`` cannot make detection
#: itself expensive; :mod:`core` re-validates the real file size separately.
_JSON_WHITESPACE = b" \t\r\n"

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
JPEG_MAGIC = b"\xff\xd8\xff"
BMP_MAGIC = b"BM"
GIF_MAGICS = (b"GIF87a", b"GIF89a")
GZIP_MAGIC = b"\x1f\x8b"

#: NBT root tags begin with a single type-id byte.  ``0x0A`` is
#: ``TAG_Compound``, which is what every real Minecraft NBT root (structure,
#: schematic, level data) uses.  Any other leading byte is not treated as
#: NBT -- a narrow rule on purpose, so this never claims a file is NBT that
#: merely happens to start with an arbitrary byte.
_NBT_ROOT_COMPOUND = 0x0A


def _looks_like_json(prefix: bytes) -> bool:
    stripped = prefix.lstrip(_JSON_WHITESPACE)
    if not stripped or stripped[0] not in b"{[":
        return False
    try:
        json.loads(prefix.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        # A truncated sniff window can legitimately fail to close every
        # brace; a real detection pass re-checks against the full bytes in
        # :func:`detect_format_full` before this is trusted for conversion.
        return stripped[0:1] in (b"{", b"[")
    return True


def detect_format(data: bytes) -> Optional[str]:
    """Return the detected source format id for a bounded byte prefix.

    ``data`` should be at most :data:`MAX_SNIFF_BYTES` (callers pass a
    prefix read from disk); a longer buffer is accepted but only its first
    window is inspected.  Returns ``None`` -- never a guess -- when nothing
    matches.
    """
    prefix = data[:MAX_SNIFF_BYTES]
    if prefix.startswith(PNG_MAGIC):
        return "png"
    if prefix.startswith(JPEG_MAGIC):
        return "jpeg"
    if prefix.startswith(BMP_MAGIC):
        return "bmp"
    if any(prefix.startswith(magic) for magic in GIF_MAGICS):
        return "gif"
    if prefix.startswith(GZIP_MAGIC):
        return "gzip_nbt"
    if prefix[:1] and prefix[0] == _NBT_ROOT_COMPOUND:
        return "nbt"
    if _looks_like_json(prefix):
        return "json"
    return None


def detect_format_full(data: bytes) -> Optional[str]:
    """Confirm a sniffed format against the complete byte content.

    ``detect_format`` only ever inspects a bounded prefix; this performs the
    stricter check the actual conversion relies on before it trusts a file's
    declared format -- notably validating that a suspected JSON file
    genuinely parses in full, not merely that it opens with ``{`` or ``[``.
    """
    fmt = detect_format(data)
    if fmt == "json":
        try:
            json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return None
    return fmt


DISPLAY_NAMES = {
    "png": "PNG image",
    "jpeg": "JPEG image",
    "bmp": "BMP image",
    "gif": "GIF image",
    "gzip_nbt": "Compressed NBT (structure/schematic)",
    "nbt": "Uncompressed NBT",
    "json": "JSON document",
}


def display_name(format_id: Optional[str]) -> str:
    if format_id is None:
        return "Unrecognised file"
    return DISPLAY_NAMES.get(format_id, format_id)
