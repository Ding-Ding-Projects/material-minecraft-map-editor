# The capture matrix

Every image in the README is a real photograph of the built interface, taken by
`scripts/capture_studio_surfaces.py` at a named commit and recorded in a
manifest beside the files. Nothing is a mockup, a design file, or a retouched
image, and a surface that could not be photographed is written down with the
reason rather than left out.

## What a run photographs

| Group | What is in it |
| --- | --- |
| Backstage | The six backstage tabs |
| Workspace | The ribbon, navigator, viewport, properties pane and status bar |
| Ribbon tabs | Every ribbon tab with its panel open |
| Context menus | Every searchable right-click menu, **open, with its rows drawn** |
| Overlays | The move-into-group picker, the anchored regex builder from each kind of host, the ribbon tab overflow list and both command-palette presentations |
| Dropdowns | Every `SearchableChoice` option popup in the shell and in every spec surface, open |
| Surfaces | Every registered spec surface |

## Why the menus were added

For 141 surfaces the matrix covered pages and nothing on top of them: not one
context menu, dropdown, popover or anchored panel. Six blank menu rows shipped
under that matrix without a single check going red, and nothing about the
tooling was broken — a gate cannot catch what a run never photographs, and every
structural field in the capture report stays clean for a window nobody asked to
be drawn.

## How a popup is photographed without taking over the machine

`Popup()` grabs the mouse and the keyboard so a transient window can see the
click that dismisses it, and `popup_at` clamps its point into the display work
area — so an off-screen coordinate handed to a menu is dragged back onto the
desktop and shown there. A capture run must not take the pointer, the keyboard
or the screen from the machine it is running on, so the run replaces that grab
with a plain `Show()` at a coordinate no display covers, which is what the
harness frame already does.

Everything else stays real: each menu, picker and popup is opened through the
**application's own opener**, so what is photographed is the window the product
constructs rather than one the harness assembled to look like it.

## The three things a run checks, and why one is not enough

1. **Route.** Every descendant must have drawn through `render_to`, its own
   paint handler, or `PrintWindow` — never through a device-context read, which
   off-screen copies a surface nobody composited and returns a white rectangle.
2. **Colour floor.** Under eight distinct colours the picture is empty beyond
   argument. This is what caught the appearance menu and the application command
   menus: every descendant composited, nothing was skipped, nothing was blitted,
   and the file was an empty card.
3. **Ink per row.** The two checks above are both blind to one row among
   nineteen drawing nothing — the picture keeps its header, its search field and
   eighteen good rows, so its colour count stays healthy and its uniform
   fraction *improves*. Stubbing a menu row's paint handler moves the whole
   picture from 0.829 to 0.631 of one colour, which is the direction a healthy
   capture moves in.

   Ink inside each row's own rectangle is the measurement that separates them: a
   row that drew nothing measures precisely zero, whatever its label was. A run
   that finds one deletes the file and names the row.

### It asks whether the row drew anything, never whether it drew enough

Ink is a share of the row's whole rectangle, so it depends on how long the label
is. A menu row reading "Close tabs not containing text…" inks four to ten
percent of itself; a dropdown row whose entire label is `X` inks **0.4%** of a
rectangle the same size, because that is one glyph in 244×30 pixels.

A floor set for the first calls the second blank. The workplane axis list — `Y
(height)`, `X`, `Z` — was deleted as broken while its picture showed all three
letters perfectly. The floor now sits just above rounding, which leaves the
shortest real label in this interface a factor of five clear of it and still
catches the only failure that matters: a row that drew nothing at all.

### Ink is measured against the row, not against a brightness threshold

The first version of that check counted pixels darker than a fixed luminance,
and it threw away two perfectly good menus on its first real run.

A **disabled** menu row draws its label in the palette's disabled ink, which on
this light surface sits at roughly 170 luminance — lighter than any threshold
that would still call the surface itself blank. Measured for darkness, every
disabled row in the shell reads as *exactly zero* ink, so the viewport and
navigator menus were deleted as broken while the pictures were correct.

Measuring each row against its **own commonest colour** fixes it and is
theme-independent besides: pale text still differs from the surface it is drawn
on. The same rows then read between five and seven percent. There is a test that
opens a menu with disabled rows and asserts none of them reads as blank, and
another that does the same for a one-character label, so tightening the
measurement again cannot quietly resume deleting healthy pictures.

### It reads the image once, not pixel by pixel

