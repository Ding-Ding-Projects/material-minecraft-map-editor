from pathlib import Path


SOURCE = Path(
    "amulet_map_editor/api/wx/ui/block_select/block_define.py"
).read_text(encoding="utf-8")


def test_block_entity_is_preserved_instead_of_discarded():
    assert "self._block_entity: Optional[BlockEntity] = None" in SOURCE
    assert "return self._block_entity" in SOURCE
    assert "self._block_entity = block_entity" in SOURCE
    assert "return None  # TODO" not in SOURCE
