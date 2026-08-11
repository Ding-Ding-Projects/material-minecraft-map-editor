/* A QR encoder, byte mode, versions 1-10, error-correction level M.
 *
 * This exists because the pairing QR carries a shared secret. Every remote QR
 * service is handed that secret on the way to drawing it, so the only honest
 * way to render one is to render it here, in the page, with no request made.
 *
 * Scope is deliberately narrow: byte mode at level M covers an otpauth:// URI
 * comfortably at version 6-8, and refusing anything longer is better than
 * silently emitting a code that will not scan. The output is checked
 * module-for-module against an independent reference implementation in the
 * test suite, because "it looks like a QR code" is not evidence that a phone
 * can read it.
 */
(function () {
  "use strict";

  /* Total codewords, EC codewords per block, and the block layout for level M.
   * groups is [[blockCount, dataCodewordsPerBlock], ...]. */
  var VERSIONS = {
    1: { total: 26, ec: 10, groups: [[1, 16]] },
    2: { total: 44, ec: 16, groups: [[1, 28]] },
    3: { total: 70, ec: 26, groups: [[1, 44]] },
    4: { total: 100, ec: 18, groups: [[2, 32]] },
    5: { total: 134, ec: 24, groups: [[2, 43]] },
    6: { total: 172, ec: 16, groups: [[4, 27]] },
    7: { total: 196, ec: 18, groups: [[4, 31]] },
    8: { total: 242, ec: 22, groups: [[2, 38], [2, 39]] },
    9: { total: 292, ec: 22, groups: [[3, 36], [2, 37]] },
    10: { total: 346, ec: 26, groups: [[4, 43], [1, 44]] },
  };

  var ALIGNMENT = {
    1: [],
    2: [6, 18],
    3: [6, 22],
    4: [6, 26],
    5: [6, 30],
    6: [6, 34],
    7: [6, 22, 38],
    8: [6, 24, 42],
    9: [6, 26, 46],
    10: [6, 28, 50],
  };

  /* ------------------------------------------------------- Galois field */

  var EXP = new Array(512);
  var LOG = new Array(256);
  (function initTables() {
    var x = 1;
    for (var i = 0; i < 255; i++) {
      EXP[i] = x;
      LOG[x] = i;
      x <<= 1;
      if (x & 0x100) x ^= 0x11d;
    }
    for (i = 255; i < 512; i++) EXP[i] = EXP[i - 255];
  })();

  function gfMul(a, b) {
    if (a === 0 || b === 0) return 0;
    return EXP[LOG[a] + LOG[b]];
  }

  function rsGenerator(degree) {
    var poly = [1];
    for (var d = 0; d < degree; d++) {
      var next = new Array(poly.length + 1);
      for (var i = 0; i < next.length; i++) next[i] = 0;
      for (i = 0; i < poly.length; i++) {
        next[i] ^= poly[i];
        next[i + 1] ^= gfMul(poly[i], EXP[d]);
      }
      poly = next;
    }
    return poly;
  }

  function rsEncode(data, ecLength) {
    var gen = rsGenerator(ecLength);
    var remainder = new Array(ecLength);
    for (var i = 0; i < ecLength; i++) remainder[i] = 0;
    for (i = 0; i < data.length; i++) {
      var factor = data[i] ^ remainder[0];
      remainder.shift();
      remainder.push(0);
      for (var j = 0; j < gen.length - 1; j++) {
        remainder[j] ^= gfMul(gen[j + 1], factor);
      }
    }
    return remainder;
  }

  /* --------------------------------------------------------- bit stream */

  function utf8Bytes(text) {
    var out = [];
    for (var i = 0; i < text.length; i++) {
      var c = text.charCodeAt(i);
      if (c < 0x80) {
        out.push(c);
      } else if (c < 0x800) {
        out.push(0xc0 | (c >> 6), 0x80 | (c & 63));
      } else if (c >= 0xd800 && c <= 0xdbff && i + 1 < text.length) {
        var lo = text.charCodeAt(i + 1);
        var cp = 0x10000 + ((c - 0xd800) << 10) + (lo - 0xdc00);
        i++;
        out.push(
          0xf0 | (cp >> 18),
          0x80 | ((cp >> 12) & 63),
          0x80 | ((cp >> 6) & 63),
          0x80 | (cp & 63)
        );
      } else {
        out.push(0xe0 | (c >> 12), 0x80 | ((c >> 6) & 63), 0x80 | (c & 63));
      }
    }
    return out;
  }

  function chooseVersion(byteLength) {
    for (var v = 1; v <= 10; v++) {
      var spec = VERSIONS[v];
      var capacity = 0;
      spec.groups.forEach(function (g) {
        capacity += g[0] * g[1];
      });
      /* 4 mode bits plus the character-count field, which widens at v10. */
      var headerBits = 4 + (v < 10 ? 8 : 16);
      if (capacity * 8 >= headerBits + byteLength * 8) return v;
    }
    throw new Error(
      "that text needs a QR version above 10; this encoder refuses rather " +
        "than emitting a code that will not scan"
    );
  }

  function buildCodewords(text) {
    var data = utf8Bytes(text);
    var version = chooseVersion(data.length);
    var spec = VERSIONS[version];
    var dataCapacity = 0;
    spec.groups.forEach(function (g) {
      dataCapacity += g[0] * g[1];
    });

    var bits = [];
    function push(value, count) {
      for (var i = count - 1; i >= 0; i--) bits.push((value >> i) & 1);
    }
    push(0x4, 4); // byte mode
    push(data.length, version < 10 ? 8 : 16);
    for (var i = 0; i < data.length; i++) push(data[i], 8);

    /* Terminator, then pad to a byte boundary, then the alternating pad
     * codewords the spec names explicitly. */
    var remaining = dataCapacity * 8 - bits.length;
    push(0, Math.min(4, remaining));
    while (bits.length % 8 !== 0) bits.push(0);
    var codewords = [];
    for (i = 0; i < bits.length; i += 8) {
      var byte = 0;
      for (var b = 0; b < 8; b++) byte = (byte << 1) | bits[i + b];
      codewords.push(byte);
    }
    var pads = [0xec, 0x11];
    var p = 0;
    while (codewords.length < dataCapacity) {
      codewords.push(pads[p % 2]);
      p++;
    }

    /* Split into blocks, error-correct each, then interleave - the
     * interleaving is what makes a scratch across the printed code damage a
     * little of every block instead of destroying one entirely. */
    var blocks = [];
    var offset = 0;
    spec.groups.forEach(function (group) {
      for (var n = 0; n < group[0]; n++) {
        var chunk = codewords.slice(offset, offset + group[1]);
        offset += group[1];
        blocks.push({ data: chunk, ec: rsEncode(chunk, spec.ec) });
      }
    });

    var out = [];
    var maxData = 0;
    blocks.forEach(function (block) {
      maxData = Math.max(maxData, block.data.length);
    });
    for (i = 0; i < maxData; i++) {
      blocks.forEach(function (block) {
        if (i < block.data.length) out.push(block.data[i]);
      });
    }
    for (i = 0; i < spec.ec; i++) {
      blocks.forEach(function (block) {
        out.push(block.ec[i]);
      });
    }
    return { version: version, codewords: out };
  }

  /* ------------------------------------------------------------- matrix */

  function makeMatrix(version) {
    var size = version * 4 + 17;
    var modules = [];
    var reserved = [];
    for (var r = 0; r < size; r++) {
      modules.push(new Array(size).fill(0));
      reserved.push(new Array(size).fill(false));
    }

    function placeFinder(row, col) {
      for (var r = -1; r <= 7; r++) {
        for (var c = -1; c <= 7; c++) {
          var rr = row + r,
            cc = col + c;
          if (rr < 0 || rr >= size || cc < 0 || cc >= size) continue;
          var dark =
            r >= 0 && r <= 6 && (c === 0 || c === 6) ||
            c >= 0 && c <= 6 && (r === 0 || r === 6) ||
            (r >= 2 && r <= 4 && c >= 2 && c <= 4);
          modules[rr][cc] = dark ? 1 : 0;
          reserved[rr][cc] = true;
        }
      }
    }
    placeFinder(0, 0);
    placeFinder(0, size - 7);
    placeFinder(size - 7, 0);

    // timing patterns
    for (var i = 8; i < size - 8; i++) {
      modules[6][i] = i % 2 === 0 ? 1 : 0;
      modules[i][6] = i % 2 === 0 ? 1 : 0;
      reserved[6][i] = true;
      reserved[i][6] = true;
    }

    // alignment patterns, skipping the three finder corners
    var centers = ALIGNMENT[version];
    centers.forEach(function (row) {
      centers.forEach(function (col) {
        if (
          (row === 6 && col === 6) ||
          (row === 6 && col === size - 7) ||
          (row === size - 7 && col === 6)
        ) {
          return;
        }
        for (var r = -2; r <= 2; r++) {
          for (var c = -2; c <= 2; c++) {
            var dark = Math.max(Math.abs(r), Math.abs(c)) !== 1;
            modules[row + r][col + c] = dark ? 1 : 0;
            reserved[row + r][col + c] = true;
          }
        }
      });
    });

    // dark module and reserved format areas
    modules[size - 8][8] = 1;
    reserved[size - 8][8] = true;
    for (i = 0; i <= 8; i++) {
      if (!reserved[8][i]) reserved[8][i] = true;
      if (!reserved[i][8]) reserved[i][8] = true;
    }
    for (i = 0; i < 8; i++) {
      reserved[8][size - 1 - i] = true;
      reserved[size - 1 - i][8] = true;
    }

    // version information, versions 7 and up
    if (version >= 7) {
      var bch = versionBits(version);
      for (i = 0; i < 18; i++) {
        var bit = (bch >> i) & 1;
        var r1 = Math.floor(i / 3);
        var c1 = size - 11 + (i % 3);
        modules[r1][c1] = bit;
        reserved[r1][c1] = true;
        modules[c1][r1] = bit;
        reserved[c1][r1] = true;
      }
    }

    return { size: size, modules: modules, reserved: reserved };
  }

  /* BCH(18,6). The obvious transcription of this - xor the generator shifted
   * by (5 - i) - shifts by a negative amount once i passes 5, and JavaScript
   * turns a negative shift into a shift by (32 + n), quietly producing a
   * different number instead of an error. Feed the remainder through one bit
   * at a time so no shift count can ever go negative. */
  function versionBits(version) {
    var rem = version;
    for (var i = 0; i < 12; i++) {
      rem = ((rem << 1) ^ (((rem >>> 11) & 1) * 0x1f25)) & 0xfff;
    }
    return (((version << 12) | rem) >>> 0) & 0x3ffff;
  }

  function formatBits(mask) {
    /* Level M is 00 in the two format bits. */
    var value = (0x0 << 3) | mask;
    var rem = value << 10;
    for (var i = 0; i < 5; i++) {
      if (rem & (1 << (14 - i))) rem ^= 0x537 << (4 - i);
    }
    return ((value << 10) | rem) ^ 0x5412;
  }

  function placeData(grid, codewords) {
    var size = grid.size;
    var bitIndex = 0;
    var direction = -1;
    var row = size - 1;
    for (var col = size - 1; col > 0; col -= 2) {
      if (col === 6) col--; // the vertical timing column is not a data column
      while (true) {
        for (var c = 0; c < 2; c++) {
          var cc = col - c;
          if (!grid.reserved[row][cc]) {
            var bit = 0;
            if (bitIndex < codewords.length * 8) {
              bit = (codewords[bitIndex >> 3] >> (7 - (bitIndex & 7))) & 1;
            }
            grid.modules[row][cc] = bit;
            bitIndex++;
          }
        }
        row += direction;
        if (row < 0 || row >= size) {
          row -= direction;
          direction = -direction;
          break;
        }
      }
    }
  }

  function maskFn(mask, r, c) {
    switch (mask) {
      case 0: return (r + c) % 2 === 0;
      case 1: return r % 2 === 0;
      case 2: return c % 3 === 0;
      case 3: return (r + c) % 3 === 0;
      case 4: return (Math.floor(r / 2) + Math.floor(c / 3)) % 2 === 0;
      case 5: return ((r * c) % 2) + ((r * c) % 3) === 0;
      case 6: return (((r * c) % 2) + ((r * c) % 3)) % 2 === 0;
      default: return (((r + c) % 2) + ((r * c) % 3)) % 2 === 0;
    }
  }

  function applyMask(grid, mask) {
    var out = grid.modules.map(function (row) {
      return row.slice();
    });
    for (var r = 0; r < grid.size; r++) {
      for (var c = 0; c < grid.size; c++) {
        if (!grid.reserved[r][c] && maskFn(mask, r, c)) out[r][c] ^= 1;
      }
    }
    return out;
  }

  function writeFormat(modules, size, mask) {
    var bits = formatBits(mask);
    for (var i = 0; i < 15; i++) {
      var bit = (bits >> i) & 1;
      // vertical strip beside the top-left finder, then the horizontal one
      if (i < 6) modules[i][8] = bit;
      else if (i === 6) modules[7][8] = bit;
      else if (i === 7) modules[8][8] = bit;
      else if (i === 8) modules[8][7] = bit;
      else modules[8][14 - i] = bit;

      if (i < 8) modules[8][size - 1 - i] = bit;
      else modules[size - 15 + i][8] = bit;
    }
    modules[size - 8][8] = 1;
  }

  function penalty(modules, size) {
    var score = 0;
    var r, c, run, i;
    // rule 1: runs of five or more
    for (r = 0; r < size; r++) {
      run = 1;
      for (c = 1; c < size; c++) {
        if (modules[r][c] === modules[r][c - 1]) {
          run++;
        } else {
          if (run >= 5) score += run - 2;
          run = 1;
        }
      }
      if (run >= 5) score += run - 2;
    }
    for (c = 0; c < size; c++) {
      run = 1;
      for (r = 1; r < size; r++) {
        if (modules[r][c] === modules[r - 1][c]) {
          run++;
        } else {
          if (run >= 5) score += run - 2;
          run = 1;
        }
      }
      if (run >= 5) score += run - 2;
    }
    // rule 2: 2x2 blocks of one colour
    for (r = 0; r < size - 1; r++) {
      for (c = 0; c < size - 1; c++) {
        var v = modules[r][c];
        if (
          v === modules[r][c + 1] &&
          v === modules[r + 1][c] &&
          v === modules[r + 1][c + 1]
        ) {
          score += 3;
        }
      }
    }
    // rule 3: finder-like patterns
    var patternA = [1, 0, 1, 1, 1, 0, 1, 0, 0, 0, 0];
    var patternB = [0, 0, 0, 0, 1, 0, 1, 1, 1, 0, 1];
    function matches(get, start, pattern) {
      for (var k = 0; k < pattern.length; k++) {
        if (get(start + k) !== pattern[k]) return false;
      }
      return true;
    }
    for (r = 0; r < size; r++) {
      for (c = 0; c <= size - 11; c++) {
        var getRow = (function (row) {
          return function (x) {
            return modules[row][x];
          };
        })(r);
        if (matches(getRow, c, patternA)) score += 40;
        if (matches(getRow, c, patternB)) score += 40;
      }
    }
    for (c = 0; c < size; c++) {
      for (r = 0; r <= size - 11; r++) {
        var getCol = (function (col) {
          return function (x) {
            return modules[x][col];
          };
        })(c);
        if (matches(getCol, r, patternA)) score += 40;
        if (matches(getCol, r, patternB)) score += 40;
      }
    }
    // rule 4: overall balance of dark to light
    var dark = 0;
    for (r = 0; r < size; r++) {
      for (c = 0; c < size; c++) dark += modules[r][c];
    }
    var percent = (dark * 100) / (size * size);
    score += Math.floor(Math.abs(percent - 50) / 5) * 10;
    return score;
  }

  /* `options.mask` forces a mask instead of choosing one by penalty. It exists
   * for the test suite: comparing against a reference at a fixed mask
   * separates a data-path fault from a penalty-scoring one, and those two
   * failures look identical in the finished matrix. */
  function encode(text, options) {
    var opts = options || {};
    var built = buildCodewords(String(text));
    var grid = makeMatrix(built.version);
    placeData(grid, built.codewords);

    var best = null;
    var first = typeof opts.mask === "number" ? opts.mask : 0;
    var last = typeof opts.mask === "number" ? opts.mask : 7;
    for (var mask = first; mask <= last; mask++) {
      var candidate = applyMask(grid, mask);
      writeFormat(candidate, grid.size, mask);
      var score = penalty(candidate, grid.size);
      if (!best || score < best.score) {
        best = { score: score, modules: candidate, mask: mask };
      }
    }
    return {
      version: built.version,
      size: grid.size,
      mask: best.mask,
      modules: best.modules,
    };
  }

  /* Drawn with a real quiet zone and true black on true white regardless of
   * theme: a QR tinted into the page palette is a QR that reads poorly, and
   * the whole point of it is being read. */
  function draw(canvas, text, options) {
    var opts = options || {};
    var code = encode(text);
    var quiet = typeof opts.quiet === "number" ? opts.quiet : 4;
    var scale = Math.max(1, Math.floor(opts.scale || 4));
    var dimension = (code.size + quiet * 2) * scale;
    canvas.width = dimension;
    canvas.height = dimension;
    var ctx = canvas.getContext("2d");
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, dimension, dimension);
    ctx.fillStyle = "#000000";
    for (var r = 0; r < code.size; r++) {
      for (var c = 0; c < code.size; c++) {
        if (code.modules[r][c]) {
          ctx.fillRect(
            (c + quiet) * scale,
            (r + quiet) * scale,
            scale,
            scale
          );
        }
      }
    }
    return code;
  }

  /* The internals are exported so the test suite can check each stage against
   * a reference separately. A wrong Reed-Solomon block and a wrong data
   * placement produce the same symptom - a matrix that differs from the
   * reference - and testing only the finished matrix cannot tell them apart. */
  window.AmuletQR = {
    encode: encode,
    draw: draw,
    internals: {
      rsEncode: rsEncode,
      buildCodewords: buildCodewords,
      formatBits: formatBits,
      versionBits: versionBits,
      /* Render a matrix from codewords supplied by the caller. The test suite
       * uses this to feed a reference implementation's own codewords through
       * this file's placement, masking and format writing, which checks the
       * geometry without the comparison also depending on both encoders
       * choosing identical padding. */
      renderCodewords: function (version, codewords, mask) {
        var grid = makeMatrix(version);
        placeData(grid, codewords);
        var modules = applyMask(grid, mask);
        writeFormat(modules, grid.size, mask);
        return { size: grid.size, modules: modules };
      },
    },
  };
})();
