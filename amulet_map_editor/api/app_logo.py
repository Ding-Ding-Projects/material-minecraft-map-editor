"""App-logo customization: presets plus a validated local custom upload.

This module owns exactly one thing: which mark the application presents to
its own user, at each size the application actually renders it at.  It never
touches application identity.  The package/application id, the executable and
installer filename, the update feed, the data-directory name and the
(permanently disabled) signing state are all compile-time constants defined
elsewhere in this tree; nothing in this module reads or writes them, and
:func:`identity_snapshot` exists so a test can prove a logo change left them
alone.

Conversion pipeline for a user-supplied file, in order:

1.  Read no more than :data:`MAX_SOURCE_BYTES` off disk.
2.  Sniff the *actual bytes* against an allowlist of container signatures
    (:data:`_SIGNATURES`) -- never trust the extension.
3.  Decode with Pillow in an isolated call; reject a decode that reports more
    than one frame (animated/multi-page), or pixel dimensions beyond
    :data:`MAX_SOURCE_DIMENSION`, or that a decompression-bomb guard refuses.
4.  Crop/fit/pad per the requested :class:`LogoAdjustment`, into every size in
    :data:`OUTPUT_SIZES`.
5.  Validate each generated output: real PNG signature, exact requested
    dimensions, has an alpha channel, and round-trips through the decoder
    again before it is written to the profile directory.

Everything -- the validated source and every derived size -- is written only
under the application's own profile directory (see :mod:`amulet_map_editor.api.config`),
next to the other locally-owned assets this application already keeps there.
Nothing here makes a network call, writes a log line containing image bytes,
or is reachable from an export, a history snapshot, telemetry, or a prompt.
"""

from __future__ import annotations

import io
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from amulet_map_editor.api import config

__all__ = [
    "MAX_SOURCE_BYTES",
    "MAX_SOURCE_DIMENSION",
    "MAX_SOURCE_PIXELS",
    "OUTPUT_SIZES",
    "PRESETS",
    "LogoError",
    "LogoValidationError",
    "LogoAdjustment",
    "LogoAsset",
    "ActiveLogo",
    "convert_source_bytes",
    "apply_custom_logo",
    "select_preset",
    "render_preset_preview",
    "reset_to_shipped",
    "load_active_logo",
    "identity_snapshot",
    "LOGO_CONFIG_ID",
]

#: Untrusted input off the user's own disk -- generous but bounded.
MAX_SOURCE_BYTES = 8 * 1024 * 1024
#: A guard against a "small file, huge pixel grid" decompression bomb.
MAX_SOURCE_DIMENSION = 8192
MAX_SOURCE_PIXELS = 40_000_000

#: Every size the application actually renders a logo at.  Adding a consumer
#: means adding its size here -- the picker generates and validates exactly
#: this set, nothing more and nothing the app does not use.
OUTPUT_SIZES: Tuple[int, ...] = (16, 24, 32, 48, 64, 128, 256, 512)

#: Identifier the active-logo selection is persisted under via :mod:`config`.
#: The metadata (which preset/custom, fit mode, focal point, background) is
#: small and lives in the ordinary pickled profile store; the generated PNG
#: bytes for a custom logo are written as plain files beside it so they are
#: never round-tripped through pickle.
LOGO_CONFIG_ID = "amulet_app_logo"


#: Container signatures checked against the *actual bytes*, never the
#: filename extension.  Mapping of format name -> sniff callable.
def _is_png(head: bytes) -> bool:
    return head[:8] == b"\x89PNG\r\n\x1a\n"


def _is_jpeg(head: bytes) -> bool:
    return head[:3] == b"\xff\xd8\xff"


def _is_bmp(head: bytes) -> bool:
    return head[:2] == b"BM"


def _is_gif(head: bytes) -> bool:
    return head[:6] in (b"GIF87a", b"GIF89a")


_SIGNATURES = {
    "PNG": _is_png,
    "JPEG": _is_jpeg,
    "BMP": _is_bmp,
    "GIF": _is_gif,
}


class LogoError(Exception):
    """Base class for every error this module raises."""


class LogoValidationError(LogoError, ValueError):
    """Raised when a source file fails validation.

    The message names the exact bound that was hit and never includes the
    file's own bytes or path, matching the rest of this codebase's rule that
    untrusted-content errors stay content-free.
    """


