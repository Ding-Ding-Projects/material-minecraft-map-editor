# Screen, state and evidence inventory

Every row below is a design requirement, with implementation and runtime evidence pending. The selector notation defines a future deterministic contract, not an existing executable route. No entry is completed merely because it is listed.

## Addressable screen states

| Screen | Required states | Deterministic selector |
| --- | --- | --- |
| First read-only shell | empty, probing, result, unsupported; factual failure/cancellation message on empty | `probe-shell/<state>` |
| Setup | new, resumed, validation-failed, engine-unavailable, backup-probe-failed, ready | `setup/<state>` |
| Empty workspace | no recent worlds, recent worlds, missing recent path, version-provenance-unavailable | `workspace-empty/<state>` |
| Open world | browsing, probing, supported, read-only, unsupported-version, corrupt, locked, canceled | `world-open/<state>` |
| Terrain workspace | loading, ready, missing-chunk, render-failed, read-only, unsaved, external-conflict | `workspace/<state>` |
| Custom title bar | active, inactive, restored, maximized, full-screen, close-decision-pending | `titlebar/<state>` |
| Individual tools and camera | every explicit control state in `components.md`, including mode selection, focus, disabled and pointer release | `control/<component>/<state>` |
| Dimension navigator | populated, empty-filter, custom-dimension, unavailable | `dimensions/<state>` |
| Selection inspector | none, box, invalid-bounds, oversized, block-state-selected | `selection/<state>` |
| Operation preview | validating, running, ready, stale, unsupported-block, canceled, failed | `operation-preview/<state>` |
| Apply/save | running, cancel-requested, safe-canceled, succeeded, failed, recovery-required | `transaction/<state>` |
| Recovery | journal-found, backup-available, restore-preview, restoring, restored, restore-failed | `recovery/<state>` |
| History drawer | empty, populated, undo-running, redo-running, unavailable-entry, filtered | `history/<state>` |
| Block picker | loaded, loading, no-match, invalid-property, unavailable-version | `block-picker/<state>` |
| NBT inspector | typed-tree, search-results, invalid-value, read-only, validation-failed | `nbt/<state>` |
| Structure placement/export | parsing, ghost-preview, invalid-transform, unsupported, writing, complete, failed | `structure/<state>` |
| Find blocks | idle, searching, results, empty, canceled, limit-reached, failed | `find-blocks/<state>` |
| Command palette | contextual-results, unavailable-action, empty, invalid-regex | `commands/<state>` |
| Tab catalog and management | catalog, overflow, pinned, grouped, collapsed-group, move-picker, bulk-close-preview, unsaved-decision | `tabs/<state>` |
| Regex workbench | construct, explain, flavor-compare, convert, match, replace, debug, benchmark, templates, collection, file-search, unsupported, limit-exceeded | `regex/<state>` |
| Settings | each task group, matching-search, no-match, invalid-value, persisted, reset-preview, reset-complete | `settings/<state>` |
| Personal wording | empty, accepted, rejected, replaced, cleared, corrupt-cache, success-celebration, reduced-motion | `wording/<state>` |
| Accessibility/narration | tools-open, hidden-entry-restore, voices-loading, voice-missing, unavailable, speaking, paused | `accessibility/<state>` |
| Appearance/locks | element-editor, color-editor, locked, unlock-required, recovery, reset | `appearance/<state>` |
| Notifications | progress, success, warning, failure, muted-sound, unavailable-audio | `notifications/<state>` |
| Local tools | server-manager, model-manager, converter, external-editor, capability-unavailable | `tools/<state>` |
| Documentation | task-index, article, related-task, search, no-match, offline, unavailable-article | `documentation/<state>` |
| About/changelog/support | provenance, licenses, version-changelog, ticket-draft, submission-result | `information/<state>` |

State data must be deterministic fixtures of actual supported models. Freeze time, seed generated terrain where used, stop animations, use synthetic nonpersonal worlds, and never load a user's real recent-path list into captures. Fixture data cannot manufacture a capability the real engine lacks.

