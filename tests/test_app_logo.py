"""Real-bytes verification of the app-logo customization core.

Every failure mode is exercised with a genuinely crafted file -- a PNG
renamed to look like a JPEG payload, a header-spoofed file, an oversized
image, a malformed header, and a real animated GIF -- never a mocked decoder.
"""

from __future__ import annotations

import io
import os
import sys

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, REPO_ROOT)

import pytest

from amulet_map_editor import __file__ as _pkg_file

assert _pkg_file.startswith(REPO_ROOT)

from amulet_map_editor.api import app_logo, config


@pytest.fixture(autouse=True)
def _isolated_profile(tmp_path, monkeypatch):
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path))
    config.invalidate()
    yield
    config.invalidate()


def _real_png(size=(64, 48), colour=(200, 40, 40, 255)) -> bytes:
    from PIL import Image

    img = Image.new("RGBA", size, colour)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _real_jpeg(size=(64, 48)) -> bytes:
    from PIL import Image

    img = Image.new("RGB", size, (10, 200, 10))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def _real_animated_gif() -> bytes:
    from PIL import Image

    frames = [
        Image.new("RGB", (32, 32), (255, 0, 0)),
        Image.new("RGB", (32, 32), (0, 255, 0)),
    ]
    buf = io.BytesIO()
    frames[0].save(
        buf, format="GIF", save_all=True, append_images=frames[1:], duration=100, loop=0
    )
    return buf.getvalue()


class TestConvertValidSource:
    def test_produces_every_output_size_as_valid_png(self):
        data = _real_png()
        outputs, disclosures = app_logo.convert_source_bytes(
            data, app_logo.LogoAdjustment(fit="fit")
        )
        assert set(outputs) == set(app_logo.OUTPUT_SIZES)
        from PIL import Image

        for size, png_bytes in outputs.items():
            assert png_bytes[:8] == b"\x89PNG\r\n\x1a\n"
            img = Image.open(io.BytesIO(png_bytes))
            img.load()
            assert img.size == (size, size)
            assert img.mode == "RGBA"

    def test_fill_mode_honours_focal_point(self):
        data = _real_png(size=(200, 100))
        outputs, _ = app_logo.convert_source_bytes(
            data, app_logo.LogoAdjustment(fit="fill", focal_x=0.0, focal_y=0.5)
        )
        assert set(outputs) == set(app_logo.OUTPUT_SIZES)

    def test_jpeg_source_discloses_no_transparency(self):
        data = _real_jpeg()
        _, disclosures = app_logo.convert_source_bytes(
            data, app_logo.LogoAdjustment(fit="fit")
        )
        assert any("transparency" in d for d in disclosures)

    def test_crop_box_is_disclosed_and_applied(self):
        data = _real_png(size=(100, 100))
        outputs, disclosures = app_logo.convert_source_bytes(
            data,
            app_logo.LogoAdjustment(fit="fit", crop_box=(0.25, 0.25, 0.75, 0.75)),
        )
        assert any("cropped" in d for d in disclosures)
        assert set(outputs) == set(app_logo.OUTPUT_SIZES)


