# Where a pasted copy lands

A clone, a move, a pending import and a paste all end the same way: the paste
tool holds a copy, the Position boxes in the properties pane say where it is,
and confirming writes it into the world. This article is about what those three
numbers actually mean, because until this change nothing on screen said.

## Behaviour

The editor's paste puts the **centre** of the copy at the position it is given.
amulet-core's clone takes `rotation_point = (min + max) // 2` of the source
bounds and displaces the whole copy by `location - rotation_point`, so a
4 × 1 × 4 slab sent to `8, 40, 8` fills `6, 40, 6` to `9, 40, 9` — half a
structure away from the numbers that were typed, in every direction at once.

That is correct behaviour and it was invisible. Somebody who typed the
coordinate they wanted, confirmed, and went to look for their blocks found
nothing there, with no message, no readout and no note to explain it. It is the
most likely reading of "cloning doesn't work".

The **Position** section of the Tool tab now carries three things.

**A picker naming the point.** *Position refers to* offers four choices:

| Choice | What `x, y, z` names |
| --- | --- |
| Centre of the copy | the editor's own behaviour, and the default |
| Centre of its base | the middle of the bottom layer — the block it stands on |
| Lowest corner, -x -y -z | the smallest x, the smallest y and the smallest z |
| Highest corner, +x +y +z | the largest x, the largest y and the largest z |

Choosing one renames the point; it never moves the copy. The value in the boxes
changes to the point now being named, and the object stays exactly where it was.

**A sentence saying which.** Directly under the boxes, in words, for whichever
choice is active. A coordinate control that does not say which point of an
object it names is one the user has to discover by pasting and looking.

**A live box.** *Fills from* and *Fills to* are the inclusive block box the
confirm will write, re-read several times a second, so the answer to "then where
do the blocks actually go" is on screen beside the numbers as they are typed.

<details>
<summary>The Position section, at both anchors</summary>

![The Position section of the Tool tab with the anchor set to Centre of the
copy. The picker reads "Position refers to: Centre of the copy", the sentence
below the coordinate boxes reads "x, y and z are the centre of the copy, not a
corner. The blocks land in the box below, which is half the copy away in every
direction.", and the two rows beneath it read "Fills from 6, 40, 6" and "Fills
to 9, 40, 9" for a 4 by 1 by 4 copy held at 8, 40,
8.](../../huishots/paste-anchor-centre.png)

![The same section with the anchor set to the lowest corner. The picker reads
"Position refers to: Lowest corner, -x -y -z", the sentence reads "x, y and z
are the copy's lowest corner: its smallest x, its smallest y and its smallest z.
The blocks land in the box below.", and the box rows are unchanged at "Fills
from 6, 40, 6" and "Fills to 9, 40, 9" — because naming a different point does
not move the copy.](../../huishots/paste-anchor-corner.png)

Both were taken from the real pane by `scripts/capture_paste_anchor.py`, which
composites every widget through its own drawing code. Two harness artefacts are
visible and neither is in the running interface: the three coordinate boxes
photograph empty, because their value lives in a native text control that does
not answer `PrintWindow` with its content on a desktop nobody is compositing —
every committed capture of the Clone tool shows the same thing — and content
scrolled out of the column still lands in the picture, because the composite
draws each descendant at its own position without the scroller's clipping.

</details>

The box accounts for rotation and scale as well as position. For the ninety-
degree turns the tool's own rotate buttons make, and for any scale, it is exact;
for a free rotation in between it is the axis-aligned bounding box of the
transformed structure, which is a true bound rather than an exact outline.

## Configuration

The chosen anchor is persisted in the profile under
`amulet_studio_paste_anchor` and restored on the next launch, like any other
setting. One record for the profile rather than one per project: which point a
coordinate means is a habit of the person, not a fact about a world.

The default is **Centre of the copy**, which is exactly what the editor did
before this existed, so an existing habit and anybody's own arithmetic keep
working unchanged. An anchor stored by a build that offered a different set
falls back to the centre rather than failing.

## Failure modes

The copy's own extent is read from the held structure's bounds. When it cannot
be read — a structure whose level reports a whole dimension's bounds, or a
renderer holding no fake level — there is no way to work out which block the
centre lands on, so:

- no box is shown; both rows read `not known`;
- no anchor picker is offered at all, because an anchor other than the centre
  could not be honoured and a control that does not do what its options say is
  worse than no control;
- the boxes show the tool's own position, and the sentence says the size could
  not be read.

Nothing here guesses. A box quietly reading the position three times for an
object whose size nobody could read would be the exact defect this surface
exists to remove, stated confidently.

## Security and accessibility

Everything is local: the extent comes from the structure the editor is already
holding, and the anchor is one string in the profile. Nothing is transmitted.

The picker is the shell's standard searchable dropdown, so it carries its own
search field with the regex opt-in and builder, takes focus from the keyboard,
draws a visible focus ring, and announces itself with its label and its current
value. The box rows carry an accessible name combining their label and value,
and they are re-measured when the value grows so a coordinate at the far edge of
a world is not elided — the rows this section adds are exactly the rows somebody
opens to check a number.

The Position section sits below the fold in a 700px column, as the rotation,
scale and confirm controls already do. It is reachable by scrolling and by the
keyboard, and the checks below assert its rectangle against the scroller's
visible band rather than merely asking the widget tree whether it exists.

## Verification

```powershell
py -3.11 -m pytest tests/test_paste_anchor.py tests/test_paste_anchor_ui_contract.py -q
py -3.11 -m pytest tests/test_editor_clone_runtime.py -q
```

The first module is arithmetic: it checks the box against a second,
independently written transcription of amulet-core's own clone offset, checks
that the centre anchor is an exact no-op, and checks that every anchor reads
back to the position it came from.

The second builds the real pane around a stand-in tool and asserts on the
controls: that the picker exists, is focusable, is inside the scroller's visible
band once scrolled to, and that choosing a corner rewrites the boxes without
moving the copy.

The third is the one that matters. It opens a real world, clones a slab of gold
through the Studio's own Clone surface, chooses **Lowest corner** in the real
pane, types `11, 50, 11` into the real coordinate boxes, confirms, and then
reads the world back and finds the gold starting at exactly `11, 50, 11`. It
also records what the pane *said* the box would be before the confirm and
compares it to the blocks that actually landed.

Every one of those guards was watched failing before it was trusted: twelve
deliberate breakages — no picker, no sentence, no box, a dropped centre offset,
an anchor offset off by one block, a conversion that never reaches the tool —
each turned the covering assertions red and were then restored.

Suggested articles: [editing tools](../editing-tools/README.md),
[properties pane](../properties-pane/README.md),
[navigator](../navigator/README.md), and
[local version history](../local-history/README.md).
