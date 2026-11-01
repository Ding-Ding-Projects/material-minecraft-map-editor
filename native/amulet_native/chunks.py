"""Strict world-read schemas and exact integer slice indexing, without Qt."""

from dataclasses import dataclass
import hashlib
import re


def integer(value, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError("Integer outside supported bounds")
    return value


def coordinate(text):
    if not isinstance(text, str) or not re.fullmatch(r"-?[0-9]{1,10}", text):
        raise ValueError("Enter a signed decimal chunk coordinate")
    return integer(int(text), -(2**31), 2**31 - 1)


def text(value, maximum=32768, allow_empty=False):
    if not isinstance(value, str) or (not value and not allow_empty) or len(value) > maximum:
        raise ValueError("Invalid identifier or property text")
    return value


def dimensions(value):
    if not isinstance(value, dict) or value.get("readOnly") is not True:
        raise ValueError("Invalid dimension response")
    rows = value.get("dimensions")
    if not isinstance(rows, list) or len(rows) > 64:
        raise ValueError("Invalid dimension inventory")
    result = []
    for row in rows:
        if not isinstance(row, dict) or row.get("readOnly") is not True:
            raise ValueError("Invalid dimension entry")
        identity = text(row.get("id"), 256)
        if identity in result:
            raise ValueError("Duplicate dimension identifier")
        result.append(identity)
    return result


@dataclass(frozen=True)
class ChunkRequest:
    dimension: str
    x: int
    z: int


@dataclass(frozen=True)
class Block:
    name: str
    properties: tuple
    numeric: bool = False

    @property
    def color(self):
        digest = hashlib.sha256(repr((self.name, self.properties)).encode()).digest()
        return "#" + "".join(f"{72 + n % 120:02x}" for n in digest[:3])


@dataclass(frozen=True)
class Section:
    y: int
    blocks: tuple


@dataclass(frozen=True)
class Chunk:
    request: ChunkRequest
    available: bool
    version: int | None
    sections: tuple

    def cell(self, section_index, x, y, z):
        integer(section_index, 0, len(self.sections) - 1)
        for v in (x, y, z):
            integer(v, 0, 15)
        section = self.sections[section_index]
        block = section.blocks[y * 256 + z * 16 + x]
        return {"name": block.name, "numeric": block.numeric,
                "properties": [{"key": k, "value": v} for k, v in block.properties],
                "local": f"{x}, {y}, {z}",
                "world": f"{self.request.x * 16 + x}, {section.y * 16 + y}, {self.request.z * 16 + z}",
                "dimension": self.request.dimension,
                "chunk": f"{self.request.x}, {self.request.z}",
                "dataVersion": str(self.version), "color": block.color}

    def slice(self, section_index, y):
        return [self.cell(section_index, x, y, z) for z in range(16) for x in range(16)]


def parse_chunk(value, request):
    if not isinstance(value, dict) or value.get("readOnly") is not True:
        raise ValueError("Invalid read-only chunk response")
    if (value.get("dimension") != request.dimension
            or integer(value.get("chunkX"), -(2**31), 2**31 - 1) != request.x
            or integer(value.get("chunkZ"), -(2**31), 2**31 - 1) != request.z):
        raise ValueError("Chunk response does not match dispatched coordinates")
    if value.get("available") is False:
        if set(value) != {"dimension", "chunkX", "chunkZ", "available", "readOnly"}:
            raise ValueError("Absent chunk contains contradictory data")
        return Chunk(request, False, None, ())
    if (value.get("available") is not True or value.get("editingSupported") is not False
            or value.get("blockOrder") != "y-z-x"):
        raise ValueError("Unsupported chunk capability or block ordering")
    version = integer(value.get("dataVersion"), -(2**31), 2**31 - 1)
    rows = value.get("sections")
    if not isinstance(rows, list) or len(rows) > 256:
        raise ValueError("Invalid section inventory")
    sections, seen = [], set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Invalid section")
        y = integer(row.get("sectionY"), -128, 127)
        if y in seen or integer(row.get("minimumBlockY"), -2048, 2032) != y * 16:
            raise ValueError("Duplicate or inconsistent section height")
        seen.add(y)
        data = row.get("blocks")
        if not isinstance(data, dict):
            raise ValueError("Invalid nested block data")
        blocks = []
        if data.get("kind") == "palette":
            palette, indices = data.get("palette"), data.get("indices")
            if not isinstance(palette, list) or not 1 <= len(palette) <= 4096:
                raise ValueError("Invalid palette length")
            states = []
            for state in palette:
                if not isinstance(state, dict):
                    raise ValueError("Invalid palette state")
                properties = state.get("properties")
                if not isinstance(properties, list) or len(properties) > 64:
                    raise ValueError("Invalid property inventory")
                pairs, keys = [], set()
                for pair in properties:
                    if not isinstance(pair, list) or len(pair) != 2:
                        raise ValueError("Invalid property pair")
                    key, val = text(pair[0], allow_empty=True), text(pair[1], allow_empty=True)
                    if key in keys:
                        raise ValueError("Duplicate block property")
                    keys.add(key)
                    pairs.append((key, val))
                states.append(Block(text(state.get("name")), tuple(pairs)))
            if not isinstance(indices, list) or len(indices) != 4096:
                raise ValueError("Invalid block index array")
            blocks = [states[integer(i, 0, len(states) - 1)] for i in indices]
        elif data.get("kind") == "numeric":
            values = data.get("blocks")
            if not isinstance(values, list) or len(values) != 4096:
                raise ValueError("Invalid numeric block array")
            for pair in values:
                if not isinstance(pair, list) or len(pair) != 2:
                    raise ValueError("Invalid numeric block pair")
                block_id, metadata = integer(pair[0], 0, 4095), integer(pair[1], 0, 15)
                blocks.append(Block(f"Numeric block {block_id}", (("Block ID", str(block_id)),
                                                                       ("Metadata", str(metadata))), True))
        else:
            raise ValueError("Unsupported block representation")
        sections.append(Section(y, tuple(blocks)))
    return Chunk(request, True, version, tuple(sorted(sections, key=lambda section: section.y)))