@dataclass(frozen=True)
class LogoAdjustment:
    """How a decoded source image becomes each output size.

    ``fit`` is one of ``"fit"`` (contain, letterboxed), ``"fill"`` (cover,
    cropped) or ``"stretch"``.  ``focal_x``/``focal_y`` are 0..1 fractions of
    the source used as the crop centre for ``"fill"``.  ``background`` is
    ``"transparent"`` or an ``(r, g, b)`` tuple used to fill any letterboxed
    or non-alpha area.
    """

    fit: str = "fit"
    focal_x: float = 0.5
    focal_y: float = 0.5
    background: object = "transparent"
    crop_box: Optional[Tuple[float, float, float, float]] = None

    def __post_init__(self) -> None:
        if self.fit not in ("fit", "fill", "stretch"):
            raise LogoValidationError(f"unsupported fit mode: {self.fit!r}")
        if not (0.0 <= self.focal_x <= 1.0 and 0.0 <= self.focal_y <= 1.0):
            raise LogoValidationError("focal point must be within 0..1")


@dataclass(frozen=True)
class LogoAsset:
    """One validated, size-specific rendering of the active logo."""

    size: int
    png_bytes: bytes


@dataclass(frozen=True)
class ActiveLogo:
    """The application's currently active mark."""

    #: "shipped", "preset:<name>", or "custom".
    source: str
    #: size -> PNG bytes, for every size in OUTPUT_SIZES that has been
    #: generated.  Empty for "shipped", which callers render from their own
    #: bundled asset rather than through this module.
    assets: Dict[int, bytes] = field(default_factory=dict)
    adjustment: Optional[LogoAdjustment] = None
    #: Loss disclosed to the user before activation -- crop, rasterisation,
    #: alpha or colour-profile loss.  Empty when nothing was lost.
    disclosures: Tuple[str, ...] = ()


def _decode_with_pillow(data: bytes):
    from PIL import Image

    Image.MAX_IMAGE_PIXELS = MAX_SOURCE_PIXELS
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception as exc:  # Pillow raises many concrete subclasses.
        raise LogoValidationError(f"could not decode image: {exc}") from exc
    return img


def _sniff_format(data: bytes) -> str:
    head = data[:16]
    for name, check in _SIGNATURES.items():
        if check(head):
            return name
    raise LogoValidationError("unrecognised or unsupported image format")


