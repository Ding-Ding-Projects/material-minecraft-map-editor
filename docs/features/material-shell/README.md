# Material application shell

The application frame is frameless, with an app-owned title bar and compact
owner-drawn window controls. Its content is the **Amulet Studio** shell: a
backstage view for starting and opening projects, and a ribbon workspace for
editing one. The operating system's own title bar is never shown as product
chrome.

This replaced the earlier single start card plus command bar. That shell is
still in the tree and is still what a build shows if the Studio package cannot
be constructed — degrading to the previous interface beats refusing to open a
window — but it is no longer what the application presents.

## Behaviour

`AmuletUI` (`amulet_map_editor/api/framework/amulet_ui.py`) builds
`StudioShell` as its only visible child and hides the earlier title bar, command
bar, and notebook container. The world notebook itself is kept: it owns world
loading, per-page unsaved-work protection, and the tab dock the tab manager
edits, and it is handed to the workspace viewport once a world is open, so the
real renderer draws inside the new shell rather than beside it.

Startup stays immediately usable. There is no acknowledgement, purchase,
donation, sponsorship, rating, review, or upgrade gate — nobody ever pays to use
this application, and it does not ask. Safety guidance stays attached to the
action that opens a world and in the offline manual. Update state remains
non-blocking operational status with explicit user control over restart.

The shell's own design tokens live in
`amulet_map_editor/api/studio/tokens.py`: fourteen colour roles in a light and a
dark palette, three density heights (32, 36, 44), the spacing and radius scales,
and the local font fallback chain. The legacy Material 3 layer
(`amulet_map_editor/api/wx/material3.py`) still serves the dialogs that predate
the Studio, and both read the same persisted appearance profile, so the two
halves cannot drift into two different themes.

## Configuration and failure modes

The shell consumes the persisted theme, density, accent, interface font, and
interface scale, projected through School mode and overridden by any active
scheduled rule. `refresh_theme()` re-resolves the tokens and repaints
everything, so an appearance change lands live rather than at the next launch.

An invalid persisted appearance value normalises to the shipped roles rather
than preventing startup. A Studio package that cannot be constructed is logged
with its traceback and the frame falls back to the notebook.

Legacy dialogs still contain native controls and are reached through the same
surface keys as everything else. The shared role projection keeps them readable;
it is not evidence that each one has finished its component migration.

## Security and accessibility

Window actions resolve the real top-level owner before minimising, maximising,
or closing, so a decorative child panel cannot receive a frame operation.
Caption and shell controls have accessible names, visible focus, keyboard
activation, and bounded targets. No startup route performs a purchase or stores
payment data, and nothing in the shell reaches the network.

## Verification

```powershell
py -3 -m pytest tests/test_studio_shell_hosting_contract.py tests/test_material_components_contract.py tests/test_nag_free_startup_contract.py -q
```

The first proves the frame builds the Studio shell, hides the old chrome rather
than drawing it alongside, and keeps the fallback. The other two cover the
owner-drawn control behaviour and the quiet startup path.

No runtime capture of the Studio interface exists yet. The tracked captures in
the README are of the earlier shell and are labelled as such; they are not
evidence for this one.

Suggested articles: [project shell](../project-shell/README.md),
[appearance](../appearance/README.md),
[notification centre](../notification-centre/README.md), and
[tab groups](../tab-groups/README.md).
