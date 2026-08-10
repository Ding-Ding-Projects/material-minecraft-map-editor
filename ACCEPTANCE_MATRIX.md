# Acceptance matrix

| Area | Acceptance condition | Supplied status | Required final evidence |
|---|---|---:|---|
| Baseline | Exact `0.10` commit `684c9f2…` or explicitly reviewed descendant | Automated | Bootstrap log / `git rev-parse HEAD` |
| Source safety | Existing checkout must be clean; patch anchors fail closed | Automated | Negative-path bootstrap/patch output |
| Python syntax | All supplied Python parses | Passed | `run_static_checks.py` output |
| Headless menu model | Literal search, bounds, ranking, disabled selection | Passed, 11 tests total with contract suite | Pytest output |
| Patch idempotence | Applying integration/test-contract patch twice changes code once | Passed | Synthetic test output |
| System theme | Persisted `system` follows live OS appearance changes | Implemented/static-checked | Toggle OS app theme and restyle screenshot |
| Theme performance | One preference/schedule/override read per pass; no recursion | Implemented/static-checked | Focused tests plus runtime trace |
| Layout performance | One root `Layout()` per style pass | Implemented/static-checked | Large-page open/restyle observation |
| M3 command bar | No native `wx.Menu` construction in `create_menu` | Implemented/static-checked | Built-window screenshot and source gate |
| Menu search | Search label/description/section/keywords, bounded literal input | Implemented/headless-tested | Built-window keyboard/mouse run |
| Keyboard input | Return/Space activates once on release | Implemented/static-checked | Hold-key runtime test |
| Mouse input | Capture loss cannot leave pressed state | Implemented/static-checked | Alt-tab/capture-loss runtime test |
| Popup geometry | Popup clamped to monitor client area | Implemented | Multi-monitor edge screenshots |
| Accessibility | Stable explicit names, focus ring, keyboard traversal, explicit dismissal focus | Implemented/static-checked | Windows screen-reader/focus evidence |
| Scheduled settings | No overlapping refresh workers | Implemented/static-checked | Runtime logging during slow refresh |
| Dialog/frame M3 chrome | Existing owner-drawn chrome preserved | Implemented | Light/dark screenshots |
| Renderer safety | Opted-out OpenGL subtrees remain renderer-owned | Preserved in source | Open a real world/editor and inspect |
| Functional editor | Open/edit/save/close representative worlds | Not runnable here | Supported Windows integration run |
| Full test suite | Entire repository suite passes | Not runnable without full checkout/deps | CI or local pytest log |
| Packaging | Deterministic kit ZIP, checksum, integrity | Generated after validation | SHA-256 and `ZipFile.testzip()` |
| Release claim | Static and runtime evidence clearly separated | Required | Final release notes/evidence index |
