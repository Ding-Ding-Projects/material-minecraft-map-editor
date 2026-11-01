import json
import unittest

from native.amulet_native.framing import Decoder, MAX_FRAME, accepts_reply, encode_request, probe_facts


def framed(value):
    data = json.dumps(value).encode()
    return len(data).to_bytes(4, "big") + data


class FramingTests(unittest.TestCase):
    def test_fragmentation_and_coalescing(self):
        value = {"version": 1, "id": "1:probe", "result": {}}
        frame = framed(value)
        decoder = Decoder()
        self.assertEqual(decoder.feed(frame[:2]), [])
        self.assertEqual(decoder.feed(frame[2:-1]), [])
        self.assertEqual(decoder.feed(frame[-1:] + frame), [value, value])

    def test_hostile_lengths_and_outcomes(self):
        for length in (0, MAX_FRAME + 1):
            with self.assertRaises(ValueError):
                Decoder().feed(length.to_bytes(4, "big"))
        for value in ([], {"version": 2, "result": {}},
                      {"version": 1, "result": {}, "error": {}}):
            with self.assertRaises(ValueError):
                Decoder().feed(framed(value))

    def test_request_path_is_data(self):
        request = encode_request("1:probe", "world.probe", {"path": 'C:/world "quoted"'})
        self.assertEqual(len(request) - 4, int.from_bytes(request[:4], "big"))
        self.assertEqual(json.loads(request[4:])["params"]["path"], 'C:/world "quoted"')

    def test_stale_reply_identity_and_generation(self):
        reply = {"id": "2:probe"}
        self.assertTrue(accepts_reply(reply, "2:probe", 2, 2, "world", "world"))
        self.assertFalse(accepts_reply(reply, "2:probe", 2, 3, "world", "world"))
        self.assertFalse(accepts_reply(reply, "2:probe", 2, 2, "old", "new"))
        self.assertFalse(accepts_reply(reply, "3:probe", 2, 2, "world", "world"))

    def test_probe_never_claims_editing(self):
        result = {"edition": "java", "dataVersion": 1343, "readOnly": True,
                  "editingSupported": False, "versionSupport": "structural-probe-only"}
        self.assertEqual(probe_facts(result)["dataVersion"], "1343")
        for change in ({"editingSupported": True}, {"dataVersion": True}, {"edition": "bedrock"}):
            with self.assertRaises(ValueError):
                probe_facts(dict(result, **change))


if __name__ == "__main__":
    unittest.main()
