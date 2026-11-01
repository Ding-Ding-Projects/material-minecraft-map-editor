"""Strict bounded streamed scene assembly and immutable retained cell semantics."""

from array import array
from dataclasses import dataclass
import hashlib
import itertools
import json
import sys
from collections.abc import Mapping
from types import MappingProxyType
import copy

from .terrain_digest import BOUND_KEYS,exact,integer,digest_bytes,read_set_digest

CAPABILITY='cube-shapes-v1'
SHAPE_HASH='88b22690a55926aa1e6b3cc4a29ca52107a1699983d7a36a504c4d8ef1320a21'
REGISTRY={'schemaVersion':1,'version':'vanilla-java-1.20.1','sha256':'f10d5da83ec8cd995d4f484b788c5b1467a490728e687c629a681450e3253017'}
IDENTITY_KEYS=('worldId','dimension','generation','sceneId','readSetDigest','registry','geometrySchema','geometryCapability','shapeEvidenceSha256')
BASE_KEYS=('schemaVersion','readSetEncoding',*IDENTITY_KEYS)
TOTAL_KEYS=('states','sections','decodedCells','cubeCells','airCells','unsupportedCells','faces','pages')
DIRECTIONS=('xp','xn','yp','yn','zp','zn')
MAX_PAGE=262144
MAX_TOTAL=64*1024*1024


def canonical_json(value):
    def plain(v):
        if isinstance(v,float):raise ValueError('Floating-point terrain payload is not supported')
        if isinstance(v,(list,tuple)):
            return [plain(x) for x in v]
        elif isinstance(v,Mapping):
            if any(not isinstance(k,str) for k in v):raise ValueError('Invalid payload key')
            return {k:plain(x) for k,x in v.items()}
        return v
    return json.dumps(plain(value),sort_keys=True,ensure_ascii=False,separators=(',',':')).encode('utf-8')


@dataclass(frozen=True)
class TerrainRequest:
    path:str
    world_id:str
    dimension:str
    generation:int
    bounds:dict

    def __post_init__(self):
        object.__setattr__(self,'bounds',MappingProxyType(dict(self.bounds)))

    def params(self):
        return {'path':self.path,'worldId':self.world_id,'dimension':self.dimension,'generation':self.generation,
                **self.bounds,'geometryCapability':CAPABILITY,'limitProfile':'terrain-small-v1'}


def deep_size(value):
    if isinstance(value,Mapping):return sys.getsizeof(value)+sum(deep_size(k)+deep_size(v) for k,v in value.items())
    if isinstance(value,memoryview):return sys.getsizeof(value)+value.nbytes
    if isinstance(value,(list,tuple)):return sys.getsizeof(value)+sum(deep_size(v) for v in value)
    return sys.getsizeof(value)


