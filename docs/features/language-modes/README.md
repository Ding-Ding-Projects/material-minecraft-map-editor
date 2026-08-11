# Language modes and funny levels

Every visible string in Amulet Studio goes through one function, so the language
mode and the tone reach the whole shell rather than the handful of surfaces
somebody remembered to wire.

## Behaviour

`studio_text(english, cantonese)`
(`amulet_map_editor/api/studio/copy.py`) returns one string in the reader's
language and tone:

| Mode | Result |
| --- | --- |
| English | the English line, styled |
| Cantonese | the Cantonese line, styled — the English when no Cantonese was written |
| Bilingual | both lines, separated by a newline |

Bilingual mode returns two lines rather than one crowded line, and the controls
draw them as a prominent primary label above a compact secondary one. A control
that drew only the first line would silently drop half the label, so the
drawing helpers split on the newline explicitly.

**Two funny levels, from 1 to 5, one per language**, adjustable independently.
Level 1 reads fully professional; level 5 is maximum playfulness. The styling
itself is `tts_narrator.style_text` — the same styling the spoken narrator and
the notification copy use — so a message never sounds like one product when it
is read and another when it is spoken.

**The level applies to every category with no exemptions**, including errors,
warnings, and the destructive-action gate.

## Tone styles the voice, never the fact

This is the rule that makes the previous paragraph safe. A string made entirely
of factual tokens — an identifier, a coordinate, a count, a path, a hash, a
version — is returned exactly as it was given. So is a short control label,
because a button whose name grew an aside would both mislead and clip.

Everything else is prose, and prose is what the levels are for. A warning at
level 5 is still a warning that names the file, the count, and whether the
action can be undone; only the sentence around those facts changes.

## Configuration

The mode and both levels live in the shared preference profile and are read
through the School-mode projection, so School mode forces English at level 1
without every caller checking for it. A scheduled rule can override the mode for
a window of time; the user's own choice is retained and returns when the rule
ends.

## Failure modes

When no Cantonese source was written for a string, the English is shown instead.
Inventing a translation at display time would put words in the product's mouth
that nobody wrote and nobody reviewed.

An unreadable preference profile falls back to the shipped defaults rather than
preventing the shell from painting.

## Security and accessibility

No copy is fetched; every string is in the source. Nothing about the chosen
language or level is transmitted.

Bilingual mode is the widest case every layout is checked against, because two
lines per label at 200% display scale is where clipping appears first. Both
lines are part of the control's accessible name, so a screen reader gets what a
sighted reader gets.

## Verification

```powershell
py -3 -m pytest tests/test_lang.py tests/test_tts_narrator.py -q
```

Those cover the persisted mode, both levels, and the shared styling this module
delegates to.

Suggested articles: [settings and appearance](../settings/README.md),
[school mode](../school-mode/README.md),
[optional narrator](../tts-narrator/README.md), and
[scheduled settings](../scheduled-settings/README.md).
