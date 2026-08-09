from pathlib import Path


SOURCE = Path("amulet_map_editor/api/framework/licence_dialog.py").read_text(
    encoding="utf-8"
)


def test_licence_dialog_uses_shared_material3_styling():
    assert "SetFont(" not in SOURCE
    assert "apply_material3(self)" in SOURCE
