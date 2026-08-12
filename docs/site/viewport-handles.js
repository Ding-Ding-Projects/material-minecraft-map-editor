/* Selection-box grab handles: where they sit, what dragging one does.
 *
 * A mechanical JS port of amulet_map_editor/api/opengl/mesh/selection/box/
 * handles.py, kept function-for-function so the wx editor and this one
 * cannot disagree about how a box resizes -- see that file's module
 * docstring for the reasoning behind face vs. corner handles, why a drag
 * resolves to a *world* delta rather than a pixel delta, and why a face
 * handle stared straight down its own axis is withheld rather than merely
 * inert. Constants below are copied from there and must stay in sync.
 *
 * Everything here is arithmetic: a handle is a position and a constraint, a
 * drag is a ray and a subtraction. No canvas, no GL, no DOM -- checked
 * directly in Node (tests/test_viewport_handle_drag.py) the same way
 * viewport-picking.js's ray-cast is.
 */
(function (global) {
  "use strict";

  var AXIS_NAMES = ["x", "y", "z"];

  var MIN_HANDLE_HALF = 0.15;
  var MAX_HANDLE_HALF = 0.75;
  var HANDLE_SIZE_DIVISOR = 6.0;
  var MAX_FACE_ALIGNMENT = 0.9;
  var AXIS_EPSILON = 1e-9;

  function clamp(value, low, high) {
    return Math.max(low, Math.min(high, value));
  }

  function sub(a, b) {
    return [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
  }
  function dot(a, b) {
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
  }
  function scale(a, s) {
    return [a[0] * s, a[1] * s, a[2] * s];
  }
  function add(a, b) {
    return [a[0] + b[0], a[1] + b[1], a[2] + b[2]];
  }
  function length(a) {
    return Math.sqrt(dot(a, a));
  }

  function buildHandles() {
    var faces = [];
    for (var axis = 0; axis < 3; axis++) {
      [-1, 1].forEach(function (direction) {
        var offset = [0, 0, 0];
        offset[axis] = direction;
        var sign = direction > 0 ? "+" : "-";
        faces.push({ name: "face:" + sign + AXIS_NAMES[axis], offset: offset, axis: axis });
      });
    }
    var corners = [];
    [-1, 1].forEach(function (x) {
      [-1, 1].forEach(function (y) {
        [-1, 1].forEach(function (z) {
          var offset = [x, y, z];
          var name =
            "corner:" +
            offset
              .map(function (value, index) {
                return (value > 0 ? "+" : "-") + AXIS_NAMES[index];
              })
              .join("");
          corners.push({ name: name, offset: offset, axis: null });
        });
      });
    });
    return { faces: faces, corners: corners };
  }

  var BUILT = buildHandles();
  var FACE_HANDLES = BUILT.faces;
  var CORNER_HANDLES = BUILT.corners;
  var BOX_HANDLES = FACE_HANDLES.concat(CORNER_HANDLES);

  function isFace(handle) {
    return handle.axis !== null;
  }
  function isCorner(handle) {
    return handle.axis === null;
  }

  function handleHalfSize(boxMin, boxMax) {
    var extent = [
      Math.abs(boxMax[0] - boxMin[0]),
      Math.abs(boxMax[1] - boxMin[1]),
      Math.abs(boxMax[2] - boxMin[2]),
    ];
    var smallest = Math.min(extent[0], extent[1], extent[2]);
    return clamp(smallest / HANDLE_SIZE_DIVISOR, MIN_HANDLE_HALF, MAX_HANDLE_HALF);
  }

  function handleCentre(handle, boxMin, boxMax) {
    var centre = [0, 0, 0];
    for (var axis = 0; axis < 3; axis++) {
      var value = handle.offset[axis];
      if (value < 0) centre[axis] = boxMin[axis];
      else if (value > 0) centre[axis] = boxMax[axis];
      else centre[axis] = (boxMin[axis] + boxMax[axis]) / 2;
    }
    return centre;
  }

  function handleBounds(handle, boxMin, boxMax) {
    var centre = handleCentre(handle, boxMin, boxMax);
    var half = handleHalfSize(boxMin, boxMax);
    return [
      [centre[0] - half, centre[1] - half, centre[2] - half],
      [centre[0] + half, centre[1] + half, centre[2] + half],
    ];
  }

  function faceHandleIsUsable(handle, viewDirection) {
    if (!isFace(handle)) return true;
    var len = length(viewDirection);
    if (len < 1e-12) return true;
    return Math.abs(viewDirection[handle.axis] / len) < MAX_FACE_ALIGNMENT;
  }

  /** The handles worth drawing/hit-testing from this view. Pass
   * `viewDirection` for an orthographic camera; pass `cameraPosition` for a
   * perspective one, where each handle is seen along its own ray. With
   * neither, every handle is returned. */
  function visibleHandles(boxMin, boxMax, cameraPosition, viewDirection, handles) {
    handles = handles || BOX_HANDLES;
    if (!viewDirection && !cameraPosition) return handles.slice();
    var kept = [];
    for (var i = 0; i < handles.length; i++) {
      var handle = handles[i];
      var direction = viewDirection
        ? viewDirection
        : sub(handleCentre(handle, boxMin, boxMax), cameraPosition);
      if (faceHandleIsUsable(handle, direction)) kept.push(handle);
    }
    return kept;
  }

  /** How far along `direction` the ray first meets the box, or `null` on a
   * miss (or a box entirely behind the origin). A ray starting inside the
   * box returns 0. */
  function rayBoxDistance(origin, direction, boxMin, boxMax) {
    var near = -Infinity;
    var far = Infinity;
    for (var axis = 0; axis < 3; axis++) {
      var d = direction[axis];
      if (Math.abs(d) < 1e-12) {
        if (origin[axis] < boxMin[axis] || origin[axis] > boxMax[axis]) return null;
        continue;
      }
      var t1 = (boxMin[axis] - origin[axis]) / d;
      var t2 = (boxMax[axis] - origin[axis]) / d;
      if (t1 > t2) {
        var tmp = t1;
        t1 = t2;
        t2 = tmp;
      }
      near = Math.max(near, t1);
      far = Math.min(far, t2);
      if (near > far) return null;
    }
    if (far < 0) return null;
    return Math.max(near, 0);
  }

  /** The nearest handle the ray passes through, or `null`. Nearest rather
   * than first-found: two handles genuinely overlap on screen when the
   * camera is edge-on to the box. */
  function hitHandle(boxMin, boxMax, origin, direction, handles) {
    handles = handles || BOX_HANDLES;
    var best = null;
    var bestDistance = Infinity;
    for (var i = 0; i < handles.length; i++) {
      var handle = handles[i];
      var bounds = handleBounds(handle, boxMin, boxMax);
      var distance = rayBoxDistance(origin, direction, bounds[0], bounds[1]);
      if (distance === null) continue;
      if (distance < bestDistance) {
        best = handle;
        bestDistance = distance;
      }
    }
    return best;
  }

  /** `t` where the line (linePoint, lineDirection) is closest to the ray, or
   * `null` when the two are parallel. */
  function closestParameterOnLine(linePoint, lineDirection, rayOrigin, rayDirection) {
    var u = lineDirection;
    var v = rayDirection;
    var uu = dot(u, u);
    var vv = dot(v, v);
    var uv = dot(u, v);
    var denominator = uu * vv - uv * uv;
    if (Math.abs(denominator) < 1e-12 || uu < 1e-12) return null;
    var w = sub(linePoint, rayOrigin);
    var uw = dot(u, w);
    var vw = dot(v, w);
    return (uv * vw - vv * uw) / denominator;
  }

  /** Where the ray meets the plane, or `null` if it never does (including a
   * ray running away from the plane -- never the mirrored point behind the
   * camera). */
  function rayPlaneIntersection(origin, direction, planePoint, planeNormal) {
    var denominator = dot(planeNormal, direction);
    if (Math.abs(denominator) < 1e-9) return null;
    var distance = dot(planeNormal, sub(planePoint, origin)) / denominator;
    if (distance < 0) return null;
    return add(origin, scale(direction, distance));
  }

  function dominantAxis(direction) {
    var vector = [Math.abs(direction[0]), Math.abs(direction[1]), Math.abs(direction[2])];
    for (var i = 0; i < 3; i++) {
      if (vector[i] < AXIS_EPSILON) vector[i] = 0;
    }
    var best = 0;
    for (var j = 1; j < 3; j++) {
      if (vector[j] > vector[best]) best = j;
    }
    return best;
  }

  /** Start a drag on `handle`, or `null` if it cannot be started from here.
   * The corner-drag plane is chosen once, from the camera direction at the
   * moment of the press -- re-choosing every frame would flip the plane
   * mid-drag and jump the box. */
  function beginDrag(handle, boxMin, boxMax, origin, direction) {
    var centre = handleCentre(handle, boxMin, boxMax);

    if (isFace(handle)) {
      var axis = handle.axis;
      var unit = [0, 0, 0];
      unit[axis] = 1;
      var parameter = closestParameterOnLine(centre, unit, origin, direction);
      if (parameter === null) return null;
      return {
        handle: handle,
        startMin: boxMin.slice(),
        startMax: boxMax.slice(),
        planeNormal: null,
        startParameter: parameter,
        startPoint: null,
      };
    }

    var normal = [0, 0, 0];
    normal[dominantAxis(direction)] = 1;
    var point = rayPlaneIntersection(origin, direction, centre, normal);
    if (point === null) return null;
    return {
      handle: handle,
      startMin: boxMin.slice(),
      startMax: boxMax.slice(),
      planeNormal: normal,
      startParameter: 0,
      startPoint: point,
    };
  }

  /** The continuous world offset for the cursor ray during `drag`, or `null`
   * when the ray says nothing usable this frame (looking away from the drag
   * plane, or straight down the drag axis) -- the caller should leave the
   * box where it is rather than guess. */
  function dragWorldOffset(drag, origin, direction) {
    if (drag.planeNormal === null) {
      var axis = drag.handle.axis;
      var unit = [0, 0, 0];
      unit[axis] = 1;
      var centre = handleCentre(drag.handle, drag.startMin, drag.startMax);
      var parameter = closestParameterOnLine(centre, unit, origin, direction);
      if (parameter === null) return null;
      return scale(unit, parameter - drag.startParameter);
    }

    if (drag.startPoint === null) return null;
    var point = rayPlaneIntersection(origin, direction, drag.startPoint, drag.planeNormal);
    if (point === null) return null;
    var offset = sub(point, drag.startPoint);
    var alongNormal = dot(offset, drag.planeNormal);
    return sub(offset, scale(drag.planeNormal, alongNormal));
  }

  /** The whole-block offset for the cursor ray during `drag`, or `null`.
   * Rounded rather than truncated, or the box would lag half a block behind
   * the cursor in one direction and not the other. */
  function dragBlockOffset(drag, origin, direction) {
    var offset = dragWorldOffset(drag, origin, direction);
    if (offset === null) return null;
    return [Math.round(offset[0]), Math.round(offset[1]), Math.round(offset[2])];
  }

  /** Apply a whole-block offset from `beginDrag` to the box the drag started
   * from, returning a new `[min, max]` with the dragged handle's face/corner
   * moved and the opposite side left where it was. */
  function applyDragOffset(drag, blockOffset) {
    var min = drag.startMin.slice();
    var max = drag.startMax.slice();
    var offset = drag.handle.offset;
    for (var axis = 0; axis < 3; axis++) {
      if (offset[axis] > 0) {
        max[axis] = drag.startMax[axis] + blockOffset[axis];
      } else if (offset[axis] < 0) {
        min[axis] = drag.startMin[axis] + blockOffset[axis];
      }
    }
    return [min, max];
  }

  var api = {
    AXIS_NAMES: AXIS_NAMES,
    MIN_HANDLE_HALF: MIN_HANDLE_HALF,
    MAX_HANDLE_HALF: MAX_HANDLE_HALF,
    HANDLE_SIZE_DIVISOR: HANDLE_SIZE_DIVISOR,
    MAX_FACE_ALIGNMENT: MAX_FACE_ALIGNMENT,
    FACE_HANDLES: FACE_HANDLES,
    CORNER_HANDLES: CORNER_HANDLES,
    BOX_HANDLES: BOX_HANDLES,
    isFace: isFace,
    isCorner: isCorner,
    handleHalfSize: handleHalfSize,
    handleCentre: handleCentre,
    handleBounds: handleBounds,
    faceHandleIsUsable: faceHandleIsUsable,
    visibleHandles: visibleHandles,
    rayBoxDistance: rayBoxDistance,
    hitHandle: hitHandle,
    closestParameterOnLine: closestParameterOnLine,
    rayPlaneIntersection: rayPlaneIntersection,
    dominantAxis: dominantAxis,
    beginDrag: beginDrag,
    dragWorldOffset: dragWorldOffset,
    dragBlockOffset: dragBlockOffset,
    applyDragOffset: applyDragOffset,
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
  if (typeof global !== "undefined") {
    global.AmuletViewportHandles = api;
  }
})(typeof window !== "undefined" ? window : this);
