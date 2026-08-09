from pathlib import Path


M3 = Path("amulet_map_editor/api/wx/material3.py").read_text(encoding="utf-8")
DIM_SUM = Path(
    "amulet_map_editor/api/wx/ui/dim_sum_surprise.py"
).read_text(encoding="utf-8")


def test_material3_owns_semantic_heading_typography():
    assert 'marker in ("title", "heading")' in M3
    assert "heading.SetFont" not in DIM_SUM
