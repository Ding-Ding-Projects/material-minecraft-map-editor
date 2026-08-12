"""Pure byte-in/byte-out adapter implementations.

Every function here takes the *complete* source bytes and returns the
*complete* target bytes, or raises :class:`ValueError` naming what was wrong.
Nothing in this module touches a filesystem path, the network, or global
state -- that is what lets :mod:`sandbox` run each one in an isolated child
process with nothing but the bytes it was handed.
"""

from __future__ import annotations

import gzip
import io
import json
from typing import Any, Dict

import amulet_nbt as nbt

#: Adapters refuse to allocate more than this for any single decoded value
#: (an image's pixel buffer, a parsed NBT tree's JSON form). This is a
#: courtesy backstop; the hard bound is enforced by the sandbox around the
#: whole call.
_MAX_JSON_NBT_DEPTH = 512


# ---------------------------------------------------------------------------
# JSON <-> NBT
#
# The JSON representation keeps every NBT tag's type explicit, so the round
# trip is structurally lossless: a byte stays a byte, a list of longs stays a
# list of longs, and re-converting the JSON back to NBT reproduces the
# original tag tree rather than a JSON-native approximation of it (which
# would silently promote every integer tag to a JSON float-or-int and lose
# which NBT type it started as).
# ---------------------------------------------------------------------------

_TAG_TYPE_NAMES = {
    nbt.ByteTag: "byte",
    nbt.ShortTag: "short",
    nbt.IntTag: "int",
    nbt.LongTag: "long",
    nbt.FloatTag: "float",
    nbt.DoubleTag: "double",
    nbt.StringTag: "string",
    nbt.ByteArrayTag: "byte_array",
    nbt.IntArrayTag: "int_array",
    nbt.LongArrayTag: "long_array",
    nbt.ListTag: "list",
    nbt.CompoundTag: "compound",
}
_NAME_TO_CTOR = {v: k for k, v in _TAG_TYPE_NAMES.items()}


def _tag_to_json(tag: Any, depth: int = 0) -> Dict[str, Any]:
    if depth > _MAX_JSON_NBT_DEPTH:
        raise ValueError("NBT structure is nested deeper than this converter allows")
    tag_type = type(tag)
    name = _TAG_TYPE_NAMES.get(tag_type)
    if name is None:
        raise ValueError(f"Unsupported NBT tag type: {tag_type.__name__}")
    if name == "compound":
        return {
            "type": name,
            "value": {
                str(key): _tag_to_json(value, depth + 1) for key, value in tag.items()
            },
        }
    if name == "list":
        return {
            "type": name,
            "value": [_tag_to_json(item, depth + 1) for item in tag],
        }
    if name in ("byte_array", "int_array", "long_array"):
        return {"type": name, "value": [int(v) for v in tag.np_array.tolist()]}
    if name in ("float", "double"):
        return {"type": name, "value": float(tag.py_data)}
    if name == "string":
        return {"type": name, "value": str(tag.py_data)}
    return {"type": name, "value": int(tag.py_data)}


def _json_to_tag(node: Dict[str, Any], depth: int = 0) -> Any:
    if depth > _MAX_JSON_NBT_DEPTH:
        raise ValueError("JSON structure is nested deeper than this converter allows")
    if not isinstance(node, dict) or "type" not in node or "value" not in node:
        raise ValueError("Malformed NBT-as-JSON node: expected {'type', 'value'}")
    tag_name = node["type"]
    ctor = _NAME_TO_CTOR.get(tag_name)
    if ctor is None:
        raise ValueError(f"Unrecognised NBT tag type in JSON: {tag_name!r}")
    value = node["value"]
    if tag_name == "compound":
        if not isinstance(value, dict):
            raise ValueError("Compound tag value must be a JSON object")
        return nbt.CompoundTag(
            {str(k): _json_to_tag(v, depth + 1) for k, v in value.items()}
        )
    if tag_name == "list":
        if not isinstance(value, list):
            raise ValueError("List tag value must be a JSON array")
        return nbt.ListTag([_json_to_tag(v, depth + 1) for v in value])
    if tag_name in ("byte_array", "int_array", "long_array"):
        if not isinstance(value, list):
            raise ValueError(f"{tag_name} value must be a JSON array of integers")
        return ctor(value)
    return ctor(value)


