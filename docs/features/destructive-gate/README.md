# Destructive-action gate

Anything irreversible in Amulet Studio passes through one gate: two
independently operated keys, then a slider that has to travel its full range,
with an emergency exit available the whole time.

It is deliberately more work than a confirmation dialog. A dialog with a
default button is dismissed by muscle memory; a gate that needs two separate
actions and a deliberate drag cannot be.

## Behaviour

`KeyGate` (`amulet_map_editor/api/studio/widgets.py`) draws three things in
order:

1. **Two key controls.** Each is operated separately. Turning one changes
   nothing; the slider stays disabled until both are turned.
2. **A full-range slider.** Partial travel authorises nothing and returns to
   zero. Only a complete traverse authorises the action.
3. **An emergency exit**, always available, always the fastest control to reach.

Escape cancels, the platform's own back gesture cancels, and focus returns to
whatever opened the gate on either path — cancelled or completed.

The gate is anchored beside the destructive control where the layout allows it,
and is modal only where it cannot be.

## What it guards

Regenerating chunks, deleting chunks, filtered entity removal, repairs that
rewrite world data, bulk deletions in any list, deleting a tag in the NBT
editor, and discarding unsaved work. Anything else that becomes irreversible
gets the gate as part of becoming so.

Discarding unsaved work is itself recorded in the local history before the close
completes, so the discard is auditable and can be restored later.

## Configuration

The gate is a section kind in the spec renderer — `keygate` — so a declarative
surface gets it by naming it rather than by building one. It is one
implementation in the application's own UI layer; there is no separate helper
window, hosted page, or external service.

## Failure modes

The gate names the exact thing it is guarding — the count, the region, the
dimension, the file — before it will authorise anything. Playful copy styles the
sentence around those facts and never replaces them: at every language mode and
every funny level, the gate still says what will be deleted and whether it can
be undone.

If the action fails after authorisation, the failure is reported with its reason
and the gate resets rather than leaving the interface in a state that looks
authorised.

An action that turns out to affect nothing reports that instead of running.

## Localisation

The gate's own copy — the status line at every state, the two key labels, the
slider's accessible name, the progress row title, and the emergency exit's
label and hint — is not hard-coded English. It goes through
`amulet_map_editor.api.studio.copy.studio_text` (the status prose, which the
funny-level sliders may style) and `copy.studio_label` (the key, slider,
progress-row, and exit-button names, which stay factual and untouched by tone).
Switching the active language mode changes what the gate says without a
restart, in English, playful Hong Kong-style Cantonese, and bilingual mode
alike, and the fact that will be deleted never changes with it.

## Security and accessibility

The gate is a safety control, not a security boundary, and it does not pretend
otherwise: it protects against a slip, not against someone who means to delete
something.

Both keys and the slider are keyboard-operable — the slider moves with arrow
keys and Home/End as well as by dragging — each has an accessible name and
value, focus is visible on all three, and the whole gate is usable at narrow
widths and high display scales. It is reduced-motion aware: the animation is
decoration, and turning it off does not remove a step or change what the
controls say.

## Verification

```powershell
py -3.11 -m pytest tests/test_material_confirmation_contract.py tests/test_studio_spec_registry.py tests/test_destructive_gate_end_to_end.py -q
```

The first two are source-text contracts and prove every surface that declares
a gate section still carries one and says the right things. Neither one drives
a real `wx.Slider` or a real key press, so neither can tell a wired gate from
one whose handlers were never bound.

`tests/test_destructive_gate_end_to_end.py` is the one that does: it builds a
real `KeyGate` in a real `wx.Frame` and dispatches real `EVT_SLIDER`,
`EVT_SCROLL_THUMBRELEASE`, `EVT_KEY_DOWN`, and `EVT_CHAR_HOOK` events through
it, and asserts on a callback standing in for the destructive action rather
than on the gate's own `authorized` flag. It covers the untouched state, one
key held, both keys held, releasing a key mid-authorisation, every partial
slider position from 1% to 99% (asserting the action never fires), full
travel (asserting it fires exactly once and cannot fire twice), the emergency
exit, Escape, focus returning to the control that opened the gate, reduced
motion skipping the completion flourish, full motion running and finishing a
timed flourish, Space/Enter arming a focused key, distinct accessible names on
every control, the accessible name changing with held state, all three
language modes, a destructive action that raises being isolated rather than
crashing the gate, and a capture taken mid-flourish that is read back and
confirmed to be more than a flat colour.

Suggested articles: [per-project version history](../project-history/README.md),
[bulk actions](../bulk-actions/README.md),
[terrain tools](../terrain/README.md), and
[entities and world data](../entities-and-data/README.md).