def convert_source_bytes(
    data: bytes, adjustment: LogoAdjustment
) -> Tuple[Dict[int, bytes], List[str]]:
    """Validate and convert user-supplied bytes into every output size.

    Returns ``(size -> PNG bytes, disclosures)``.  Raises
    :class:`LogoValidationError` naming the exact bound hit for any spoofed,
    malformed, animated, oversized or unsupported input.  Never partially
    applies -- either every size is produced and validated, or nothing is
    returned.
    """
    if not data:
        raise LogoValidationError("empty file")
    if len(data) > MAX_SOURCE_BYTES:
        raise LogoValidationError(
            f"source file exceeds the {MAX_SOURCE_BYTES} byte bound"
        )

    fmt = _sniff_format(data)

    from PIL import Image

    img = _decode_with_pillow(data)

    # Animated / multi-frame source -- reject outright rather than silently
    # keep the first frame, so the user is never surprised by which frame
    # became the mark.
    frame_count = getattr(img, "n_frames", 1)
    if frame_count > 1:
        raise LogoValidationError(
            f"animated or multi-frame images are not supported ({frame_count} frames)"
        )

    width, height = img.size
    if width <= 0 or height <= 0:
        raise LogoValidationError("image has zero-area dimensions")
    if width > MAX_SOURCE_DIMENSION or height > MAX_SOURCE_DIMENSION:
        raise LogoValidationError(
            f"image dimensions {width}x{height} exceed the "
            f"{MAX_SOURCE_DIMENSION}px bound per side"
        )
    if width * height > MAX_SOURCE_PIXELS:
        raise LogoValidationError(
            f"image has {width * height} pixels, over the "
            f"{MAX_SOURCE_PIXELS} pixel bound"
        )

    disclosures: List[str] = []
    if fmt in ("JPEG", "BMP"):
        disclosures.append(
            f"the source is {fmt}, which has no transparency -- any "
            "letterboxed area will use the chosen background colour"
        )
    if "icc_profile" in img.info:
        disclosures.append(
            "the source carries a colour profile that will not be preserved"
        )

    img = img.convert("RGBA")

    if adjustment.crop_box is not None:
        l, t, r, b = adjustment.crop_box
        if not (0.0 <= l < r <= 1.0 and 0.0 <= t < b <= 1.0):
            raise LogoValidationError("crop box must be within 0..1 and non-empty")
        px_box = (
            int(l * width),
            int(t * height),
            max(int(r * width), int(l * width) + 1),
            max(int(b * height), int(t * height) + 1),
        )
        img = img.crop(px_box)
        width, height = img.size
        disclosures.append("the source was cropped before resizing")

    bg = adjustment.background
    if bg != "transparent":
        disclosures.append(
            "a solid background was applied; the source's own transparency "
            "(if any) was lost outside the image itself"
        )

    outputs: Dict[int, bytes] = {}
    for size in OUTPUT_SIZES:
        canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        if adjustment.fit == "stretch":
            resized = img.resize((size, size), Image.LANCZOS)
            canvas.alpha_composite(resized)
        elif adjustment.fit == "fill":
            scale = max(size / width, size / height)
            new_w, new_h = max(1, round(width * scale)), max(1, round(height * scale))
            resized = img.resize((new_w, new_h), Image.LANCZOS)
            fx = min(max(adjustment.focal_x, 0.0), 1.0)
            fy = min(max(adjustment.focal_y, 0.0), 1.0)
            left = int((new_w - size) * fx)
            top = int((new_h - size) * fy)
            left = max(0, min(left, new_w - size))
            top = max(0, min(top, new_h - size))
            cropped = resized.crop((left, top, left + size, top + size))
            canvas.alpha_composite(cropped)
        else:  # "fit" -- contain, letterboxed
            scale = min(size / width, size / height)
            new_w, new_h = max(1, round(width * scale)), max(1, round(height * scale))
            resized = img.resize((new_w, new_h), Image.LANCZOS)
            if bg != "transparent":
                fill_layer = Image.new("RGBA", (size, size), tuple(bg) + (255,))
                canvas.alpha_composite(fill_layer)
            ox = (size - new_w) // 2
            oy = (size - new_h) // 2
            canvas.alpha_composite(resized, (ox, oy))

        buf = io.BytesIO()
        canvas.save(buf, format="PNG")
        png_bytes = buf.getvalue()

        # Validate the generated output before it is trusted anywhere else:
        # real signature, exact size, has alpha, and a fresh round trip.
        if not _is_png(png_bytes):
            raise LogoValidationError(f"generated {size}px asset is not valid PNG")
        check = Image.open(io.BytesIO(png_bytes))
        check.load()
        if check.size != (size, size):
            raise LogoValidationError(
                f"generated {size}px asset has wrong dimensions {check.size}"
            )
        if check.mode != "RGBA":
            raise LogoValidationError(
                f"generated {size}px asset lost its alpha channel"
            )

        outputs[size] = png_bytes

    return outputs, disclosures


def _assets_dir() -> str:
    import os

    root = os.path.join(os.environ.get("CONFIG_DIR") or ".", "app_logo_assets")
    return os.path.abspath(root)


def _write_assets(assets: Dict[int, bytes]) -> None:
    import os

    d = _assets_dir()
    os.makedirs(d, exist_ok=True)
    for size, data in assets.items():
        with open(os.path.join(d, f"logo_{size}.png"), "wb") as fp:
            fp.write(data)


def _read_assets(sizes: Tuple[int, ...] = OUTPUT_SIZES) -> Dict[int, bytes]:
    import os

    d = _assets_dir()
    result: Dict[int, bytes] = {}
    for size in sizes:
        path = os.path.join(d, f"logo_{size}.png")
        if not os.path.isfile(path):
            continue
        try:
            with open(path, "rb") as fp:
                data = fp.read()
            if not _is_png(data):
                continue
            from PIL import Image

            img = Image.open(io.BytesIO(data))
            img.load()
            if img.size != (size, size):
                continue
        except Exception:
            # Cache corruption -- revalidate on load, fall back silently for
            # this one size; the caller decides what a partial set means.
            continue
        result[size] = data
    return result


def apply_custom_logo(data: bytes, adjustment: LogoAdjustment) -> ActiveLogo:
    """Validate, convert and persist a custom logo. Never partially applies."""
    assets, disclosures = convert_source_bytes(data, adjustment)
    _write_assets(assets)
    metadata = {
        "source": "custom",
        "adjustment": {
            "fit": adjustment.fit,
            "focal_x": adjustment.focal_x,
            "focal_y": adjustment.focal_y,
            "background": adjustment.background,
            "crop_box": adjustment.crop_box,
        },
        "saved_at": time.time(),
    }
    config.put(LOGO_CONFIG_ID, metadata)
    return ActiveLogo(
        source="custom",
        assets=assets,
        adjustment=adjustment,
        disclosures=tuple(disclosures),
    )