class SceneAssembler:
    def __init__(self,manifest,request,encoded_bytes):
        exact(manifest,(*BASE_KEYS,'schemaVersion','readSetEncoding','readOnly','editingSupported','bounds','limitProfile','coverage','sources','pages','totals'))
        integer(manifest['schemaVersion'],1,1);integer(manifest['readSetEncoding'],1,1)
        if manifest['readOnly'] is not True or manifest['editingSupported'] is not False:raise ValueError('Invalid terrain write capability')
        self.request=request;self.manifest=copy.deepcopy(manifest);self.cursor=0;self.encoded_bytes=encoded_bytes;self._sealed=False
        self.state_table={};self.section_cells={};self.face_data=array('i');self.face_masks={}
        self._state_bytes=0
        if not 0<encoded_bytes<=MAX_PAGE:raise ValueError('Terrain manifest exceeds frame bound')
        if manifest['worldId']!=request.world_id or manifest['dimension']!=request.dimension or manifest['generation']!=request.generation:
            raise ValueError('Terrain manifest does not match request identity')
        integer(manifest['generation'],0,2**53-1)
        if (manifest['geometrySchema']!=1 or type(manifest['geometrySchema']) is not int
                or manifest['geometryCapability']!=CAPABILITY or manifest['shapeEvidenceSha256']!=SHAPE_HASH
                or manifest['registry']!=REGISTRY or manifest['limitProfile']!='terrain-small-v1'):
            raise ValueError('Terrain capability or reference identity mismatch')
        if not isinstance(manifest['sceneId'],str) or not 1<=len(manifest['sceneId'])<=128 or not manifest['sceneId'].isascii():
            raise ValueError('Invalid scene identifier')
        bounds=exact(manifest['bounds'],BOUND_KEYS)
        if bounds!=request.bounds:raise ValueError('Terrain coverage differs from request')
        for lo,hi,minimum,maximum in (('chunkXMin','chunkXMax',-2**31,2**31-1),('chunkZMin','chunkZMax',-2**31,2**31-1),('sectionYMin','sectionYMax',-128,127)):
            integer(bounds[lo],minimum,maximum);integer(bounds[hi],minimum,maximum)
            if not 1<=bounds[hi]-bounds[lo]+1<=3:raise ValueError('Terrain coverage exceeds small profile')
        expected=set(itertools.product(range(bounds['chunkXMin'],bounds['chunkXMax']+1),range(bounds['chunkZMin'],bounds['chunkZMax']+1),range(bounds['sectionYMin'],bounds['sectionYMax']+1)))
        if read_set_digest(manifest)!=manifest['readSetDigest']:raise ValueError('Terrain read-set digest mismatch')
        self.coverage={(v['chunkX'],v['chunkZ'],v['sectionY']):v for v in manifest['coverage']}
        if set(self.coverage)!=expected:raise ValueError('Coverage inventory is not exhaustive')
        for row in self.coverage.values():
            counts=[integer(row[k],0,4096) for k in ('decodedCells','cubeCells','airCells','unsupportedCells')]
            if row['availability']=='present':
                if counts[0]!=4096 or sum(counts[1:])!=4096 or counts[2]!=0 or row['dataVersion']!=3465 or row['reasonCode']!='':
                    raise ValueError('Inconsistent decoded coverage counts')
            elif any(counts):raise ValueError('Unavailable coverage contains invented cells')
        pages=manifest['pages']
        if not isinstance(pages,list) or len(pages)>1024:raise ValueError('Invalid page inventory')
        previous=-1
        for index,page in enumerate(pages):
            exact(page,('pageIndex','kind','recordCount','encodedBytes','payloadSha256'))
            if integer(page['pageIndex'],0,1023)!=index or page['kind'] not in ('states','cells','faces'):raise ValueError('Invalid terrain page order')
            order=('states','cells','faces').index(page['kind'])
            if order<previous:raise ValueError('Page kinds out of order')
            previous=order
            integer(page['encodedBytes'],1,MAX_PAGE);integer(page['recordCount'],1,4096);digest_bytes(page['payloadSha256'])
        if encoded_bytes+sum(p['encodedBytes'] for p in pages)>MAX_TOTAL:raise ValueError('Terrain encoded total exceeds budget')
        totals=exact(manifest['totals'],TOTAL_KEYS)
        limits={'states':4096,'sections':27,'decodedCells':110592,'cubeCells':110592,'airCells':0,'unsupportedCells':110592,'faces':663552,'pages':1024}
        for key,limit in limits.items():integer(totals[key],0,limit)
        if totals['pages']!=len(pages) or totals['faces']!=totals['cubeCells']*6:raise ValueError('Invalid terrain totals')
        for key in ('decodedCells','cubeCells','airCells','unsupportedCells'):
            if totals[key]!=sum(row[key] for row in self.coverage.values()):raise ValueError('Coverage totals disagree')
        if totals['sections']!=sum(row['availability']=='present' for row in self.coverage.values()):raise ValueError('Section totals disagree')

    @property
    def identity(self):return {k:self.manifest[k] for k in IDENTITY_KEYS}

    def _check_base(self,result):
        if any(result.get(k)!=v for k,v in self.identity.items()):raise ValueError('Terrain page/end identity changed')
        integer(result['generation'],0,2**53-1)
        integer(result['schemaVersion'],1,1);integer(result['readSetEncoding'],1,1)
        integer(result['geometrySchema'],1,1)
        integer(result['registry']['schemaVersion'],1,1)

    def accept_page(self,result,encoded_bytes):
        if self._sealed:raise ValueError('Scene has already been sealed')
        exact(result,(*BASE_KEYS,'pageIndex','kind','recordCount','payloadSha256','payload'))
        self._check_base(result)
        if self.cursor>=len(self.manifest['pages']):raise ValueError('Unexpected extra terrain page')
        descriptor=self.manifest['pages'][self.cursor]
        for key in ('pageIndex','kind','recordCount','payloadSha256'):
            if result[key]!=descriptor[key]:raise ValueError('Terrain page descriptor mismatch')
        integer(result['pageIndex'],0,1023);integer(result['recordCount'],1,4096)
        if encoded_bytes!=descriptor['encodedBytes'] or not 0<encoded_bytes<=MAX_PAGE:raise ValueError('Terrain encoded page size mismatch')
        self.encoded_bytes+=encoded_bytes
        if self.encoded_bytes>MAX_TOTAL:raise ValueError('Terrain total response budget exceeded')
        payload=result['payload']
        if hashlib.sha256(canonical_json(payload)).hexdigest()!=result['payloadSha256']:raise ValueError('Terrain page payload digest mismatch')
        self._check_memory(encoded_bytes*64)
        kind=result['kind']
        if kind=='states':self._states(payload,result['recordCount'])
        elif kind=='cells':self._cells(payload,result['recordCount'])
        else:self._faces(payload,result['recordCount'])
        self._check_memory(0);self.cursor+=1

    def _states(self,payload,count):
        exact(payload,('states',));rows=payload['states']
        if not isinstance(rows,list) or not 1<=len(rows)<=16 or len(rows)!=count:raise ValueError('Invalid state page')
        for row in rows:
            exact(row,('stateId','dataVersion','registryStateId','name','properties','classification'))
            state=integer(row['stateId'],0,4095)
            if state in self.state_table or state!=len(self.state_table):raise ValueError('Duplicate or noncontiguous state ID')
            if len(canonical_json(row))>4096:raise ValueError('State entry exceeds byte bound')
            integer(row['dataVersion'],-2**31,2**31-1)
            if row['registryStateId'] is not None:integer(row['registryStateId'],0,24134)
            if not isinstance(row['name'],str) or not row['name'] or len(row['name'].encode())>256:raise ValueError('Invalid state name')
            properties=row['properties']
            if not isinstance(properties,list) or len(properties)>64:raise ValueError('Invalid property count')
            keys=set()
            for pair in properties:
                if not isinstance(pair,list) or len(pair)!=2 or any(not isinstance(s,str) or len(s.encode())>256 for s in pair):raise ValueError('Invalid state property pair')
                if pair[0] in keys:raise ValueError('Duplicate state property')
                keys.add(pair[0])
            if row['classification']=='unitCubeShape':
                if row['dataVersion']!=3465 or row['name'] not in ('minecraft:stone','minecraft:cobblestone') or properties or row['registryStateId'] is None:
                    raise ValueError('Unverified cube shape classification')
            elif row['classification']!='unsupported':raise ValueError('Unsupported classification')
            self._state_bytes+=deep_size(row);self.state_table[state]=copy.deepcopy(row)

    def _cells(self,payload,count):
        exact(payload,('chunkX','chunkZ','sectionY','stateIds'))
        key=tuple(integer(payload[k],-2**31,2**31-1) for k in ('chunkX','chunkZ','sectionY'))
        if key in self.section_cells or key not in self.coverage or self.coverage[key]['availability']!='present':raise ValueError('Unexpected cell section')
        values=payload['stateIds']
        if not isinstance(values,list) or len(values)!=4096 or count!=4096:raise ValueError('Invalid cell page length')
        states=array('H');supported=0
        for state in values:
            integer(state,0,4095)
            if state not in self.state_table:raise ValueError('Unknown cell state ID')
            if self.state_table[state]['dataVersion']!=self.coverage[key]['dataVersion']:
                raise ValueError('Cell state data version differs from source section')
            states.append(state);supported+=int(self.supported(state))
        if supported!=self.coverage[key]['cubeCells']:raise ValueError('Cell classification count mismatch')
        self.section_cells[key]=states;self.face_masks[key]=bytearray(4096)

    def _faces(self,payload,count):
        exact(payload,('faces',));rows=payload['faces']
        if not isinstance(rows,list) or not 1<=len(rows)<=2048 or len(rows)!=count:raise ValueError('Invalid face page length')
        for row in rows:
            if not isinstance(row,list) or len(row)!=8:raise ValueError('Invalid face record')
            cx,cz,sy=(integer(row[i],-2**31,2**31-1) for i in range(3))
            x,y,z=(integer(row[i],0,15) for i in range(3,6))
            direction=row[6];state=integer(row[7],0,4095);key=(cx,cz,sy);index=y*256+z*16+x
            if key not in self.section_cells or direction not in DIRECTIONS or self.section_cells[key][index]!=state or not self.supported(state):raise ValueError('Face does not match supported cell')
            bit=1<<DIRECTIONS.index(direction)
            if self.face_masks[key][index]&bit:raise ValueError('Duplicate face identity')
            self.face_masks[key][index]|=bit
            self.face_data.extend((cx,cz,sy,x,y,z,DIRECTIONS.index(direction),state))
            if len(self.face_data)//8>663552:raise ValueError('Face count exceeded')

    def finish(self,result,encoded_bytes):
        exact(result,(*BASE_KEYS,'released','releasedCounts','deliveredPages'))
        self._check_base(result)
        exact(result['releasedCounts'],TOTAL_KEYS)
        for key,value in result['releasedCounts'].items():integer(value,0,663552)
        if result['released'] is not True or result['releasedCounts']!=self.manifest['totals'] or type(result['deliveredPages']) is not int or result['deliveredPages']!=self.cursor or self.cursor!=len(self.manifest['pages']):raise ValueError('Scene release/count acknowledgement mismatch')
        if self.encoded_bytes+encoded_bytes>MAX_TOTAL:raise ValueError('Scene end exceeds encoded budget')
        totals=self.manifest['totals']
        if len(self.state_table)!=totals['states'] or len(self.section_cells)!=totals['sections'] or len(self.face_data)//8!=totals['faces']:raise ValueError('Incomplete scene inventory')
        for key,states in self.section_cells.items():
            for index,state in enumerate(states):
                if self.face_masks[key][index]!=(63 if self.supported(state) else 0):raise ValueError('Missing or invented cube face')
        self.face_masks.clear()
        self.state_table=MappingProxyType({i:MappingProxyType({**row,'properties':tuple(tuple(p) for p in row['properties'])}) for i,row in self.state_table.items()})
        self.section_cells=MappingProxyType({key:memoryview(values.tobytes()).cast('H') for key,values in self.section_cells.items()})
        self.face_data=memoryview(self.face_data.tobytes()).cast('i')
        self._sealed=True
        return self

    def _check_memory(self,temporary):
        used=self._state_bytes+sys.getsizeof(self.face_data)+sum(sys.getsizeof(v) for v in self.section_cells.values())+sum(sys.getsizeof(v) for v in self.face_masks.values())+deep_size(self.manifest)
        if used+temporary>256*1024*1024:raise ValueError('Native scene allocation budget exceeded')

    def retained_bytes(self):
        return self._state_bytes+deep_size(self.face_data)+sum(deep_size(v) for v in self.section_cells.values())+deep_size(self.manifest)

    def reserve_decode(self,encoded_bytes):self._check_memory(encoded_bytes*64)

    @property
    def bounds(self):
        b=self.request.bounds
        return ((b['chunkXMin']*16,b['sectionYMin']*16,b['chunkZMin']*16),((b['chunkXMax']+1)*16,(b['sectionYMax']+1)*16,(b['chunkZMax']+1)*16))

    def supported(self,state):return self.state_table[state]['classification']=='unitCubeShape'
    def cell_state(self,x,y,z):
        data=self.section_cells.get((x//16,z//16,y//16))
        return None if data is None else int(data[(y%16)*256+(z%16)*16+x%16])
    def cells(self):
        for (cx,cz,sy),data in self.section_cells.items():
            for index,state in enumerate(data):yield cx*16+index%16,sy*16+index//256,cz*16+(index//16)%16,int(state)
    def faces(self):
        data=self.face_data
        for i in range(0,len(data),8):
            cx,cz,sy,x,y,z,direction,state=data[i:i+8]
            yield cx*16+x,sy*16+y,cz*16+z,DIRECTIONS[direction],state
    def colors(self):
        return {i:tuple((72+n%120)/255 for n in hashlib.sha256(canonical_json(s)).digest()[:3])+(1.,) for i,s in self.state_table.items()}

    def project_chunk(self,cx,cz):
        from .chunks import Block,Section,Chunk,ChunkRequest
        if not self._sealed:raise ValueError('Terrain snapshot is not accepted yet')
        integer(cx,-2**31,2**31-1);integer(cz,-2**31,2**31-1)
        b=self.request.bounds
        if not b['chunkXMin']<=cx<=b['chunkXMax'] or not b['chunkZMin']<=cz<=b['chunkZMax']:
            raise ValueError('Chunk is outside accepted terrain coverage')
        # Reuse immutable strings/property tuples. Do not build and reparse
        # multi-section JSON palettes or duplicate all state objects per section.
        blocks={i:Block(row['name'],row['properties']) for i,row in self.state_table.items()}
        sections=tuple(Section(sy,tuple(blocks[int(i)] for i in values))
                       for (x,z,sy),values in sorted(self.section_cells.items()) if x==cx and z==cz)
        coverage=[row for (x,z,sy),row in self.coverage.items() if x==cx and z==cz]
        absent=all(row['availability'] in ('absent-region','absent-chunk') for row in coverage)
        return Chunk(ChunkRequest(self.request.dimension,cx,cz),not absent,3465,sections)
