# Build tools

Six surfaces for putting things into a world rather than reshaping what is
there. They live on the Build and Structures ribbon tabs.

## Behaviour

| Surface | What it does |
| --- | --- |
| **Pattern and mask** (`patternMask`) | Define a weighted block pattern and the mask deciding where it may be placed. |
| **Stack and array** (`stackArray`) | Repeat the selection along an axis, or across a grid, with spacing and counts. |
| **Structure library** (`schematicLibrary`) | The saved structures on this machine, searchable, with a preview and a place action. |
| **Waypoints** (`waypoints`) | Named coordinates in the open project, with a jump-to action. |
| **Nether portal travel builder** (`portalBuilder`) | Build a matched portal pair, with the coordinate arithmetic between the two dimensions done for you. |
| **Rail tunnel builder** (`railTunnel`) | Build a complete rail tunnel. |

The **rail tunnel builder** is the largest surface in the group and is worth
naming in full, because it is several tools in one window:

- **Routing** — start, end, and the gradient the track is allowed to take.
- **Profile** — the tunnel's cross-section: width, height, and floor.
- **Four editable wall courses** — each course is a block choice of its own, so
  a wall can be banded rather than uniform.
- **Roof shapes with ribs** — flat, arched, or vaulted, with a rib spacing.
- **A lighting designer** — fixture definitions, where fixtures are placed, the
  spacing between them, and a post-build light verification that reports any
  stretch left below the threshold that allows hostile spawning.

Every block choice in the group shows a generated placeholder swatch, labelled
as one, with its top, side, and bottom faces.

## Configuration

The pattern is weighted: each entry carries a share, and the preview shows the
highest-weighted block. The mask decides what may be replaced — air only,
non-air, a specific state, or everything.

Waypoints and the structure library are per project and stay local. The
structure library's list is searchable with the regex opt-in and the `.*`
builder.

## Failure modes

A portal pair whose coordinates cannot both be satisfied — because one side
falls outside the world border or the height limits — is reported with the exact
constraint rather than built half-linked.

The rail tunnel's light verification reports its result honestly: a tunnel with
a dark stretch says where, rather than reporting success because the fixtures
were placed. Placing fixtures and the tunnel actually being lit are different
claims.

An array or stack that would exceed the world's limits reports the limit it hit
and how much it could place. Every placement is one commit in the project
repository, so it can be restored.

## Security and accessibility

Structures are read from and written to local paths, chosen through path fields
with native browse buttons; a typed path and a browsed one run through the same
validation. Nothing is downloaded.

Every fixture, course, and range control is keyboard reachable and named, the
long forms scroll rather than clipping, and coordinates use the monospaced face.

## Verification

```powershell
py -3 -m pytest tests/test_studio_spec_registry.py -q
```

That proves every surface here is structurally complete, every texture section
names a block and a drop target, and every range is internally consistent. The
tunnel and portal arithmetic against a real world needs a build.

Suggested articles: [terrain tools](../terrain/README.md),
[texture previews](../texture-previews/README.md),
[editing tools](../editing-tools/README.md), and
[redstone and mechanics](../redstone/README.md).