## Exact tuple matrix

Logical client sizes: `1600x900` and `1280x720`. Display scales: `1.00`, `1.25`, `1.50`, `2.00`. Themes: `light`, `dark`. Language modes: `en`, `yue-Hant-HK`, `bilingual`. The cross-product contains 48 tuples per screen/state. Every screen/state receives a normal baseline; the full responsive matrix must be exercised for each layout family and every state whose content changes geometry, with documented mapping rather than sampling silently presented as complete coverage.

Physical image sizes follow logical size multiplied by scale: normal 1600×900, 2000×1125, 2400×1350, 3200×1800; minimum 1280×720, 1600×900, 1920×1080, 2560×1440. A 1280×720 physical desktop at 200% yields 640×360 logical space and is below the declared minimum. Record that limitation; do not call it a tested 1280×720 logical layout. Also exercise enlarged text, long world names and bilingual expansion separately.

Future deterministic reference/runtime parameters: `screen`, `state`, `theme`, `language`, `clientWidth`, `clientHeight`, `scale`, `fixture`, `motion=off`. Exact executable commands remain to be implemented and documented. Do not advertise nonexistent CLI flags.

## Evidence required for each accepted tuple

Record source commit, built binary hash, build receipt, fixture identity, actual client and physical dimensions, language/theme/scale, component registry audit, reference file hash, reference-viewer route, real-runtime route, raw reference capture, raw runtime capture, labeled comparison, visual-diff data, keyboard/focus results, native accessibility results and layout measurements. A native Qt probe must report item bounds, clipping/visibility, parent bounds, text implicit sizes and actual font fallback. Browser DOM geometry cannot stand in for Qt evidence.

Each discrepancy receives exact element/state/tuple, observed versus intended result, bounded impact and repair or explicitly reviewed deviation. No blanket visual tolerance masks missing components or unreadable text. Keep screenshots private when they contain user data; use synthetic worlds for public evidence.

## Current parity inventory

| Reference | Tuple | Viewer | Runtime | Comparison and audit | Verdict |
| --- | --- | --- | --- | --- | --- |
| `workspace-dark.svg` | workspace/ready; dark; en; 1600×900; 1.00 | Not implemented | Not implemented | Not produced | Design reference only |
| Other workspace tuples | Remaining 47 tuples | Not implemented | Not implemented | Not produced | References pending |
| Other screens and states above | All applicable tuples | Not implemented | Not implemented | Not produced | References pending |

## Known reference gaps, not accepted parity

The populated workspace SVG retains a 40-unit drawer summary while the prose specifies 48 units. Its generic font-family is nondeterministic pending licensed bundled font selection. Its tool and camera groups remain schematic despite the explicit state registry. No minimum-size or bilingual first-shell reference exists yet. These gaps are recorded, not accepted deviations, and block visual-parity acceptance. They do not require drawing every future editing state before implementation of the bounded read-only probe shell can begin.

## Independent review checklist

- [ ] Confirm terrain-first hierarchy, compact contextual tools and absence of generic dashboard/ribbon content.
- [ ] Confirm all visible chrome has a registered Material Design 3 implementation plan; record missing component provenance.
- [ ] Confirm engine-backed capabilities, immutable preview identity, transaction/cancellation and recovery contracts.
- [ ] Confirm actual Java-version support remains separate from the full compatibility target; Bedrock remains deferred.
- [ ] Confirm keyboard, accessibility, bilingual and minimum-size behavior.
- [ ] Confirm every search owns a full independent regex workbench and unsupported capabilities remain unfinished.
- [ ] Confirm complete product-wide feature mapping and real consumer/persistence coverage before completion.
- [ ] Author and review remaining reference states and tuples.
- [ ] Build the native reference viewer and matching deterministic runtime routes.
- [ ] Run real native layout/accessibility and design-parity verification, retaining source-bound captures.

The design author cannot provide the independent-review verdict. A review must name its actual reviewer, scope, findings and disposition. Installation, packaging, release and documentation deployment remain separate acceptance work.
