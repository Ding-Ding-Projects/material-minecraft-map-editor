import copy
import unittest

from native.amulet_native.chunks import ChunkRequest, coordinate, dimensions, parse_chunk


def palette_result():
    return {"dimension": "minecraft:overworld", "chunkX": -1, "chunkZ": -1,
            "available": True, "readOnly": True, "editingSupported": False,
            "dataVersion": 2975, "blockOrder": "y-z-x", "sections": [
                {"sectionY": -4, "minimumBlockY": -64, "blocks": {"kind": "palette",
                 "palette": [{"name": "minecraft:stone", "properties": [["axis", "y"]]},
                             {"name": "minecraft:dirt", "properties": []}],
                 "indices": [0] * 4096}}]}


class ChunkTests(unittest.TestCase):
    def setUp(self): self.request = ChunkRequest("minecraft:overworld", -1, -1)

    def test_index_axes_and_signed_coordinates(self):
        value = palette_result()
        value["sections"][0]["blocks"]["indices"][2 * 256 + 3 * 16 + 4] = 1
        chunk = parse_chunk(value, self.request)
        selected = chunk.cell(0, 4, 2, 3)
        self.assertEqual(selected["name"], "minecraft:dirt")
        self.assertEqual(selected["world"], "-12, -62, -13")
        self.assertEqual(chunk.slice(0, 2)[3 * 16 + 4], selected)
        self.assertEqual(chunk.cell(0, 3, 2, 4)["name"], "minecraft:stone")
        with self.assertRaises(ValueError): chunk.cell(0, True, 0, 0)

    def test_extreme_chunk_coordinates_do_not_overflow(self):
        value = palette_result()
        value["chunkX"], value["chunkZ"] = -(2**31), 2**31 - 1
        chunk = parse_chunk(value, ChunkRequest(value["dimension"], value["chunkX"], value["chunkZ"]))
        self.assertEqual(chunk.cell(0, 0, 15, 15)["world"], "-34359738368, -49, 34359738367")

    def test_absent_is_not_air_and_no_sections_is_distinct(self):
        absent = {"dimension": self.request.dimension, "chunkX": -1, "chunkZ": -1, "available": False, "readOnly": True}
        self.assertFalse(parse_chunk(absent, self.request).available)
        with self.assertRaises(ValueError): parse_chunk(dict(absent, sections=[]), self.request)
        value = palette_result(); value["sections"] = []
        self.assertTrue(parse_chunk(value, self.request).available)
        self.assertEqual(parse_chunk(value, self.request).sections, ())

    def test_malformed_palette_and_integer_values_rejected(self):
        mutations = [
            lambda v: v.update(chunkX=True), lambda v: v.update(available=1),
            lambda v: v.update(dataVersion=True), lambda v: v.update(blockOrder="x-y-z"),
            lambda v: v["sections"][0].update(sectionY=False),
            lambda v: v["sections"][0]["blocks"].update(indices=[0] * 4095),
            lambda v: v["sections"][0]["blocks"]["indices"].__setitem__(0, True),
            lambda v: v["sections"][0]["blocks"]["indices"].__setitem__(0, 2),
            lambda v: v["sections"][0]["blocks"].update(palette=[]),
            lambda v: v["sections"][0]["blocks"]["palette"][0].update(properties=[["a", "x"], ["a", "y"]]),
            lambda v: v["sections"][0]["blocks"]["palette"][0].update(properties=[[str(i), "x"] for i in range(65)]),
            lambda v: v["sections"].append(copy.deepcopy(v["sections"][0])),
        ]
        for mutation in mutations:
            value = palette_result(); mutation(value)
            with self.assertRaises(ValueError): parse_chunk(value, self.request)

    def test_numeric_identity_and_metadata_are_literal(self):
        value = palette_result()
        value["sections"][0]["blocks"] = {"kind": "numeric", "blocks": [[4095, 15]] * 4096}
        cell = parse_chunk(value, self.request).cell(0, 0, 0, 0)
        self.assertEqual(cell["name"], "Numeric block 4095")
        self.assertEqual(cell["properties"][1]["value"], "15")
        value["sections"][0]["blocks"]["blocks"][0] = [True, 0]
        with self.assertRaises(ValueError): parse_chunk(value, self.request)

    def test_coordinate_drafts_and_dimension_schema(self):
        for invalid in ("", "-", "1.0", "1e2", "2147483648", "-2147483649", True):
            with self.assertRaises(ValueError): coordinate(invalid)
        self.assertEqual(coordinate("-2147483648"), -(2**31))
        row = {"id": "minecraft:overworld", "readOnly": True}
        self.assertEqual(dimensions({"dimensions": [row], "readOnly": True}), [row["id"]])
        with self.assertRaises(ValueError): dimensions({"dimensions": [row, row], "readOnly": True})

    def test_empty_property_strings_match_engine_schema(self):
        value = palette_result()
        value["sections"][0]["blocks"]["palette"][0]["properties"] = [["", ""], ["name", ""]]
        cell = parse_chunk(value, self.request).cell(0, 0, 0, 0)
        self.assertEqual(cell["properties"][0], {"key": "", "value": ""})
        value["sections"][0]["blocks"]["palette"][0]["name"] = ""
        with self.assertRaises(ValueError): parse_chunk(value, self.request)


if __name__ == "__main__": unittest.main()
