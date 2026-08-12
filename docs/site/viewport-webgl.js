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

    this.vao = gl.createVertexArray();
    gl.bindVertexArray(this.vao);
    this.vbo = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, this.vbo);
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
    gl.bindVertexArray(null);

    this.texture = gl.createTexture();
    this.vertexCount = 0;

    this.camera = { position: [8, 20, 8], yaw: 0, pitch: 0.5 };
    this.fovYRadians = (70 * Math.PI) / 180;
    this.near = 0.1;
    this.far = 1000;
    this.clearColor = [0.53, 0.75, 0.93, 1.0]; // Minecraft-ish sky blue

    gl.enable(gl.DEPTH_TEST);
    gl.enable(gl.CULL_FACE);
  }

  /** Upload one chunk's interleaved float32 vertex buffer. */
  Viewport.prototype.loadMesh = function (arrayBuffer, vertexCount) {
    var gl = this.gl;
    gl.bindBuffer(gl.ARRAY_BUFFER, this.vbo);
    gl.bufferData(gl.ARRAY_BUFFER, arrayBuffer, gl.STATIC_DRAW);
    gl.bindBuffer(gl.ARRAY_BUFFER, null);
    this.vertexCount = vertexCount;
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

  Viewport.prototype.render = function () {
    var gl = this.gl;
    var canvas = this.canvas;
    var width = canvas.width;
    var height = canvas.height;
    gl.viewport(0, 0, width, height);
    gl.clearColor(this.clearColor[0], this.clearColor[1], this.clearColor[2], this.clearColor[3]);
    gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);

    if (this.vertexCount <= 0) return;

    var projection = mat4Perspective(this.fovYRadians, width / height, this.near, this.far);
    var view = mat4View(this.camera.position, this.camera.yaw, this.camera.pitch);
    var transform = mat4Multiply(projection, view);

    gl.useProgram(this.program);
    gl.uniformMatrix4fv(this.transformLocation, false, transform);
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, this.texture);
    gl.uniform1i(this.imageLocation, 0);
    gl.bindVertexArray(this.vao);
    gl.drawArrays(gl.TRIANGLES, 0, this.vertexCount);
    gl.bindVertexArray(null);
  };

  var api = {
    Viewport: Viewport,
    VERTEX_STRIDE_FLOATS: VERTEX_STRIDE_FLOATS,
    _mat4Perspective: mat4Perspective,
    _mat4View: mat4View,
    _mat4Multiply: mat4Multiply,
    _mat4Identity: mat4Identity,
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
  global.AmuletViewportWebGL = api;
})(typeof window !== "undefined" ? window : globalThis);
