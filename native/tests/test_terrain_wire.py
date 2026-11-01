"""Consumer agreement with independent engine wire fixtures, not runtime proof."""

import json
from pathlib import Path
import unittest
from native.amulet_native.terrain_scene import TerrainRequest,SceneAssembler,canonical_json
from native.amulet_native.terrain_digest import BOUND_KEYS,encode_read_set

FIXTURE=Path(__file__).resolve().parents[2]/'engine/docs/terrain-wire-v1-fixtures.json'


@unittest.skipUnless(FIXTURE.is_file(),'Shared engine wire fixtures have not been integrated')
class SharedTerrainWireTests(unittest.TestCase):
    def test_independent_byte_vectors_and_complete_streams(self):
        fixture=json.loads(FIXTURE.read_text(encoding='utf-8'))
        for case in fixture['cases']:
            with self.subTest(case=case['name']):
                params=case['beginRequest']['params'];manifest=case['beginResponse']['result']
                request=TerrainRequest(params['path'],params['worldId'],params['dimension'],params['generation'],{k:params[k] for k in BOUND_KEYS})
                self.assertEqual(encode_read_set(manifest).hex(),case['readSetBytesHex'])
                scene=SceneAssembler(manifest,request,len(canonical_json(case['beginResponse'])))
                for response in case['pageResponses']:scene.accept_page(response['result'],len(canonical_json(response)))
                scene.finish(case['endResponse']['result'],len(canonical_json(case['endResponse'])))
                self.assertEqual(len(list(scene.faces())),manifest['totals']['faces'])
