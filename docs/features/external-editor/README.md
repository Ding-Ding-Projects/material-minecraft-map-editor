# External editor integration

Amulet can open an exported file or folder in a locally installed Visual Studio
Code-compatible editor. The integration is deliberately wx-independent in
`amulet_map_editor.api.external_editor`, so export flows can use the same
validation and result contract from the desktop UI, a headless test, or a
future documentation surface.

## Behaviour

- Detection checks `code` and `code-insiders` on `PATH`, the normal Windows
  per-user/system installations, Scoop installations, and a bounded
  `VSCODE_PORTABLE` location. Existing files are deduplicated in deterministic
  order.
- Preferences stores only the selected executable path. The path is capped at
  4096 characters and is revalidated every time it is used, so uninstalling or
  moving Code produces a recoverable unavailable state instead of a crash.
- The native **Preferences → Appearance** tab provides a path field, a native
  browse button, and a non-blocking **Check editor** action. The field is staged
  until **OK** saves preferences.
- Opening a file invokes the selected editor with the file path. Opening a
  folder invokes `--folder-uri` so the folder is treated as a workspace root.
  All launches include `--reuse-window` and return a structured result.

## Failure modes and security

The bridge never shells through a command interpreter and never interpolates a
path into a command string. Missing, non-file, overlong, or stale paths return
`not_configured`, `invalid_target`, or `unavailable` results. A launch failure
returns `launch_failed` with the original `OSError` message for the native
notification surface. The bridge does not read editor settings, credentials,
workspace contents, or user files beyond checking the requested path.

## Verification

```text
python -m unittest tests.test_external_editor tests.test_external_editor_ui_contract
```

The tests cover deterministic PATH/location discovery, duplicate suppression,
selection persistence, folder workspace-root arguments, and safe unavailable
results without starting a real editor process.