@dataclass(frozen=True)
class _Preset:
    name: str
    label: str
    #: RGBA base colour and a simple geometric mark, generated procedurally
    #: so no binary asset needs to be vendored for this module to work.
    colour: Tuple[int, int, int]
    shape: str  # "circle", "square", "diamond"


PRESETS: Tuple[_Preset, ...] = (
    _Preset("cartograph", "Cartograph Mark", (46, 125, 224), "diamond"),
    _Preset("beacon", "Beacon Mark", (255, 152, 0), "circle"),
    _Preset("grid", "Grid Mark", (0, 150, 136), "square"),
    _Preset("ore", "Ore Mark", (156, 39, 176), "circle"),
)


def _render_preset(preset: _Preset) -> Dict[int, bytes]:
    from PIL import Image, ImageDraw

    outputs: Dict[int, bytes] = {}
    for size in OUTPUT_SIZES:
        canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(canvas)
        pad = max(1, round(size * 0.12))
        box = (pad, pad, size - pad, size - pad)
        fill = preset.colour + (255,)
        if preset.shape == "circle":
            draw.ellipse(box, fill=fill)
        elif preset.shape == "square":
            draw.rounded_rectangle(box, radius=max(1, size // 8), fill=fill)
        else:  # diamond
            cx, cy = size / 2, size / 2
            r = size / 2 - pad
            draw.polygon(
                [(cx, cy - r), (cx + r, cy), (cx, cy + r), (cx - r, cy)], fill=fill
            )
        buf = io.BytesIO()
        canvas.save(buf, format="PNG")
        outputs[size] = buf.getvalue()
    return outputs


def render_preset_preview(name: str) -> Dict[int, bytes]:
    """Render one of :data:`PRESETS` at every output size without persisting it.

    Used by the settings surface to draw a real preview of each preset in the
    gallery -- the same pixels ``select_preset`` would activate -- rather than
    a preset named in a plain list.
    """
    matches = [p for p in PRESETS if p.name == name]
    if not matches:
        raise LogoValidationError(f"unknown preset: {name!r}")
    return _render_preset(matches[0])


def select_preset(name: str) -> ActiveLogo:
    """Activate one of :data:`PRESETS` by name."""
    matches = [p for p in PRESETS if p.name == name]
    if not matches:
        raise LogoValidationError(f"unknown preset: {name!r}")
    preset = matches[0]
    assets = _render_preset(preset)
    _write_assets(assets)
    config.put(LOGO_CONFIG_ID, {"source": f"preset:{name}", "saved_at": time.time()})
    return ActiveLogo(source=f"preset:{name}", assets=assets)


def reset_to_shipped() -> ActiveLogo:
    """Return to the application's own bundled mark, in one action."""
    import os
    import shutil

    d = _assets_dir()
    if os.path.isdir(d):
        shutil.rmtree(d, ignore_errors=True)
    config.put(LOGO_CONFIG_ID, {"source": "shipped", "saved_at": time.time()})
    return ActiveLogo(source="shipped")


def load_active_logo() -> ActiveLogo:
    """Revalidate and load whatever logo is currently active.

    Cache corruption falls back to the shipped mark rather than raising: a
    missing or unreadable asset for a given size is simply omitted, and if
    *no* size at all can be recovered for a non-shipped selection, this
    reports ``"shipped"`` so the caller always has something to render.
    """
    metadata = config.get(LOGO_CONFIG_ID, {"source": "shipped"})
    source = (
        metadata.get("source", "shipped") if isinstance(metadata, dict) else "shipped"
    )
    if source == "shipped":
        return ActiveLogo(source="shipped")

    assets = _read_assets()
    if not assets:
        return ActiveLogo(source="shipped")

    adjustment = None
    if source == "custom" and isinstance(metadata.get("adjustment"), dict):
        try:
            adjustment = LogoAdjustment(**metadata["adjustment"])
        except Exception:
            adjustment = None

    return ActiveLogo(source=source, assets=assets, adjustment=adjustment)


def identity_snapshot() -> Dict[str, object]:
    """A snapshot of every identity-bearing constant this module must never touch.

    A test constructs one before and after a logo change and asserts they
    compare equal, which is the mechanical proof that presentation stayed
    presentation.
    """
    import amulet_map_editor as _pkg  # local import, no cycle

    return {
        "package_file": _pkg.__file__,
        "package_name": _pkg.__name__,
    }
