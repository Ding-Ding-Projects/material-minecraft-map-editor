# Windows packaging contract

The supported Windows release artifact is an **unsigned Squirrel.Windows
release** built from the PyInstaller bundle by `installer/build-squirrel.ps1`.
Each architecture produces `Setup.exe`, `RELEASES`, and a full `.nupkg`; delta
packages are emitted when a prior full package is available. CI verifies the
release index and checks every generated executable and DLL with
`Get-AuthenticodeSignature`, which must report `NotSigned`.

The runtime bridge in
`amulet_map_editor/api/framework/squirrel_update.py` validates an HTTPS feed,
reports available/ready/failed/not-installed states, and leaves restart under
explicit user control. It never invokes signing and always exposes the
unsigned-artifact warning.

Code signing is intentionally disabled. Users may see an unknown-publisher or
SmartScreen warning when installing the unsigned artifact.
