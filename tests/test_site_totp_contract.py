"""The site's authenticator crypto and QR encoder, checked against published values.

An authenticator that is subtly wrong emits codes every server rejects, with no
error anywhere to read, and a QR code that is subtly wrong simply fails to scan.
Neither failure shows up in a screenshot, and neither shows up in a test that
only asserts the surface rendered. So the arithmetic is checked here against
values published in the RFCs and the QR specification rather than against this
repository's own output.

Node runs the checks because the code under test is JavaScript. A missing Node
is a hard failure rather than a skip: a skip here would leave the suite green
while nothing at all had been verified, which is the exact shape of a guard that
silently stops guarding.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SITE = REPO / "docs" / "site"
TOTP_JS = SITE / "totp.js"
QR_JS = SITE / "qr.js"


def run_node(script: str) -> dict:
    node = shutil.which("node")
    if node is None:
        raise AssertionError(
            "node is required to check the site's TOTP and QR arithmetic and was "
            "not found on PATH. This is not skipped, because skipping would leave "
            "the suite green while the authenticator went unverified."
        )
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "check.cjs"
        path.write_text(script, encoding="utf-8")
        result = subprocess.run(
            [node, str(path)], capture_output=True, text=True, timeout=120
        )
    if result.returncode != 0:
        raise AssertionError(
            f"the node harness failed:\n{result.stdout}\n{result.stderr}"
        )
    return json.loads(result.stdout)


def harness(body: str, *sources: Path) -> str:
    loads = "\n".join(
        f"eval(fs.readFileSync(String.raw`{p.as_posix()}`, 'utf8'));" for p in sources
    )
    return (
        "const fs = require('fs');\nglobal.window = {};\n"
        + loads
        + "\nconst out = (function(){\n"
        + body
        + "\n})();\nprocess.stdout.write(JSON.stringify(out));\n"
    )


class TotpMatchesTheRfcVectors(unittest.TestCase):
    """RFC 6238 Appendix B, all three hash functions at eight digits."""

    #: (unix seconds, SHA1, SHA256, SHA512)
    VECTORS = [
        (59, "94287082", "46119246", "90693936"),
        (1111111109, "07081804", "68084774", "25091201"),
        (1111111111, "14050471", "67062674", "99943326"),
        (1234567890, "89005924", "91819424", "93441116"),
        (2000000000, "69279037", "90698825", "38618901"),
        # Past 2^31 *seconds*, but note that this still does not exercise the
        # 64-bit counter: 20000000000 / 30 is 666666666, which fits in 32 bits
        # comfortably. Nothing in the published set reaches the high word, so
        # it is covered separately below.
        (20000000000, "65353130", "77737706", "47863826"),
    ]

    SEEDS = {
        "SHA1": "12345678901234567890",
        "SHA256": "12345678901234567890123456789012",
        "SHA512": "1234567890123456789012345678901234567890123456789012345678901234",
    }

    def test_every_published_vector_matches(self) -> None:
        body = (
            "const T = window.AmuletTOTP;"
            "const bytes = s => Array.from(Buffer.from(s, 'utf8'));"
            f"const seeds = {json.dumps(self.SEEDS)};"
            f"const vectors = {json.dumps(self.VECTORS)};"
            "const results = [];"
            "for (const [t, a, b, c] of vectors) {"
            "  ['SHA1','SHA256','SHA512'].forEach((alg, i) => {"
            "    results.push({t: t, alg: alg, expected: [a,b,c][i],"
            "      got: T.totp({secretBytes: bytes(seeds[alg]), seconds: t,"
            "                   algorithm: alg, digits: 8, period: 30})});"
            "  });"
            "}"
            "return results;"
        )
        results = run_node(harness(body, TOTP_JS))
        self.assertEqual(len(results), 18, "expected 6 times x 3 algorithms")
        for row in results:
            with self.subTest(t=row["t"], algorithm=row["alg"]):
                self.assertEqual(row["got"], row["expected"])

    def test_the_hashes_match_known_digests(self) -> None:
        body = (
            "const T = window.AmuletTOTP;"
            "const hex = b => b.map(x => x.toString(16).padStart(2,'0')).join('');"
            "const abc = Array.from(Buffer.from('abc','utf8'));"
            "return {sha1: hex(T.sha1(abc)), sha256: hex(T.sha256(abc)),"
            "        sha512: hex(T.sha512(abc))};"
        )
        got = run_node(harness(body, TOTP_JS))
        self.assertEqual(got["sha1"], "a9993e364706816aba3e25717850c26c9cd0d89d")
        self.assertEqual(
            got["sha256"],
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
        )
        self.assertEqual(
            got["sha512"],
            "ddaf35a193617abacc417349ae20413112e6fa4e89a97ea20a9eeee64b55d39a"
            "2192992a274fc1a836ba3c23a3feebbd454d4423643ce80e2a9ac94fa54ca49f",
        )

    def test_the_counter_uses_both_32_bit_words(self) -> None:
        """RFC 4226 counts with a 64-bit counter, and none of the published
        vectors reach past the low word, so dropping the high word entirely
        leaves every one of them passing. Counter 2**32 and counter 0 share a
        low word and differ only in the high one, so they must not agree."""

        body = (
            "const T = window.AmuletTOTP;"
            "const secret = T.decodeBase32('GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ');"
            "return {zero: T.hotp(secret, 0, 'SHA1', 8),"
            "        high: T.hotp(secret, 4294967296, 'SHA1', 8),"
            "        mixed: T.hotp(secret, 4294967297, 'SHA1', 8)};"
        )
        got = run_node(harness(body, TOTP_JS))
        self.assertNotEqual(
            got["zero"],
            got["high"],
            "counter 2**32 produced the same code as counter 0, so the high "
            "word is being discarded",
        )
        self.assertNotEqual(got["high"], got["mixed"])

    def test_a_uri_keeps_its_own_parameters(self) -> None:
        """A URI that says SHA512/8/60 must not be paired as SHA1/6/30."""

        body = (
            "const T = window.AmuletTOTP;"
            "return T.parseUri('otpauth://totp/Issuer:me?secret=JBSWY3DPEHPK3PXP"
            "&algorithm=SHA512&digits=8&period=60&issuer=Issuer');"
        )
        got = run_node(harness(body, TOTP_JS))
        self.assertEqual(got["algorithm"], "SHA512")
        self.assertEqual(got["digits"], 8)
        self.assertEqual(got["period"], 60)
        self.assertEqual(got["issuer"], "Issuer")
        self.assertEqual(got["account"], "me")

    def test_a_malformed_secret_is_refused_rather_than_guessed(self) -> None:
        body = (
            "const T = window.AmuletTOTP;"
            "const tries = ['', 'not base32 !!!', 'otpauth://totp/x'];"
            "return tries.map(t => {"
            "  try { T.decodeBase32(t); return null; }"
            "  catch (e) { return String(e.message); }"
            "});"
        )
        got = run_node(harness(body, TOTP_JS))
        for message in got:
            self.assertIsInstance(
                message, str, "a bad secret must raise rather than decode to something"
            )


class QrEncoderMatchesTheSpecification(unittest.TestCase):
    def test_reed_solomon_matches_the_published_block(self) -> None:
        body = (
            "const I = window.AmuletQR.internals;"
            "return I.rsEncode([32,91,11,120,209,114,220,77,67,64,236,17,236,17,236,17], 10);"
        )
        self.assertEqual(
            run_node(harness(body, QR_JS)),
            [196, 35, 39, 119, 235, 215, 231, 226, 93, 23],
        )

    def test_format_bits_match_all_eight_published_masks(self) -> None:
        body = (
            "const I = window.AmuletQR.internals;"
            "return [0,1,2,3,4,5,6,7].map(m => I.formatBits(m));"
        )
        self.assertEqual(
            run_node(harness(body, QR_JS)),
            [0x5412, 0x5125, 0x5E7C, 0x5B4B, 0x45F9, 0x40CE, 0x4F97, 0x4AA0],
        )

    def test_version_bits_match_the_published_table(self) -> None:
        """The obvious BCH transcription shifts by a negative amount past i=5,
        and JavaScript turns that into a shift by (32 + n) rather than an
        error, so the wrong number is produced silently."""

        body = (
            "const I = window.AmuletQR.internals;"
            "return {7: I.versionBits(7), 8: I.versionBits(8),"
            "        9: I.versionBits(9), 10: I.versionBits(10)};"
        )
        got = run_node(harness(body, QR_JS))
        self.assertEqual(got["7"], 0x07C94)
        self.assertEqual(got["8"], 0x085BC)
        self.assertEqual(got["9"], 0x09A99)
        self.assertEqual(got["10"], 0x0A4D3)

    def test_the_penalty_scores_hand_computable_matrices(self) -> None:
        """All-dark scores 798 (runs) + 1200 (2x2 blocks) + 100 (balance), and a
        perfect checkerboard scores nothing at all."""

        body = (
            "const N = 21;"
            "const dark = Array.from({length:N}, () => new Array(N).fill(1));"
            "const light = Array.from({length:N}, () => new Array(N).fill(0));"
            "const check = Array.from({length:N}, (_, r) =>"
            "  Array.from({length:N}, (_, c) => (r + c) % 2));"
            "const P = window.__penalty;"
            "return {dark: P(dark, N), light: P(light, N), check: P(check, N)};"
        )
        source = QR_JS.read_text(encoding="utf-8").replace(
            "window.AmuletQR = {", "window.__penalty = penalty; window.AmuletQR = {"
        )
        with tempfile.TemporaryDirectory() as tmp:
            patched = Path(tmp) / "qr.js"
            patched.write_text(source, encoding="utf-8")
            got = run_node(harness(body, patched))
        self.assertEqual(got["dark"], 2098)
        self.assertEqual(got["light"], 2098)
        self.assertEqual(got["check"], 0)

    def test_an_over_long_payload_is_refused_not_silently_truncated(self) -> None:
        body = (
            "try { window.AmuletQR.encode('x'.repeat(400)); return {refused: false}; }"
            "catch (e) { return {refused: true, message: String(e.message)}; }"
        )
        got = run_node(harness(body, QR_JS))
        self.assertTrue(got["refused"], "an oversized payload must not be truncated")
        self.assertIn("will not scan", got["message"])


class TheCryptoStaysLocal(unittest.TestCase):
    """A pairing QR handed to a remote service is a secret handed to a stranger."""

    def test_neither_file_reaches_the_network(self) -> None:
        for path in (TOTP_JS, QR_JS):
            source = path.read_text(encoding="utf-8")
            for needle in (
                "fetch(",
                "XMLHttpRequest",
                "WebSocket",
                "https://",
                "http://",
                "importScripts",
            ):
                with self.subTest(file=path.name, needle=needle):
                    # otpauth:// is a URI scheme, not a request; nothing else may appear.
                    self.assertNotIn(
                        needle,
                        source,
                        f"{path.name} must not reference {needle}: the secret would "
                        "leave the machine on its way to being drawn",
                    )


if __name__ == "__main__":
    unittest.main()
