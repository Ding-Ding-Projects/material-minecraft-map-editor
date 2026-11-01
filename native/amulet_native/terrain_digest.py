"""Read-set encoding v1 shared with the bounded engine scene contract."""

import hashlib
import re
import struct

AVAILABILITY=("present","absent-region","absent-chunk","no-decoded-section",
              "unsupported-data-version","unsupported-encoding","corrupt","budget-exceeded")
BOUND_KEYS=("chunkXMin","chunkXMax","chunkZMin","chunkZMax","sectionYMin","sectionYMax")


def integer(value,low,high):
    if type(value) is not int or not low<=value<=high: raise ValueError("Invalid bounded terrain integer")
    return value


def exact(value,keys):
    if not isinstance(value,dict) or set(value)!=set(keys): raise ValueError("Unexpected terrain record fields")
    return value


def digest_bytes(value):
    if not isinstance(value,str) or not re.fullmatch('[0-9a-f]{64}',value): raise ValueError("Invalid terrain digest")
    return bytes.fromhex(value)


def utf8(value,maximum=4096):
    if not isinstance(value,str) or '\0' in value: raise ValueError("Invalid terrain text")
    raw=value.encode('utf-8',errors='strict')
    if len(raw)>maximum: raise ValueError("Terrain text exceeds bound")
    return struct.pack('>I',len(raw))+raw


def u8(v):return struct.pack('>B',integer(v,0,255))
def u16(v):return struct.pack('>H',integer(v,0,65535))
def u32(v):return struct.pack('>I',integer(v,0,2**32-1))
def u64(v):return struct.pack('>Q',integer(v,0,2**64-1))
def i32(v):return struct.pack('>i',integer(v,-2**31,2**31-1))
def optional(v,encoder):return b'\0' if v is None else b'\1'+encoder(v)


def file_identity(value):
    exact(value,('scheme','volumeSerial','fileId'))
    if value['scheme']!=1 or type(value['scheme']) is not int: raise ValueError("Unsupported file identity scheme")
    if not isinstance(value['fileId'],str) or not re.fullmatch('[0-9a-f]{32}',value['fileId']): raise ValueError("Invalid file identity")
    return b'\1'+u64(value['volumeSerial'])+bytes.fromhex(value['fileId'])


def encode_read_set(manifest):
    bounds=exact(manifest['bounds'],BOUND_KEYS)
    registry=exact(manifest['registry'],('schemaVersion','version','sha256'))
    out=bytearray(b'MWETERRAIN\0READSET\0'+u16(1)+utf8(manifest['dimension'],256))
    for key in BOUND_KEYS:out.extend(i32(bounds[key]))
    out.extend(u16(manifest['geometrySchema'])+utf8(manifest['geometryCapability'],64)
               +digest_bytes(manifest['shapeEvidenceSha256'])+u16(registry['schemaVersion'])
               +utf8(registry['version'],64)+digest_bytes(registry['sha256']))
    coverage=manifest['coverage']
    if not isinstance(coverage,list) or len(coverage)>27:raise ValueError("Invalid coverage count")
    out.extend(u32(len(coverage)))
    keys=set()
    for row in sorted(coverage,key=lambda r:(r['chunkX'],r['chunkZ'],r['sectionY'])):
        exact(row,('chunkX','chunkZ','sectionY','availability','dataVersion','decodedCells','cubeCells','airCells','unsupportedCells','reasonCode'))
        key=(row['chunkX'],row['chunkZ'],row['sectionY'])
        if key in keys:raise ValueError("Duplicate coverage key")
        keys.add(key)
        for item in key:out.extend(i32(item))
        if row['availability'] not in AVAILABILITY:raise ValueError("Invalid coverage availability")
        out.extend(u8(AVAILABILITY.index(row['availability']))+optional(row['dataVersion'],i32))
        for name in ('decodedCells','cubeCells','airCells','unsupportedCells'):out.extend(u32(row[name]))
        reason=row['reasonCode']
        if reason and (not isinstance(reason,str) or not re.fullmatch('[a-z0-9_]{1,64}',reason)):
            raise ValueError("Invalid coverage reason code")
        out.extend(utf8(reason,64))
    sources=manifest['sources']
    if not isinstance(sources,list) or len(sources)>32:raise ValueError("Invalid source count")
    out.extend(u32(len(sources)))
    paths=set();identities=set()
    for row in sorted(sources,key=lambda r:r['relativePath'].encode('utf-8')):
        exact(row,('relativePath','observation','fileIdentity','fileBytes','lastWriteFileTime','contentSha256'))
        path=row['relativePath']
        if (not isinstance(path,str) or not path or ':' in path or '\\' in path
                or any(p in ('','.','..') for p in path.split('/')) or path in paths):
            raise ValueError("Invalid source relative path")
        paths.add(path);out.extend(utf8(path))
        present=row['observation']=='present'
        if row['observation'] not in ('present','absent'):raise ValueError("Invalid source observation")
        values=[row[k] for k in ('fileIdentity','fileBytes','lastWriteFileTime','contentSha256')]
        if any((v is None)==present for v in values):raise ValueError("Inconsistent optional source facts")
        out.extend(u8(int(present)))
        if present:
            identity=file_identity(row['fileIdentity'])
            if identity in identities:raise ValueError("Duplicate source file identity")
            identities.add(identity)
        out.extend(optional(row['fileIdentity'],file_identity)+optional(row['fileBytes'],u64)
                   +optional(row['lastWriteFileTime'],u64)+optional(row['contentSha256'],digest_bytes))
    return bytes(out)


def read_set_digest(manifest):return hashlib.sha256(encode_read_set(manifest)).hexdigest()
