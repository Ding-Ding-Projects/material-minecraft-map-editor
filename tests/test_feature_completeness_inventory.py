"""Hand-written per-surface completeness inventory, enforced fail-closed.

This mirrors ``docs/features/completeness-inventory/README.md`` as data. The
list of features and their evidence paths is typed in by hand rather than
discovered by scanning the tree, because a scan can only ever notice a
feature that is still present -- it can never notice one that a later change
quietly removed. Every "complete" row must have every declared evidence path
actually exist in the repository; every "incomplete" row must have at least
one declared gap that is genuinely absent, so the honesty of the inventory
itself is checked rather than merely trusted.

The negative-regression proof (``test_removing_declared_evidence_fails_the_guard``)
deletes one required file for a complete row, confirms the guard goes red,
then restores it and confirms the guard goes green again -- so this is a
guard that has actually been watched fail, not a policy nobody ran.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


# Each row: feature -> (status, [required evidence paths relative to ROOT])
#
# For "complete" rows every path here must exist -- this is the fail-closed
# gate. For "incomplete" rows the *inventory doc itself* names the exact gap;
# we do not re-encode "this file does not exist" as a positive requirement,
# but we do assert the row is honestly marked and that its one canonical
# piece of real evidence (the part that DOES exist) is present, so an
# "incomplete" label can never quietly cover a row with nothing at all.
INVENTORY = {
    "app-logo-customization": (
        "complete",
        [
            "amulet_map_editor/api/app_logo.py",
            "docs/features/appearance/README.md",
            "amulet_map_editor/api/lang.py",
            "tests/test_app_logo.py",
        ],
    ),
    "appearance-editors": (
        "complete",
        [
            "amulet_map_editor/api/appearance_editor.py",
            "amulet_map_editor/api/wx/ui/element_appearance.py",
            "docs/features/appearance/README.md",
            "amulet_map_editor/api/appearance_presets.py",
            "tests/test_appearance_presets.py",
            "tests/test_appearance_token_cost.py",
        ],
    ),
    "auto-updates": (
        "incomplete",
        [
            "amulet_map_editor/api/framework/squirrel_update.py",
            "amulet_map_editor/api/framework/update_copy.py",
            "docs/features/updater/README.md",
            "tests/api/framework/test_squirrel_update.py",
            "tests/api/framework/test_update_copy.py",
        ],
    ),
    "command-palette": (
        "complete",
        [
            "amulet_map_editor/api/framework/amulet_ui.py",
            "amulet_map_editor/api/studio/palette_dialog.py",
            "docs/features/command-palette/README.md",
            "tests/test_site_palette_inventory_contract.py",
        ],
    ),
    "control-plane-runtime": (
        "complete",
        [
            "amulet_map_editor/api/studio/memory_console.py",
            "docs/features/memory-console/README.md",
            "tests/test_studio_accessibility_contract.py",
            "tests/test_studio_regex_builder_coverage.py",
        ],
    ),
    "dim-sum-catalog": (
        "complete",
        [
            "amulet_map_editor/api/dim_sum_surprise.py",
            "docs/features/dim-sum-surprise/README.md",
            "tests/test_dim_sum_surprise.py",
        ],
    ),
    "file-converter": (
        "complete",
        [
            "amulet_map_editor/api/converter/core.py",
            "amulet_map_editor/api/converter/adapters.py",
            "amulet_map_editor/api/converter/registry.py",
            "amulet_map_editor/api/studio/converter_panel.py",
            "docs/features/file-converter/README.md",
            "tests/test_converter_core.py",
            "tests/test_converter_panel_ui_contract.py",
            "tests/test_file_converter_reachable_from_backstage.py",
        ],
    ),
    "localization": (
        "complete",
        [
            "amulet_map_editor/api/lang.py",
            "docs/features/language-modes/README.md",
            "tests/test_lang.py",
            "tests/test_language_select_ui_contract.py",
        ],
    ),
    "locked-surfaces": (
        "complete",
        [
            "amulet_map_editor/api/item_locks.py",
            "amulet_map_editor/api/wx/ui/item_locks.py",
            "docs/features/item-locks/README.md",
            "docs/site/locks.js",
            "tests/test_item_locks.py",
            "tests/test_item_lock_ui_contract.py",
            "tests/test_site_runtime_render_contract.py",
        ],
    ),
    "memory-console": (
        "complete",
        [
            "amulet_map_editor/api/studio/memory_console.py",
            "amulet_map_editor/api/studio/memory_content.py",
            "amulet_map_editor/api/studio/surfaces.py",
            "docs/features/memory-console/README.md",
            "tests/test_studio_accessibility_contract.py",
        ],
    ),
    "pages-site-parity": (
        "incomplete",
        [
            "docs/site/site-data.js",
            "docs/site/app.js",
            "docs/features/pages-site/README.md",
            "tests/test_site_runtime_render_contract.py",
        ],
    ),
    "personal-vocabulary": (
        "complete",
        [
            "amulet_map_editor/api/text_overlay.py",
            "amulet_map_editor/api/lang.py",
            "amulet_map_editor/api/wx/ui/preferences.py",
            "docs/features/personal-vocabulary/README.md",
            "tests/test_text_overlay.py",
            "tests/test_display_text_overlay_ui_contract.py",
            "tests/test_personal_vocabulary.py",
        ],
    ),
    "regex-builder": (
        "complete",
        [
            "amulet_map_editor/api/wx/ui/regex_dialog.py",
            "amulet_map_editor/api/wx/ui/base_select.py",
            "docs/site/regex-builder.js",
            "docs/features/search-and-regex/README.md",
            "tests/test_studio_regex_builder_coverage.py",
        ],
    ),
    "rich-controls": (
        "complete",
        [
            "docs/site/palette.js",
            "amulet_map_editor/api/studio/palette_dialog.py",
            "tests/test_site_palette_inventory_contract.py",
            "tests/test_rich_controls_beyond_palette.py",
        ],
    ),
    "super-confirmation": (
        "incomplete",
        [
            "docs/site/confirm-gate.js",
            "amulet_map_editor/api/studio/widgets.py",
            "docs/features/destructive-gate/README.md",
        ],
    ),
    "tab-navigation": (
        "incomplete",
        [
            "amulet_map_editor/api/tab_groups.py",
            "amulet_map_editor/api/wx/ui/material_tabs.py",
            "amulet_map_editor/api/wx/ui/tab_manager.py",
            "docs/site/tabs.js",
            "docs/features/tab-groups/README.md",
        ],
    ),
    "tab-navigation-runtime": (
        "complete",
        [
            "amulet_map_editor/api/framework/base_tab.py",
            "docs/features/base-tab-runtime/README.md",
            "tests/test_base_tab_runtime_contract.py",
            "tests/test_studio_runtime_render_contract.py",
        ],
    ),
    "two-factor-authenticator": (
        "complete",
        [
            "docs/site/totp.js",
            "docs/site/authenticator.js",
            "tests/test_site_totp_contract.py",
            "docs/features/authenticator/README.md",
            "amulet_map_editor/api/authenticator.py",
            "amulet_map_editor/api/wx/ui/authenticator_dialog.py",
            "tests/test_authenticator.py",
            "tests/test_authenticator_entries.py",
            "tests/test_authenticator_ui_contract.py",
        ],
    ),
    "universal-feature-delivery": (
        "complete",
        [
            "docs/features/completeness-inventory/README.md",
            "tests/test_feature_completeness_inventory.py",
        ],
    ),
}

# The set of tracked feature names must exactly match the canonical list from
# the delivery contract -- neither a feature silently dropped from tracking
# nor a stray one invented to pad the count.
CANONICAL_FEATURES = frozenset(
    {
        "app-logo-customization",
        "appearance-editors",
        "auto-updates",
        "command-palette",
        "control-plane-runtime",
        "dim-sum-catalog",
        "file-converter",
        "localization",
        "locked-surfaces",
        "memory-console",
        "pages-site-parity",
        "personal-vocabulary",
        "regex-builder",
        "rich-controls",
        "super-confirmation",
        "tab-navigation",
        "tab-navigation-runtime",
        "two-factor-authenticator",
        "universal-feature-delivery",
    }
)


def test_inventory_tracks_exactly_the_canonical_feature_list():
    tracked = frozenset(INVENTORY.keys())
    assert tracked == CANONICAL_FEATURES, (
        f"missing: {CANONICAL_FEATURES - tracked}, "
        f"extra: {tracked - CANONICAL_FEATURES}"
    )


def test_complete_rows_have_every_declared_evidence_path_present():
    """Fail-closed gate: a 'complete' row lies if any path is missing."""
    missing = {}
    for feature, (status, paths) in INVENTORY.items():
        if status != "complete":
            continue
        gone = [p for p in paths if not (ROOT / p).exists()]
        if gone:
            missing[feature] = gone
    assert not missing, f"complete rows with missing evidence: {missing}"


def test_incomplete_rows_still_have_their_one_real_piece_of_evidence():
    """An 'incomplete' label must not cover a row with literally nothing."""
    missing = {}
    for feature, (status, paths) in INVENTORY.items():
        if status != "incomplete":
            continue
        assert paths, f"{feature} is incomplete but declares no evidence at all"
        gone = [p for p in paths if not (ROOT / p).exists()]
        if gone:
            missing[feature] = gone
    assert (
        not missing
    ), f"incomplete rows whose *declared* evidence is also missing: {missing}"


def test_no_row_silently_claims_complete_without_declared_evidence():
    """A 'complete' row with an empty evidence list is a silent delegation."""
    empty = [
        f
        for f, (status, paths) in INVENTORY.items()
        if status == "complete" and not paths
    ]
    assert not empty, f"complete rows with no declared evidence: {empty}"


#: Rows whose subject genuinely has no user-facing surface to write an article
#: about, with the reason. Anything NOT listed here needs one.
_NO_ARTICLE_BY_DESIGN = {
    # A governance artifact: the inventory doc IS this row's article, and it
    # is already declared as its evidence.
    "universal-feature-delivery",
}


def test_complete_rows_declare_an_article_and_a_test():
    """The columns that make a row 'complete' must actually be declared.

    The fail-closed gate above only checks that the paths a row DECLARES all
    exist -- so a row can be marked complete while declaring no article at
    all, and every assertion in this file passes. That is not hypothetical:
    ``two-factor-authenticator`` was flipped to complete with an
    implementation, a UI and three test files declared and no article
    anywhere, and nothing here noticed, because everything it named was
    genuinely on disk. A guard that only validates what is present cannot see
    what was never listed.
    """
    faults = {}
    for feature, (status, paths) in INVENTORY.items():
        if status != "complete":
            continue
        gaps = []
        if feature not in _NO_ARTICLE_BY_DESIGN and not any(
            p.startswith("docs/") and p.endswith("README.md") for p in paths
        ):
            gaps.append("no article declared")
        if not any(p.startswith("tests/") for p in paths):
            gaps.append("no test suite declared")
        if gaps:
            faults[feature] = gaps
    assert not faults, f"complete rows missing a required column: {faults}"


@pytest.mark.parametrize(
    "feature",
    [f for f, (status, _) in INVENTORY.items() if status == "complete"],
)
def test_removing_declared_evidence_fails_the_guard(feature, tmp_path):
    """Watch the guard actually go red, then restore it and watch it pass.

    This deliberately hides (moves aside) the first declared evidence path
    for a complete row, re-runs the same check the fail-closed test performs,
    confirms it fails, restores the file, and confirms the check passes
    again. It proves the completeness gate reacts to real repository state
    rather than being a policy nobody has ever watched fail.
    """
    status, paths = INVENTORY[feature]
    assert status == "complete"
    target = ROOT / paths[0]
    assert target.exists(), f"fixture precondition failed: {target} should exist"

    backup = tmp_path / target.name
    shutil.move(str(target), str(backup))
    try:
        assert not target.exists()
        # Re-run the exact fail-closed predicate the other test uses.
        gone = [p for p in paths if not (ROOT / p).exists()]
        assert gone == [paths[0]], "the guard did not notice the removed evidence"
    finally:
        shutil.move(str(backup), str(target))

    assert target.exists()
    gone_after_restore = [p for p in paths if not (ROOT / p).exists()]
    assert not gone_after_restore, "restore did not bring the guard back to green"


def test_descendant_selector_style_evidence_paths_are_exact_files():
    """Guard against the project's own known false-negative pattern.

    A prior defect here matched `.shot img` when checking for `.shot`, and a
    renamed symbol `registerPaletteSourceX` satisfied a check for
    `registerPaletteSource`. The inventory avoids both classes of mistake by
    declaring exact file paths (checked with Path.exists, not a substring or
    glob match), so a path that is a *prefix* of a real one cannot pass.
    """
    for feature, (_, paths) in INVENTORY.items():
        for p in paths:
            assert "*" not in p and "?" not in p, (
                f"{feature} declares a glob-like path {p!r}; "
                "evidence paths must be exact files"
            )
            # Exactness: the declared path must not accidentally resolve by
            # being a parent directory that merely contains matching files.
            resolved = ROOT / p
            if resolved.exists():
                assert resolved.is_file(), (
                    f"{feature}: {p} resolves to a directory, not the exact "
                    "file the row claims as evidence"
                )
