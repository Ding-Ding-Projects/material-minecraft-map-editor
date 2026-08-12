/* WebGL2 overlays for the viewport: the selection box and a reference grid.
 *
 * Without a selection box the viewport can display a world but cannot be
 * used to edit one -- there is nowhere on screen that says "this is the
 * region you are about to operate on". This module draws exactly that, plus
 * a ground-plane grid so placing a box in otherwise-empty space is not pure
 * guesswork.
 *
 * The look is deliberately not invented here. It matches the desktop app's
 * existing selection box, defined in
 * amulet_map_editor/api/opengl/mesh/selection/box/render_selection.py,
 * render_selection_editable.py and colours.json:
 *   - translucent faces + a wireframe outline drawn with depth test
 *     disabled (so the outline always reads, even inside terrain) --
 *     see RenderSelection.draw() in render_selection.py.
 *   - point1 tinted green (0,1,0), point2 tinted blue (0,0,1) -- see
 *     colours.json's box_point1/box_point2 and RenderSelectionEditable's
 *     point1_colour/point2_colour.
 *
 * This module owns no canvas and no GL context of its own -- it is handed
 * the same WebGL2RenderingContext and the same camera*projection transform
 * matrix that docs/site/viewport-webgl.js already computes for drawing the
 * chunk mesh, and draws on top of whatever is already in that framebuffer.
 * It knows nothing about Electron, IPC, or where the viewport is hosted.
 *
 * Integration call site (for whoever owns the Viewport/shell wiring):
 *
 *   var overlay = new window.AmuletViewportOverlays.SelectionOverlay(viewport.gl);
 *   overlay.setGrid({ y: 0 });                 // optional; omit to hide the grid
 *   overlay.setSelection(point1, point2);      // [x,y,z] arrays, or...
 *   overlay.clearSelection();                  // ...call this when nothing is selected
 *   // after viewport.render() has drawn the chunk mesh into the same canvas:
 *   overlay.render(transform, viewport.camera.position);
 *
 * `transform` is the same `mat4Multiply(projection, view)` result
 * viewport-webgl.js already builds for its own draw call -- this module
 * does not build its own camera matrix, so the overlay and the terrain
 * never drift apart. `camera.position` is optional; pass it so a box the
 * camera is standing inside still renders (matches RenderSelection.draw's
 * camera_position handling, minus the face-cull flip, which is moot here
 * since overlay faces are drawn with culling disabled).
 */
