/* The renderer-side half of the occupancy seam that closes
 * window.__AmuletViewportPanel.setSolidTest's stub: viewport-panel.js's
 * default solidTest used to be able to test the ray against nothing but the
 * reference grid's own y=0 plane, because the sidecar only ever streamed
 * whole meshed chunks to the GPU with no "what block is at x,y,z" call.
 *
 * amulet_map_editor/api/sidecar/mesh_methods.py now computes, alongside
 * every chunk's mesh in the SAME "viewport.chunk_mesh_batch" call, a packed
 * occupancy bitset -- one bit per block, solid or not -- for every sub-chunk
 * that chunk has. This module is the store that keeps those bitsets for the
 * chunks currently loaded and answers solidTest(x, y, z) from them in
 * constant time, with no IPC round trip on the picking ray's hot path.
 *
 * Bit layout (must match mesh_methods.py's OCCUPANCY_* doc comment exactly
 * -- an off-by-one here makes picking miss by one block everywhere, and it
 * reads as "the ray is slightly wrong" rather than as a packing bug):
 *   For local (in-sub-chunk) coordinates lx, ly, lz each in [0, 16):
 *     bitIndex   = (ly * 16 + lz) * 16 + lx
 *     byteIndex  = bitIndex >> 3
 *     bitInByte  = bitIndex & 7        (bit 0 = least-significant bit)
 *     solid      = (bytes[byteIndex] >> bitInByte) & 1 === 1
 *
 * A chunk (or a sub-chunk within one -- a column can be loaded up to y=80
 * and still have nothing above it) that has not streamed in yet answers
 * "not solid" rather than blocking the ray: picking is a best-effort probe
 * against whatever has actually loaded, not a query that should ever stall
 * the pointer on a cache miss. Air and, deliberately, water/lava are also
 * "not solid" -- see mesh_methods.py's _NON_SOLID_BASE_NAMES -- so a ray can
 * pass through the surface of a lake and pick the lakebed under it.
 */
(function (global) {
  "use strict";

  var DIM = 16;
  var BYTES_PER_SUB_CHUNK = (DIM * DIM * DIM) / 8; // 512

  function floorDiv(value, size) {
    return Math.floor(value / size);
  }

  function mod(value, size) {
    var m = value % size;
    return m < 0 ? m + size : m;
  }

  /**
   * Creates a store bounded to `maxChunks` loaded chunks' worth of
   * occupancy at once -- the same "drop it when the chunk is evicted, keep
   * memory bounded exactly as the mesh cache already is" contract
   * viewport-panel.js's own streaming loop follows for GPU buffers. Callers
   * are expected to call unloadChunk() whenever they call
   * viewport.unloadChunk(), and setChunk() is naturally re-entrant so a
   * re-requested chunk simply replaces its old entry.
   */
  function createOccupancyStore(maxChunks) {
    var limit = typeof maxChunks === "number" && maxChunks > 0 ? maxChunks : 512;
    var chunks = new Map(); // "cx,cz" -> Map(cy -> Uint8Array(512))
    var order = []; // insertion order, for the bound above

    function key(cx, cz) {
      return cx + "," + cz;
    }

    function evictIfNeeded() {
      while (order.length > limit) {
        var oldest = order.shift();
        chunks.delete(oldest);
      }
    }

    /**
     * Records one chunk's occupancy from a batch response.
     *
     * @param cx, cz          chunk coordinates
     * @param subChunksMeta   the "occupancy_sub_chunks" array from that
     *                        chunk's batch result entry: [{cy, byte_offset,
     *                        byte_length}, ...], offsets relative to the
     *                        start of the combined occupancy buffer
     * @param combinedBuffer  the raw ArrayBuffer read from the batch's
     *                        "occupancy_path" file (the whole batch's
     *                        combined buffer, shared across chunks)
     */
    function setChunk(cx, cz, subChunksMeta, combinedBuffer) {
      var k = key(cx, cz);
      var subChunks = new Map();
      for (var i = 0; i < (subChunksMeta ? subChunksMeta.length : 0); i++) {
        var meta = subChunksMeta[i];
        if (!meta || meta.byte_length !== BYTES_PER_SUB_CHUNK) continue; // malformed entry -- skip rather than throw
        subChunks.set(meta.cy, new Uint8Array(combinedBuffer, meta.byte_offset, meta.byte_length));
      }
      if (!chunks.has(k)) order.push(k);
      chunks.set(k, subChunks);
      evictIfNeeded();
    }

    function unloadChunk(cx, cz) {
      var k = key(cx, cz);
      chunks.delete(k);
      var idx = order.indexOf(k);
      if (idx !== -1) order.splice(idx, 1);
    }

    function clear() {
      chunks.clear();
      order = [];
    }

    /** How many chunks' occupancy are currently held -- exposed for tests. */
    function size() {
      return chunks.size;
    }

    /**
     * solidTest(x, y, z): true only when the block is known-loaded AND its
     * occupancy bit is set. Unknown chunk, unknown sub-chunk (nothing
     * meshed at that height), or an out-of-range byte -- all answer false,
     * never throw, so a picking ray never stalls or crashes on a cache miss
     * or a world edge.
     */
    function isSolid(x, y, z) {
      var cx = floorDiv(x, DIM);
      var cz = floorDiv(z, DIM);
      var cy = floorDiv(y, DIM);
      var subChunks = chunks.get(key(cx, cz));
      if (!subChunks) return false;
      var bytes = subChunks.get(cy);
      if (!bytes) return false;

      var lx = mod(x, DIM);
      var ly = mod(y, DIM);
      var lz = mod(z, DIM);
      var bitIndex = (ly * DIM + lz) * DIM + lx;
      var byteIndex = bitIndex >> 3;
      if (byteIndex >= bytes.length) return false;
      var bitInByte = bitIndex & 7;
      return ((bytes[byteIndex] >> bitInByte) & 1) === 1;
    }

    return {
      setChunk: setChunk,
      unloadChunk: unloadChunk,
      clear: clear,
      size: size,
      isSolid: isSolid,
    };
  }

  var api = {
    OCCUPANCY_DIM: DIM,
    OCCUPANCY_BYTES_PER_SUB_CHUNK: BYTES_PER_SUB_CHUNK,
    createOccupancyStore: createOccupancyStore,
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
  if (typeof global !== "undefined") {
    global.AmuletViewportOccupancy = api;
  }
})(typeof window !== "undefined" ? window : this);
