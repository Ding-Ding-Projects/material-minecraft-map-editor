# The WebGL2 viewport: first pass

The 3D viewport is the last major surface still living only in the wxPython
application. This is the first real, verified pass at moving it into the
Electron renderer. It proves the pipeline end to end; it does not yet match
what the wx viewport draws.

## The design (fixed, not revisited here)

- **Meshing stays in Python.** The existing Cython mesher
  (`amulet_map_editor/api/opengl/mesh/level/chunk/chunk_builder_cy`) already
  produces exactly what a GPU wants: an interleaved `float32` array of
  `position(vec3) texcoord(vec2) texoffset(vec4) tint(vec3)` per vertex, the
  same layout `amulet_map_editor/api/opengl/mesh/tri_mesh.py`'s `TriMesh`
  uploads today. Porting that mesher (and the block-model/resource-pack
  handling behind it) to JavaScript is where the correctness risk lives, and
  it stays in Python.
- **WebGL2 (`docs/site/viewport-webgl.js`) draws it.** WebGL2 is ES 3.0 and
  is feature-parity with the GL 3.3 the existing shaders target. The vertex
  and fragment shaders are a mechanical GLSL ES 300 port of
  `amulet_map_editor/api/opengl/shaders/render_chunk_330.vert`/`.frag`: same
  attribute layout, same uniforms (`transformation_matrix`, `image`), same
  fragment math (bilinear atlas-cell lookup via `mix`, alpha-discard,
  `tint * 0.85`).
- **Only the camera, draw loop and buffer uploads are JavaScript.** Column-
  major perspective/view matrices, a `gl.bufferData`/`gl.texImage2D` upload,
  and one `gl.drawArrays` call.

## The binary side channel

The sidecar's wire protocol (`amulet_map_editor/api/sidecar/protocol.py`) is
newline-delimited JSON -- correct for preferences and settings, wrong by an
order of magnitude for a chunk's vertex data (tens of thousands of floats)
or a 4096x4096 texture atlas.

`amulet_map_editor/api/sidecar/mesh_methods.py`'s `viewport.chunk_mesh` and
`viewport.atlas` instead write raw bytes to a file under the sidecar's own
per-process temp directory (`%TEMP%/amulet-viewport-mesh/<pid>/`) and return
that path plus small metadata (vertex count, the fixed 12-float stride, the
opaque/translucent split offset) in their JSON result. `electron/main.js`
exposes exactly one new IPC handler, `sidecar:readBinary`, that asks the
sidecar itself (via `viewport.temp_root`) what that directory is and refuses
to open anything outside it -- the sidecar can hand the renderer a chunk
mesh or an atlas PNG, never an arbitrary file on the user's disk.

This was measured against a real 16x16 chunk with height-varying stone/
dirt/grass terrain: **10,248 vertices, 491,904 bytes** (12 floats x 4 bytes
x 10,248), written and read back as one `fs.readFileSync` call. The 4096x4096
RGBA texture atlas PNG is a separate ~1-8MB file depending on the resource
pack, fetched once per world and cached by `world_id`.

## Building the resource pack is asynchronous, like `world.open`

The bundled `amulet_resource_pack` carries only the editor's own UI textures
(selection box outline, missing-texture placeholder) -- no block models at
all, so meshing against it alone produces zero faces for every real block.
Real block textures come from downloading the actual vanilla Java resource
pack from Mojang's own launcher manifest (the same official path a
Minecraft launcher uses), the same thing
`amulet_map_editor/programs/edit/api/canvas/base_edit_canvas.py` already
does for the wx viewport, cached under `CACHE_DIR`.