(function (global) {
  "use strict";

  // Matches amulet_map_editor's colours.json (selection box palette).
  var COLOUR_BOX_FACE = [1.0, 1.0, 1.0, 0.12]; // box_normal, low alpha
  var COLOUR_BOX_EDGE = [0.5, 1.0, 1.0, 1.0]; // box_edge
  var COLOUR_POINT1 = [0.0, 1.0, 0.0, 1.0]; // box_point1 (green)
  var COLOUR_POINT2 = [0.0, 0.0, 1.0, 1.0]; // box_point2 (blue)
  var COLOUR_GRID = [1.0, 1.0, 1.0, 0.18];

  // -------------------------------------------------------------------
  // Pure geometry generation. No GL call anywhere in this section, so it
  // is testable arithmetic on a machine with no GPU at all -- the vertex
  // data for a box of known bounds is checkable the same way the Python
  // box-render module's own vertex math is.
  // -------------------------------------------------------------------

  /** The 8 corners of an axis-aligned box, in a fixed bit-indexed order:
   * bit0 -> x (0=min,1=max), bit1 -> y, bit2 -> z. */
  function boxCorners(min, max) {
    var corners = new Array(8);
    for (var i = 0; i < 8; i++) {
      corners[i] = [
        i & 1 ? max[0] : min[0],
        i & 2 ? max[1] : min[1],
        i & 4 ? max[2] : min[2],
      ];
    }
    return corners;
  }

  var EDGE_PAIRS = [
    [0, 1], [1, 3], [3, 2], [2, 0], // y = min face
    [4, 5], [5, 7], [7, 6], [6, 4], // y = max face
    [0, 4], [1, 5], [3, 7], [2, 6], // verticals
  ];

  var FACE_QUADS = [
    [0, 4, 6, 2], // -X
    [1, 3, 7, 5], // +X
    [0, 1, 5, 4], // -Y
    [2, 6, 7, 3], // +Y
    [0, 2, 3, 1], // -Z
    [4, 5, 7, 6], // +Z
  ];

  /** GL_LINES vertex data (position-only, 3 floats/vertex) outlining the
   * 12 edges of an axis-aligned box. 24 vertices. */
  function buildBoxEdgeVertices(min, max) {
    var corners = boxCorners(min, max);
    var out = new Float32Array(EDGE_PAIRS.length * 2 * 3);
    var o = 0;
    for (var e = 0; e < EDGE_PAIRS.length; e++) {
      var a = corners[EDGE_PAIRS[e][0]];
      var b = corners[EDGE_PAIRS[e][1]];
      out[o++] = a[0]; out[o++] = a[1]; out[o++] = a[2];
      out[o++] = b[0]; out[o++] = b[1]; out[o++] = b[2];
    }
    return out;
  }

  /** GL_TRIANGLES vertex data (position-only, 3 floats/vertex) for the 6
   * faces of an axis-aligned box, two triangles per face. 36 vertices.
   * Winding is not guaranteed consistent -- the caller draws this with
   * face culling disabled, since the faces are translucent anyway. */
  function buildBoxFaceVertices(min, max) {
    var corners = boxCorners(min, max);
    var out = new Float32Array(FACE_QUADS.length * 6 * 3);
    var o = 0;
    function push(idx) {
      var c = corners[idx];
      out[o++] = c[0]; out[o++] = c[1]; out[o++] = c[2];
    }
    for (var f = 0; f < FACE_QUADS.length; f++) {
      var q = FACE_QUADS[f];
      push(q[0]); push(q[1]); push(q[2]);
      push(q[0]); push(q[2]); push(q[3]);
    }
    return out;
  }

  /** A small cube's worth of edge + face vertices centred on `center`,
   * used to mark point1/point2 exactly (rather than only the box's min/max
   * corners, which are not always point1/point2 -- see RenderSelection's
   * _offset_points/points setter: point1 and point2 are the two corners the
   * user actually placed, sorted into min/max only for the box itself). */
  function buildMarkerCube(center, halfSize) {
    var min = [center[0] - halfSize, center[1] - halfSize, center[2] - halfSize];
    var max = [center[0] + halfSize, center[1] + halfSize, center[2] + halfSize];
    return {
      edges: buildBoxEdgeVertices(min, max),
      faces: buildBoxFaceVertices(min, max),
    };
  }

  /** GL_LINES vertex data for a ground-plane grid on the XZ plane at
   * height `y`, centred at (centerX, centerZ), covering +/-halfExtent at
   * `spacing`-block intervals. */
  function buildGridVertices(centerX, centerZ, y, halfExtent, spacing) {
    var lines = [];
    var startX = Math.floor((centerX - halfExtent) / spacing) * spacing;
    var endX = centerX + halfExtent;
    var startZ = Math.floor((centerZ - halfExtent) / spacing) * spacing;
    var endZ = centerZ + halfExtent;
    for (var x = startX; x <= endX; x += spacing) {
      lines.push(x, y, centerZ - halfExtent, x, y, centerZ + halfExtent);
    }
    for (var z = startZ; z <= endZ; z += spacing) {
      lines.push(centerX - halfExtent, y, z, centerX + halfExtent, y, z);
    }
    return new Float32Array(lines);
  }

  function sortedBounds(point1, point2) {
    var min = [
      Math.min(point1[0], point2[0]),
      Math.min(point1[1], point2[1]),
      Math.min(point1[2], point2[2]),
    ];
    var max = [
      Math.max(point1[0], point2[0]),
      Math.max(point1[1], point2[1]),
      Math.max(point1[2], point2[2]),
    ];
    return { min: min, max: max };
  }

  function pointInBox(point, min, max) {
    if (!point) return false;
    return (
      point[0] >= min[0] && point[0] <= max[0] &&
      point[1] >= min[1] && point[1] <= max[1] &&
      point[2] >= min[2] && point[2] <= max[2]
    );
  }

  // -------------------------------------------------------------------
  // GL plumbing.
  // -------------------------------------------------------------------

  var VERTEX_SHADER_SOURCE = [
    "#version 300 es",
    "layout(location = 0) in vec3 position;",
    "uniform mat4 transform;",
    "void main(){",
    "    gl_Position = transform * vec4(position, 1.0);",
    "}",
  ].join("\n");

  var FRAGMENT_SHADER_SOURCE = [
    "#version 300 es",
    "precision highp float;",
    "out vec4 outColor;",
    "uniform vec4 color;",
    "void main(){",
    "    outColor = color;",
    "}",
  ].join("\n");

  function compileShader(gl, type, source) {
    var shader = gl.createShader(type);
    gl.shaderSource(shader, source);
    gl.compileShader(shader);
    if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
      var log = gl.getShaderInfoLog(shader);
      gl.deleteShader(shader);
      throw new Error("Overlay shader compile failed: " + log);
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
      throw new Error("Overlay program link failed: " + log);
    }
    return program;
  }

  /**
   * @param {WebGL2RenderingContext} gl
   */
  function SelectionOverlay(gl) {
    this.gl = gl;
    this.program = linkProgram(gl, VERTEX_SHADER_SOURCE, FRAGMENT_SHADER_SOURCE);
    this.transformLocation = gl.getUniformLocation(this.program, "transform");
    this.colorLocation = gl.getUniformLocation(this.program, "color");

    this.vao = gl.createVertexArray();
    this.vbo = gl.createBuffer();
    gl.bindVertexArray(this.vao);
    gl.bindBuffer(gl.ARRAY_BUFFER, this.vbo);
    gl.vertexAttribPointer(0, 3, gl.FLOAT, false, 0, 0);
    gl.enableVertexAttribArray(0);
    gl.bindVertexArray(null);

    this._selection = null; // { point1, point2 } or null
    this._grid = null; // { y, halfExtent, spacing } or null
  }

  /** Set the current selection. Draws nothing until this (or restored
   * state) is called -- a zero-size box at the origin when nothing is
   * selected would read as a bug, not as "nothing selected". */
  SelectionOverlay.prototype.setSelection = function (point1, point2) {
    this._selection = { point1: point1.slice(0, 3), point2: point2.slice(0, 3) };
  };

  SelectionOverlay.prototype.clearSelection = function () {
    this._selection = null;
  };

  SelectionOverlay.prototype.hasSelection = function () {
    return this._selection !== null;
  };

  /** Show a reference grid. `options.y` is the plane height (default 0),
   * `options.halfExtent` how far it extends (default 64 blocks),
   * `options.spacing` the line spacing (default 1 block). Pass no
   * arguments / call clearGrid() to hide it. */
  SelectionOverlay.prototype.setGrid = function (options) {
    options = options || {};
    // Chunk spacing, not block spacing.
    //
    // The default was one line per block over 64 blocks either way: 258 lines,
    // which from any normal camera angle is seen nearly edge-on and collapses
    // into a moire of dense horizontal stripes filling half the viewport. It
    // read as a rendering fault rather than as a reference plane, and it hid
    // the terrain behind it.
    //
    // Sixteen is also the more useful number in a Minecraft editor: chunk
    // boundaries are a thing the user acts on, and a line per block is
    // information nobody asked for at a density nobody can read.
    this._grid = {
      y: typeof options.y === "number" ? options.y : 0,
      halfExtent: typeof options.halfExtent === "number" ? options.halfExtent : 128,
      spacing: typeof options.spacing === "number" ? options.spacing : 16,
    };
  };

  SelectionOverlay.prototype.clearGrid = function () {
    this._grid = null;
  };

  SelectionOverlay.prototype._uploadAndDraw = function (vertices, drawMode, color) {
    if (vertices.length === 0) return;
    var gl = this.gl;
    gl.bindBuffer(gl.ARRAY_BUFFER, this.vbo);
    gl.bufferData(gl.ARRAY_BUFFER, vertices, gl.DYNAMIC_DRAW);
    gl.uniform4fv(this.colorLocation, color);
    gl.bindVertexArray(this.vao);
    gl.drawArrays(drawMode, 0, vertices.length / 3);
    gl.bindVertexArray(null);
  };

  /**
   * Draw the grid (if set) and the selection box (if one is set), on top
   * of whatever the caller has already rendered into the same canvas.
   * @param {Float32Array} transform column-major mat4, the same
   *   projection*view matrix the terrain draw used.
   * @param {number[]} [cameraPosition] [x,y,z]; when given and the camera
   *   is inside the selection box, the box is still drawn (its faces are
   *   drawn without culling regardless, so this only affects nothing
   *   visually today, but is accepted to keep the call site stable if
   *   culling is added later).
   */
  SelectionOverlay.prototype.render = function (transform, cameraPosition) {
    var gl = this.gl;
    if (!this._selection && !this._grid) return;

    gl.useProgram(this.program);
    gl.uniformMatrix4fv(this.transformLocation, false, transform);

    var blendWasEnabled = gl.isEnabled(gl.BLEND);
    var cullWasEnabled = gl.isEnabled(gl.CULL_FACE);
    var depthWasEnabled = gl.isEnabled(gl.DEPTH_TEST);

    gl.enable(gl.BLEND);
    gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
    gl.disable(gl.CULL_FACE);

    if (this._grid) {
      var g = this._grid;
      var cx = cameraPosition ? cameraPosition[0] : 0;
      var cz = cameraPosition ? cameraPosition[2] : 0;
      var gridVertices = buildGridVertices(cx, cz, g.y, g.halfExtent, g.spacing);
      this._uploadAndDraw(gridVertices, gl.LINES, COLOUR_GRID);
    }

    if (this._selection) {
      var bounds = sortedBounds(this._selection.point1, this._selection.point2);

      // Faces first, with depth test on, so terrain in front of the box
      // still occludes it -- matches RenderSelection.draw()'s ordering.
      this._uploadAndDraw(buildBoxFaceVertices(bounds.min, bounds.max), gl.TRIANGLES, COLOUR_BOX_FACE);

      // Outline and point markers always read, even through terrain --
      // RenderSelection.draw() explicitly disables depth test for its
      // GL_LINE_STRIP pass for the same reason.
      if (depthWasEnabled) gl.disable(gl.DEPTH_TEST);
      this._uploadAndDraw(buildBoxEdgeVertices(bounds.min, bounds.max), gl.LINES, COLOUR_BOX_EDGE);

      var markerHalf = Math.max(0.06, Math.min(0.3, (bounds.max[0] - bounds.min[0]) / 24));
      var point1Marker = buildMarkerCube(this._selection.point1, markerHalf);
      var point2Marker = buildMarkerCube(this._selection.point2, markerHalf);
      this._uploadAndDraw(point1Marker.faces, gl.TRIANGLES, COLOUR_POINT1);
      this._uploadAndDraw(point1Marker.edges, gl.LINES, COLOUR_POINT1);
      this._uploadAndDraw(point2Marker.faces, gl.TRIANGLES, COLOUR_POINT2);
      this._uploadAndDraw(point2Marker.edges, gl.LINES, COLOUR_POINT2);
      if (depthWasEnabled) gl.enable(gl.DEPTH_TEST);
    }

    if (!blendWasEnabled) gl.disable(gl.BLEND);
    if (cullWasEnabled) gl.enable(gl.CULL_FACE);
  };

  var api = {
    SelectionOverlay: SelectionOverlay,
    _buildBoxEdgeVertices: buildBoxEdgeVertices,
    _buildBoxFaceVertices: buildBoxFaceVertices,
    _buildMarkerCube: buildMarkerCube,
    _buildGridVertices: buildGridVertices,
    _boxCorners: boxCorners,
    _sortedBounds: sortedBounds,
    _pointInBox: pointInBox,
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
  global.AmuletViewportOverlays = api;
})(typeof window !== "undefined" ? window : globalThis);
