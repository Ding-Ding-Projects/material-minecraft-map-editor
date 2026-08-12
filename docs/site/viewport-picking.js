/* Ray-casting into the voxel world: cursor -> ray, ray -> first solid block.
 *
 * Both halves are pure functions -- no canvas, no GL, no Electron -- so they
 * are checked directly in Node against known camera matrices and known
 * geometry, the same discipline docs/site/viewport-webgl.js's camera math
 * already gets (see tests/test_viewport_picking_raycast.py). Nothing here
 * assumes a GPU exists.
 *
 * rayFromCamera() builds the world-space ray a screen point looks along,
 * using the exact yaw/pitch/forward convention viewport-webgl.js's mat4View
 * uses: yaw 0 looks toward -Z, positive pitch looks down. Any camera JSON
 * pulled from a live Viewport (camera.position/yaw/pitch, fovYRadians,
 * canvas aspect) can be handed straight in.
 *
 * voxelRaycast() marches that ray through the block grid with a 3D DDA
 * (Amanatides & Woo) rather than fixed-step sampling: fixed steps can jump
 * clean over a thin sliver of geometry and always cost one call to
 * isSolid() per step regardless of how far the nearest block actually is,
 * where a DDA visits exactly the voxels the ray passes through, in order,
 * and stops at the first solid one.
 */
(function (global) {
  "use strict";

  /** Right-handed camera basis, matching viewport-webgl.js's mat4View: yaw 0
   * looks toward -Z, positive pitch looks down. */
  function cameraBasis(yawRadians, pitchRadians) {
    var cosYaw = Math.cos(yawRadians);
    var sinYaw = Math.sin(yawRadians);
    var cosPitch = Math.cos(pitchRadians);
    var sinPitch = Math.sin(pitchRadians);
    var forward = [sinYaw * cosPitch, -sinPitch, -cosYaw * cosPitch];
    var right = [cosYaw, 0, sinYaw];
    var up = [
      right[1] * forward[2] - right[2] * forward[1],
      right[2] * forward[0] - right[0] * forward[2],
      right[0] * forward[1] - right[1] * forward[0],
    ];
    return { forward: forward, right: right, up: up };
  }

  function normalize(v) {
    var length = Math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]);
    if (length < 1e-12) return [0, 0, 0];
    return [v[0] / length, v[1] / length, v[2] / length];
  }

  /** Build the world-space ray the cursor points along.
   *
   * `camera` is `{position: [x,y,z], yaw: radians, pitch: radians}`.
   * `ndcX`/`ndcY` are the cursor in normalized device coordinates, each in
   * [-1, 1] with +X right and +Y up (i.e. already flipped from a DOM
   * pointer event's top-down clientY -- the caller does that flip, since
   * only it knows the canvas rect). `fovYRadians` and `aspect` match the
   * Viewport's own `fovYRadians` and `canvas.width / canvas.height`.
   *
   * Returns `{origin: [x,y,z], direction: [x,y,z]}` with `direction`
   * normalized.
   */
  function rayFromCamera(camera, fovYRadians, aspect, ndcX, ndcY) {
    var basis = cameraBasis(camera.yaw, camera.pitch);
    var tanHalfFovY = Math.tan(fovYRadians / 2);
    var tanHalfFovX = tanHalfFovY * aspect;
    var dx = ndcX * tanHalfFovX;
    var dy = ndcY * tanHalfFovY;
    var direction = [
      basis.forward[0] + basis.right[0] * dx + basis.up[0] * dy,
      basis.forward[1] + basis.right[1] * dx + basis.up[1] * dy,
      basis.forward[2] + basis.right[2] * dx + basis.up[2] * dy,
    ];
    return { origin: camera.position.slice(), direction: normalize(direction) };
  }

  function sign(x) {
    if (x > 0) return 1;
    if (x < 0) return -1;
    return 0;
  }

  /** March `origin + t*direction` through the block grid with a 3D DDA and
   * return the first block `isSolid(x, y, z)` accepts.
   *
   * Returns `{block: [x, y, z], face: [nx, ny, nz], distance: t}` or `null`
   * if nothing solid is hit within `maxDistance`. `face` is the outward
   * normal of the face the ray entered through -- the face a click should
   * "place against" -- and is `[0, 0, 0]` for the degenerate case of a ray
   * that starts inside a solid block (distance 0, no face was crossed).
   *
   * `isSolid` is called with integer block coordinates; the caller supplies
   * it (backed by whatever chunk data is loaded), so this module has no
   * knowledge of chunks, sidecar protocol, or which blocks exist.
   */
  function voxelRaycast(origin, direction, isSolid, maxDistance) {
    maxDistance = typeof maxDistance === "number" ? maxDistance : 256;
    var dir = normalize(direction);
    if (dir[0] === 0 && dir[1] === 0 && dir[2] === 0) return null;

    var x = Math.floor(origin[0]);
    var y = Math.floor(origin[1]);
    var z = Math.floor(origin[2]);

    if (isSolid(x, y, z)) {
      return { block: [x, y, z], face: [0, 0, 0], distance: 0 };
    }

    var stepX = sign(dir[0]);
    var stepY = sign(dir[1]);
    var stepZ = sign(dir[2]);

    function nextBoundaryT(originComponent, dirComponent, blockComponent, step) {
      if (dirComponent === 0) return Infinity;
      var boundary = step > 0 ? blockComponent + 1 : blockComponent;
      return (boundary - originComponent) / dirComponent;
    }

    var tMaxX = nextBoundaryT(origin[0], dir[0], x, stepX);
    var tMaxY = nextBoundaryT(origin[1], dir[1], y, stepY);
    var tMaxZ = nextBoundaryT(origin[2], dir[2], z, stepZ);

    var tDeltaX = dir[0] !== 0 ? Math.abs(1 / dir[0]) : Infinity;
    var tDeltaY = dir[1] !== 0 ? Math.abs(1 / dir[1]) : Infinity;
    var tDeltaZ = dir[2] !== 0 ? Math.abs(1 / dir[2]) : Infinity;

    var t = 0;
    var guard = 0;
    // A generous but finite step budget: maxDistance blocks along the
    // longest axis, times 3 for the worst-case diagonal march, plus slack.
    // This is a belt-and-braces bound against an isSolid() that never
    // returns true and a maxDistance the caller set absurdly high -- the
    // t > maxDistance check below is what normally ends the loop.
    var guardLimit = Math.ceil(maxDistance) * 3 + 64;

    while (t <= maxDistance && guard < guardLimit) {
      guard++;
      var normal;
      if (tMaxX < tMaxY && tMaxX < tMaxZ) {
        x += stepX;
        t = tMaxX;
        tMaxX += tDeltaX;
        normal = [-stepX, 0, 0];
      } else if (tMaxY < tMaxZ) {
        y += stepY;
        t = tMaxY;
        tMaxY += tDeltaY;
        normal = [0, -stepY, 0];
      } else {
        z += stepZ;
        t = tMaxZ;
        tMaxZ += tDeltaZ;
        normal = [0, 0, -stepZ];
      }
      if (t > maxDistance) break;
      if (isSolid(x, y, z)) {
        return { block: [x, y, z], face: normal, distance: t };
      }
    }
    return null;
  }

  var api = {
    cameraBasis: cameraBasis,
    normalize: normalize,
    rayFromCamera: rayFromCamera,
    voxelRaycast: voxelRaycast,
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
  if (typeof global !== "undefined") {
    global.AmuletViewportPicking = api;
  }
})(typeof window !== "undefined" ? window : this);
