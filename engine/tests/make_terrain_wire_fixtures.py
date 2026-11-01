"""Generate synthetic shared terrain wire/codec fixtures, never runtime proof."""
import gzip,hashlib,json,struct,zlib
from pathlib import Path
PROFILE='vanilla-java-1.20.1'
SHAPE='88b22690a55926aa1e6b3cc4a29ca52107a1699983d7a36a504c4d8ef1320a21'
REGISTRY={'schemaVersion':1,'version':PROFILE,'sha256':'f10d5da83ec8cd995d4f484b788c5b1467a490728e687c629a681450e3253017'}
CAP='cube-shapes-v1'
def compact(v):return json.dumps(v,ensure_ascii=False,separators=(',',':'),sort_keys=True).encode()
def u8(n):return struct.pack('>B',n)
def u16(n):return struct.pack('>H',n)
def u32(n):return struct.pack('>I',n)
def u64(n):return struct.pack('>Q',n)
def i32(n):return struct.pack('>i',n)
def text(s):return u32(len(s.encode()))+s.encode()
def readset(m):
 b=m['bounds'];out=b'MWETERRAIN\0READSET\0'+u16(1)+text(m['dimension'])
 for k in ['chunkXMin','chunkXMax','chunkZMin','chunkZMax','sectionYMin','sectionYMax']:out+=i32(b[k])
 out+=u16(1)+text(CAP)+bytes.fromhex(SHAPE)+u16(1)+text(REGISTRY['version'])+bytes.fromhex(REGISTRY['sha256'])
 out+=u32(len(m['coverage']))
 codes=['present','absent-region','absent-chunk','no-decoded-section','unsupported-data-version','unsupported-encoding','corrupt','budget-exceeded']
 for c in sorted(m['coverage'],key=lambda c:(c['chunkX'],c['chunkZ'],c['sectionY'])):
  out+=i32(c['chunkX'])+i32(c['chunkZ'])+i32(c['sectionY'])+u8(codes.index(c['availability']))
  out+=b'\0' if c['dataVersion']is None else b'\1'+i32(c['dataVersion'])
  for k in ['decodedCells','cubeCells','airCells','unsupportedCells']:out+=u32(c[k])
  out+=text(c['reasonCode'])
 out+=u32(len(m['sources']))
 for s in sorted(m['sources'],key=lambda s:s['relativePath'].encode()):
  out+=text(s['relativePath'])+u8(s['observation']=='present')
  if s['observation']=='absent':out+=bytes(4);continue
  identity=s['fileIdentity'];out+=b'\1'+u8(1)+u64(identity['volumeSerial'])+bytes.fromhex(identity['fileId'])
  out+=b'\1'+u64(s['fileBytes'])+b'\1'+u64(s['lastWriteFileTime'])+b'\1'+bytes.fromhex(s['contentSha256'])
 return out
# Independent small NBT writer for synthetic fixtures only.
def string(s):b=s.encode();return u16(len(b))+b
def named(kind,name,payload):return u8(kind)+string(name)+payload
def compound(entries):return b''.join(entries)+b'\0'
def world(mixed):
 level=named(10,'',compound([named(10,'Data',compound([named(3,'DataVersion',i32(3465))]))]))
 level=gzip.compress(level,mtime=0)
 names=['minecraft:stone','minecraft:air']if mixed else['minecraft:air']
 palette=b''.join(compound([named(8,'Name',string(n))])for n in names)
 bs=[named(9,'palette',u8(10)+i32(len(names))+palette)]
 if mixed:
  words=[0x1111111111111111]*256;words[0]&=~15
  bs.append(named(12,'data',i32(256)+b''.join(u64(w)for w in words)))
 section=compound([named(1,'Y',struct.pack('>b',-4)),named(10,'block_states',compound(bs))])
 chunk=named(10,'',compound([named(3,'DataVersion',i32(3465)),named(3,'xPos',i32(-1)),named(3,'zPos',i32(0)),named(9,'sections',u8(10)+i32(1)+section)]))
 encoded=zlib.compress(chunk);region=bytearray(12288);region[31*4:31*4+4]=bytes([0,0,2,1]);region[8192:8196]=u32(len(encoded)+1);region[8196]=2;region[8197:8197+len(encoded)]=encoded
 return {'level.dat':level,'region/r.-1.0.mca':bytes(region)}
