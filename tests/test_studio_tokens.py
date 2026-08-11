"""The Studio's design tokens are the design's values, not approximations.

The palettes, the density heights, and the spacing and radius scales are the one
place a colour or a size is decided; every surface paints against them.  A drift
here is invisible in review -- one hex digit -- and visible everywhere at once
when the application runs, so the values are asserted literally against the
design handoff.

Most of this file reads the token module as source rather than importing it,
because :mod:`amulet_map_editor.api.studio.tokens` imports wxPython and a build
machine without a display should still be able to prove the palette is right.
The two checks that genuinely need wx -- the accent reseeding, which computes
real colours -- say so by skipping.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOKENS = ROOT / "amulet_map_editor" / "api" / "studio" / "tokens.py"

#: The light palette, transcribed from the design handoff.
DESIGN_LIGHT = {
    "surface": ("#F7FAF9", 255),
    "surface_container": ("#EDF3F2", 255),
    "surface_container_high": ("#E1EAE8", 255),
    "on_surface": ("#171D1C", 255),
    "on_surface_variant": ("#3F4948", 255),
    "outline": ("#6F7978", 255),
    "outline_variant": ("#BFC9C7", 255),
    "primary": ("#006A63", 255),
    "on_primary": ("#FFFFFF", 255),
    "primary_container": ("#A6F2E9", 255),
    "on_primary_container": ("#00504A", 255),
    "error": ("#BA1A1A", 255),
    "scrim": ("#0E1514", 128),
    "tint": ("#006A63", 15),
}

#: The dark palette, transcribed from the same source.
DESIGN_DARK = {
    "surface": ("#0E1514", 255),
    "surface_container": ("#182020", 255),
    "surface_container_high": ("#232C2B", 255),
    "on_surface": ("#DDE4E2", 255),
    "on_surface_variant": ("#BEC9C7", 255),
    "outline": ("#899391", 255),
    "outline_variant": ("#3F4948", 255),
    "primary": ("#82D5CC", 255),
    "on_primary": ("#003733", 255),
    "primary_container": ("#00504A", 255),
    "on_primary_container": ("#A6F2E9", 255),
    "error": ("#FFB4AB", 255),
    "scrim": ("#000000", 158),
    "tint": ("#82D5CC", 20),
}

#: Control height per density, before the persisted interface scale is applied.
DESIGN_DENSITY_HEIGHTS = {"compact": 32, "comfortable": 36, "spacious": 44}


def _module_constant(name: str):
    """Return one module-level literal from the token source, without wx."""
    tree = ast.parse(TOKENS.read_text(encoding="utf-8"))
    for node in tree.body:
        targets = []
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        else:
            continue
        for target in targets:
            if isinstance(target, ast.Name) and target.id == name:
                return ast.literal_eval(node.value)
    raise AssertionError(f"{name} is no longer defined in tokens.py")


def test_the_light_palette_is_the_designs_own_values():
    assert _module_constant("LIGHT_ROLES") == DESIGN_LIGHT


def test_the_dark_palette_is_the_designs_own_values():
    assert _module_constant("DARK_ROLES") == DESIGN_DARK


def test_both_palettes_define_exactly_the_declared_roles():
    roles = _module_constant("ROLE_NAMES")
    assert set(roles) == set(DESIGN_LIGHT) == set(DESIGN_DARK)
    assert len(roles) == len(set(roles)) == 14


def test_density_sets_the_three_control_heights_the_design_names():
    assert _module_constant("DENSITY_HEIGHTS") == DESIGN_DENSITY_HEIGHTS


def test_the_spacing_and_radius_scales_are_unchanged():
    assert _module_constant("SPACE_XS") == 4
    assert _module_constant("SPACE_SM") == 8
    assert _module_constant("SPACE_MD") == 16
    assert _module_constant("SPACE_LG") == 24
    assert _module_constant("SPACE_XL") == 32
    assert _module_constant("RADIUS_SM") == 8
    assert _module_constant("RADIUS_MD") == 12
    assert _module_constant("RADIUS_LG") == 16
    assert _module_constant("RADIUS_PILL") == 999


def test_the_interface_face_falls_back_locally_and_never_downloads():
    ui_faces = _module_constant("UI_FONT_CANDIDATES")
    mono_faces = _module_constant("MONO_FONT_CANDIDATES")
    assert ui_faces[0] == "IBM Plex Sans"
    assert mono_faces[0] == "IBM Plex Mono"
    # Bilingual mode has to render Traditional Chinese even when nothing the
    # design named is installed, so the tail of the list carries CJK faces.
    assert any("JhengHei" in face or "CJK" in face or "PingFang" in face for face in ui_faces)
    source = TOKENS.read_text(encoding="utf-8")
    for forbidden in ("urllib", "requests", "http://", "https://", "urlopen"):
        assert forbidden not in source, f"tokens.py reaches the network: {forbidden}"


def test_the_shell_resolves_system_appearance_rather_than_assuming_light():
    source = TOKENS.read_text(encoding="utf-8")
    assert "def _system_is_dark" in source
    assert "wx.SystemSettings" in source
    assert 'if theme == "dark"' in source
    # A scheduled rule overrides the persisted preference, and School mode is
    # read through the shared projection rather than re-implemented here.
    assert "scheduled_runtime.current_values()" in source
    assert "school_mode.presentation_preferences" in source


def test_an_unreadable_profile_still_paints_the_shipped_palette():
    source = TOKENS.read_text(encoding="utf-8")
    presentation = source.split("def _presentation", 1)[1].split("\ndef ", 1)[0]
    assert "except (OSError, AttributeError, TypeError, ValueError)" in presentation
    assert "preferences.Preferences().normalised()" in presentation


# ---------------------------------------------------------------------------
# the parts that genuinely need wxPython
# ---------------------------------------------------------------------------


def _luminance(colour) -> float:
    """Return the same weighted luminance the token module reads ink from."""
    return (
        299 * colour.Red() + 587 * colour.Green() + 114 * colour.Blue()
    ) / 1000


def _rgb(hex_value: str):
    """Return ``(red, green, blue)`` for a ``#RRGGBB`` string."""
    value = hex_value.lstrip("#")
    return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16))


