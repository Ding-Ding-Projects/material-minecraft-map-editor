/* RFC 6238 TOTP over RFC 4226 HOTP, and a QR encoder, in plain JavaScript.
 *
 * Two constraints shaped every decision in this file.
 *
 * The first is that the page has to work from a file:// preview, and
 * crypto.subtle is unavailable outside a secure context. So the hashes are
 * implemented here rather than borrowed from the platform. That is more code
 * than calling WebCrypto, and it is the only version that works everywhere the
 * rest of this site works.
 *
 * The second is that a QR code carrying a shared secret must never be drawn by
 * asking a server to draw it. Every remote QR service is handed the secret on
 * the way to rendering it, which defeats the point of the pairing. So the
 * encoder is here too, byte mode, versions 1-10, drawn to a canvas locally.
 *
 * An authenticator that is subtly wrong produces codes every server rejects
 * with no error to read, so the whole surface is checked against the published
 * RFC 6238 vectors for all three hash functions.
 */
(function () {
  "use strict";

  /* ---------------------------------------------------------------- SHA-1 */

  function sha1(bytes) {
    var h = [0x67452301, 0xefcdab89, 0x98badcfe, 0x10325476, 0xc3d2e1f0];
    var msg = pad64(bytes, false);
    var w = new Array(80);
    for (var i = 0; i < msg.length; i += 64) {
      for (var t = 0; t < 16; t++) {
        w[t] =
          (msg[i + t * 4] << 24) |
          (msg[i + t * 4 + 1] << 16) |
          (msg[i + t * 4 + 2] << 8) |
          msg[i + t * 4 + 3];
      }
      for (t = 16; t < 80; t++) {
        w[t] = rotl32(w[t - 3] ^ w[t - 8] ^ w[t - 14] ^ w[t - 16], 1);
      }
      var a = h[0],
        b = h[1],
        c = h[2],
        d = h[3],
        e = h[4];
      for (t = 0; t < 80; t++) {
        var f, k;
        if (t < 20) {
          f = (b & c) | (~b & d);
          k = 0x5a827999;
        } else if (t < 40) {
          f = b ^ c ^ d;
          k = 0x6ed9eba1;
        } else if (t < 60) {
          f = (b & c) | (b & d) | (c & d);
          k = 0x8f1bbcdc;
        } else {
          f = b ^ c ^ d;
          k = 0xca62c1d6;
        }
        var tmp = (rotl32(a, 5) + f + e + k + w[t]) | 0;
        e = d;
        d = c;
        c = rotl32(b, 30);
        b = a;
        a = tmp;
      }
      h[0] = (h[0] + a) | 0;
      h[1] = (h[1] + b) | 0;
      h[2] = (h[2] + c) | 0;
      h[3] = (h[3] + d) | 0;
      h[4] = (h[4] + e) | 0;
    }
    return words32ToBytes(h);
  }

  /* -------------------------------------------------------------- SHA-256 */

  var K256 = [
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1,
    0x923f82a4, 0xab1c5ed5, 0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3,
    0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786,
    0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147,
    0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13,
    0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b,
    0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a,
    0x5b9cca4f, 0x682e6ff3, 0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208,
    0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
  ];

  function sha256(bytes) {
    var h = [
      0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c,
      0x1f83d9ab, 0x5be0cd19,
    ];
    var msg = pad64(bytes, false);
    var w = new Array(64);
    for (var i = 0; i < msg.length; i += 64) {
      for (var t = 0; t < 16; t++) {
        w[t] =
          (msg[i + t * 4] << 24) |
          (msg[i + t * 4 + 1] << 16) |
          (msg[i + t * 4 + 2] << 8) |
          msg[i + t * 4 + 3];
      }
      for (t = 16; t < 64; t++) {
        var s0 = rotr32(w[t - 15], 7) ^ rotr32(w[t - 15], 18) ^ (w[t - 15] >>> 3);
        var s1 = rotr32(w[t - 2], 17) ^ rotr32(w[t - 2], 19) ^ (w[t - 2] >>> 10);
        w[t] = (w[t - 16] + s0 + w[t - 7] + s1) | 0;
      }
      var a = h[0],
        b = h[1],
        c = h[2],
        d = h[3],
        e = h[4],
        f = h[5],
        g = h[6],
        hh = h[7];
      for (t = 0; t < 64; t++) {
        var S1 = rotr32(e, 6) ^ rotr32(e, 11) ^ rotr32(e, 25);
        var ch = (e & f) ^ (~e & g);
        var t1 = (hh + S1 + ch + K256[t] + w[t]) | 0;
        var S0 = rotr32(a, 2) ^ rotr32(a, 13) ^ rotr32(a, 22);
        var maj = (a & b) ^ (a & c) ^ (b & c);
        var t2 = (S0 + maj) | 0;
        hh = g;
        g = f;
        f = e;
        e = (d + t1) | 0;
        d = c;
        c = b;
        b = a;
        a = (t1 + t2) | 0;
      }
      h[0] = (h[0] + a) | 0;
      h[1] = (h[1] + b) | 0;
      h[2] = (h[2] + c) | 0;
      h[3] = (h[3] + d) | 0;
      h[4] = (h[4] + e) | 0;
      h[5] = (h[5] + f) | 0;
      h[6] = (h[6] + g) | 0;
      h[7] = (h[7] + hh) | 0;
    }
    return words32ToBytes(h);
  }

  /* -------------------------------------------------------------- SHA-512 */
  /* 64-bit arithmetic as [high, low] 32-bit pairs. JavaScript numbers cannot
   * hold a 64-bit integer exactly, and BigInt is far slower than the pairs for
   * a hash this size. */

  var K512 = [
    [0x428a2f98, 0xd728ae22], [0x71374491, 0x23ef65cd],
    [0xb5c0fbcf, 0xec4d3b2f], [0xe9b5dba5, 0x8189dbbc],
    [0x3956c25b, 0xf348b538], [0x59f111f1, 0xb605d019],
    [0x923f82a4, 0xaf194f9b], [0xab1c5ed5, 0xda6d8118],
    [0xd807aa98, 0xa3030242], [0x12835b01, 0x45706fbe],
    [0x243185be, 0x4ee4b28c], [0x550c7dc3, 0xd5ffb4e2],
    [0x72be5d74, 0xf27b896f], [0x80deb1fe, 0x3b1696b1],
    [0x9bdc06a7, 0x25c71235], [0xc19bf174, 0xcf692694],
    [0xe49b69c1, 0x9ef14ad2], [0xefbe4786, 0x384f25e3],
    [0x0fc19dc6, 0x8b8cd5b5], [0x240ca1cc, 0x77ac9c65],
    [0x2de92c6f, 0x592b0275], [0x4a7484aa, 0x6ea6e483],
    [0x5cb0a9dc, 0xbd41fbd4], [0x76f988da, 0x831153b5],
    [0x983e5152, 0xee66dfab], [0xa831c66d, 0x2db43210],
    [0xb00327c8, 0x98fb213f], [0xbf597fc7, 0xbeef0ee4],
    [0xc6e00bf3, 0x3da88fc2], [0xd5a79147, 0x930aa725],
    [0x06ca6351, 0xe003826f], [0x14292967, 0x0a0e6e70],
    [0x27b70a85, 0x46d22ffc], [0x2e1b2138, 0x5c26c926],
    [0x4d2c6dfc, 0x5ac42aed], [0x53380d13, 0x9d95b3df],
    [0x650a7354, 0x8baf63de], [0x766a0abb, 0x3c77b2a8],
    [0x81c2c92e, 0x47edaee6], [0x92722c85, 0x1482353b],
    [0xa2bfe8a1, 0x4cf10364], [0xa81a664b, 0xbc423001],
    [0xc24b8b70, 0xd0f89791], [0xc76c51a3, 0x0654be30],
    [0xd192e819, 0xd6ef5218], [0xd6990624, 0x5565a910],
    [0xf40e3585, 0x5771202a], [0x106aa070, 0x32bbd1b8],
    [0x19a4c116, 0xb8d2d0c8], [0x1e376c08, 0x5141ab53],
    [0x2748774c, 0xdf8eeb99], [0x34b0bcb5, 0xe19b48a8],
    [0x391c0cb3, 0xc5c95a63], [0x4ed8aa4a, 0xe3418acb],
    [0x5b9cca4f, 0x7763e373], [0x682e6ff3, 0xd6b2b8a3],
    [0x748f82ee, 0x5defb2fc], [0x78a5636f, 0x43172f60],
    [0x84c87814, 0xa1f0ab72], [0x8cc70208, 0x1a6439ec],
    [0x90befffa, 0x23631e28], [0xa4506ceb, 0xde82bde9],
    [0xbef9a3f7, 0xb2c67915], [0xc67178f2, 0xe372532b],
    [0xca273ece, 0xea26619c], [0xd186b8c7, 0x21c0c207],
    [0xeada7dd6, 0xcde0eb1e], [0xf57d4f7f, 0xee6ed178],
    [0x06f067aa, 0x72176fba], [0x0a637dc5, 0xa2c898a6],
    [0x113f9804, 0xbef90dae], [0x1b710b35, 0x131c471b],
    [0x28db77f5, 0x23047d84], [0x32caab7b, 0x40c72493],
    [0x3c9ebe0a, 0x15c9bebc], [0x431d67c4, 0x9c100d4c],
    [0x4cc5d4be, 0xcb3e42b6], [0x597f299c, 0xfc657e2a],
    [0x5fcb6fab, 0x3ad6faec], [0x6c44198c, 0x4a475817],
  ];

  function add64(a, b) {
    var lo = (a[1] >>> 0) + (b[1] >>> 0);
    var hi = (a[0] >>> 0) + (b[0] >>> 0) + (lo > 0xffffffff ? 1 : 0);
    return [hi >>> 0, lo >>> 0];
  }
  function xor64(a, b) {
    return [(a[0] ^ b[0]) >>> 0, (a[1] ^ b[1]) >>> 0];
  }
  function rotr64(x, n) {
    var hi = x[0] >>> 0,
      lo = x[1] >>> 0;
    if (n === 32) return [lo, hi];
    if (n < 32) {
      return [
        ((hi >>> n) | (lo << (32 - n))) >>> 0,
        ((lo >>> n) | (hi << (32 - n))) >>> 0,
      ];
    }
    n -= 32;
    return [
      ((lo >>> n) | (hi << (32 - n))) >>> 0,
      ((hi >>> n) | (lo << (32 - n))) >>> 0,
    ];
  }
  function shr64(x, n) {
    var hi = x[0] >>> 0,
      lo = x[1] >>> 0;
    if (n < 32) {
      return [hi >>> n, ((lo >>> n) | (hi << (32 - n))) >>> 0];
    }
    return [0, hi >>> (n - 32)];
  }

  function sha512(bytes) {
    var h = [
      [0x6a09e667, 0xf3bcc908], [0xbb67ae85, 0x84caa73b],
      [0x3c6ef372, 0xfe94f82b], [0xa54ff53a, 0x5f1d36f1],
      [0x510e527f, 0xade682d1], [0x9b05688c, 0x2b3e6c1f],
      [0x1f83d9ab, 0xfb41bd6b], [0x5be0cd19, 0x137e2179],
    ];
    var msg = pad128(bytes);
    var w = new Array(80);
    for (var i = 0; i < msg.length; i += 128) {
      for (var t = 0; t < 16; t++) {
        var o = i + t * 8;
        w[t] = [
          ((msg[o] << 24) | (msg[o + 1] << 16) | (msg[o + 2] << 8) | msg[o + 3]) >>> 0,
          ((msg[o + 4] << 24) | (msg[o + 5] << 16) | (msg[o + 6] << 8) | msg[o + 7]) >>> 0,
        ];
      }
      for (t = 16; t < 80; t++) {
        var s0 = xor64(xor64(rotr64(w[t - 15], 1), rotr64(w[t - 15], 8)), shr64(w[t - 15], 7));
        var s1 = xor64(xor64(rotr64(w[t - 2], 19), rotr64(w[t - 2], 61)), shr64(w[t - 2], 6));
        w[t] = add64(add64(add64(w[t - 16], s0), w[t - 7]), s1);
      }
      var a = h[0], b = h[1], c = h[2], d = h[3];
      var e = h[4], f = h[5], g = h[6], hh = h[7];
      for (t = 0; t < 80; t++) {
        var S1 = xor64(xor64(rotr64(e, 14), rotr64(e, 18)), rotr64(e, 41));
        var ch = [
          ((e[0] & f[0]) ^ (~e[0] & g[0])) >>> 0,
          ((e[1] & f[1]) ^ (~e[1] & g[1])) >>> 0,
        ];
        var t1 = add64(add64(add64(add64(hh, S1), ch), K512[t]), w[t]);
        var S0 = xor64(xor64(rotr64(a, 28), rotr64(a, 34)), rotr64(a, 39));
        var maj = [
          ((a[0] & b[0]) ^ (a[0] & c[0]) ^ (b[0] & c[0])) >>> 0,
          ((a[1] & b[1]) ^ (a[1] & c[1]) ^ (b[1] & c[1])) >>> 0,
        ];
        var t2 = add64(S0, maj);
        hh = g; g = f; f = e;
        e = add64(d, t1);
        d = c; c = b; b = a;
        a = add64(t1, t2);
      }
      h[0] = add64(h[0], a); h[1] = add64(h[1], b);
      h[2] = add64(h[2], c); h[3] = add64(h[3], d);
      h[4] = add64(h[4], e); h[5] = add64(h[5], f);
      h[6] = add64(h[6], g); h[7] = add64(h[7], hh);
    }
    var out = [];
    for (i = 0; i < h.length; i++) {
      out.push(
        (h[i][0] >>> 24) & 0xff, (h[i][0] >>> 16) & 0xff,
        (h[i][0] >>> 8) & 0xff, h[i][0] & 0xff,
        (h[i][1] >>> 24) & 0xff, (h[i][1] >>> 16) & 0xff,
        (h[i][1] >>> 8) & 0xff, h[i][1] & 0xff
      );
    }
    return out;
  }

  /* --------------------------------------------------------------- shared */

  function rotl32(n, b) {
    return ((n << b) | (n >>> (32 - b))) | 0;
  }
  function rotr32(n, b) {
    return ((n >>> b) | (n << (32 - b))) | 0;
  }
  function words32ToBytes(words) {
    var out = [];
    for (var i = 0; i < words.length; i++) {
      out.push(
        (words[i] >>> 24) & 0xff,
        (words[i] >>> 16) & 0xff,
        (words[i] >>> 8) & 0xff,
        words[i] & 0xff
      );
    }
    return out;
  }

  /* Both padding schemes append 0x80, then zeros, then the bit length. The
   * only difference is the block size and the width of that length field. */
  function pad64(bytes) {
    var len = bytes.length;
    var bitLenHi = Math.floor((len * 8) / 0x100000000);
    var bitLenLo = (len * 8) >>> 0;
    var out = bytes.slice();
    out.push(0x80);
    while (out.length % 64 !== 56) out.push(0);
    out.push(
      (bitLenHi >>> 24) & 0xff, (bitLenHi >>> 16) & 0xff,
      (bitLenHi >>> 8) & 0xff, bitLenHi & 0xff,
      (bitLenLo >>> 24) & 0xff, (bitLenLo >>> 16) & 0xff,
      (bitLenLo >>> 8) & 0xff, bitLenLo & 0xff
    );
    return out;
  }

  function pad128(bytes) {
    var len = bytes.length;
    var bitLenHi = Math.floor((len * 8) / 0x100000000);
    var bitLenLo = (len * 8) >>> 0;
    var out = bytes.slice();
    out.push(0x80);
    while (out.length % 128 !== 112) out.push(0);
    for (var i = 0; i < 8; i++) out.push(0);
    out.push(
      (bitLenHi >>> 24) & 0xff, (bitLenHi >>> 16) & 0xff,
      (bitLenHi >>> 8) & 0xff, bitLenHi & 0xff,
      (bitLenLo >>> 24) & 0xff, (bitLenLo >>> 16) & 0xff,
      (bitLenLo >>> 8) & 0xff, bitLenLo & 0xff
    );
    return out;
  }

  var ALGORITHMS = {
    SHA1: { fn: sha1, block: 64 },
    SHA256: { fn: sha256, block: 64 },
    SHA512: { fn: sha512, block: 128 },
  };

  function hmac(algorithm, key, message) {
    var spec = ALGORITHMS[algorithm];
    if (!spec) throw new Error("unsupported algorithm: " + algorithm);
    var k = key.slice();
    if (k.length > spec.block) k = spec.fn(k);
    while (k.length < spec.block) k.push(0);
    var inner = [],
      outer = [];
    for (var i = 0; i < spec.block; i++) {
      inner.push(k[i] ^ 0x36);
      outer.push(k[i] ^ 0x5c);
    }
    return spec.fn(outer.concat(spec.fn(inner.concat(message))));
  }

  /* --------------------------------------------------------------- base32 */

  var B32 = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";

  function decodeBase32(text) {
    var clean = String(text || "")
      .toUpperCase()
      .replace(/[\s-]/g, "")
      .replace(/=+$/, "");
    if (!clean) throw new Error("the secret is empty");
    var bits = 0,
      value = 0,
      out = [];
    for (var i = 0; i < clean.length; i++) {
      var idx = B32.indexOf(clean.charAt(i));
      if (idx < 0) {
        throw new Error(
          "the secret has a character base32 does not use: " + clean.charAt(i)
        );
      }
      value = (value << 5) | idx;
      bits += 5;
      if (bits >= 8) {
        out.push((value >>> (bits - 8)) & 0xff);
        bits -= 8;
      }
    }
    if (!out.length) throw new Error("the secret decoded to no bytes");
    return out;
  }

  function encodeBase32(bytes) {
    var bits = 0,
      value = 0,
      out = "";
    for (var i = 0; i < bytes.length; i++) {
      value = (value << 8) | bytes[i];
      bits += 8;
      while (bits >= 5) {
        out += B32.charAt((value >>> (bits - 5)) & 31);
        bits -= 5;
      }
    }
    if (bits > 0) out += B32.charAt((value << (5 - bits)) & 31);
    return out;
  }

  /* ----------------------------------------------------------------- TOTP */

  function counterBytes(counter) {
    var out = new Array(8);
    var hi = Math.floor(counter / 0x100000000);
    var lo = counter >>> 0;
    out[0] = (hi >>> 24) & 0xff;
    out[1] = (hi >>> 16) & 0xff;
    out[2] = (hi >>> 8) & 0xff;
    out[3] = hi & 0xff;
    out[4] = (lo >>> 24) & 0xff;
    out[5] = (lo >>> 16) & 0xff;
    out[6] = (lo >>> 8) & 0xff;
    out[7] = lo & 0xff;
    return out;
  }

  function hotp(secretBytes, counter, algorithm, digits) {
    var mac = hmac(algorithm || "SHA1", secretBytes, counterBytes(counter));
    var offset = mac[mac.length - 1] & 0x0f;
    var binary =
      ((mac[offset] & 0x7f) << 24) |
      ((mac[offset + 1] & 0xff) << 16) |
      ((mac[offset + 2] & 0xff) << 8) |
      (mac[offset + 3] & 0xff);
    var mod = Math.pow(10, digits || 6);
    var code = String(binary % mod);
    while (code.length < (digits || 6)) code = "0" + code;
    return code;
  }

  /* `seconds` is passed in rather than read from the clock so the caller owns
   * the time source, which is what makes the RFC vectors checkable at all. */
  function totp(options) {
    var opts = options || {};
    var secret =
      opts.secretBytes || decodeBase32(opts.secret || "");
    var period = opts.period || 30;
    var seconds = typeof opts.seconds === "number" ? opts.seconds : 0;
    var counter = Math.floor((seconds - (opts.t0 || 0)) / period);
    return hotp(secret, counter, opts.algorithm || "SHA1", opts.digits || 6);
  }

  /* -------------------------------------------------------- otpauth:// URI */

  function buildUri(entry) {
    var issuer = String(entry.issuer || "").trim();
    var account = String(entry.account || "").trim();
    var label = issuer ? issuer + ":" + account : account;
    var params = [
      "secret=" + encodeURIComponent(entry.secret),
      "algorithm=" + (entry.algorithm || "SHA1"),
      "digits=" + (entry.digits || 6),
      "period=" + (entry.period || 30),
    ];
    if (issuer) params.push("issuer=" + encodeURIComponent(issuer));
    return "otpauth://totp/" + encodeURIComponent(label) + "?" + params.join("&");
  }

  /* A URI carries its own parameters, so honour them rather than overwriting
   * them with this site's defaults - a 8-digit SHA256 issuer is rare but real,
   * and silently pairing it as 6-digit SHA1 produces codes nothing accepts. */
  function parseUri(text) {
    var raw = String(text || "").trim();
    if (!/^otpauth:\/\/totp\//i.test(raw)) {
      throw new Error("that is not an otpauth://totp/ URI");
    }
    var qIndex = raw.indexOf("?");
    var label = decodeURIComponent(
      raw.slice("otpauth://totp/".length, qIndex < 0 ? raw.length : qIndex)
    );
    var query = qIndex < 0 ? "" : raw.slice(qIndex + 1);
    var params = {};
    query.split("&").forEach(function (pair) {
      if (!pair) return;
      var eq = pair.indexOf("=");
      var key = eq < 0 ? pair : pair.slice(0, eq);
      var value = eq < 0 ? "" : decodeURIComponent(pair.slice(eq + 1));
      params[key.toLowerCase()] = value;
    });
    if (!params.secret) throw new Error("the URI carries no secret");
    decodeBase32(params.secret);
    var issuer = params.issuer || "";
    var account = label;
    var colon = label.indexOf(":");
    if (colon >= 0) {
      if (!issuer) issuer = label.slice(0, colon);
      account = label.slice(colon + 1);
    }
    var algorithm = String(params.algorithm || "SHA1").toUpperCase();
    if (!ALGORITHMS[algorithm]) {
      throw new Error("unsupported algorithm in the URI: " + algorithm);
    }
    var digits = parseInt(params.digits || "6", 10);
    if (!(digits >= 6 && digits <= 8)) {
      throw new Error("digits must be 6, 7, or 8; the URI said " + params.digits);
    }
    var period = parseInt(params.period || "30", 10);
    if (!(period > 0 && period <= 300)) {
      throw new Error("period is out of range: " + params.period);
    }
    return {
      issuer: issuer.trim(),
      account: account.trim(),
      secret: params.secret.replace(/\s/g, "").toUpperCase(),
      algorithm: algorithm,
      digits: digits,
      period: period,
    };
  }

  window.AmuletTOTP = {
    sha1: sha1,
    sha256: sha256,
    sha512: sha512,
    hmac: hmac,
    hotp: hotp,
    totp: totp,
    decodeBase32: decodeBase32,
    encodeBase32: encodeBase32,
    buildUri: buildUri,
    parseUri: parseUri,
    algorithms: ["SHA1", "SHA256", "SHA512"],
  };
})();
