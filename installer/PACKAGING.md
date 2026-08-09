# Windows packaging contract

The supported Windows release artifact is an **unsigned Squirrel.Windows
release** built from the PyInstaller bundle by `installer/build-squirrel.ps1`.

CI dev builds use a dotted source version such as `0.10.0-dev.154`, but
Squirrel.Windows 2.0.1 reads package metadata with the older NuGet semantic
version parser.  `scripts/normalize_squirrel_version.py` maps that bounded CI
shape to `0.10.0-dev154` before packaging; stable release versions and
single-token prereleases are preserved.  The normalized value is used
consistently for the package, `RELEASES`, `Setup.exe` directory, and uploaded
asset names.
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

## Other release lanes

The macOS release lane follows the same unsigned policy. It builds a DMG but
does not import a certificate, call `codesign`, call `xcrun notarytool`, or
staple a ticket. This keeps a missing Apple credential from turning into a
false-green packaging step or a hard failure; the workflow log states that the
DMG is unsigned.

Wayland pointer locking is an optional Linux runtime enhancement. The base
package does not require `wayland-lock-pointer`, and `pip install
amulet-map-editor[wayland]` may be used on a compatible Wayland host. Debian CI
does not install that optional extra because its desktop build has a safe
pointer fallback when the extension is unavailable.