def test_the_built_palettes_carry_the_design_values_as_real_colours():
    pytest.importorskip("wx")
    from amulet_map_editor.api.studio import tokens

    for palette, table in ((tokens.LIGHT, DESIGN_LIGHT), (tokens.DARK, DESIGN_DARK)):
        for role, (hex_value, alpha) in table.items():
            colour = getattr(palette, role)
            assert (colour.Red(), colour.Green(), colour.Blue()) == _rgb(hex_value), role
            assert colour.Alpha() == alpha, role
    assert tokens.LIGHT.dark is False
    assert tokens.DARK.dark is True
    # A typo asks for a role that does not exist, and painting something
    # legible beats raising inside a paint handler.
    assert tokens.LIGHT.role("no_such_role") == tokens.LIGHT.surface


def test_reseeding_from_an_accent_produces_readable_inks():
    """Every seed must leave the label on top of it legible, not merely tinted."""
    pytest.importorskip("wx")
    from amulet_map_editor.api.studio import tokens

    seeds = (
        "#000000",
        "#FFFFFF",
        "#BA1A1A",
        "#006A63",
        "#82D5CC",
        "#3F51B5",
        "#FFEB3B",
        "#7E57C2",
    )
    for theme in ("light", "dark"):
        for seed in seeds:
            palette = tokens._build_palette(theme, seed)
            assert palette.primary == tokens._colour(seed)
            for background, ink in (
                (palette.primary, palette.on_primary),
                (palette.primary_container, palette.on_primary_container),
            ):
                gap = abs(_luminance(background) - _luminance(ink))
                assert gap >= 100, (
                    f"{theme} accent {seed}: ink on the "
                    f"{background.Red()},{background.Green()},{background.Blue()} "
                    "container is not readable"
                )
                assert ink in (tokens._colour("#171D1C"), tokens._colour("#FFFFFF"))


def test_an_absent_or_malformed_accent_leaves_the_shipped_palette_alone():
    pytest.importorskip("wx")
    from amulet_map_editor.api.studio import tokens

    for accent in ("", "   ", "not-a-colour", "#12", tokens.DEFAULT_ACCENT):
        assert tokens._build_palette("light", accent) == tokens.LIGHT
        assert tokens._build_palette("dark", accent) == tokens.DARK


def test_the_accent_seeds_the_whole_primary_family_not_one_button():
    pytest.importorskip("wx")
    from amulet_map_editor.api.studio import tokens

    palette = tokens._build_palette("light", "#7E57C2")
    assert palette.primary != tokens.LIGHT.primary
    assert palette.primary_container != tokens.LIGHT.primary_container
    assert palette.on_primary_container != tokens.LIGHT.on_primary_container
    assert (palette.tint.Red(), palette.tint.Green(), palette.tint.Blue()) == (
        palette.primary.Red(),
        palette.primary.Green(),
        palette.primary.Blue(),
    )
    # A reseed changes the accent family and nothing else; the surface roles a
    # reader's eyes rest on stay exactly where the design put them.
    assert palette.surface == tokens.LIGHT.surface
    assert palette.on_surface == tokens.LIGHT.on_surface
    assert palette.error == tokens.LIGHT.error
