"""Synthetic wire fixtures for adversarial consumer checks, not world evidence."""
import copy
import hashlib
from native.amulet_native.terrain_scene import TerrainRequest,BASE_KEYS,REGISTRY,SHAPE_HASH,canonical_json
from native.amulet_native.terrain_digest import read_set_digest


def envelope_bytes(identifier,result):return len(canonical_json({'version':1,'id':identifier,'result':result}))


def wire_fixture():
    bounds={'chunkXMin':0,'chunkXMax':0,'chunkZMin':0,'chunkZMax':0,'sectionYMin':0,'sectionYMax':0}
    request=TerrainRequest('unused','synthetic-test','minecraft:overworld',1,bounds)
    manifest={'worldId':request.world_id,'dimension':request.dimension,'generation':1,'sceneId':'synthetic-scene',
              'schemaVersion':1,'readSetEncoding':1,'readOnly':True,'editingSupported':False,
              'registry':copy.deepcopy(REGISTRY),'geometrySchema':1,'geometryCapability':'cube-shapes-v1',
              'shapeEvidenceSha256':SHAPE_HASH,'bounds':bounds,'limitProfile':'terrain-small-v1',
              'coverage':[{'chunkX':0,'chunkZ':0,'sectionY':0,'availability':'present','dataVersion':3465,
                           'decodedCells':4096,'cubeCells':1,'airCells':0,'unsupportedCells':4095,'reasonCode':''}],
              'sources':[{'relativePath':'region/r.0.0.mca','observation':'present',
                          'fileIdentity':{'scheme':1,'volumeSerial':7,'fileId':'01'*16},'fileBytes':12288,
                          'lastWriteFileTime':1,'contentSha256':'02'*32}],
              'totals':{'states':2,'sections':1,'decodedCells':4096,'cubeCells':1,'airCells':0,'unsupportedCells':4095,'faces':6,'pages':3},'pages':[]}
    manifest['readSetDigest']=read_set_digest(manifest)
    states=[{'stateId':0,'dataVersion':3465,'registryStateId':1,'name':'minecraft:stone','properties':[],'classification':'unitCubeShape'},
            {'stateId':1,'dataVersion':3465,'registryStateId':0,'name':'minecraft:air','properties':[],'classification':'unsupported'}]
    payloads=[('states',2,{'states':states}),('cells',4096,{'chunkX':0,'chunkZ':0,'sectionY':0,'stateIds':[0]+[1]*4095}),
              ('faces',6,{'faces':[[0,0,0,0,0,0,d,0] for d in ('xp','xn','yp','yn','zp','zn')]})]
    pages=[]
    for index,(kind,count,payload) in enumerate(payloads):
        digest=hashlib.sha256(canonical_json(payload)).hexdigest()
        page={**{k:manifest[k] for k in BASE_KEYS},'pageIndex':index,'kind':kind,'recordCount':count,'payloadSha256':digest,'payload':payload}
        descriptor={'pageIndex':index,'kind':kind,'recordCount':count,'payloadSha256':digest,'encodedBytes':envelope_bytes(f'terrain:1:page:{index}',page)}
        manifest['pages'].append(descriptor);pages.append(page)
    end={**{k:manifest[k] for k in BASE_KEYS},'released':True,'releasedCounts':copy.deepcopy(manifest['totals']),'deliveredPages':3}
    return request,manifest,pages,end
