import copy
import hashlib
import unittest
from native.amulet_native.terrain_scene import SceneAssembler,canonical_json
from terrain_protocol_fixture import wire_fixture,envelope_bytes


class TerrainSceneTests(unittest.TestCase):
    def assemble(self,manifest,pages,request):
        scene=SceneAssembler(manifest,request,envelope_bytes('terrain:1:begin',manifest))
        for index,page in enumerate(pages):scene.accept_page(page,envelope_bytes(f'terrain:1:page:{index}',page))
        return scene

    def test_complete_scene_retains_unknown_cells_and_all_shape_faces(self):
        request,manifest,pages,end=wire_fixture()
        scene=self.assemble(manifest,pages,request)
        scene.finish(end,envelope_bytes('terrain:1:end',end))
        self.assertEqual(scene.cell_state(0,0,0),0)
        self.assertTrue(scene.supported(0));self.assertFalse(scene.supported(1))
        self.assertIsNone(scene.cell_state(-1,0,0))
        self.assertEqual(len(list(scene.faces())),6)
        self.assertEqual(len(list(scene.cells())),4096)

    def test_digest_identity_and_complete_coverage_are_required(self):
        for mutate in (lambda m:m.update(readSetDigest='ff'*32),lambda m:m.update(worldId='other'),
                       lambda m:m.update(geometryCapability='cube-faces-v1'),lambda m:m.update(generation=True),
                       lambda m:m['coverage'].clear()):
            request,manifest,pages,end=wire_fixture();mutate(manifest)
            with self.assertRaises(ValueError):SceneAssembler(manifest,request,envelope_bytes('terrain:1:begin',manifest))

    def test_duplicate_face_rejected_even_with_consistent_payload_hash(self):
        request,manifest,pages,end=wire_fixture()
        pages[2]['payload']['faces'][5]=pages[2]['payload']['faces'][0]
        digest=hashlib.sha256(canonical_json(pages[2]['payload'])).hexdigest()
        pages[2]['payloadSha256']=manifest['pages'][2]['payloadSha256']=digest
        with self.assertRaises(ValueError):self.assemble(manifest,pages,request)

    def test_missing_page_stale_identity_wrong_byte_count_and_boolean_end_rejected(self):
        request,manifest,pages,end=wire_fixture()
        scene=SceneAssembler(manifest,request,envelope_bytes('terrain:1:begin',manifest))
        with self.assertRaises(ValueError):scene.accept_page(pages[1],manifest['pages'][1]['encodedBytes'])
        with self.assertRaises(ValueError):scene.accept_page(pages[0],manifest['pages'][0]['encodedBytes']+1)
        stale=copy.deepcopy(pages[0]);stale['geometrySchema']=True
        with self.assertRaises(ValueError):scene.accept_page(stale,manifest['pages'][0]['encodedBytes'])
        scene=self.assemble(manifest,pages,request)
        end['releasedCounts']['sections']=True
        with self.assertRaises(ValueError):scene.finish(end,envelope_bytes('terrain:1:end',end))

    def test_unknown_name_cannot_claim_supported_shape(self):
        request,manifest,pages,end=wire_fixture()
        pages[0]['payload']['states'][0]['name']='minecraft:glass'
        digest=hashlib.sha256(canonical_json(pages[0]['payload'])).hexdigest()
        pages[0]['payloadSha256']=manifest['pages'][0]['payloadSha256']=digest
        manifest['pages'][0]['encodedBytes']=envelope_bytes('terrain:1:page:0',pages[0])
        with self.assertRaises(ValueError):self.assemble(manifest,pages,request)

    def test_request_bounds_and_accepted_data_do_not_alias_mutable_inputs(self):
        request,manifest,pages,end=wire_fixture()
        with self.assertRaises(TypeError):request.bounds['chunkXMin']=1
        scene=self.assemble(manifest,pages,request);scene.finish(end,envelope_bytes('terrain:1:end',end))
        pages[0]['payload']['states'][0]['name']='changed'
        self.assertEqual(scene.state_table[0]['name'],'minecraft:stone')
        with self.assertRaises(TypeError):scene.section_cells[(0,0,0)][0]=1
        projected=scene.project_chunk(0,0)
        self.assertEqual(projected.cell(0,0,0,0)['name'],'minecraft:stone')
        self.assertEqual(projected.cell(0,1,0,0)['name'],'minecraft:air')
        with self.assertRaises(ValueError):scene.project_chunk(1,0)

    def test_surrogate_strings_and_excessive_integers_rejected(self):
        request,manifest,pages,end=wire_fixture()
        manifest['sources'][0]['relativePath']='region/\ud800.mca'
        with self.assertRaises(ValueError):SceneAssembler(manifest,request,1000)
        request,manifest,pages,end=wire_fixture();manifest['sources'][0]['fileBytes']=2**64
        with self.assertRaises(ValueError):SceneAssembler(manifest,request,1000)
