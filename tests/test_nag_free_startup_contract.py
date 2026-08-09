from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_startup_has_no_unsolicited_modal_gate():
    source = (ROOT / "amulet_map_editor/api/framework/app.py").read_text(
        encoding="utf-8"
    )
    for marker in ("WarningDialog", "LicenceDialog", "ShowModal()"):
        assert marker not in source
    assert "wx.CallLater(0, self._amulet_ui.begin_startup_dim_sum_surprise)" in source


def test_dormant_purchase_and_modal_update_surfaces_are_removed():
    for relative in (
        "amulet_map_editor/api/framework/warning_dialog.py",
        "amulet_map_editor/api/framework/licence_dialog.py",
        "amulet_map_editor/api/framework/update_check.py",
    ):
        assert not (ROOT / relative).exists()


def test_localization_does_not_retain_purchase_prompt_keys():
    offenders = []
    for path in (ROOT / "amulet_map_editor/lang").glob("*.lang"):
        source = path.read_text(encoding="utf-8")
        if "licence_dialog." in source or "license_dialog." in source:
            offenders.append(path.name)
    assert not offenders, f"purchase prompt translations remain: {offenders}"


def test_required_operational_update_surface_stays_nonblocking():
    source = (ROOT / "amulet_map_editor/api/framework/amulet_ui.py").read_text(
        encoding="utf-8"
    )
    assert "def _render_update_banner" in source
    assert "def _hide_update_banner" in source
    start = source.index("    def _render_update_banner")
    end = source.index("    def _show_update_state", start)
    assert "ShowModal" not in source[start:end]