`wx.Image.GetRed` and its siblings are a call across the wrapper per channel per
pixel. Measuring a couple of hundred surfaces that way took a run from about
eleven minutes to well over an hour on a loaded machine. `GetData()` once per
picture, then indexing the buffer, measures the same pixels for nothing — and it
returns a `bytearray`, whose slices are unhashable, so it is converted to
`bytes` before anything counts colours with it.

Rows that scrolled past the bottom of a clamped popup are not measured — they
are legitimately absent rather than blank — and the manifest records how many
rows were actually inside each picture, so a surface whose rows all fell outside
the frame cannot pass by having proved nothing.

## A gap nobody mentions reads as coverage

Every surface a run could not photograph is written into the manifest's
`notOpened` list with the reason, and the README renders that list as its own
table. That is not decoration: on one run the regex builder's dropdown host
could not be produced and the surface was simply *absent* — in neither the
captures nor the gaps — which is the same silent hole the whole matrix exists to
close, reproduced inside the tool meant to close it.

Two things a run now says out loud rather than skipping:

- **A host that could not be produced.** Each kind of search field the builder is
  photographed from records its own absence if it cannot be opened.
- **A disabled dropdown.** `open_popup` declines silently when the combo is
  disabled, so a run that finds one names it.

One gap remains open and is stated here rather than left implied: the **Studio
shell's own dimension dropdown** is in none of the 112 dropdown captures, and the
run does not record why either. It is disabled on a capture project with no world
behind it — verified directly, so it genuinely cannot open — but the shell walk
reports neither the dropdown nor its disabled state, and the reason for that has
not been established.

## Known gap: the `MaterialMenu` family draws blank

`MaterialMenu`, and the `MaterialCard`, `MaterialButton` and
`MaterialSearchField` controls it is built from
(`amulet_map_editor/api/wx/components.py`), paint in `EVT_PAINT` using device
contexts of their own. They expose no `render_to`, and their handlers do not go
through the shared `paint_context` helper that the capture redirects, so
`render_via_paint` cannot drive them either. Every remaining route falls through
to `PrintWindow`, which answers *success* and draws nothing for an owner-drawn
control on a window nobody composited.

The effect is that the **appearance menu** every native control raises, and the
**application command-bar menus**, come back as an empty card with an empty
search field and no rows at all. Those files are deleted rather than shipped and
the manifest names them, because a blank capture is worse than none: it looks
like evidence.

This is a real hole rather than a harness quirk. Those rows cannot be proved to
draw by this capture harness or any future one until those widgets gain a
callable draw route — which is exactly what every Studio widget already has, and
why every Studio menu in the matrix photographs correctly.

## Verification

- `tests/test_capture_menu_coverage_contract.py` holds a **hand-written** list of
  the menus and overlays the manifest must contain. A rule shaped "every menu in
  the manifest is well formed" passes perfectly on a manifest with no menus in
  it, which is the state that let this ship; the list is what makes an absence
  fail.
- The same module opens a real menu off-screen and asserts every visible row
  carries ink, and then **stubs the row paint handler and asserts the check goes
  red**. A guard nobody has watched fail proves nothing, and this one had to be
  rewritten once for exactly that reason.
- `tests/test_capture_blank_detection.py` keeps `uniform_fraction` from quietly
  becoming a constant.

## Running it

```
py -3.11 scripts/capture_studio_surfaces.py --out docs/huishots
py -3.11 scripts/build_readme_captures.py --manifest docs/huishots/capture-manifest-<sha>.json
```

Run it from a clean checkout of the commit being recorded. A ten-minute run over
a working tree that other work is landing in photographs two different versions
of the application into one manifest, and the manifest's commit is then true of
neither.

Leave `--commit` off. It exists for a caller that genuinely knows better, and it
is a foot-gun for everyone else: handing it the *main* checkout's HEAD while the
harness runs in a linked worktree files the whole matrix under a commit that was
never photographed. Without it the commit comes from the checkout the run is in,
and the manifest is self-consistent by construction.

## Suggested articles

- [Searchable menus and dropdowns](../searchable-menus/README.md) — the menus
  this matrix photographs
- [Command palette](../command-palette/README.md) — both presentations are in
  the Overlays group
- [Search and regex](../search-and-regex/README.md) — the anchored builder, shot
  from each kind of host that opens one
- [Material shell](../material-shell/README.md) — the widgets whose callable
  draw route is what makes any of this photographable
