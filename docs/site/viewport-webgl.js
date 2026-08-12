/* A WebGL2 renderer for one real, meshed Minecraft chunk.
 *
 * The design is fixed (see docs/articles/webgl2-viewport.md): meshing stays
 * in Python -- amulet_map_editor.api.opengl.mesh.level.chunk.chunk_builder_cy
 * already produces exactly what a GPU wants, an interleaved float32 array
 * of position(vec3) texcoord(vec2) texoffset(vec4) tint(vec3) -- and only
 * the camera, the draw loop and the buffer uploads live here. The shaders
 * below are a mechanical GLSL ES 300 port of
 * amulet_map_editor/api/opengl/shaders/render_chunk_330.vert/.frag: same
 * uniforms, same attribute layout, same fragment math.
 *
 * This module knows nothing about Electron, IPC or the sidecar protocol --
 * it is handed raw bytes (an ArrayBuffer/Uint8Array for the mesh, an
 * ImageBitmap or {bytes,width,height} for the atlas) and a <canvas>, and it
 * draws. Wiring it to `window.mmweDesktop.sidecar` and
 * `window.mmweDesktop.sidecar.readBinary` is the caller's job (see
 * electron/viewport-harness.js, the one real call site so far).
 */
(function (global) {
  "use strict";

  var VERTEX_STRIDE_FLOATS = 12; // position(3) texcoord(2) texoffset(4) tint(3)

  var VERTEX_SHADER_SOURCE = [
    "#version 300 es",
    "layout(location = 0) in vec3 positions;",
    "layout(location = 1) in vec2 vTexCoord;",
    "layout(location = 2) in vec4 vTexOffset;",
    "layout(location = 3) in vec3 vTint;",
    "",
    "out vec2 fTexCoord;",
    "out vec4 fTexOffset;",
    "out vec3 fTint;",
    "",
    "uniform mat4 transformation_matrix;",
    "",
    "void main(){",
    "    gl_Position = transformation_matrix * vec4(positions, 1.0);",
    "    fTexCoord = vTexCoord;",
    "    fTexOffset = vTexOffset;",
    "    fTint = vTint;",
    "}",
  ].join("\n");

  var FRAGMENT_SHADER_SOURCE = [
    "#version 300 es",
    "precision highp float;",
    "in vec2 fTexCoord;",
    "in vec4 fTexOffset;",
    "in vec3 fTint;",
    "",
    "out vec4 outColor;",
    "",
    "uniform sampler2D image;",
    "",
    "void main(){",
    "    vec4 texColor = texture(",
    "        image,",
    "        vec2(",
    "            mix(fTexOffset.x, fTexOffset.z, mod(fTexCoord.x, 1.0)),",
    "            mix(fTexOffset.y, fTexOffset.w, mod(fTexCoord.y, 1.0))",
    "        )",
    "    );",
    "    if (texColor.a < 0.02) discard;",
    "    texColor.rgb = texColor.rgb * fTint * 0.85;",
    "    outColor = texColor;",
    "}",
  ].join("\n");

  function compileShader(gl, type, source) {
    var shader = gl.createShader(type);
    gl.shaderSource(shader, source);
    gl.compileShader(shader);
    if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
      var log = gl.getShaderInfoLog(shader);
      gl.deleteShader(shader);
      throw new Error("Shader compile failed: " + log);
    }
    return shader;
  }

  function linkProgram(gl, vertexSource, fragmentSource) {
    var vertex = compileShader(gl, gl.VERTEX_SHADER, vertexSource);
    var fragment = compileShader(gl, gl.FRAGMENT_SHADER, fragmentSource);
    var program = gl.createProgram();
    gl.attachShader(program, vertex);
    gl.attachShader(program, fragment);
    gl.linkProgram(program);
    gl.deleteShader(vertex);
    gl.deleteShader(fragment);
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
      var log = gl.getProgramInfoLog(program);
      gl.deleteProgram(program);
      throw new Error("Program link failed: " + log);
    }
    return program;
  }

  // --- Minimal column-major 4x4 matrix helpers (the WebGL convention;
  // Float32Array(16) laid out so element [column*4 + row] is M[row][col]).
  // Deliberately hand-rolled rather than pulling in a matrix library --
  // this is the entire matrix surface the viewport needs.

  function mat4Identity() {
    var m = new Float32Array(16);
    m[0] = m[5] = m[10] = m[15] = 1;
    return m;
  }

  function mat4Multiply(a, b) {
    var out = new Float32Array(16);
    for (var col = 0; col < 4; col++) {
      for (var row = 0; row < 4; row++) {
        var sum = 0;
        for (var k = 0; k < 4; k++) {
          sum += a[k * 4 + row] * b[col * 4 + k];
        }
        out[col * 4 + row] = sum;
      }
    }
    return out;
  }

  function mat4Perspective(fovyRadians, aspect, near, far) {
    var f = 1 / Math.tan(fovyRadians / 2);
    var m = new Float32Array(16);
    m[0] = f / aspect;
    m[5] = f;
    m[10] = (far + near) / (near - far);
    m[11] = -1;
    m[14] = (2 * far * near) / (near - far);
    return m;
  }

  // Right-handed look-from/yaw/pitch camera, Minecraft-style angles: yaw 0
  // looks toward -Z, pitch positive looks down (matching
  // amulet_map_editor.api.opengl.matrix.rotation_matrix_yx's convention).
  function mat4View(position, yawRadians, pitchRadians) {
    var cosYaw = Math.cos(yawRadians);
    var sinYaw = Math.sin(yawRadians);
    var cosPitch = Math.cos(pitchRadians);
    var sinPitch = Math.sin(pitchRadians);

    // Camera basis vectors in world space.
    var forward = [sinYaw * cosPitch, -sinPitch, -cosYaw * cosPitch];
    var right = [cosYaw, 0, sinYaw];
    var up = [
      right[1] * forward[2] - right[2] * forward[1],
      right[2] * forward[0] - right[0] * forward[2],
      right[0] * forward[1] - right[1] * forward[0],
    ];

    function dot(a, b) {
      return a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
    }

    var m = new Float32Array(16);
    m[0] = right[0];
    m[4] = right[1];
    m[8] = right[2];
    m[1] = up[0];
    m[5] = up[1];
    m[9] = up[2];
    m[2] = -forward[0];
    m[6] = -forward[1];
    m[10] = -forward[2];
    m[15] = 1;
    m[12] = -dot(right, position);
    m[13] = -dot(up, position);
    m[14] = dot(forward, position);
    return m;
  }

  function setupVertexAttribs(gl, vbo) {
    gl.bindBuffer(gl.ARRAY_BUFFER, vbo);
    var stride = VERTEX_STRIDE_FLOATS * 4;
    var attrs = [
      { index: 0, size: 3, offset: 0 },
      { index: 1, size: 2, offset: 3 * 4 },
      { index: 2, size: 4, offset: 5 * 4 },
      { index: 3, size: 3, offset: 9 * 4 },
    ];
    for (var i = 0; i < attrs.length; i++) {
      var a = attrs[i];
      gl.vertexAttribPointer(a.index, a.size, gl.FLOAT, false, stride, a.offset);
      gl.enableVertexAttribArray(a.index);
    }
  }

  var CHUNK_SIZE = 16;

  function Viewport(canvas) {
    // preserveDrawingBuffer is needed so a synchronous canvas.toDataURL()
    // readback right after render() reliably sees this frame's pixels
    // rather than a browser-timed clear.
    var gl = canvas.getContext("webgl2", { antialias: true, preserveDrawingBuffer: true });
    if (!gl) {
      throw new Error("WebGL2 is not available in this renderer");
    }
    this.gl = gl;
    this.canvas = canvas;
    this.program = linkProgram(gl, VERTEX_SHADER_SOURCE, FRAGMENT_SHADER_SOURCE);
    this.transformLocation = gl.getUniformLocation(this.program, "transformation_matrix");
    this.imageLocation = gl.getUniformLocation(this.program, "image");

    // Kept for backward compatibility with the single-chunk proof harness:
    // loadMesh()/vertexCount still upload into this one legacy VAO/VBO and
    // render() still draws it first (at chunk-local origin, i.e. as if it
    // were chunk (0, 0)) when it holds any vertices.
    this.vao = gl.createVertexArray();
    gl.bindVertexArray(this.vao);
    this.vbo = gl.createBuffer();
    setupVertexAttribs(gl, this.vbo);
    gl.bindVertexArray(null);
    this.vertexCount = 0;

    // Streamed chunks, keyed by "cx,cz". Each entry owns its own VAO/VBO
    // (mesh vertices arrive chunk-local, 0..16) and is drawn with a
    // per-chunk model translation of (cx*16, 0, cz*16) baked into the
    // uploaded transform -- see render().
    this.chunks = {};
    this.chunkCount = 0;

    this.texture = gl.createTexture();

    this.camera = { position: [8, 20, 8], yaw: 0, pitch: 0.5 };
    this.fovYRadians = (70 * Math.PI) / 180;
    this.near = 0.1;
    this.far = 1000;
    this.clearColor = [0.53, 0.75, 0.93, 1.0]; // Minecraft-ish sky blue

    gl.enable(gl.DEPTH_TEST);
    gl.enable(gl.CULL_FACE);
    gl.enable(gl.BLEND);
    gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);

    // World vertical bounds used only for frustum-culling chunk AABBs (the
    // mesher does not hand this renderer per-chunk height data). Overridable
    // via setWorldHeightBounds() when a real level's bounds are known.
    this.worldMinY = DEFAULT_WORLD_MIN_Y;
    this.worldMaxY = DEFAULT_WORLD_MAX_Y;

    // Frustum culling is opt-in (default on) so the camera-only unit tests
    // and the single-chunk proof harness keep working unchanged.
    this.frustumCullingEnabled = true;
  }

  /** Override the vertical span used for chunk frustum-culling AABBs. */
  Viewport.prototype.setWorldHeightBounds = function (minY, maxY) {
    this.worldMinY = minY;
    this.worldMaxY = maxY;
  };

  /** Upload one chunk's interleaved float32 vertex buffer (legacy single-chunk API). */
  Viewport.prototype.loadMesh = function (arrayBuffer, vertexCount) {
    var gl = this.gl;
    gl.bindBuffer(gl.ARRAY_BUFFER, this.vbo);
    gl.bufferData(gl.ARRAY_BUFFER, arrayBuffer, gl.STATIC_DRAW);
    gl.bindBuffer(gl.ARRAY_BUFFER, null);
    this.vertexCount = vertexCount;
  };

  function chunkKey(cx, cz) {
    return cx + "," + cz;
  }

  /** Upload (or replace) chunk (cx, cz)'s interleaved float32 vertex buffer.
   * Vertices are chunk-local; render() applies the (cx*16, 0, cz*16) world
   * translation. Safe to call again for an already-loaded chunk (re-mesh). */
  Viewport.prototype.loadChunkMesh = function (cx, cz, arrayBuffer, vertexCount) {
    var gl = this.gl;
    var key = chunkKey(cx, cz);
    var entry = this.chunks[key];
    if (!entry) {
      entry = { vao: gl.createVertexArray(), vbo: gl.createBuffer(), vertexCount: 0, cx: cx, cz: cz };
      gl.bindVertexArray(entry.vao);
      setupVertexAttribs(gl, entry.vbo);
      gl.bindVertexArray(null);
      this.chunks[key] = entry;
      this.chunkCount++;
    }
    gl.bindBuffer(gl.ARRAY_BUFFER, entry.vbo);
    gl.bufferData(gl.ARRAY_BUFFER, arrayBuffer, gl.STATIC_DRAW);
    gl.bindBuffer(gl.ARRAY_BUFFER, null);
    entry.vertexCount = vertexCount;
  };

  /** Release chunk (cx, cz)'s GPU buffers so streaming out of range does not
   * grow GPU memory without bound. A no-op if that chunk was never loaded. */
  Viewport.prototype.unloadChunk = function (cx, cz) {
    var gl = this.gl;
    var key = chunkKey(cx, cz);
    var entry = this.chunks[key];
    if (!entry) return;
    gl.deleteBuffer(entry.vbo);
    gl.deleteVertexArray(entry.vao);
    delete this.chunks[key];
    this.chunkCount--;
  };

  Viewport.prototype.hasChunk = function (cx, cz) {
    return Object.prototype.hasOwnProperty.call(this.chunks, chunkKey(cx, cz));
  };

  /** cx,cz of every chunk currently resident on the GPU. */
  Viewport.prototype.loadedChunkCoords = function () {
    var out = [];
    for (var key in this.chunks) {
      if (!Object.prototype.hasOwnProperty.call(this.chunks, key)) continue;
      var entry = this.chunks[key];
      out.push([entry.cx, entry.cz]);
    }
    return out;
  };

  /** Upload the texture atlas from raw RGBA8 bytes (width x height x 4). */
  Viewport.prototype.loadAtlasRGBA = function (rgbaBytes, width, height) {
    var gl = this.gl;
    gl.bindTexture(gl.TEXTURE_2D, this.texture);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    gl.texImage2D(
      gl.TEXTURE_2D,
      0,
      gl.RGBA,
      width,
      height,
      0,
      gl.RGBA,
      gl.UNSIGNED_BYTE,
      rgbaBytes
    );
    gl.bindTexture(gl.TEXTURE_2D, null);
  };

  /** Upload the texture atlas from a decoded ImageBitmap (e.g. a PNG). */
  Viewport.prototype.loadAtlasImage = function (imageBitmapOrElement) {
    var gl = this.gl;
    gl.bindTexture(gl.TEXTURE_2D, this.texture);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, imageBitmapOrElement);
    gl.bindTexture(gl.TEXTURE_2D, null);
  };

  // --- Frustum culling. Pure functions, no GL: given a 4x4 view-projection
  // (the same column-major layout mat4Multiply/mat4Perspective produce),
  // extract the six clip planes (Gribb/Hartmann method) and test an
  // axis-aligned box against them. A plane is {a,b,c,d} with ax+by+cz+d>=0
  // meaning "inside" that plane's half-space; a box is outside the frustum
  // the moment it is fully behind any one plane.

  function normalizePlane(p) {
    var len = Math.sqrt(p.a * p.a + p.b * p.b + p.c * p.c);
    if (len === 0) return p;
    return { a: p.a / len, b: p.b / len, c: p.c / len, d: p.d / len };
  }

  /** Extract the six view-frustum planes [left, right, bottom, top, near, far]
   * from a column-major view-projection matrix M (Float32Array/Array(16),
   * M[col*4+row]). Each plane satisfies ax+by+cz+d >= 0 for points inside. */
  function frustumPlanesFromViewProjection(m) {
    // Row i of M as (M[i], M[4+i], M[8+i], M[12+i]) since storage is
    // column-major: element [col*4+row].
    function row(i) {
      return [m[i], m[4 + i], m[8 + i], m[12 + i]];
    }
    var r0 = row(0);
    var r1 = row(1);
    var r2 = row(2);
    var r3 = row(3);

    function combine(ra, sign, rb) {
      return {
        a: ra[0] + sign * rb[0],
        b: ra[1] + sign * rb[1],
        c: ra[2] + sign * rb[2],
        d: ra[3] + sign * rb[3],
      };
    }

    return [
      normalizePlane(combine(r3, 1, r0)), // left
      normalizePlane(combine(r3, -1, r0)), // right
      normalizePlane(combine(r3, 1, r1)), // bottom
      normalizePlane(combine(r3, -1, r1)), // top
      normalizePlane(combine(r3, 1, r2)), // near
      normalizePlane(combine(r3, -1, r2)), // far
    ];
  }

  /** True if the axis-aligned box [min,max] (each a 3-array) is at least
   * partially inside every frustum plane -- the standard "positive vertex"
   * test: for each plane, pick the box corner farthest along the plane
   * normal and reject only if even that corner is behind the plane. A box
   * straddling a plane is therefore kept (never falsely culled), which is
   * what makes this safe to use for culling rather than exact containment. */
  function boxIntersectsFrustum(planes, boxMin, boxMax) {
    for (var i = 0; i < planes.length; i++) {
      var p = planes[i];
      var px = p.a >= 0 ? boxMax[0] : boxMin[0];
      var py = p.b >= 0 ? boxMax[1] : boxMin[1];
      var pz = p.c >= 0 ? boxMax[2] : boxMin[2];
      if (p.a * px + p.b * py + p.c * pz + p.d < 0) {
        return false;
      }
    }
    return true;
  }

  /** The world-space AABB of chunk (cx, cz): 16x16 in X/Z, and a fixed
   * vertical span covering the whole build height so culling never depends
   * on per-chunk height data it does not have. */
  function chunkWorldBounds(cx, cz, minY, maxY) {
    var x0 = cx * CHUNK_SIZE;
    var z0 = cz * CHUNK_SIZE;
    return {
      min: [x0, minY, z0],
      max: [x0 + CHUNK_SIZE, maxY, z0 + CHUNK_SIZE],
    };
  }

  var DEFAULT_WORLD_MIN_Y = -64;
  var DEFAULT_WORLD_MAX_Y = 320;

  // --- Back-to-front draw ordering, for translucent content (water, glass,
  // leaves-with-alpha) drawn with depth writes disabled: with no ordering,
  // two overlapping translucent chunks composite in whatever order the
  // streaming cache happens to iterate, which is a different, wrong picture
  // every time a chunk streams in or out. This is a pure function over
  // {cx, cz, distance} so the ordering itself is testable with no GPU.

  /** Sort chunk coordinate entries [{cx, cz}, ...] back-to-front (farthest
   * first) by squared distance from `cameraPosition` to each chunk's
   * horizontal centre. Returns a NEW array; does not mutate the input. Squared
   * distance is used (never sqrt) so ties and ordering are exact, not subject
   * to floating-point sqrt rounding. */
  function sortChunksBackToFront(entries, cameraPosition) {
    var cx0 = cameraPosition[0];
    var cz0 = cameraPosition[2];
    var withDistance = entries.map(function (entry) {
      var centreX = entry.cx * CHUNK_SIZE + CHUNK_SIZE / 2;
      var centreZ = entry.cz * CHUNK_SIZE + CHUNK_SIZE / 2;
      var dx = centreX - cx0;
      var dz = centreZ - cz0;
      return { entry: entry, distanceSquared: dx * dx + dz * dz };
    });
    // Stable sort descending by distance (farthest drawn first). Array.sort
    // is stable per spec in every runtime this project targets (Node 24,
    // Chromium/V8 in Electron), so equal-distance chunks keep their
    // original relative order rather than flickering between frames.
    withDistance.sort(function (a, b) {
      return b.distanceSquared - a.distanceSquared;
    });
    return withDistance.map(function (w) {
      return w.entry;
    });
  }

  function mat4Translation(x, y, z) {
    var m = mat4Identity();
    m[12] = x;
    m[13] = y;
    m[14] = z;
    return m;
  }

  Viewport.prototype.render = function () {
    var gl = this.gl;
    var canvas = this.canvas;
    var width = canvas.width;
    var height = canvas.height;
    gl.viewport(0, 0, width, height);
    gl.clearColor(this.clearColor[0], this.clearColor[1], this.clearColor[2], this.clearColor[3]);
    gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);

    var projection = mat4Perspective(this.fovYRadians, width / height, this.near, this.far);
    var view = mat4View(this.camera.position, this.camera.yaw, this.camera.pitch);
    var viewProjection = mat4Multiply(projection, view);

    // Anything drawn on top of the terrain -- the selection box, its handles,
    // the reference grid -- runs through this hook with the SAME
    // view-projection the chunks were drawn with. Handing the matrix over
    // rather than letting an overlay build its own camera is what stops the two
    // drifting apart: a box that is one frame or one convention behind the
    // terrain sits visibly in the wrong place, and nothing in either module
    // would be wrong on its own.
    var afterRender = this.afterRender;

    // The early return used to happen here, before any of this, so a world with
    // no chunks loaded yet drew nothing at all. That is also the exact moment a
    // grid is most useful -- placing a selection in empty space with no
    // reference is guesswork -- so the overlay hook runs whether or not there is
    // terrain to draw, and only the chunk drawing below is skipped.
    if (this.vertexCount <= 0 && this.chunkCount <= 0) {
      if (afterRender) afterRender(viewProjection, this.camera.position);
      return;
    }

    gl.useProgram(this.program);
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, this.texture);
    gl.uniform1i(this.imageLocation, 0);

    if (this.vertexCount > 0) {
      gl.uniformMatrix4fv(this.transformLocation, false, viewProjection);
      gl.bindVertexArray(this.vao);
      gl.drawArrays(gl.TRIANGLES, 0, this.vertexCount);
      gl.bindVertexArray(null);
    }

    // Cull chunks whose AABB the camera cannot see at all, then draw the
    // survivors back-to-front. Draw order matters even though every chunk is
    // a single opaque+translucent buffer: with BLEND enabled (see the
    // constructor) any translucent quads in a chunk composite correctly
    // against chunks already drawn behind them only if farther chunks go
    // first. This is chunk-granularity ordering, not a true opaque/
    // translucent pass split -- the mesher hands this renderer one
    // interleaved buffer per chunk with no per-quad alpha classification, so
    // two translucent surfaces inside the SAME chunk are not sorted against
    // each other. See docs/articles/webgl2-viewport.md for the limitation.
    var planes = this.frustumCullingEnabled ? frustumPlanesFromViewProjection(viewProjection) : null;
    var visible = [];
    for (var key in this.chunks) {
      if (!Object.prototype.hasOwnProperty.call(this.chunks, key)) continue;
      var candidate = this.chunks[key];
      if (candidate.vertexCount <= 0) continue;
      if (planes) {
        var bounds = chunkWorldBounds(candidate.cx, candidate.cz, this.worldMinY, this.worldMaxY);
        if (!boxIntersectsFrustum(planes, bounds.min, bounds.max)) continue;
      }
      visible.push(candidate);
    }
    var ordered = sortChunksBackToFront(visible, this.camera.position);
    for (var i = 0; i < ordered.length; i++) {
      var entry = ordered[i];
      var model = mat4Translation(entry.cx * CHUNK_SIZE, 0, entry.cz * CHUNK_SIZE);
      var transform = mat4Multiply(viewProjection, model);
      gl.uniformMatrix4fv(this.transformLocation, false, transform);
      gl.bindVertexArray(entry.vao);
      gl.drawArrays(gl.TRIANGLES, 0, entry.vertexCount);
      gl.bindVertexArray(null);
    }

    // Overlays last, so they draw over the terrain rather than under it.
    if (afterRender) afterRender(viewProjection, this.camera.position);
  };

  // --- Camera input. Conventions match amulet_map_editor.api.opengl.camera.
  // Camera: yaw in degrees, wrapped to [-180, 180); pitch in degrees, clamped
  // to [-90, 90]; position is [x, y, z] world units; movement is relative to
  // yaw only (pitch does not tilt horizontal movement), same as Minecraft
  // and the wx canvas's own WASD handling.

  function wrapYawDegrees(yaw) {
    yaw = yaw % 360;
    if (yaw >= 180) yaw -= 360;
    if (yaw < -180) yaw += 360;
    return yaw;
  }

  function clampPitchDegrees(pitch) {
    return Math.max(-90, Math.min(90, pitch));
  }

  /** Set absolute yaw/pitch in degrees, applying the same wrap/clamp rules
   * as amulet_map_editor.api.opengl.camera.Camera.set_rotation. */
  Viewport.prototype.setRotationDegrees = function (yawDegrees, pitchDegrees) {
    this.camera.yaw = (wrapYawDegrees(yawDegrees) * Math.PI) / 180;
    this.camera.pitch = (clampPitchDegrees(pitchDegrees) * Math.PI) / 180;
  };

  /** Rotate by a yaw/pitch delta in degrees (mouse-drag/arrow-key input). */
  Viewport.prototype.rotateDegrees = function (deltaYawDegrees, deltaPitchDegrees) {
    var yawDegrees = (this.camera.yaw * 180) / Math.PI;
    var pitchDegrees = (this.camera.pitch * 180) / Math.PI;
    this.setRotationDegrees(yawDegrees + deltaYawDegrees, pitchDegrees - deltaPitchDegrees);
  };

  /** Move the camera in its own horizontal-forward/right/world-up basis,
   * exactly the WASD+Q/E convention: forward/back follow the look direction
   * projected onto the horizontal plane, strafe is perpendicular to it, up
   * is always world +Y regardless of pitch. */
  Viewport.prototype.moveLocal = function (forwardDelta, rightDelta, upDelta) {
    var yaw = this.camera.yaw;
    var sinYaw = Math.sin(yaw);
    var cosYaw = Math.cos(yaw);
    var forward = [sinYaw, 0, -cosYaw];
    var right = [cosYaw, 0, sinYaw];
    var pos = this.camera.position;
    this.camera.position = [
      pos[0] + forward[0] * forwardDelta + right[0] * rightDelta,
      pos[1] + upDelta,
      pos[2] + forward[2] * forwardDelta + right[2] * rightDelta,
    ];
  };

  /** Wire mouse-drag-to-look, wheel-to-move, and a full keyboard equivalent
   * (WASD move, arrow keys move+look, Q/E vertical) onto `canvas`. Returns a
   * detach() function that removes every listener it added. Every mouse
   * action has a keyboard equivalent, per the project's accessibility rule --
   * this is not decoration, arrow keys alone can fly the whole viewport. */
  Viewport.prototype.attachControls = function (canvas, options) {
    var self = this;
    options = options || {};
    var lookSpeed = options.lookSpeed || 0.25; // degrees per pixel of drag
    var moveSpeed = options.moveSpeed || 12; // world units per second
    var keyLookSpeed = options.keyLookSpeed || 90; // degrees per second
    var wheelMoveScale = options.wheelMoveScale || 0.03;

    var dragging = false;
    var lastX = 0;
    var lastY = 0;
    var keys = {};
    var rafHandle = null;
    var lastFrameTime = null;

    function onPointerDown(event) {
      if (event.button !== 0) return;
      dragging = true;
      lastX = event.clientX;
      lastY = event.clientY;
      canvas.setPointerCapture && canvas.setPointerCapture(event.pointerId);
    }
    function onPointerMove(event) {
      if (!dragging) return;
      var dx = event.clientX - lastX;
      var dy = event.clientY - lastY;
      lastX = event.clientX;
      lastY = event.clientY;
      self.rotateDegrees(dx * lookSpeed, dy * lookSpeed);
    }
    function onPointerUp(event) {
      dragging = false;
      canvas.releasePointerCapture && canvas.releasePointerCapture(event.pointerId);
    }
    function onWheel(event) {
      event.preventDefault();
      self.moveLocal(-event.deltaY * wheelMoveScale, 0, 0);
    }
    function onKeyDown(event) {
      keys[event.key.toLowerCase()] = true;
    }
    function onKeyUp(event) {
      keys[event.key.toLowerCase()] = false;
    }

    function tick(now) {
      if (lastFrameTime === null) lastFrameTime = now;
      var dt = Math.min((now - lastFrameTime) / 1000, 0.25);
      lastFrameTime = now;

      var forward = 0;
      var right = 0;
      var up = 0;
      if (keys["w"] || keys["arrowup"]) forward += moveSpeed * dt;
      if (keys["s"] || keys["arrowdown"]) forward -= moveSpeed * dt;
      if (keys["d"]) right += moveSpeed * dt;
      if (keys["a"]) right -= moveSpeed * dt;
      if (keys["q"]) up -= moveSpeed * dt;
      if (keys["e"]) up += moveSpeed * dt;
      if (forward || right || up) self.moveLocal(forward, right, up);

      var yawDelta = 0;
      var pitchDelta = 0;
      if (keys["arrowright"]) yawDelta += keyLookSpeed * dt;
      if (keys["arrowleft"]) yawDelta -= keyLookSpeed * dt;
      if (yawDelta || pitchDelta) self.rotateDegrees(yawDelta, pitchDelta);

      rafHandle = requestAnimationFrame(tick);
    }

    canvas.addEventListener("pointerdown", onPointerDown);
    canvas.addEventListener("pointermove", onPointerMove);
    canvas.addEventListener("pointerup", onPointerUp);
    canvas.addEventListener("pointercancel", onPointerUp);
    canvas.addEventListener("wheel", onWheel, { passive: false });
    canvas.addEventListener("keydown", onKeyDown);
    canvas.addEventListener("keyup", onKeyUp);
    if (typeof requestAnimationFrame === "function") {
      rafHandle = requestAnimationFrame(tick);
    }

    return function detach() {
      canvas.removeEventListener("pointerdown", onPointerDown);
      canvas.removeEventListener("pointermove", onPointerMove);
      canvas.removeEventListener("pointerup", onPointerUp);
      canvas.removeEventListener("pointercancel", onPointerUp);
      canvas.removeEventListener("wheel", onWheel);
      canvas.removeEventListener("keydown", onKeyDown);
      canvas.removeEventListener("keyup", onKeyUp);
      if (rafHandle !== null && typeof cancelAnimationFrame === "function") {
        cancelAnimationFrame(rafHandle);
      }
    };
  };

  var api = {
    Viewport: Viewport,
    VERTEX_STRIDE_FLOATS: VERTEX_STRIDE_FLOATS,
    CHUNK_SIZE: CHUNK_SIZE,
    _mat4Perspective: mat4Perspective,
    _mat4View: mat4View,
    _mat4Multiply: mat4Multiply,
    _mat4Identity: mat4Identity,
    frustumPlanesFromViewProjection: frustumPlanesFromViewProjection,
    boxIntersectsFrustum: boxIntersectsFrustum,
    chunkWorldBounds: chunkWorldBounds,
    sortChunksBackToFront: sortChunksBackToFront,
    DEFAULT_WORLD_MIN_Y: DEFAULT_WORLD_MIN_Y,
    DEFAULT_WORLD_MAX_Y: DEFAULT_WORLD_MAX_Y,
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
  global.AmuletViewportWebGL = api;
})(typeof window !== "undefined" ? window : globalThis);