def nbt_to_json(data: bytes, *, compressed: bool) -> bytes:
    """Convert raw NBT bytes to the type-preserving JSON representation."""
    try:
        named_tag = nbt.load(data, compressed=compressed)
    except Exception as exc:  # amulet_nbt raises its own error hierarchy
        raise ValueError(f"Could not parse NBT data: {exc}") from exc
    document = {
        "__nbt_root_name__": named_tag.name,
        "root": _tag_to_json(named_tag.tag),
    }
    return json.dumps(document, indent=2, sort_keys=False).encode("utf-8")


def json_to_nbt(data: bytes, *, compressed: bool) -> bytes:
    """Convert the type-preserving JSON representation back to raw NBT bytes."""
    try:
        document = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValueError(f"Source is not valid JSON: {exc}") from exc
    if not isinstance(document, dict) or "root" not in document:
        raise ValueError(
            "JSON does not carry an NBT root (expected the converter's own "
            "'__nbt_root_name__' / 'root' shape -- arbitrary JSON cannot be "
            "converted to NBT without a declared tag structure)"
        )
    root_name = document.get("__nbt_root_name__", "") or ""
    tag = _json_to_tag(document["root"])
    named_tag = nbt.NamedTag(tag, root_name)
    buffer = io.BytesIO()
    named_tag.save_to(buffer, compressed=compressed)
    return buffer.getvalue()


def gzip_nbt_to_json(data: bytes) -> bytes:
    return nbt_to_json(data, compressed=True)


def json_to_gzip_nbt(data: bytes) -> bytes:
    return json_to_nbt(data, compressed=True)


def nbt_uncompressed_to_json(data: bytes) -> bytes:
    return nbt_to_json(data, compressed=False)


def json_to_nbt_uncompressed(data: bytes) -> bytes:
    return json_to_nbt(data, compressed=False)


# ---------------------------------------------------------------------------
# Images, via Pillow.  Every pairing between png/jpeg/bmp/gif is offered;
# lossiness is declared per adapter in the registry, not decided here.
# ---------------------------------------------------------------------------

_PIL_FORMAT = {"png": "PNG", "jpeg": "JPEG", "bmp": "BMP", "gif": "GIF"}


def convert_image(data: bytes, *, target: str, max_pixels: int) -> bytes:
    from PIL import Image

    Image.MAX_IMAGE_PIXELS = max_pixels
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.load()
            width, height = image.size
            if width * height > max_pixels:
                raise ValueError(
                    f"Image is {width}x{height} ({width * height} pixels), "
                    f"over this converter's {max_pixels}-pixel limit"
                )
            pil_format = _PIL_FORMAT[target]
            if pil_format == "JPEG" and image.mode in ("RGBA", "LA", "P"):
                # Disclosed by the adapter's declared lossiness: JPEG carries
                # no alpha channel, so a transparent source is flattened onto
                # white rather than silently corrupting the write.
                background = Image.new("RGB", image.size, (255, 255, 255))
                rgba = image.convert("RGBA")
                background.paste(rgba, mask=rgba.split()[-1])
                image = background
            elif pil_format != "GIF" and image.mode == "P":
                image = image.convert("RGBA" if "transparency" in image.info else "RGB")
            out = io.BytesIO()
            save_kwargs = {}
            if pil_format == "JPEG":
                save_kwargs["quality"] = 92
            image.save(out, format=pil_format, **save_kwargs)
            return out.getvalue()
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"Could not decode source image: {exc}") from exc


def make_image_adapter(target: str, max_pixels: int = 64_000_000):
    """Return a picklable ``bytes -> bytes`` callable bound to one target.

    A closure would not survive the sandbox's ``multiprocessing`` pickling
    boundary (the child process is a fresh interpreter, not a fork that
    inherits the parent's local functions), so this binds arguments to the
    module-level :func:`convert_image` with :func:`functools.partial`
    instead -- partials of a top-level function pickle by reference plus
    plain-value arguments, which survives the trip to the child process.
    """
    import functools

    return functools.partial(convert_image, target=target, max_pixels=max_pixels)