def source(path,data,index):return {'relativePath':path,'observation':'present','fileIdentity':{'scheme':1,'volumeSerial':1,'fileId':bytes(range(index*16,(index+1)*16)).hex()},'fileBytes':len(data),'lastWriteFileTime':132000000000000000+index,'contentSha256':hashlib.sha256(data).hexdigest()}
def example(name,mixed=True,absent=False):
 gen=7;files=world(mixed);coverage={'chunkX':-1,'chunkZ':0,'sectionY':-4,'availability':'absent-region'if absent else'present','dataVersion':None if absent else 3465,'decodedCells':0 if absent else 4096,'cubeCells':0 if absent or not mixed else 1,'airCells':0,'unsupportedCells':0 if absent else 4095 if mixed else 4096,'reasonCode':'absent_region'if absent else''}
 sources=[source('level.dat',files['level.dat'],0)]
 if absent:sources.append({'relativePath':'region/r.-1.0.mca','observation':'absent','fileIdentity':None,'fileBytes':None,'lastWriteFileTime':None,'contentSha256':None});files.pop('region/r.-1.0.mca')
 else:sources.append(source('region/r.-1.0.mca',files['region/r.-1.0.mca'],1))
 bounds={'chunkXMin':-1,'chunkXMax':-1,'chunkZMin':0,'chunkZMax':0,'sectionYMin':-4,'sectionYMax':-4}
 base={'schemaVersion':1,'readSetEncoding':1,'worldId':'fixture-world','dimension':'minecraft:overworld','generation':gen,'sceneId':'00000000000000000000000000000001','registry':REGISTRY,'geometrySchema':1,'geometryCapability':CAP,'shapeEvidenceSha256':SHAPE}
 manifest={**base,'bounds':bounds,'limitProfile':'terrain-small-v1','readOnly':True,'editingSupported':False,'coverage':[coverage],'sources':sources}
 encoded=readset(manifest);digest=hashlib.sha256(encoded).hexdigest();manifest['readSetDigest']=digest;base['readSetDigest']=digest
 states=[]if absent else[{'stateId':0,'dataVersion':3465,'registryStateId':1 if mixed else 0,'name':'minecraft:stone'if mixed else'minecraft:air','properties':[],'classification':'unitCubeShape'if mixed else'unsupported'}]
 if not absent and mixed:states.append({'stateId':1,'dataVersion':3465,'registryStateId':0,'name':'minecraft:air','properties':[],'classification':'unsupported'})
 payloads=[]if absent else[('states',len(states),{'states':states}),('cells',4096,{'chunkX':-1,'chunkZ':0,'sectionY':-4,'stateIds':([0]+[1]*4095)if mixed else[0]*4096})]
 if mixed and not absent:payloads.append(('faces',6,{'faces':[[-1,0,-4,0,0,0,d,0]for d in ['xp','xn','yp','yn','zp','zn']]}))
 pages=[];requests=[];descriptors=[]
 params={k:base[k]for k in ['worldId','dimension','generation','sceneId','readSetDigest','registry','geometrySchema','geometryCapability','shapeEvidenceSha256']}
 for index,(kind,count,payload)in enumerate(payloads):
  ph=hashlib.sha256(compact(payload)).hexdigest();response={'version':1,'id':f'terrain:{gen}:page:{index}','result':{**base,'pageIndex':index,'kind':kind,'recordCount':count,'payloadSha256':ph,'payload':payload}}
  pages.append(response);requests.append({'version':1,'id':response['id'],'method':'world.terrain_page','params':{**params,'pageIndex':index}});descriptors.append({'pageIndex':index,'kind':kind,'recordCount':count,'encodedBytes':len(compact(response)),'payloadSha256':ph})
 totals={'states':len(states),'sections':0 if absent else 1,'decodedCells':coverage['decodedCells'],'cubeCells':coverage['cubeCells'],'airCells':0,'unsupportedCells':coverage['unsupportedCells'],'faces':6 if mixed and not absent else 0,'pages':len(pages)}
 manifest.update({'pages':descriptors,'totals':totals})
 begin={'version':1,'id':f'terrain:{gen}:begin','method':'world.terrain_begin','params':{'path':'<explicit-synthetic-world-directory>','worldId':'fixture-world','dimension':'minecraft:overworld','generation':gen,'geometryCapability':CAP,'limitProfile':'terrain-small-v1',**bounds}}
 end={'version':1,'id':f'terrain:{gen}:end','method':'world.terrain_end','params':params}
 return {'name':name,'fixtureOnly':True,'identityEvidence':'Fixed symbolic file identities/time for codec agreement, not runtime source observations','files':[{'relativePath':k,'bytesHex':v.hex()}for k,v in files.items()],'beginRequest':begin,'beginResponse':{'version':1,'id':begin['id'],'result':manifest},'pageRequests':requests,'pageResponses':pages,'endRequest':end,'endResponse':{'version':1,'id':end['id'],'result':{**base,'released':True,'releasedCounts':totals,'deliveredPages':len(pages)}},'readSetBytesHex':encoded.hex(),'readSetDigest':digest}
value={'schemaVersion':1,'scope':'Synthetic shared wire and digest fixtures; never default terrain, installed-source proof or rendering evidence','cases':[example('one_cube_and_unsupported_cells'),example('absent_region',absent=True),example('unsupported_only',mixed=False)],'negativeVectors':[{'name':'boolean_count','pointer':'/coverage/0/decodedCells','value':True},{'name':'missing_coverage','pointer':'/coverage','value':[]},{'name':'wrong_shape','pointer':'/shapeEvidenceSha256','value':'0'*64},{'name':'unsafe_source_path','pointer':'/sources/0/relativePath','value':'../escape'},{'name':'absent_with_evidence','pointer':'/sources/0/observation','value':'absent'},{'name':'bad_identity_scheme','pointer':'/sources/0/fileIdentity/scheme','value':2},{'name':'boolean_file_time','pointer':'/sources/0/lastWriteFileTime','value':True},{'name':'nul_dimension','pointer':'/dimension','value':'minecraft:\0overworld'}]}
Path(__file__).resolve().parents[1].joinpath('docs/terrain-wire-v1-fixtures.json').write_text(json.dumps(value,indent=2,ensure_ascii=False)+'\n',encoding='utf-8',newline='\n')
print([(c['name'],c['readSetDigest'])for c in value['cases']])
