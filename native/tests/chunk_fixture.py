"""Synthetic on-disk Java chunks for protocol tests, never product startup data."""

import gzip
from pathlib import Path
import struct
import zlib


def string(value):
    raw = value.encode()
    return struct.pack(">H", len(raw)) + raw


def tag(kind, name, payload):
    return bytes([kind]) + string(name) + payload


def compound(name, content): return tag(10, name, content + b"\0")
def number(name, value): return tag(3, name, struct.pack(">i", value))
def byte_array(name, value): return tag(7, name, struct.pack(">i", len(value)) + value)
def compounds(name, values): return tag(9, name, b"\x0a" + struct.pack(">i", len(values)) + b"".join(v + b"\0" for v in values))


def write_world(path: Path, numeric=False, x=-1, z=-1):
    version = 1343 if numeric else 2975
    level = compound("", compound("Data", number("DataVersion", version)))
    (path / "level.dat").write_bytes(gzip.compress(level))
    section = tag(1, "Y", struct.pack("b", -4))
    if numeric:
        values = bytearray([1] * 4096)
        values[2 * 256 + 3 * 16 + 4] = 5
        metadata = bytearray(2048)
        metadata[(2 * 256 + 3 * 16 + 4) // 2] = 7
        section += byte_array("Blocks", values) + byte_array("Data", metadata)
        body = number("xPos", x) + number("zPos", z) + compounds("Sections", [section])
        root = compound("", number("DataVersion", version) + compound("Level", body))
    else:
        state = tag(8, "Name", string("minecraft:stone"))
        state += compound("Properties", tag(8, "axis", string("y")))
        section += compound("block_states", compounds("palette", [state]))
        root = compound("", number("DataVersion", version) + number("xPos", x) + number("zPos", z)
                        + compounds("sections", [section]))
    payload = zlib.compress(root)
    count = (len(payload) + 5 + 4095) // 4096
    region = bytearray(8192 + count * 4096)
    index = (z % 32) * 32 + x % 32
    region[index * 4:index * 4 + 4] = bytes([0, 0, 2, count])
    region[8192:8196] = struct.pack(">I", len(payload) + 1)
    region[8196] = 2
    region[8197:8197 + len(payload)] = payload
    (path / "region").mkdir(exist_ok=True)
    (path / "region" / f"r.{x // 32}.{z // 32}.mca").write_bytes(region)


def snapshot(path):
    return {str(p.relative_to(path)): p.read_bytes() for p in path.rglob("*") if p.is_file()}


def write_terrain_world(path: Path, x=-1, z=-1):
    """Nonlaunchable 3465 data fixture, containing real MCA bytes, not startup data."""
    if (path / "level.dat").exists() or (path / "region").exists():
        raise ValueError("Synthetic fixture destination must not contain world files")
    path.mkdir(parents=True, exist_ok=True)
    version = 3465
    level = compound("", compound("Data", number("DataVersion", version)))
    (path / "level.dat").write_bytes(gzip.compress(level, mtime=0))
    names = ("minecraft:stone", "minecraft:cobblestone", "minecraft:air", "minecraft:glass")
    states = [tag(8, "Name", string(name)) for name in names]
    cells = []
    for y in range(16):
        for lz in range(16):
            for lx in range(16):
                state = 0 if y < 4 else 2
                if lx in (4,5) and lz in (4,5) and 4 <= y <= 10: state = 1
                if (lx,lz,y) == (10,10,6): state = 3
                cells.append(state)
    words = [sum(cells[start+i] << (4*i) for i in range(16)) for start in range(0,4096,16)]
    packed = struct.pack(">i",len(words)) + b"".join(struct.pack(">Q",word) for word in words)
    section = tag(1,"Y",struct.pack("b",-4)) + compound("block_states", compounds("palette",states) + tag(12,"data",packed))
    root = compound("",number("DataVersion",version)+number("xPos",x)+number("zPos",z)+compounds("sections",[section]))
    payload=zlib.compress(root)
    count=(len(payload)+5+4095)//4096
    region=bytearray(8192+count*4096)
    index=(z%32)*32+x%32
    region[index*4:index*4+4]=bytes([0,0,2,count])
    region[8192:8196]=struct.pack(">I",len(payload)+1)
    region[8196]=2
    region[8197:8197+len(payload)]=payload
    (path/"region").mkdir()
    (path/"region"/f"r.{x//32}.{z//32}.mca").write_bytes(region)
    return {"synthetic":True,"dataVersion":3465,"chunkX":x,"chunkZ":z,"sectionY":-4,
            "stoneCells":1024,"cobblestoneCells":28,"unsupportedCells":3044,
            "expectedShapeFaces":6312,"launchableGameWorld":False}
