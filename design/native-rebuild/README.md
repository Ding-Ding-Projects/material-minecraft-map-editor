# Native editor design handoff

Status: design specification, awaiting independent review. No application behavior, visual parity, compatibility, or runtime acceptance is demonstrated by these files.

Baseline: `371b470c6ab79b90b03769eb66e108abd7549c7d`. Target: native Qt/PySide6 presentation with a Rust world engine. This record supplements and preserves the historical `design/HANDOFF.md`; its ribbon and backstage direction is not the new implementation target.

## Files and review order

1. [Workspace and component contract](workspace.md): visual hierarchy, native architecture, action and safety contracts.
2. [Screen and verification inventory](states.md): addressable states, required features, exact responsive tuples and unverified evidence.
3. [Normal dark workspace reference](workspace-dark.svg): deterministic schematic design reference at 1600 × 900 logical units, English. It is neither a screenshot nor a rendered application.
4. [Component registration](components.md): explicit primitive anatomy, individual action/camera states, proposed native paths and source-provenance limits.

## Product boundary

Build a serious Java world editor. A user opens a local world, inspects its format and dimensions, explores terrain, selects blocks, previews an operation, applies it to an editing session, and safely saves. Editing tools belong next to their terrain and selection. No promotional hero, dashboard statistics, generic feature cards, ribbon, or page of decorative commands.

Java stable releases from 1.12 onward are the compatibility target, not a delivered promise. Display the detected version, data version, engine support verdict and read/write capabilities from actual probing. Never infer support from a recognizable folder. Unknown formats open read-only only when the engine can safely decode them. Bedrock is explicitly deferred and must not appear as a working editor choice.

## Acceptance boundary

The independent reviewer must approve the action/state coverage and component plan before runtime implementation. A separate Qt reference viewer must render the checked-in SVG directly, using an exact screen/state/theme/size/scale selector. It must not redraw the reference. Other themes, languages, states and minimum-size references remain to be authored and independently reviewed. One SVG is a composition reference, not a complete design-parity matrix.

Actual built-runtime captures, accessibility interaction, terrain rendering, engine capability evidence, installation, release and deployed documentation evidence are all pending. No reference should be relabelled as runtime evidence. See the explicit evidence inventory in `states.md`.