That download, plus packing everything into one 4096x4096 atlas, routinely
takes far longer than the sidecar dispatcher's per-request timeout
(`DEFAULT_TIMEOUT_SECONDS = 10.0`). So it never runs inline on a request
thread: `viewport.prepare` kicks it off on a background thread and returns
`{"status": "building"}` immediately; callers poll it (cheap, near-instant)
exactly the way `world.open` callers poll `world.open_status`.
`viewport.atlas` and `viewport.chunk_mesh` both call the same build
internally, so skipping straight to them without polling `viewport.prepare`
first still gets a clean `world_not_ready`-style error rather than a
request that silently blocks the pipe.

## The proof

`scripts/capture_viewport_render.js`:

1. Builds a real, fresh Java world on disk through amulet-core directly
   (`scripts/make_viewport_fixture_world.py`) -- stepped stone/dirt/grass
   terrain in chunk (0, 0), never a checked-in binary save file.
2. Launches the packaged Electron shell headlessly (`AMULET_HEADLESS=1`,
   never shows a window -- see `electron/main.js`), pointed at
   `docs/site/viewport-harness.html?world=<path>` via the
   `AMULET_VIEWPORT_HARNESS_WORLD` env var main.js checks for.
3. Drives the real page over the Chrome DevTools protocol: opens the world
   through the real sidecar, polls `viewport.prepare`, pulls the mesh and
   atlas back as real bytes through `sidecar:readBinary`, and lets the real
   `AmuletViewportWebGL.Viewport` draw them.
4. Reads the rendered pixels back with `canvas.toDataURL()` (a CDP
   `Page.captureScreenshot` against this WebGL2 canvas hung indefinitely
   under a hidden `--disable-gpu` headless window with no error and no
   timeout -- `toDataURL()` reads the canvas's own backing store directly
   and needs no compositor). `--use-gl=angle --use-angle=swiftshader
   --enable-unsafe-swiftshader` gives WebGL2 a real, headless-safe,
   software-rendered GL backend to draw with in the first place.
5. Decodes the captured PNG and asserts real pixel variance (min/max byte
   range > 20) -- not just "a file exists", a captured image that is not a
   flat clear-colour rectangle.

The result: `docs/huishots/electron/viewport-webgl2-chunk-render.png`,
showing real stepped stone/dirt/grass terrain with correct vanilla textures,
a working perspective camera, and per-face tinting -- drawn by real GL2
draw calls from a mesh the real Python Cython mesher produced.

## What this pass does NOT do

Named honestly, so the next pass starts from the truth rather than from a
"the viewport is done" that isn't:

- **Only one chunk, requested by exact coordinate.** No chunk streaming, no
  loading chunks around a moving camera, no unloading far chunks, no
  region-level batching (`amulet_map_editor/api/opengl/mesh/level/region.py`'s
  region grouping is not used at all).
- **No mouse/keyboard camera controls.** The harness sets a fixed camera
  position and pitch; there is no orbit/fly/first-person input handling in
  `viewport-webgl.js` yet.
- **No selection boxes, no floor/ceiling grid planes**, both of which the wx
  `RenderChunk` can draw (`_draw_floor`/`_draw_ceil`, `selection.py`).
- **No biome tint beyond the mesher's own per-vertex tint** (grass/foliage
  color is whatever the mesher already baked in; nothing here reads or
  overrides it separately).
- **No LOD.** The wx codebase has `_create_lod1` stubs (`# TODO` in
  `chunk.py` itself) -- this pass only ever asks for LOD0.
- **No translucent-pass depth sorting**, no fog, no skybox beyond a flat
  clear color.
- **Not wired into the product's tabbed Material 3 shell.** This lives in a
  standalone proof harness (`docs/site/viewport-harness.html`), loaded by
  Electron's main process only when `AMULET_VIEWPORT_HARNESS_WORLD` is set
  (the capture script's own doing). The ordinary app still loads
  `docs/site/index.html` exactly as before; there is no viewport tab, no
  Material 3 chrome, no settings integration for it yet.
- **Resource pack is Java-only in practice.** The Bedrock branch of
  `_ResourcePackCache._build` is written and mirrors the Java one but is
  untested here -- no Bedrock world was exercised.