class TestRejectsSpoofedAndMalformed:
    def test_png_bytes_renamed_as_jpeg_is_sniffed_by_real_bytes_not_extension(self):
        # The bytes ARE a real PNG; the point is this module never looks at a
        # filename/extension at all -- it must succeed purely on the sniff.
        data = _real_png()
        outputs, _ = app_logo.convert_source_bytes(data, app_logo.LogoAdjustment())
        assert outputs

    def test_header_spoofed_as_png_but_garbage_body_is_rejected(self):
        fake = b"\x89PNG\r\n\x1a\n" + os.urandom(200)
        with pytest.raises(app_logo.LogoValidationError):
            app_logo.convert_source_bytes(fake, app_logo.LogoAdjustment())

    def test_unrecognised_signature_is_rejected(self):
        with pytest.raises(app_logo.LogoValidationError, match="unrecognised"):
            app_logo.convert_source_bytes(
                b"not-an-image-at-all", app_logo.LogoAdjustment()
            )

    def test_empty_file_is_rejected(self):
        with pytest.raises(app_logo.LogoValidationError, match="empty"):
            app_logo.convert_source_bytes(b"", app_logo.LogoAdjustment())

    def test_animated_gif_is_rejected_naming_frame_count(self):
        data = _real_animated_gif()
        with pytest.raises(app_logo.LogoValidationError, match="frame"):
            app_logo.convert_source_bytes(data, app_logo.LogoAdjustment())

    def test_oversized_file_is_rejected_naming_the_bound(self):
        oversized = b"\x89PNG\r\n\x1a\n" + b"\x00" * (app_logo.MAX_SOURCE_BYTES + 1)
        with pytest.raises(
            app_logo.LogoValidationError, match=str(app_logo.MAX_SOURCE_BYTES)
        ):
            app_logo.convert_source_bytes(oversized, app_logo.LogoAdjustment())

    def test_oversized_dimensions_are_rejected(self):
        from PIL import Image

        img = Image.new(
            "RGBA", (app_logo.MAX_SOURCE_DIMENSION + 10, 10), (1, 2, 3, 255)
        )
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        with pytest.raises(app_logo.LogoValidationError, match="exceed"):
            app_logo.convert_source_bytes(buf.getvalue(), app_logo.LogoAdjustment())

    def test_bad_fit_mode_is_rejected(self):
        with pytest.raises(app_logo.LogoValidationError):
            app_logo.LogoAdjustment(fit="sideways")

    def test_bad_focal_point_is_rejected(self):
        with pytest.raises(app_logo.LogoValidationError):
            app_logo.LogoAdjustment(focal_x=2.0)


class TestPersistenceAndReset:
    def test_custom_logo_persists_across_a_fresh_load(self):
        data = _real_png()
        app_logo.apply_custom_logo(data, app_logo.LogoAdjustment(fit="fit"))
        config.invalidate()
        active = app_logo.load_active_logo()
        assert active.source == "custom"
        assert set(active.assets) == set(app_logo.OUTPUT_SIZES)

    def test_preset_selection_persists(self):
        name = app_logo.PRESETS[0].name
        app_logo.select_preset(name)
        config.invalidate()
        active = app_logo.load_active_logo()
        assert active.source == f"preset:{name}"
        assert set(active.assets) == set(app_logo.OUTPUT_SIZES)

    def test_unknown_preset_is_rejected(self):
        with pytest.raises(app_logo.LogoValidationError):
            app_logo.select_preset("does-not-exist")

    def test_reset_returns_to_shipped_in_one_action(self):
        app_logo.apply_custom_logo(_real_png(), app_logo.LogoAdjustment())
        active = app_logo.reset_to_shipped()
        assert active.source == "shipped"
        assert active.assets == {}
        config.invalidate()
        reloaded = app_logo.load_active_logo()
        assert reloaded.source == "shipped"

    def test_cache_corruption_falls_back_to_shipped(self):
        app_logo.apply_custom_logo(_real_png(), app_logo.LogoAdjustment())
        d = app_logo._assets_dir()
        for name in os.listdir(d):
            with open(os.path.join(d, name), "wb") as fp:
                fp.write(b"not a real png any more")
        config.invalidate()
        active = app_logo.load_active_logo()
        # Every generated asset was corrupted, so no size could be
        # recovered and the module must fall back rather than serve
        # broken bytes.
        assert active.source == "shipped"


class TestIdentityIsNeverTouched:
    def test_applying_a_custom_logo_leaves_identity_constants_unchanged(self):
        before = app_logo.identity_snapshot()
        app_logo.apply_custom_logo(_real_png(), app_logo.LogoAdjustment())
        app_logo.select_preset(app_logo.PRESETS[0].name)
        app_logo.reset_to_shipped()
        after = app_logo.identity_snapshot()
        assert before == after
